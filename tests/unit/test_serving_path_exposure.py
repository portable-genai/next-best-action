"""The loopback bound is a property of the APP OBJECT, and this repo had no other place for it.

Every other repo in the fleet at least called ``resolve_bind_host`` in a ``main()``; this one
has no entry point at all. The Dockerfile CMD is
``exec uvicorn next_best_action.api.app:app --host 0.0.0.0 --port ${PORT}`` and the Makefile
``run-api`` target serves the same object, so nothing bounded the unauthenticated posture
anywhere. Executed before the guard existed: a peer at 203.0.113.7 got ``200`` on
``GET /v1/personas`` with the complete seeded-persona list (subjects, tenants and entitlement
groups) off an unauthenticated ``local`` deployment.

Both directions are proved here, because a guard that refuses everybody would satisfy the
first claim while breaking the offline demo it exists to protect, and would be reverted:

* an off-loopback peer is refused with ``503`` before any route or dependency runs, and
* a loopback peer still gets the seeded personas and the working local demo.

The control is the last pair: a VERIFYING identity binding stands the guard down, so
"everything refuses a LAN peer" is not true for the boring reason that the guard is always on.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from next_best_action.api import app as app_module
from next_best_action.api import deps

_PROFILE_ENV = "MKT_NBA_PROFILE"
_INSECURE_DEMO_ENV = "MKT_NBA_ALLOW_INSECURE_DEMO"

#: A peer on the LAN. RFC 5737 documentation address: no real host, and obviously fictional.
LAN_PEER = ("203.0.113.7", 51234)

#: Everything the app serves without a request body. The unauthenticated posture must refuse
#: ALL of it, including the two routes that need no identity at all.
UNAUTHENTICATED_ROUTES: tuple[str, ...] = (
    "/healthz",
    "/v1/personas",
    "/.well-known/agent-card.json",
)


@pytest.fixture
def rebuilt_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """Re-import the API module under a chosen profile, and restore it on teardown.

    The posture is decided at import (that is what makes it a boot-time property of the app
    object), so changing it means rebuilding the module rather than patching afterwards.
    """
    yield app_module
    monkeypatch.undo()
    importlib.reload(app_module)


def _under_profile(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, profile: str | None
) -> ModuleType:
    if profile is None:
        monkeypatch.delenv(_PROFILE_ENV, raising=False)
    else:
        monkeypatch.setenv(_PROFILE_ENV, profile)
    monkeypatch.delenv(_INSECURE_DEMO_ENV, raising=False)
    return importlib.reload(module)


@pytest.mark.parametrize("path", UNAUTHENTICATED_ROUTES)
def test_a_lan_peer_is_refused_before_any_route_runs(path: str) -> None:
    """The exact defect: ``GET /v1/personas`` used to answer 200 with the seeded personas."""
    response = TestClient(app_module.app, client=LAN_PEER).get(path)
    assert response.status_code == 503, f"{path} answered {response.status_code}"
    detail = response.json()["detail"]
    assert "non-loopback peer" in detail
    assert "203.0.113.7" in detail


def test_the_refusal_names_the_documented_opt_in_so_it_is_actionable() -> None:
    response = TestClient(app_module.app, client=LAN_PEER).get("/v1/personas")
    assert _INSECURE_DEMO_ENV in response.json()["detail"]


@pytest.mark.parametrize("path", UNAUTHENTICATED_ROUTES)
def test_a_loopback_peer_still_gets_the_offline_demo(path: str) -> None:
    """The other direction. A guard that breaks local development would simply be reverted."""
    assert TestClient(app_module.app, client=LOOPBACK_PEER).get(path).status_code == 200


def test_the_loopback_peer_still_gets_the_whole_seeded_persona_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """The picker the local UI needs is intact; only the LAN is cut off from it."""
    monkeypatch.setenv("MKT_NBA_PROFILE", "local")
    deps.get_container.cache_clear()
    personas = TestClient(app_module.app, client=LOOPBACK_PEER).get("/v1/personas").json()
    assert [p["id"] for p in personas] == ["analyst", "approver", "auditor", "other-tenant"]


def test_a_forwarding_header_disqualifies_even_a_loopback_peer() -> None:
    """A proxy has already rewritten the scope peer, so the header's presence is disqualifying."""
    response = TestClient(app_module.app, client=LOOPBACK_PEER).get(
        "/v1/personas", headers={"X-Forwarded-For": "127.0.0.1"}
    )
    assert response.status_code == 503
    assert "forwarding header" in response.json()["detail"]


def test_the_documented_opt_in_restores_service_to_a_lan_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator may accept the exposure explicitly; nothing else may accept it for them."""
    monkeypatch.setenv(_INSECURE_DEMO_ENV, "1")
    assert TestClient(app_module.app, client=LAN_PEER).get("/v1/personas").status_code == 200


def test_the_shipped_entry_points_serve_the_app_object() -> None:
    """There is no ``main()`` here at all, so the app object is the only place the bound fits."""
    with open("Dockerfile", encoding="utf-8") as handle:
        dockerfile = handle.read()
    with open("Makefile", encoding="utf-8") as handle:
        makefile = handle.read()
    assert "next_best_action.api.app:app" in dockerfile
    assert "--host 0.0.0.0" in dockerfile
    assert "run-api" in makefile


def test_an_unconsented_deployment_refuses_a_lan_peer_and_names_itself(
    rebuilt_app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset is not consent: a deploy whose profile variable went missing is bounded too."""
    module = _under_profile(rebuilt_app, monkeypatch, None)
    response = TestClient(module.app, client=LAN_PEER).get("/healthz")
    assert response.status_code == 503
    # The refusal names the posture, so an operator can tell an unconfigured deployment from a
    # deliberate offline demo without reading the source.
    assert "unconfigured" in response.json()["detail"]


def test_a_verifying_identity_binding_stands_the_guard_down(
    rebuilt_app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: the managed profile verifies an IAP assertion, so it may be reached.

    Without this the refusals above would be satisfied by a guard that is simply always on,
    which is not a working service and would prove nothing about the derivation.
    """
    module = _under_profile(rebuilt_app, monkeypatch, "gcp")
    assert TestClient(module.app, client=LAN_PEER).get("/healthz").status_code == 200


def test_an_unimplemented_identity_binding_is_bounded_like_any_other_no_auth_posture(
    rebuilt_app: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``onprem`` is a placeholder that resolves nobody, so it authenticates nobody."""
    module = _under_profile(rebuilt_app, monkeypatch, "onprem")
    response = TestClient(module.app, client=LAN_PEER).get("/healthz")
    assert response.status_code == 503
    assert "'onprem'" in response.json()["detail"]
