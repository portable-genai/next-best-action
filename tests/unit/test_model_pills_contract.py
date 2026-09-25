"""What the console's model pills state must be true of the profile the service is running.

Every served console shows two small pills at the top right of every page (owner decision,
2026-09-23; they replaced the full-width provenance banner of 2026-08-30): the model that
ANSWERED the last request, and ``Search`` when that answer used an online search tool. Before
any answer, the model pill shows the configured ``generator_model`` from ``/healthz``, with
WHERE the process runs (``runtime``) in its title. Both come from ``/healthz`` because the
browser cannot know either: a console that read its runtime from ``window.location`` would be
right until the day the deployment served through a proxy, and wrong silently after that.

The reason this is worth a test rather than a glance is what the pill is FOR. These systems
are demonstrated on a laptop and on a deployment, sometimes in the same hour, and a screenshot
of one is indistinguishable from the other. A pill that was merely present but wrong is worse
than no pill: it converts "the viewer does not know" into "the viewer has been told the wrong
thing", and the wrong thing here is whether a figure came from a managed model or from a
deterministic offline stub.

So the service assertions below are about AGREEMENT with the profile, not about presence. The
browser half is held at the end: the pills read the base this console actually serves, read
both answer headers, and the service lets a cross-origin console read them.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from next_best_action.config import Settings

CONFIG_PATH = Path("config/settings.yaml")

#: Answers that mean "no managed model produced this". Each says something different and the
#: difference is the point, which is why this is a set rather than one sentinel:
#: ``deterministic-offline-stub`` says a model-shaped port is bound to a stub;
#: ``no-model`` says there is no such port at all; ``onprem-not-implemented`` says the port
#: exists and refuses. A reviewer approving an escalation is entitled to know which they read.
_NON_MANAGED_ANSWERS = frozenset(
    {
        "deterministic-offline-stub",
        "no-model",
        "onprem-not-implemented",
        "managed-model-unavailable",
    }
)


def _for_profile(profile: str) -> Settings:
    return dataclasses.replace(Settings.load(CONFIG_PATH), profile=profile)


@pytest.mark.parametrize("profile", ["local", "live", "gcp", "onprem"])
def test_the_runtime_half_states_where_the_process_runs(profile: str) -> None:
    """``onprem`` reads ``local``, because that is its entire point.

    A managed model call does not make a process cloud-hosted. This half is about where the
    PROCESS runs and the other half is about whose model answers, and collapsing the two is how
    an on-premises deployment ends up describing itself as running on GCP.
    """
    settings = _for_profile(profile)
    assert settings.runtime == ("gcp" if profile == "gcp" else "local")


@pytest.mark.parametrize("profile", ["local", "live", "gcp", "onprem"])
def test_the_model_half_is_always_answered(profile: str) -> None:
    """A blank is not an option: the pill renders nothing rather than render a falsehood."""
    assert _for_profile(profile).generator_model.strip()


@pytest.mark.parametrize("profile", ["local", "onprem"])
def test_no_offline_profile_claims_a_managed_model(profile: str) -> None:
    """The defect that matters, stated as an assertion.

    A laptop run naming a Gemini model is precisely the confusion the pill exists to remove,
    and it is the one direction a reviewer cannot detect by looking at the page.
    """
    answer = _for_profile(profile).generator_model
    assert answer in _NON_MANAGED_ANSWERS, (
        f"the {profile!r} profile reports {answer!r}, which reads as a managed model answering "
        "a request that never left the machine"
    )


def test_the_health_contract_carries_both_halves() -> None:
    """The wire contract the console actually reads. A property nothing serves is not a contract.

    Asserted on the response MODEL rather than by calling ``/healthz`` through a test client.
    That is not a convenience: under the ``local`` posture these services deliberately refuse an
    unauthenticated non-loopback peer, so a client call here would exercise that refusal instead
    of this contract, and the refusal already has its own tests. What must not rot is that the
    two fields exist on the response the endpoint returns.
    """
    from next_best_action.api.schemas import HealthModel

    fields = set(HealthModel.model_fields)
    assert "runtime" in fields, "the console reads runtime off /healthz and the field is absent"
    assert "generator_model" in fields


def test_the_endpoint_answers_from_settings_rather_than_a_literal() -> None:
    """A pill value hard-coded at the endpoint would be right once and wrong after a rebind.

    Both halves are properties of :class:`Settings`, so the values the endpoint sends are the
    values the profile implies; this pins that they are readable and non-empty together, which
    is what the endpoint relies on.
    """
    settings = Settings.load(CONFIG_PATH)
    assert settings.runtime in {"gcp", "local"}
    assert settings.generator_model.strip()


def test_the_managed_profile_names_a_model_or_says_exactly_why_not() -> None:
    """No placeholder survives here: every answer is a model id or a stated reason.

    ``managed-model-unnamed`` used to be a real answer in twenty-five trees, and it was the
    resolver looking in the wrong place rather than the trees being silent -- most of the fleet
    pins the id in settings under a per-repository field name. It is kept only as a defensive
    fallback and no tree should reach it.
    """
    answer = _for_profile("gcp").generator_model
    assert answer != "managed-model-unnamed", (
        "the managed model id is not being resolved from anywhere: set _GENERATOR_MODEL_ATTR "
        "to the settings path holding it, or declare _MODEL on the bound adapter"
    )
    assert answer.strip()


def test_not_implemented_is_claimed_only_by_an_adapter_that_never_calls_a_model() -> None:
    """The one answer that is INFERRED rather than read, so it is the one that can be wrong.

    ``managed-not-implemented`` is reached when a tree names no settings path and its adapter
    declares no model constant. That is correct for a deployment-wired placeholder, and a LIE
    for an adapter that generates while declaring nothing.

    The check is "does it call the model API", not "does it raise". Raising was tried first and
    is too weak: it passed `soc-fraud-fusion`, which generates and also raises on bad input, and
    it had already let a real mis-classification through -- `conversation-qa-scorecard` calls
    ``generate_content`` and raises only when its model is unconfigured, and was grouped with
    the placeholders on the strength of that raise. Its model is named now.
    """
    from importlib import import_module
    from pathlib import Path as _Path

    # The MANAGED profile, not whatever the settings file defaults to. Reading the default
    # profile here made this test inert: offline it answers `deterministic-offline-stub`, so it
    # returned before checking anything, and it passed a deliberately broken tree.
    settings = _for_profile("gcp")
    if settings.generator_model != "managed-not-implemented":
        return
    from next_best_action.config import _GENERATOR_PORT

    binding = str((settings.adapters.get(_GENERATOR_PORT) or {}).get("gcp", ""))
    module = import_module(binding.partition(":")[0])
    source = _Path(module.__file__ or "").read_text()
    for call in ("generate_content", ".predict(", ".invoke("):
        assert call not in source, (
            f"{binding} reports managed-not-implemented but calls {call!r}: it generates, so "
            "the model it calls must be named rather than declared absent"
        )


UI = Path("ui")


def _code_only(source: str) -> str:
    """``source`` with ``//`` line comments and ``/* */`` blocks removed, so prose cannot pass."""
    import re as _re

    source = _re.sub(r"/\*.*?\*/", "", source, flags=_re.DOTALL)
    return "\n".join(line.split("//", 1)[0] for line in source.splitlines())


def test_the_pills_call_a_base_this_console_actually_serves() -> None:
    """The half of the contract that lives in the BROWSER, and the half that was once broken.

    Every assertion above is about the service, and all of it was true, and green, while the
    banner these pills replaced rendered nothing at all, on every page load. It was fetching
    ``/api/agent/healthz``, the same-origin route handler the service template ships. This
    console does not ship one; it calls its backend directly on ``NEXT_PUBLIC_API_BASE``. So the
    health call 404'd, took the failure branch, and the failure branch renders nothing,
    deliberately, because a pill that guessed would assert provenance it does not have. A check
    that cannot fail loudly fails as an ABSENCE, and an absence is what no reviewer notices.

    Both architectures are legitimate, so this pins AGREEMENT rather than a literal: a tree with
    ``ui/app/api/agent`` proxies through its own origin and the pills should name that path; a
    tree without one must read the same ``API_BASE`` the rest of its console reads, for health
    AND for the answer headers.
    """
    pills = _code_only((UI / "app" / "ModelPills.tsx").read_text(encoding="utf-8"))
    proxies_through_own_origin = (UI / "app" / "api" / "agent").is_dir()

    assert ('"/api/agent"' in pills) == proxies_through_own_origin, (
        "the pills name /api/agent but this console has no route handler at "
        "ui/app/api/agent, so the health call reaches nothing and the pills render nothing"
        if not proxies_through_own_origin
        else "this console ships a /api/agent route handler but the pills do not use it"
    )
    if not proxies_through_own_origin:
        assert "${API_BASE}/healthz" in pills, (
            "the pills must resolve their base the way the rest of the console does, through "
            "the NEXT_PUBLIC_API_BASE reader in ui/lib/api.ts; a second, independently spelled "
            "base is how the two drift apart again"
        )
        assert "watchAnswers(window, API_BASE" in pills, (
            "the answer headers must be read off responses from the same API_BASE"
        )


def test_the_console_shows_the_model_that_answered_as_pills_not_a_banner() -> None:
    """Two pills at the top right name the model that ANSWERED, and Search when it searched.

    The whole chain is held here from the offline gate: the pills start from ``/healthz``, read
    both answer headers through the one fetch wrapper, are mounted in the layout, and the
    service names both headers in ``Access-Control-Expose-Headers``. This console calls the
    service directly, cross-origin when standalone, and a cross-origin response hides every
    header not listed there: the pills would stay on the configured model forever with every
    node test green. ``ui/tests/answer-provenance.test.mjs`` proves the wrapper itself.
    """
    pills = _code_only((UI / "app" / "ModelPills.tsx").read_text(encoding="utf-8"))
    assert "/healthz" in pills, "the pills do not start from the service's own /healthz"
    assert "generator_model" in pills and "runtime" in pills
    watcher = (UI / "lib" / "answer-provenance.mjs").read_text(encoding="utf-8")
    for header in ('"x-answered-by"', '"x-search-used"'):
        assert header in watcher, "the pills never read " + header
    layout = (UI / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert "<ModelPills />" in layout, "the pills are not mounted on every page"
    assert not (UI / "app" / "ProvenanceBanner.tsx").exists(), "the old banner is back"
    assert (UI / "tests" / "answer-provenance.test.mjs").exists()

    from fastapi.testclient import TestClient
    from tests.conftest import LOOPBACK_PEER

    from next_best_action.api import app as app_module

    response = TestClient(app_module.app, client=LOOPBACK_PEER).get("/healthz")
    listed = response.headers.get("access-control-expose-headers", "")
    exposed = {h.strip().lower() for h in listed.split(",")}
    assert {"x-answered-by", "x-search-used"} <= exposed, (
        f"the service does not expose the answer headers to a cross-origin console: {exposed}"
    )


def _rule(css: str, selector: str) -> str:
    start = css.index(selector + " {")
    return css[start : css.index("}", start)]


def test_the_pills_are_fixed_at_the_top_right_where_a_reader_can_see_them() -> None:
    """A provenance strip that renders off-screen satisfies every other assertion in this file.

    The banner these pills replaced was hoisted 32px above the viewport by margins written for a
    console whose ``body`` carried padding this one does not: rendered on every page load, seen
    on none. The pills sidestep that whole class by being fixed to the viewport, so this asserts
    exactly that, and that the old rule is gone rather than left to be re-mounted.
    """
    css = Path("ui/app/globals.css").read_text()
    assert ".provenance-banner" not in css, "the old banner rule is back"
    block = _rule(css, ".model-pills")
    assert "position: fixed;" in block, "the pills are not fixed to the viewport"
    assert "top:" in block and "right:" in block, "the pills are not anchored top right"
    assert "bottom:" not in block and "left:" not in block
