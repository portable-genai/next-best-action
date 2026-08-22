"""Fail-closed network defaults (C5), as THIS repo wires them.

The shared ``hex-service-kit`` rule is only as good as the profile string handed to it. These
prove the wiring: the localhost dev-origin fallback needs a local profile that was actually
chosen, so a deployment that forgot ``MKT_NBA_PROFILE`` gets no cross-origin trust rather than
silently trusting arbitrary local processes on a user's machine.
"""

from __future__ import annotations

import dataclasses
import importlib
from collections.abc import Callable, Iterator
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from next_best_action.api import app as app_module
from next_best_action.config import Container

_FRAME_ENV = "MKT_NBA_FRAME_ANCESTORS"


@pytest.fixture
def app_with_frame_ancestors(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[str | None], ModuleType]]:
    """Rebuild the app module with ``MKT_NBA_FRAME_ANCESTORS`` in a chosen state.

    The header value is resolved once at import, which is what makes it a boot-time posture,
    so proving the three states means re-importing. The module is restored on teardown.
    """

    def build(raw: str | None) -> ModuleType:
        if raw is None:
            monkeypatch.delenv(_FRAME_ENV, raising=False)
        else:
            monkeypatch.setenv(_FRAME_ENV, raw)
        return importlib.reload(app_module)

    yield build
    monkeypatch.undo()
    importlib.reload(app_module)


def _origins_for_profile(
    monkeypatch: pytest.MonkeyPatch, profile: str, *, explicit: bool = True
) -> list[str]:
    monkeypatch.delenv("MKT_NBA_CORS_ORIGINS", raising=False)
    base = app_module.deps.get_container().settings
    container = Container(dataclasses.replace(base, profile=profile, profile_explicit=explicit))
    monkeypatch.setattr(app_module.deps, "get_container", lambda: container)
    return app_module._cors_origins()


def test_cors_fallback_only_under_local_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _origins_for_profile(monkeypatch, "local") == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    assert _origins_for_profile(monkeypatch, "gcp") == []


def test_cors_fallback_needs_a_local_profile_that_was_actually_chosen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inherited ``local`` is not consent to trust arbitrary local processes."""
    assert _origins_for_profile(monkeypatch, "local", explicit=False) == []


def test_explicit_allowlist_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MKT_NBA_CORS_ORIGINS", "https://tenant.example")
    assert app_module._cors_origins() == ["https://tenant.example"]


def test_an_emptied_cors_allowlist_denies_instead_of_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set-and-empty is a configuration, not an omission.

    Red against a two-state read, which took the empty string for unset and handed back the
    localhost dev origins the operator had just removed.
    """
    base = app_module.deps.get_container().settings
    container = Container(dataclasses.replace(base, profile="local", profile_explicit=True))
    monkeypatch.setattr(app_module.deps, "get_container", lambda: container)
    monkeypatch.setenv("MKT_NBA_CORS_ORIGINS", "")
    assert app_module._cors_origins() == []


def test_unset_frame_ancestors_keeps_the_self_default(
    app_with_frame_ancestors: Callable[[str | None], ModuleType],
) -> None:
    module = app_with_frame_ancestors(None)
    headers = TestClient(module.app, client=LOOPBACK_PEER).get("/healthz").headers
    assert headers["content-security-policy"] == "frame-ancestors 'self'"
    assert headers["x-frame-options"] == "SAMEORIGIN"


@pytest.mark.parametrize("raw", ["", "   "])
def test_an_emptied_frame_ancestors_refuses_framing_rather_than_dropping_the_directive(
    app_with_frame_ancestors: Callable[[str | None], ModuleType], raw: str
) -> None:
    """Red before the three-state read, on both headers at once.

    The old code interpolated the empty value straight into the header, so the response
    carried ``frame-ancestors`` with an EMPTY directive, which browsers discard as a parse
    error; and the ``== "'self'"`` branch was skipped, so no ``X-Frame-Options`` went out
    either. Emptying the allowlist silently removed the clickjacking control instead of
    tightening it.
    """
    module = app_with_frame_ancestors(raw)
    headers = TestClient(module.app, client=LOOPBACK_PEER).get("/healthz").headers
    assert headers["content-security-policy"] == "frame-ancestors 'none'"
    assert headers["x-frame-options"] == "DENY"


def test_a_named_frame_ancestors_allowlist_is_used_as_configured(
    app_with_frame_ancestors: Callable[[str | None], ModuleType],
) -> None:
    module = app_with_frame_ancestors("  https://portal.example   https://admin.example  ")
    headers = TestClient(module.app, client=LOOPBACK_PEER).get("/healthz").headers
    assert headers["content-security-policy"] == (
        "frame-ancestors https://portal.example https://admin.example"
    )
    # No X-Frame-Options can express a named allowlist, so none is sent.
    assert "x-frame-options" not in headers
