"""
Defaults for an incomplete `TriageAgent` spec.

The CRD's OpenAPI schema (deploy/crd.yaml) sets defaults for simple scalar leaf fields;
this module is the single source of truth whenever the two could disagree (AGENTS.md
section 3.4), and it is the only place that knows the operator's built-in image pins and
resource sizing. Keep these defaults in sync with `components/triage-agent/values.yaml`
in the `gitops` repo when that chart's defaults change.
"""

from __future__ import annotations

import copy
from typing import Any

# tag v0.2.0, resolved on quay.io on 2026-10-04 (gitops components/triage-agent/values.yaml)
DEFAULT_IMAGE = (
    "quay.io/sovereign-selfheal/triage-agent@sha256:"
    "a8340b5c1b4006dc8418a8c2646caeaf03e3bb52bad41e2830895a32605b7781"
)
# tag latest, resolved on docker.io on 2026-09-29
DEFAULT_OGX_IMAGE = (
    "docker.io/ogxai/distribution-starter@sha256:"
    "9d6afd54417bee1f37768a054e198becfadbed21d270d8ec1cdfb699e35e9924"
)

DEFAULTS: dict[str, Any] = {
    "image": DEFAULT_IMAGE,
    "ogxImage": DEFAULT_OGX_IMAGE,
    "replicas": 1,
    "router": {
        "model": "auto",
        "tlsVerify": True,
    },
    "apiKey": {
        "tier": "agents",
        "prefix": "sk-",
        "length": 40,
        "existingSecret": "",
    },
    "mcpServers": {
        "prometheus": "",
        "ticketing": "",
        "ocp": "",
    },
    "knowledge": {
        "configMapName": "",
        "fileName": "knowledge.md",
        "mountPath": "/etc/triage-agent",
        "content": "",
    },
    "namespaceHint": False,
    "route": {
        "enabled": True,
        "host": "",
    },
    "resources": {
        "agent": {
            "requests": {"cpu": "100m", "memory": "256Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        },
        "ogx": {
            "requests": {"cpu": "250m", "memory": "512Mi"},
            "limits": {"cpu": "1", "memory": "1Gi"},
        },
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` on top of `base`. Returns a new dict; neither
    argument is mutated. A key present in `override` with value `None` is ignored (so
    a CR author can omit a key rather than null it out)."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def resolve_spec(raw_spec: dict[str, Any]) -> dict[str, Any]:
    """Merge a CR's `spec` with the operator's built-in defaults.

    `raw_spec` is expected to already satisfy the CRD's required fields (the API server
    rejects a CR missing `spec.router.url` before the operator ever sees it); this
    function only fills in everything that is optional.
    """
    return _deep_merge(DEFAULTS, raw_spec or {})
