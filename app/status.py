"""Status/condition helpers (AGENTS.md section 3.6: status must reflect real state)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_FATAL_WAITING_REASONS = frozenset({"CrashLoopBackOff", "ImagePullBackOff"})


def _resource_status(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        nested = obj.get("status")
        if nested is not None:
            return dict(nested)
        return dict(obj)
    status = getattr(obj, "status", None)
    if status is None:
        return {}
    if hasattr(status, "to_dict"):
        return status.to_dict()
    return dict(status or {})


def _progress_deadline_exceeded(status: dict[str, Any]) -> bool:
    for condition in status.get("conditions") or []:
        if condition.get("type") != "Progressing":
            continue
        if condition.get("reason") == "ProgressDeadlineExceeded":
            return True
    return False


def _container_waiting_reasons(pod_status: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for key in ("containerStatuses", "initContainerStatuses"):
        for container in pod_status.get(key) or []:
            waiting = (container.get("state") or {}).get("waiting") or {}
            reason = waiting.get("reason")
            if reason:
                reasons.append(reason)
    return reasons


def pods_have_fatal_waiting(pods: list[Any] | None) -> bool:
    """True when any owned Pod is stuck in CrashLoopBackOff or ImagePullBackOff."""
    if not pods:
        return False
    for pod in pods:
        for reason in _container_waiting_reasons(_resource_status(pod)):
            if reason in _FATAL_WAITING_REASONS:
                return True
    return False


def phase_from_deployment(deployment: Any, pods: list[Any] | None = None) -> str:
    """`Pending` until the Deployment exists and has been observed at least once,
    `Running` once at least one replica is available, `Degraded` when the rollout
    missed its progress deadline or a Pod reports CrashLoopBackOff / ImagePullBackOff,
    otherwise `Pending` while a rollout is still in progress (e.g. image pull)."""
    if deployment is None:
        return "Pending"
    status = _resource_status(deployment)
    if not status.get("observedGeneration"):
        return "Pending"
    if (status.get("availableReplicas") or 0) >= 1:
        return "Running"
    if _progress_deadline_exceeded(status):
        return "Degraded"
    if pods_have_fatal_waiting(pods):
        return "Degraded"
    return "Pending"


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
