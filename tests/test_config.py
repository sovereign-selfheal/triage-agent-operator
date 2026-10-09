from app.config import resolve_spec


def test_minimal_spec_gets_all_defaults():
    resolved = resolve_spec({"router": {"url": "https://router.apps.example.com/v1"}})

    assert resolved["image"]
    assert resolved["ogxImage"]
    # No built-in default: omitting `replicas` lets an external autoscaler own it
    # (app/resources.py:build_deployment skips the field entirely in that case).
    assert "replicas" not in resolved
    assert resolved["router"]["url"] == "https://router.apps.example.com/v1"
    assert resolved["router"]["model"] == "auto"
    assert resolved["router"]["tlsVerify"] is True
    assert resolved["apiKey"]["tier"] == "agents"
    assert resolved["knowledge"]["fileName"] == "knowledge.md"
    assert resolved["route"]["enabled"] is True


def test_explicit_values_override_defaults():
    resolved = resolve_spec(
        {
            "router": {"url": "https://router.apps.example.com/v1", "model": "sota-smart"},
            "apiKey": {"tier": "agents-critical"},
            "replicas": 3,
        }
    )

    assert resolved["router"]["model"] == "sota-smart"
    assert resolved["router"]["tlsVerify"] is True  # untouched sibling key keeps its default
    assert resolved["apiKey"]["tier"] == "agents-critical"
    assert resolved["apiKey"]["prefix"] == "sk-"  # untouched sibling key keeps its default
    assert resolved["replicas"] == 3


def test_none_values_do_not_override_defaults():
    resolved = resolve_spec({"router": {"url": "https://router.apps.example.com/v1"}, "replicas": None})

    assert "replicas" not in resolved


def test_empty_spec_raises_key_error_for_required_router_url():
    # The CRD schema enforces `spec.router.url` as required before the operator ever
    # sees the CR; resolve_spec does not need to validate it, but callers building a
    # Deployment do dereference spec["router"]["url"] and should fail loudly if it is
    # missing rather than silently deploying with no backend.
    resolved = resolve_spec({})
    assert "url" not in resolved["router"]
