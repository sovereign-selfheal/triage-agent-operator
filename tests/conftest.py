import pytest

from app.config import resolve_spec


@pytest.fixture
def minimal_resolved_spec():
    return resolve_spec(
        {
            "router": {"url": "https://router.apps.example.com/v1"},
            "mcpServers": {
                "prometheus": "http://prometheus-mcp-server.agentic-triage.svc:8080/mcp",
                "ticketing": "http://ticketing-mcp-server.agentic-triage.svc:8080/mcp",
            },
        }
    )
