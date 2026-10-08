"""
kopf handlers for `TriageAgent` (triage.sovereign-selfheal.io/v1alpha1).

See AGENTS.md section 3 for the reconciliation rules this module must follow: one CR
reconciles exactly its own namespace's child resources, every child gets an owner
reference, reconciliation is idempotent (server-side apply of the full desired state
every time), and status reflects the real state of the child Deployment.
"""

from __future__ import annotations

import base64
import logging

import kopf
from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.dynamic import DynamicClient
from kubernetes.dynamic.exceptions import NotFoundError

from app import resources
from app.config import resolve_spec
from app.status import build_conditions, phase_from_deployment

logger = logging.getLogger(__name__)

GROUP = "triage.sovereign-selfheal.io"
VERSION = "v1alpha1"
PLURAL = "triageagents"

FIELD_MANAGER = "triage-agent-operator"

_dyn: DynamicClient | None = None


def _dynamic_client() -> DynamicClient:
    global _dyn
    if _dyn is None:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        _dyn = DynamicClient(client.ApiClient())
    return _dyn


def _api(api_version: str, kind: str):
    return _dynamic_client().resources.get(api_version=api_version, kind=kind)


def _apply(api_version: str, kind: str, namespace: str, manifest: dict) -> None:
    """Server-side apply of the full desired manifest (AGENTS.md section 3.3)."""
    _api(api_version, kind).apply(body=manifest, namespace=namespace, field_manager=FIELD_MANAGER)


def _get(api_version: str, kind: str, namespace: str, name: str):
    try:
        return _api(api_version, kind).get(name=name, namespace=namespace)
    except NotFoundError:
        return None


def _existing_api_key(namespace: str, secret_name: str) -> str | None:
    """Read back an already-generated API key so re-reconciling never rotates it."""
    secret = _get("v1", "Secret", namespace, secret_name)
    if secret is None:
        return None
    encoded = (secret.data or {}).get("api_key")
    if not encoded:
        return None
    return base64.b64decode(encoded).decode()


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_kwargs) -> None:
    settings.posting.level = logging.INFO
    settings.persistence.finalizer = f"{GROUP}/finalizer"
    _dynamic_client()


@kopf.on.create(GROUP, VERSION, PLURAL)
@kopf.on.update(GROUP, VERSION, PLURAL)
@kopf.on.resume(GROUP, VERSION, PLURAL)
def reconcile(spec: dict, name: str, namespace: str, body: dict, patch: kopf.Patch, **_kwargs) -> None:
    resolved = resolve_spec(dict(spec))

    existing_api_key = None
    if not resolved["apiKey"].get("existingSecret"):
        existing_api_key = _existing_api_key(namespace, resources.apikey_secret_name(name))

    desired: list[tuple[str, str, dict | None]] = [
        ("v1", "ServiceAccount", resources.build_service_account(name)),
        ("v1", "ConfigMap", resources.build_ogx_configmap(name)),
        ("v1", "ConfigMap", resources.build_knowledge_configmap(name, resolved)),
        ("v1", "Secret", resources.build_apikey_secret(name, resolved, existing_api_key)),
        ("apps/v1", "Deployment", resources.build_deployment(name, resolved)),
        ("v1", "Service", resources.build_service(name)),
        ("route.openshift.io/v1", "Route", resources.build_route(name, resolved)),
    ]

    for api_version, kind, manifest in desired:
        if manifest is None:
            continue
        kopf.adopt(manifest, owner=body)
        _apply(api_version, kind, namespace, manifest)
        logger.info("Applied %s/%s %s in %s", api_version, kind, manifest["metadata"]["name"], namespace)

    deployment = _get("apps/v1", "Deployment", namespace, name)
    phase = phase_from_deployment(deployment)

    route_url = ""
    if resolved["route"].get("enabled", True):
        route = _get("route.openshift.io/v1", "Route", namespace, name)
        host = getattr(route, "spec", None) and route.spec.get("host")
        if host:
            route_url = f"https://{host}"

    patch.status["phase"] = phase
    patch.status["routeUrl"] = route_url
    patch.status["observedGeneration"] = (body.get("metadata") or {}).get("generation", 0)
    patch.status["conditions"] = build_conditions(phase)

    logger.info("Reconciled TriageAgent %s/%s -> phase=%s", namespace, name, phase)


@kopf.on.delete(GROUP, VERSION, PLURAL)
def on_delete(name: str, namespace: str, **_kwargs) -> None:
    # Every child resource carries an owner reference (kopf.adopt, set in reconcile), so
    # Kubernetes garbage-collects them automatically (AGENTS.md section 3.2). Nothing
    # else to clean up.
    logger.info(
        "TriageAgent %s/%s deleted; child resources cascade via owner references",
        namespace,
        name,
    )
