"""Unit tests for deployment phase computation."""

from app.status import phase_from_deployment, pods_have_fatal_waiting


def _deployment(
    *,
    observed_generation: int = 1,
    available_replicas: int = 0,
    conditions: list[dict] | None = None,
) -> dict:
    return {
        "status": {
            "observedGeneration": observed_generation,
            "availableReplicas": available_replicas,
            "conditions": conditions or [],
        }
    }


def _pod_waiting(reason: str) -> dict:
    return {
        "status": {
            "containerStatuses": [
                {"state": {"waiting": {"reason": reason}}},
            ]
        }
    }


def test_phase_pending_when_deployment_missing():
    assert phase_from_deployment(None) == "Pending"


def test_phase_pending_before_observed_generation():
    dep = _deployment(observed_generation=0)
    assert phase_from_deployment(dep) == "Pending"


def test_phase_running_when_replica_available():
    dep = _deployment(available_replicas=1)
    assert phase_from_deployment(dep) == "Running"


def test_phase_pending_during_rollout_with_no_available_replicas():
    dep = _deployment(
        available_replicas=0,
        conditions=[
            {"type": "Progressing", "status": "True", "reason": "ReplicaSetUpdated"},
            {"type": "Available", "status": "False", "reason": "MinimumReplicasUnavailable"},
        ],
    )
    assert phase_from_deployment(dep, []) == "Pending"


def test_phase_degraded_on_progress_deadline_exceeded():
    dep = _deployment(
        conditions=[
            {
                "type": "Progressing",
                "status": "False",
                "reason": "ProgressDeadlineExceeded",
            }
        ],
    )
    assert phase_from_deployment(dep) == "Degraded"


def test_phase_degraded_on_image_pull_backoff():
    dep = _deployment()
    pods = [_pod_waiting("ImagePullBackOff")]
    assert phase_from_deployment(dep, pods) == "Degraded"


def test_phase_degraded_on_crash_loop_backoff():
    dep = _deployment()
    pods = [_pod_waiting("CrashLoopBackOff")]
    assert phase_from_deployment(dep, pods) == "Degraded"


def test_pods_have_fatal_waiting_ignores_container_creating():
    pods = [_pod_waiting("ContainerCreating")]
    assert pods_have_fatal_waiting(pods) is False
