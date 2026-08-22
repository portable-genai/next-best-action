"""API-boundary tests for server-verified identity.

Prove that the FastAPI surface resolves the audit actor from the active IdentityPort
(never a client-supplied field): an unknown ``X-Dev-Persona`` is a hard 401, the default
persona is the audit actor when no header is sent, and a selected persona becomes the
audit actor. ``deps.get_container`` is monkeypatched to a shared in-memory local container
so identity resolution and the recommendation service share one instance (and one audit
log) without mutating the environment.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from next_best_action.api import app as app_module
from next_best_action.api import deps
from next_best_action.config import Container, LocalSettings, Settings

CONFIG_PATH = "config/settings.yaml"


def _container() -> Container:
    base = Settings.load(CONFIG_PATH)
    settings = Settings(
        project_id=base.project_id,
        region=base.region,
        profile="local",
        vertical=base.vertical,
        market=base.market,
        models=base.models,
        recommendation=base.recommendation,
        knowledge_base=base.knowledge_base,
        model_armor=base.model_armor,
        logging=base.logging,
        agent_engine=base.agent_engine,
        ranking=base.ranking,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        markets=base.markets,
        adapters=base.adapters,
    )
    return Container(settings)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # One shared in-memory container: get_container() is lru_cached in production, so we
    # replace it wholesale instead of poking the cache or the environment.
    container = _container()
    monkeypatch.setattr(deps, "get_container", lambda: container)
    return TestClient(app_module.app, client=LOOPBACK_PEER)


def _recommend_body() -> dict:
    return {"customer_id": "cust-sg-bank-1", "market": "SG", "vertical": "banking"}


def test_unknown_dev_persona_is_401(client: TestClient) -> None:
    resp = client.post(
        "/v1/recommend", json=_recommend_body(), headers={"X-Dev-Persona": "does-not-exist"}
    )
    assert resp.status_code == 401


def test_default_persona_is_the_audit_actor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = deps.get_container()
    resp = client.post("/v1/recommend", json=_recommend_body())
    assert resp.status_code == 200
    events = container.audit.read_all()
    # No X-Dev-Persona sent => the first seeded persona is the verified audit actor.
    assert any(e["actor"] == "demo.analyst@bank.example" for e in events)


def test_selected_persona_is_the_audit_actor(client: TestClient) -> None:
    container = deps.get_container()
    resp = client.post(
        "/v1/recommend", json=_recommend_body(), headers={"X-Dev-Persona": "auditor"}
    )
    assert resp.status_code == 200
    events = container.audit.read_all()
    assert any(e["actor"] == "demo.auditor@bank.example" for e in events)


def test_cross_tenant_persona_is_403(client: TestClient) -> None:
    """C2 at the HTTP boundary: an other-tenant persona is denied a demo-bank customer.

    The ``other-tenant`` seeded persona resolves to tenant ``other-bank``; requesting the
    demo-bank customer ``cust-sg-bank-1`` must be a fail-closed 403 (object authorization),
    never a 200 or a 404 that would confirm the object exists.
    """
    resp = client.post(
        "/v1/recommend", json=_recommend_body(), headers={"X-Dev-Persona": "other-tenant"}
    )
    assert resp.status_code == 403


def test_same_tenant_persona_is_200(client: TestClient) -> None:
    """A same-tenant (demo-bank) persona is served the demo-bank customer."""
    resp = client.post(
        "/v1/recommend", json=_recommend_body(), headers={"X-Dev-Persona": "analyst"}
    )
    assert resp.status_code == 200


def test_personas_route_lists_seeded_personas(client: TestClient) -> None:
    resp = client.get("/v1/personas")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert {"analyst", "approver", "auditor", "other-tenant"} <= ids


def test_health_exposes_the_profile_the_operator_actually_named(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DELIBERATE local run reports local, so the UI may switch its persona picker on."""
    monkeypatch.setenv("MKT_NBA_PROFILE", "local")
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["profile"] == "local"


def test_health_reports_unconfigured_when_no_profile_was_named(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/healthz reports the EXPOSURE profile, which withholds every relaxation.

    A run that never named a profile still binds the local adapters, but it must not look
    like local to anything keying off this value: reporting local here is what switches the
    dev persona picker on. This asserted "local" until the exposure split landed.

    The `delenv` is the whole test, not scaffolding. The Makefile exports
    `MKT_NBA_PROFILE` for every target, so a version of this test that merely relied on the
    variable being absent passed under a bare `pytest` and could NEVER pass under the repo's
    own `make test`. Naming the condition here makes the test independent of who invoked it.
    """
    monkeypatch.delenv("MKT_NBA_PROFILE", raising=False)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["profile"] == "unconfigured"
