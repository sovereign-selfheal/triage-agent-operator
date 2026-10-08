"""
Pure functions: a resolved `TriageAgent` spec -> child resource manifests (plain dicts).

No cluster access here — these functions never import `kubernetes` or `kopf`. That keeps
them trivially unit-testable (tests/test_resources.py) and keeps `app/operator.py` as the
only place that talks to the API server. Mirrors the structure of the gitops repo's
`components/triage-agent` Helm templates; see each function's docstring for the source
template it replaces.

Every manifest omits `metadata.namespace` and `metadata.ownerReferences`: the caller
(`app/operator.py`) sets the namespace (from the CR) and calls `kopf.adopt()` to add the
owner reference, so every builder stays a pure function of `(name, spec)`.
"""

from __future__ import annotations

from typing import Any

# OGX stack config template (gitops components/triage-agent/templates/stack-run-config.yaml).
# The `${env.X}` syntax belongs to OGX's own config loader, not this operator: it is
# resolved by the ogx-server process from its container env, not rendered here.
_OGX_STACK_RUN_CONFIG = """\
version: '2'
distro_name: sovereign-triage-agent

apis:
  - inference
  - responses
  - tool_runtime
  - vector_io
  - files

providers:
  inference:
    - provider_id: router
      provider_type: remote::vllm
      config:
        base_url: ${env.VLLM_URL}
        max_tokens: ${env.VLLM_MAX_TOKENS:=4096}
        api_token: ${env.VLLM_API_TOKEN}
        network:
          tls:
            verify: ${env.VLLM_TLS_VERIFY:=true}

  responses:
    - provider_id: builtin
      provider_type: inline::builtin
      config:
        persistence:
          responses:
            table_name: responses
            backend: sql_default

  vector_io:
    - provider_id: faiss
      provider_type: inline::faiss
      config:
        persistence:
          namespace: vector_io::faiss
          backend: kv_default

  tool_runtime:
    - provider_id: model-context-protocol
      provider_type: remote::model-context-protocol
      config: {}

  files:
    - provider_id: builtin-files
      provider_type: inline::localfs
      config:
        storage_dir: /tmp/ogx/files
        metadata_store:
          table_name: files_metadata
          backend: sql_default

storage:
  backends:
    kv_default:
      type: kv_sqlite
      db_path: /tmp/ogx/kvstore.db
    sql_default:
      type: sql_sqlite
      db_path: /tmp/ogx/sql_store.db
  stores:
    metadata:
      namespace: registry
      backend: kv_default
    inference:
      table_name: inference_store
      backend: sql_default
    conversations:
      table_name: openai_conversations
      backend: sql_default
    prompts:
      table_name: prompts
      backend: sql_default

# No registered_resources.models: OGX lists the models of the router itself at startup
# and names them "router/<model>".
server:
  port: 8321
"""


def _labels(name: str) -> dict[str, str]:
    return {
        "app": name,
        "app.kubernetes.io/managed-by": "triage-agent-operator",
    }


def ogx_config_name(name: str) -> str:
    return f"{name}-ogx-config"


def knowledge_config_name(name: str) -> str:
    return f"{name}-knowledge"


def apikey_secret_name(name: str) -> str:
    return f"{name}-apikey"


def build_service_account(name: str) -> dict[str, Any]:
    """gitops components/triage-agent/templates/deployment.yaml (ServiceAccount)."""
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {"name": name, "labels": _labels(name)},
    }


def build_ogx_configmap(name: str) -> dict[str, Any]:
    """gitops components/triage-agent/templates/stack-run-config.yaml."""
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": ogx_config_name(name), "labels": _labels(name)},
        "data": {"stack_run_config.yaml": _OGX_STACK_RUN_CONFIG},
    }


def build_knowledge_configmap(name: str, spec: dict[str, Any]) -> dict[str, Any] | None:
    """gitops components/triage-agent/templates/knowledge-configmap.yaml.

    Returns None when `spec.knowledge.configMapName` points at an existing ConfigMap
    (nothing to create) or when no inline `content` was given either (nothing to mount
    besides an existing/absent reference).
    """
    knowledge = spec.get("knowledge", {})
    if knowledge.get("configMapName"):
        return None
    content = knowledge.get("content", "")
    if not content:
        return None
    file_name = knowledge.get("fileName", "knowledge.md")
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": knowledge_config_name(name), "labels": _labels(name)},
        "data": {file_name: content},
    }


def resolved_knowledge_configmap_name(name: str, spec: dict[str, Any]) -> str:
    """The ConfigMap name the Deployment should mount: either the existing one from the
    spec, or the one this operator creates."""
    knowledge = spec.get("knowledge", {})
    return knowledge.get("configMapName") or knowledge_config_name(name)


def build_apikey_secret(
    name: str, spec: dict[str, Any], existing_api_key: str | None = None
) -> dict[str, Any] | None:
    """Plain Secret carrying the router API key (see AGENTS.md section 4: the operator
    does not depend on External Secrets Operator the way
    gitops components/triage-agent/templates/apikey.yaml does).

    Returns None when `spec.apiKey.existingSecret` is set (nothing to create).
    `existing_api_key`, when given, is reused verbatim so re-reconciling an existing CR
    never rotates the key (the caller reads it from the live Secret, if any, before
    calling this).
    """
    api_key_spec = spec.get("apiKey", {})
    if api_key_spec.get("existingSecret"):
        return None
    api_key = existing_api_key or _generate_api_key(
        prefix=api_key_spec.get("prefix", "sk-"),
        length=int(api_key_spec.get("length", 40)),
    )
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": apikey_secret_name(name),
            "labels": {
                **_labels(name),
                # Read by the platform's AuthPolicy (gitops component frontdoor):
                # maas-group is the token-budget tier. Must match one entry of the
                # platform's tiers.
                "authorino.kuadrant.io/managed-by": "authorino",
                "app": "maas-litellm",
                "maas-group": api_key_spec.get("tier", "agents"),
            },
        },
        "type": "Opaque",
        "stringData": {"api_key": api_key},
    }


def resolved_apikey_secret_name(name: str, spec: dict[str, Any]) -> str:
    api_key_spec = spec.get("apiKey", {})
    return api_key_spec.get("existingSecret") or apikey_secret_name(name)


def _generate_api_key(prefix: str, length: int) -> str:
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits
    return prefix + "".join(secrets.choice(alphabet) for _ in range(length))


def build_deployment(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    """gitops components/triage-agent/templates/deployment.yaml (Deployment)."""
    router = spec.get("router", {})
    mcp = spec.get("mcpServers", {})
    knowledge = spec.get("knowledge", {})
    resources = spec.get("resources", {})
    mount_path = knowledge.get("mountPath", "/etc/triage-agent")
    file_name = knowledge.get("fileName", "knowledge.md")
    model = router.get("model", "auto")

    containers = [
        {
            "name": "ogx-server",
            "image": spec["ogxImage"],
            "imagePullPolicy": "IfNotPresent",
            "command": [
                "uvicorn",
                "ogx.core.server.server:create_app",
                "--host",
                "0.0.0.0",
                "--port",
                "8321",
                "--factory",
            ],
            "ports": [{"name": "ogx-http", "containerPort": 8321}],
            "env": [
                {"name": "OGX_CONFIG", "value": "/etc/ogx/stack_run_config.yaml"},
                {"name": "OGX_LOGGING", "value": "all=INFO"},
                {"name": "SQLITE_STORE_DIR", "value": "/tmp/ogx"},
                {"name": "VLLM_URL", "value": router["url"]},
                {"name": "VLLM_MAX_TOKENS", "value": "8192"},
                {"name": "VLLM_TLS_VERIFY", "value": str(router.get("tlsVerify", True)).lower()},
                {
                    "name": "VLLM_API_TOKEN",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": resolved_apikey_secret_name(name, spec),
                            "key": "api_key",
                        }
                    },
                },
                {"name": "INFERENCE_MODEL", "value": f"router/{model}"},
                {"name": "OPENAI_MAX_RETRIES", "value": "8"},
            ],
            "volumeMounts": [
                {"name": "ogx-config", "mountPath": "/etc/ogx"},
                {"name": "ogx-data", "mountPath": "/tmp/ogx"},
            ],
            "livenessProbe": {
                "httpGet": {"path": "/v1/models", "port": 8321},
                "initialDelaySeconds": 45,
                "periodSeconds": 20,
                "failureThreshold": 4,
            },
            "readinessProbe": {
                "httpGet": {"path": "/v1/models", "port": 8321},
                "initialDelaySeconds": 30,
                "periodSeconds": 10,
                "failureThreshold": 6,
            },
            "resources": resources.get("ogx", {}),
            "securityContext": _container_security_context(),
        },
        {
            "name": "triage-agent",
            "image": spec["image"],
            "imagePullPolicy": "IfNotPresent",
            "ports": [{"name": "http", "containerPort": 7860}],
            "env": [
                {"name": "GRADIO_PORT", "value": "7860"},
                {"name": "GRADIO_ANALYTICS_ENABLED", "value": "False"},
                {"name": "OGX_BASE_URL", "value": "http://localhost:8321"},
                {"name": "ROUTER_MODEL", "value": f"router/{model}"},
                {"name": "PROMETHEUS_MCP_URL", "value": mcp.get("prometheus", "")},
                {"name": "TICKETING_MCP_URL", "value": mcp.get("ticketing", "")},
                {"name": "OCP_MCP_URL", "value": mcp.get("ocp", "")},
                {"name": "KNOWLEDGE_FILE", "value": f"{mount_path}/{file_name}"},
                {
                    "name": "ROUTER_NAMESPACE_HINT",
                    "value": str(bool(spec.get("namespaceHint", False))).lower(),
                },
                {"name": "PYTHONUNBUFFERED", "value": "1"},
            ],
            "volumeMounts": [
                {"name": "agent-knowledge", "mountPath": mount_path, "readOnly": True},
            ],
            "livenessProbe": {
                "httpGet": {"path": "/", "port": 7860},
                "initialDelaySeconds": 60,
                "periodSeconds": 15,
                "failureThreshold": 4,
            },
            "readinessProbe": {
                "httpGet": {"path": "/", "port": 7860},
                "initialDelaySeconds": 45,
                "periodSeconds": 10,
                "failureThreshold": 6,
            },
            "resources": resources.get("agent", {}),
            "securityContext": _container_security_context(),
        },
    ]

    deployment: dict[str, Any] = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "labels": _labels(name)},
        "spec": {
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {
                    "serviceAccountName": name,
                    "containers": containers,
                    "volumes": [
                        {"name": "ogx-config", "configMap": {"name": ogx_config_name(name)}},
                        {
                            "name": "agent-knowledge",
                            "configMap": {"name": resolved_knowledge_configmap_name(name, spec)},
                        },
                        {"name": "ogx-data", "emptyDir": {}},
                    ],
                },
            },
        },
    }

    # Omit `replicas` entirely when the spec does not set it, so an external autoscaler
    # (e.g. KEDA) can own the field without this operator fighting it on every reconcile
    # (AGENTS.md section 3.6 of gitops, ogx-alert-translator precedent).
    if spec.get("replicas") is not None:
        deployment["spec"]["replicas"] = int(spec["replicas"])

    return deployment


def _container_security_context() -> dict[str, Any]:
    return {
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }


def build_service(name: str) -> dict[str, Any]:
    """gitops components/triage-agent/templates/deployment.yaml (Service)."""
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "labels": _labels(name)},
        "spec": {
            "selector": {"app": name},
            "ports": [{"name": "http", "port": 7860, "targetPort": "http"}],
        },
    }


def build_route(name: str, spec: dict[str, Any]) -> dict[str, Any] | None:
    """gitops components/triage-agent/templates/deployment.yaml (Route).

    Returns None when `spec.route.enabled` is False.
    """
    route_spec = spec.get("route", {})
    if not route_spec.get("enabled", True):
        return None
    route: dict[str, Any] = {
        "apiVersion": "route.openshift.io/v1",
        "kind": "Route",
        "metadata": {"name": name, "labels": _labels(name)},
        "spec": {
            "to": {"kind": "Service", "name": name},
            "port": {"targetPort": "http"},
            "tls": {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"},
        },
    }
    if route_spec.get("host"):
        route["spec"]["host"] = route_spec["host"]
    return route
