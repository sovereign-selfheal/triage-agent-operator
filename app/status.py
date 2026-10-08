"""Status/condition helpers (AGENTS.md section 3.6: status must reflect real state)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def phase_from_deployment(deployment: Any) -> str:
    """`Pending` until the Deployment exists and has been observed at least once,
    `Running` once at least one replica is available, `Degraded` otherwise (exists,
    observed, but no available replicas — e.g. CrashLoopBackOff, failed pull)."""
    if deployment is None:
        return "Pending"
    status = deployment.status.to_dict() if hasattr(deployment.status, "to_dict") else dict(deployment.status or {})
    if not status.get("observedGeneration"):
        return "Pending"
    if (status.get("availableReplicas") or 0) >= 1:
        return "Running"
    return "Degraded"


def build_conditions(phase: str) -> list[dict[str, str]]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    available = phase == "Running"
    return [
        {
            "type": "Available",
            "status": "True" if available else "False",
            "reason": phase,
            "message": f"Deployment phase is {phase}",
            "lastTransitionTime": now,
        }
    ]
