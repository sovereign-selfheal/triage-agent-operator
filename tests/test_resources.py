from app import resources


def test_service_account_name_and_labels():
    sa = resources.build_service_account("triage-agent")
    assert sa["kind"] == "ServiceAccount"
    assert sa["metadata"]["name"] == "triage-agent"
    assert sa["metadata"]["labels"]["app"] == "triage-agent"


def test_ogx_configmap_has_stack_run_config_key():
    cm = resources.build_ogx_configmap("triage-agent")
    assert cm["metadata"]["name"] == "triage-agent-ogx-config"
    assert "stack_run_config.yaml" in cm["data"]
    assert "${env.VLLM_URL}" in cm["data"]["stack_run_config.yaml"]


def test_knowledge_configmap_created_from_inline_content(minimal_resolved_spec):
    spec = dict(minimal_resolved_spec)
    spec["knowledge"] = {**spec["knowledge"], "content": "# Some knowledge"}

    cm = resources.build_knowledge_configmap("triage-agent", spec)

    assert cm is not None
    assert cm["metadata"]["name"] == "triage-agent-knowledge"
    assert cm["data"]["knowledge.md"] == "# Some knowledge"


def test_knowledge_configmap_skipped_when_existing_configmap_set(minimal_resolved_spec):
    spec = dict(minimal_resolved_spec)
    spec["knowledge"] = {**spec["knowledge"], "configMapName": "shared-knowledge"}

    cm = resources.build_knowledge_configmap("triage-agent", spec)

    assert cm is None
    assert resources.resolved_knowledge_configmap_name("triage-agent", spec) == "shared-knowledge"


def test_knowledge_configmap_skipped_when_no_content_and_no_existing_configmap(minimal_resolved_spec):
    cm = resources.build_knowledge_configmap("triage-agent", minimal_resolved_spec)

    assert cm is None
    # Falls back to the operator-created name even though nothing was rendered: the
    # Deployment still mounts a ConfigMap of that name (e.g. provided out-of-band).
    assert (
        resources.resolved_knowledge_configmap_name("triage-agent", minimal_resolved_spec)
        == "triage-agent-knowledge"
    )


def test_apikey_secret_generated_when_no_existing_secret(minimal_resolved_spec):
    secret = resources.build_apikey_secret("triage-agent", minimal_resolved_spec)

    assert secret is not None
    assert secret["metadata"]["name"] == "triage-agent-apikey"
    assert secret["metadata"]["labels"]["maas-group"] == "agents"
    assert secret["stringData"]["api_key"].startswith("sk-")
    assert len(secret["stringData"]["api_key"]) == len("sk-") + 40


def test_apikey_secret_reuses_existing_key(minimal_resolved_spec):
    secret = resources.build_apikey_secret(
        "triage-agent", minimal_resolved_spec, existing_api_key="sk-fixed-for-test"
    )

    assert secret["stringData"]["api_key"] == "sk-fixed-for-test"


def test_apikey_secret_skipped_when_existing_secret_set(minimal_resolved_spec):
    spec = dict(minimal_resolved_spec)
    spec["apiKey"] = {**spec["apiKey"], "existingSecret": "my-secret"}

    secret = resources.build_apikey_secret("triage-agent", spec)

    assert secret is None
    assert resources.resolved_apikey_secret_name("triage-agent", spec) == "my-secret"


def test_deployment_has_two_containers_and_expected_env(minimal_resolved_spec):
    deployment = resources.build_deployment("triage-agent", minimal_resolved_spec)

    containers = deployment["spec"]["template"]["spec"]["containers"]
    names = [c["name"] for c in containers]
    assert names == ["ogx-server", "triage-agent"]

    ogx_env = {e["name"]: e["value"] for e in containers[0]["env"] if "value" in e}
    assert ogx_env["VLLM_URL"] == "https://router.apps.example.com/v1"
    assert ogx_env["INFERENCE_MODEL"] == "router/auto"

    agent_env = {e["name"]: e["value"] for e in containers[1]["env"] if "value" in e}
    assert agent_env["PROMETHEUS_MCP_URL"].endswith("/mcp")
    assert agent_env["KNOWLEDGE_FILE"] == "/etc/triage-agent/knowledge.md"
    assert agent_env["ROUTER_NAMESPACE_HINT"] == "false"


def test_deployment_omits_replicas_when_unset(minimal_resolved_spec):
    spec = dict(minimal_resolved_spec)
    spec["replicas"] = None

    deployment = resources.build_deployment("triage-agent", spec)

    assert "replicas" not in deployment["spec"]


def test_deployment_sets_replicas_when_given(minimal_resolved_spec):
    spec = dict(minimal_resolved_spec)
    spec["replicas"] = 2

    deployment = resources.build_deployment("triage-agent", spec)

    assert deployment["spec"]["replicas"] == 2


def test_service_exposes_port_7860():
    service = resources.build_service("triage-agent")

    assert service["spec"]["ports"][0]["port"] == 7860
    assert service["spec"]["selector"] == {"app": "triage-agent"}


def test_route_enabled_by_default(minimal_resolved_spec):
    route = resources.build_route("triage-agent", minimal_resolved_spec)

    assert route is not None
    assert route["spec"]["to"]["name"] == "triage-agent"
    assert route["spec"]["tls"]["termination"] == "edge"


def test_route_disabled_returns_none(minimal_resolved_spec):
    spec = dict(minimal_resolved_spec)
    spec["route"] = {**spec["route"], "enabled": False}

    assert resources.build_route("triage-agent", spec) is None


def test_route_explicit_host(minimal_resolved_spec):
    spec = dict(minimal_resolved_spec)
    spec["route"] = {**spec["route"], "host": "triage-agent.apps.example.com"}

    route = resources.build_route("triage-agent", spec)

    assert route["spec"]["host"] == "triage-agent.apps.example.com"
