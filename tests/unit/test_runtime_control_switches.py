"""The cheap runtime controls each have a switch, default on, and behave as a user expects.

The fleet's runtime-control contract (2026-09-24): the guardrail, PII redaction and review
routing are each switched by one environment variable read in three states; off binds a
disabled adapter and says so at startup; on under a networked profile refuses to boot without
the configuration it needs; and every caller that hands a recommendation set to the router
reports what happened to the hand-off.

A recommendation request carries no free text from the user, so there is no ``input_redacted``
disclosure here; the redactor is still tuned against false positives, because what it redacts
is offer, policy and profile text on its way to the model, the trace and the audit trail.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER, _settings
from typer.testing import CliRunner

from next_best_action.adapters.controls import (
    DisabledGuardrail,
    DisabledRedaction,
    DisabledReviewRouter,
    RecordingReviewRouter,
    ReviewRouting,
)
from next_best_action.adapters.gcp.dlp_redaction import DlpRedactionAdapter
from next_best_action.adapters.local.redaction import LocalRegexRedactionAdapter
from next_best_action.agent.tools import recommend_next_best_action
from next_best_action.api import app as app_module
from next_best_action.api import deps
from next_best_action.cli.main import app as cli_app
from next_best_action.config import (
    GUARDRAIL_ENV,
    HUMAN_REVIEW_URL_ENV,
    PII_REDACTION_ENV,
    REVIEW_ROUTING_ENV,
    Container,
    ControlSwitches,
    Settings,
    build_container,
    warn_switched_off,
)
from next_best_action.domain.identity import Principal
from next_best_action.domain.models import (
    Market,
    RecommendationRequest,
    RecommendationSet,
    Vertical,
)
from next_best_action.envread import ConfiguredEmptyError
from next_best_action.mcp.server import build_handlers

_SWITCHES = (GUARDRAIL_ENV, PII_REDACTION_ENV, REVIEW_ROUTING_ENV)
_PROFILE_ENV = "MKT_NBA_PROFILE"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*_SWITCHES, HUMAN_REVIEW_URL_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(_PROFILE_ENV, "local")


# --------------------------------------------------------------------------- #
# Three states
# --------------------------------------------------------------------------- #
def test_every_control_is_on_when_nothing_is_said() -> None:
    assert Settings.load().controls == ControlSwitches(True, True, True)


@pytest.mark.parametrize("name", _SWITCHES)
def test_a_control_switched_off_is_off(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "false")
    assert Settings.load().controls.switched_off() == (name,)


@pytest.mark.parametrize("name", _SWITCHES)
def test_an_emptied_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "")
    with pytest.raises(ConfiguredEmptyError, match=name):
        Settings.load()


@pytest.mark.parametrize("name", _SWITCHES)
def test_an_unrecognised_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "sometimes")
    with pytest.raises(ValueError, match=name):
        Settings.load()


# --------------------------------------------------------------------------- #
# Off binds the disabled adapter, and says so once
# --------------------------------------------------------------------------- #
def test_off_binds_the_disabled_adapters() -> None:
    settings = replace(_settings("local"), controls=ControlSwitches(False, False, False))
    container = Container(settings)
    assert isinstance(container.guardrail, DisabledGuardrail)
    assert isinstance(container.redaction, DisabledRedaction)
    assert isinstance(container.review_router, DisabledReviewRouter)


def test_on_binds_the_profile_adapters() -> None:
    container = Container(_settings("local"))
    assert not isinstance(container.guardrail, DisabledGuardrail)
    assert not isinstance(container.redaction, DisabledRedaction)
    assert not isinstance(container.review_router, DisabledReviewRouter)


def test_a_process_with_a_control_off_says_so_once(caplog: pytest.LogCaptureFixture) -> None:
    warn_switched_off.cache_clear()
    settings = replace(_settings("local"), controls=ControlSwitches(guardrail=False))
    with caplog.at_level(logging.WARNING, logger="next_best_action.config"):
        build_container(settings)
        build_container(settings)
    lines = [r for r in caplog.records if GUARDRAIL_ENV in r.getMessage()]
    assert len(lines) == 1


# --------------------------------------------------------------------------- #
# On has to work: checked at boot under a networked profile
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", ["gcp", "platform"])
def test_routing_on_without_a_console_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    monkeypatch.setenv(_PROFILE_ENV, profile)
    with pytest.raises(ConfiguredEmptyError, match=HUMAN_REVIEW_URL_ENV):
        Settings.load()


def test_routing_on_under_gcp_with_a_console_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(HUMAN_REVIEW_URL_ENV, "https://review.example.test")
    assert Settings.load().controls.review_routing is True


def test_routing_stated_off_under_gcp_needs_no_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    assert Settings.load().controls.review_routing is False


def test_the_local_profile_needs_no_console() -> None:
    assert Settings.load().controls.review_routing is True


def test_the_model_armor_guardrail_on_without_a_template_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(HUMAN_REVIEW_URL_ENV, "https://review.example.test")
    shipped = Path("config/settings.yaml").read_text(encoding="utf-8")
    emptied = shipped.replace("template_id: mkt-nba-guardrail", 'template_id: ""')
    assert emptied != shipped
    path = tmp_path / "settings.yaml"
    path.write_text(emptied, encoding="utf-8")
    with pytest.raises(ConfiguredEmptyError, match=GUARDRAIL_ENV):
        Settings.load(path)
    monkeypatch.setenv(GUARDRAIL_ENV, "false")
    assert Settings.load(path).controls.guardrail is False


# --------------------------------------------------------------------------- #
# The four routing outcomes
# --------------------------------------------------------------------------- #
class _Accepting:
    def route(self, result: object, *, maker: str, tenant: str = "") -> None:
        return None


class _Refusing:
    def route(self, result: object, *, maker: str, tenant: str = "") -> None:
        raise ConnectionError("console unreachable")


def test_routing_outcomes_take_each_of_their_four_values() -> None:
    nothing_required = RecordingReviewRouter(_Accepting())
    assert nothing_required.outcome is ReviewRouting.NOT_REQUIRED

    routed = RecordingReviewRouter(_Accepting())
    routed.route(object(), maker="m")  # type: ignore[arg-type]
    assert routed.outcome is ReviewRouting.ROUTED

    off = RecordingReviewRouter(DisabledReviewRouter(Settings()))
    off.route(object(), maker="m")  # type: ignore[arg-type]
    assert off.outcome is ReviewRouting.OFF

    failed = RecordingReviewRouter(_Refusing())
    failed.route(object(), maker="m")  # type: ignore[arg-type]
    assert failed.outcome is ReviewRouting.FAILED


def test_a_failed_hand_off_is_reported_and_logged_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failed = RecordingReviewRouter(_Refusing())
    with caplog.at_level(logging.WARNING, logger="next_best_action.adapters.controls"):
        failed.route(object(), maker="m")  # type: ignore[arg-type]
    assert failed.outcome is ReviewRouting.FAILED
    assert "ConnectionError" in caplog.text


# --------------------------------------------------------------------------- #
# Every caller reports the hand-off: API, agent tool, MCP, CLI
# --------------------------------------------------------------------------- #
_BODY = {"customer_id": "cust-sg-bank-1", "market": "SG", "vertical": "banking"}


def _container_with(controls: ControlSwitches | None = None) -> Container:
    return Container(replace(_settings("local"), controls=controls or ControlSwitches()))


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Container]]:
    holder = {"container": _container_with()}
    monkeypatch.setattr(deps, "get_container", lambda: holder["container"])
    yield holder


def _post(holder: dict[str, Container]) -> dict[str, Any]:
    with TestClient(app_module.app, client=LOOPBACK_PEER) as client:
        response = client.post("/v1/recommend", json=_BODY)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_the_api_reports_a_routed_set(served: dict[str, Container]) -> None:
    body = _post(served)
    assert body["requires_human_review"] is True
    assert body["review_routing"] == "routed"


def test_the_api_reports_routing_off(served: dict[str, Container]) -> None:
    served["container"] = _container_with(ControlSwitches(review_routing=False))
    assert _post(served)["review_routing"] == "off"


def test_the_api_reports_a_failed_hand_off_instead_of_hiding_it(
    served: dict[str, Container], monkeypatch: pytest.MonkeyPatch
) -> None:
    container = served["container"]
    monkeypatch.setattr(container, "review_router", _Refusing())
    body = _post(served)
    assert body["review_routing"] == "failed"
    assert body["requires_human_review"] is True


def test_the_agent_tool_reports_the_hand_off() -> None:
    settings = replace(_settings("local"), controls=ControlSwitches(review_routing=False))
    payload = recommend_next_best_action("cust-sg-bank-1", settings=settings)
    assert payload["review_routing"] == "off"
    assert (
        recommend_next_best_action("cust-sg-bank-1", settings=_settings("local"))["review_routing"]
        == "routed"
    )


def test_the_mcp_recommend_handler_reports_the_hand_off(
    served: dict[str, Container], monkeypatch: pytest.MonkeyPatch
) -> None:
    # MCP stdio verifies no end user, so its principal carries no tenant and a real seeded
    # customer is refused before any hand-off (mcp/server.py). What is under test is that the
    # handler reports the outcome of the router it handed the set to, so the service is a
    # stand-in that routes a real, locally assembled set.
    assembled = deps.make_recommendation_service(served["container"]).recommend(
        RecommendationRequest(
            customer_id="cust-sg-bank-1", market=Market.SG, vertical=Vertical.BANKING
        ),
        Principal(subject="t", tenant="demo-bank", source="test"),
    )

    class _Routes:
        def __init__(self, review_router: Any) -> None:
            self._router = review_router

        def recommend(self, request: object, principal: object) -> RecommendationSet:
            self._router.route(assembled, maker="mcp:test")
            return assembled

    monkeypatch.setattr(
        deps, "make_recommendation_service", lambda _c, *, review_router: _Routes(review_router)
    )
    monkeypatch.setattr(served["container"], "review_router", _Refusing())
    payload = build_handlers("mcp:test")["recommend"](
        customer_id="cust-sg-bank-1", market="SG", vertical="banking"
    )
    assert payload["review_routing"] == "failed"
    assert payload["id"] == assembled.id


def test_the_cli_states_the_hand_off_in_plain_words(served: dict[str, Container]) -> None:
    served["container"] = _container_with(ControlSwitches(review_routing=False))
    result = CliRunner().invoke(cli_app, ["recommend", "cust-sg-bank-1"])
    assert result.exit_code == 0, result.output
    assert "Review routing: off" in result.output
    assert "not queued for review" in result.output


# --------------------------------------------------------------------------- #
# Redaction tuned against false positives
# --------------------------------------------------------------------------- #
_BENIGN = (
    "recommend customer=cust-sg-bank-1 market=SG vertical=banking",
    "Merlion Rewards Credit Card (FICTIONAL): annual fee waived above SGD 30000 spend",
    "Sakura Time Deposit minimum placement JPY 1000000 for 12 months",
    "Outback Variable Home Loan requires a deposit of AUD 90000000 under APRA APG 223",
    "A single transfer of S$ 80000000 into the Priority Wealth Upgrade",
    "Consent captured on 2026-03-31 under PDPA section 13 for offer-sg-bank-03",
    "Spam Act 2003 s16 and the DNC Register; ranked 3 of 12 at propensity 0.82",
    "Minimum balance S$50,000, reviewed 2025-11-01, 15 business days to respond",
)


@pytest.mark.parametrize("text", _BENIGN)
def test_benign_marketing_text_passes_the_redactor_unchanged(text: str) -> None:
    assert LocalRegexRedactionAdapter(_settings("local")).redact(text).text == text


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("NRIC S1234567D on file", "[SG_NRIC_FIN]"),
        ("write to jane.tan@example.com", "[EMAIL_ADDRESS]"),
        ("call +65 9123 4567 today", "[PHONE_NUMBER]"),
        ("call 81234567 today", "[SG_PHONE]"),
    ],
)
def test_true_personal_data_is_still_masked(text: str, masked: str) -> None:
    assert masked in LocalRegexRedactionAdapter(_settings("local")).redact(text).text


def test_the_inline_dlp_config_is_tuned_against_false_positives() -> None:
    adapter = DlpRedactionAdapter(_settings("local"))
    inspect = adapter._inline_inspect_config()
    assert inspect["min_likelihood"] == "LIKELY"
    assert all(c["likelihood"] == "VERY_LIKELY" for c in inspect["custom_info_types"])
    exclusion = inspect["rule_set"][0]
    assert exclusion["info_types"] == [{"name": "PERSON_NAME"}]
    pattern = exclusion["rules"][0]["exclusion_rule"]["regex"]["pattern"]
    assert "Merlion" in pattern and "APRA" in pattern
    transformation = adapter._inline_deidentify_config()["info_type_transformations"][
        "transformations"
    ][0]
    assert transformation["primitive_transformation"] == {"replace_with_info_type_config": {}}
