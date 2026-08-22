"""Import-safety + wiring tests for the D5 ADK agent layer.

The local / on-prem / test profile installs **no Google Cloud SDK**, so importing the agent
wiring modules (and building the AgentCard, and calling the plain tool callable) must never pull
in ``google.adk`` / ``google-cloud-*``. The agent-card endpoint is exercised end-to-end against
the local SDK-free stack via a monkeypatched in-memory container, and the fail-closed
cross-tenant ACL is proven to survive the agent tool path.
"""

from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from next_best_action.api import deps
from next_best_action.api.app import app
from next_best_action.config import Container, Settings
from next_best_action.domain.errors import AuthorizationError

_EXPECTED_SKILLS = {"recommend_next_best_action"}


# --------------------------------------------------------------------------- #
# Import safety (no ADK installed)
# --------------------------------------------------------------------------- #
def test_agent_package_imports_without_adk() -> None:
    module = importlib.import_module("next_best_action.agent")
    assert module.build_root_agent is not None
    assert module.build_agent_card is not None
    assert "google.adk" not in sys.modules


def test_agent_root_imports_without_adk() -> None:
    module = importlib.import_module("next_best_action.agent.root_agent")
    assert repr(module.root_agent)  # touching the lazy proxy must not build the agent
    assert "google.adk" not in sys.modules


def test_mcp_toolset_is_none_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    ra = importlib.import_module("next_best_action.agent.root_agent")

    monkeypatch.delenv(ra.MCP_SERVER_URL_ENV, raising=False)
    assert ra._build_mcp_toolset() is None
    assert "google.adk" not in sys.modules


# --------------------------------------------------------------------------- #
# The AgentCard is pure domain (no ADK)
# --------------------------------------------------------------------------- #
def test_agent_card_is_pure(local_settings: Settings) -> None:
    from next_best_action.agent.agent_card import build_agent_card

    card = build_agent_card(local_settings)
    assert card.name == "next-best-action"
    assert {s.id for s in card.skills} == _EXPECTED_SKILLS


def test_governed_tools_match_card_skills() -> None:
    """Least privilege (R4): the tool surface and the advertised skills stay in step."""
    from next_best_action.agent import tools
    from next_best_action.agent.agent_card import SKILLS

    assert tools.governed_tool_names() == {s.id for s in SKILLS}


# --------------------------------------------------------------------------- #
# The plain tool callable runs offline against the local stack (no ADK)
# --------------------------------------------------------------------------- #
def test_recommend_tool_offline(local_settings: Settings) -> None:
    from next_best_action.agent.tools import recommend_next_best_action

    # Default (no persona) resolves the seed's demo-bank identity, entitled to this customer.
    result = recommend_next_best_action(
        "cust-sg-bank-1",
        market="SG",
        vertical="banking",
        settings=local_settings,
    )
    assert result["requires_human_review"] is True
    assert result["recommendations"], "expected at least one recommendation"
    assert "google.adk" not in sys.modules


def test_recommend_tool_denies_cross_tenant(local_settings: Settings) -> None:
    """The fail-closed cross-tenant ACL survives the agent tool path."""
    from next_best_action.agent.tools import recommend_next_best_action

    # The "other-tenant" persona must not be able to pull a demo-bank customer.
    with pytest.raises(AuthorizationError):
        recommend_next_best_action(
            "cust-sg-bank-1",
            market="SG",
            vertical="banking",
            persona="other-tenant",
            settings=local_settings,
        )


# --------------------------------------------------------------------------- #
# The agent-card endpoint end-to-end (local stack)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, local_settings: Settings) -> TestClient:
    container = Container(local_settings)
    monkeypatch.setattr(deps, "get_container", lambda: container)
    return TestClient(app, client=LOOPBACK_PEER)


def test_agent_card_endpoint(client: TestClient) -> None:
    response = client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "next-best-action"
    assert {s["id"] for s in body["skills"]} == _EXPECTED_SKILLS


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
