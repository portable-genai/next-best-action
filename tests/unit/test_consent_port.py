"""Consent-port tests: one Mkt6 contract, with local parity and managed fail-closed wiring."""

from __future__ import annotations

from dataclasses import replace

import pytest
from consent_preference_kit import ConsentQuery

from next_best_action.adapters.gcp.consent import RemoteConsentAdapter
from next_best_action.config import Settings
from next_best_action.ports.consent import ConsentUnavailableError


def _query(subject: str, channel: str, *, tenant: str = "demo-bank") -> ConsentQuery:
    return ConsentQuery(
        tenant=tenant,
        subject_id=subject,
        purpose="marketing",
        channel=channel,
        market="SG",
        vertical="banking",
    )


def test_local_adapter_uses_canonical_wire_types_and_is_deterministic(local_container) -> None:
    query = _query("cust-sg-bank-1", "email")
    first = local_container.consent.decide(query)
    second = local_container.consent.decide(query)
    assert first == second
    assert first.allowed
    assert first.id.startswith("cd-")
    assert first.citations


def test_local_adapter_maps_voice_to_the_fictional_phone_opt_out(local_container) -> None:
    decision = local_container.consent.decide(_query("cust-sg-bank-1", "voice"))
    assert not decision.allowed
    assert "channel_opted_out" in decision.reasons


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        (_query("not-known", "email"), "tenant_unresolved"),
        (_query("cust-sg-bank-1", "post"), "consent_unknown"),
        (_query("cust-sg-bank-1", "email", tenant="other-bank"), "tenant_unresolved"),
    ],
)
def test_local_adapter_denies_unknown_or_mismatched_inputs(local_container, query, reason) -> None:
    decision = local_container.consent.decide(query)
    assert not decision.allowed
    assert reason in decision.reasons


@pytest.mark.parametrize(
    "change",
    [
        {"purpose": "service"},
        {"market": "AU"},
        {"vertical": "online_retail"},
    ],
)
def test_local_adapter_denies_a_query_outside_the_fixture_scope(local_container, change) -> None:
    query = replace(_query("cust-sg-bank-1", "email"), **change)
    decision = local_container.consent.decide(query)
    assert not decision.allowed
    assert "market_consent_rule_unsatisfied" in decision.reasons


def test_managed_adapter_refuses_an_unconfigured_store() -> None:
    adapter = RemoteConsentAdapter(Settings(profile="gcp", consent_url=""))
    with pytest.raises(ConsentUnavailableError, match="MKT_CONSENT_STORE_URL"):
        adapter.decide(_query("cust-sg-bank-1", "email"))


def test_managed_adapter_refuses_an_unconfigured_oidc_audience() -> None:
    adapter = RemoteConsentAdapter(
        Settings(profile="gcp", consent_url="https://mkt6.example.test", consent_audience="")
    )
    with pytest.raises(ConsentUnavailableError, match="MKT_CONSENT_STORE_AUDIENCE"):
        adapter.decide(_query("cust-sg-bank-1", "email"))


def test_managed_adapter_passes_a_lazy_audience_bound_token_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    class FakeClient:
        def __init__(self, base_url, *, token_provider):
            captured["base_url"] = base_url
            captured["token_provider"] = token_provider

        def decide(self, query, *, actor):
            captured["actor"] = actor
            return "decision"

    monkeypatch.setattr("next_best_action.adapters.gcp.consent.ConsentClient", FakeClient)
    monkeypatch.setattr(
        RemoteConsentAdapter,
        "_id_token",
        staticmethod(lambda audience: f"token-for:{audience}"),
    )
    adapter = RemoteConsentAdapter(
        Settings(
            profile="gcp",
            consent_url="https://mkt6.example.test",
            consent_audience="https://mkt6.internal.example",
        )
    )

    assert adapter.decide(_query("cust-sg-bank-1", "email")) == "decision"
    assert captured["base_url"] == "https://mkt6.example.test"
    assert captured["actor"] == "next-best-action"
    assert captured["token_provider"]() == "token-for:https://mkt6.internal.example"


class _ConsentReply:
    def __init__(self, decision=None, error: Exception | None = None) -> None:
        self._decision = decision
        self._error = error

    def decide(self, query):
        if self._error is not None:
            raise self._error
        return self._decision


def _service_with_consent(local_container, consent):
    from next_best_action.domain.recommendation_service import RecommendationService

    return RecommendationService(
        recommendations=local_container.recommendation,
        knowledge_base=local_container.knowledge_base,
        llm=local_container.llm,
        guardrail=local_container.guardrail,
        redaction=local_container.redaction,
        tracer=local_container.tracer,
        audit=local_container.audit,
        consent=consent,
    )


def _recommend(service):
    from next_best_action.domain.identity import Principal
    from next_best_action.domain.models import Market, RecommendationRequest, Vertical

    return service.recommend(
        RecommendationRequest(
            customer_id="cust-sg-bank-1", market=Market.SG, vertical=Vertical.BANKING
        ),
        Principal(subject="reviewer", tenant="demo-bank", source="test"),
    )


@pytest.mark.parametrize(
    "mismatch",
    [
        {"tenant": "other-bank"},
        {"subject_id": "other-subject"},
        {"purpose": "service"},
        {"channel": "sms"},
        {"market": "AU"},
        {"vertical": "online_retail"},
    ],
)
def test_orchestrator_refuses_an_allow_not_bound_to_its_query(local_container, mismatch) -> None:
    canonical = local_container.consent.decide(_query("cust-sg-bank-1", "email"))
    result = _recommend(
        _service_with_consent(local_container, _ConsentReply(replace(canonical, **mismatch)))
    )
    assert not result.recommendations
    assert result.consent_suppressed
    assert any("response_scope_mismatch" in item.reason for item in result.consent_suppressed)


def test_orchestrator_refuses_allow_with_a_denying_reason(local_container) -> None:
    canonical = local_container.consent.decide(_query("cust-sg-bank-1", "email"))
    poisoned = replace(canonical, reasons=("consent_granted", "new_unknown_reason"))
    result = _recommend(_service_with_consent(local_container, _ConsentReply(poisoned)))
    assert not result.recommendations
    assert any("denying_reasons_present" in item.reason for item in result.consent_suppressed)


@pytest.mark.parametrize("error", [ValueError("bad credential"), NotImplementedError("exit seam")])
def test_orchestrator_degrades_any_missing_consent_answer_to_denial(local_container, error) -> None:
    result = _recommend(_service_with_consent(local_container, _ConsentReply(error=error)))
    assert not result.recommendations
    assert result.consent_suppressed
    assert all(not item.allowed for item in result.consent_suppressed)


def test_orchestrator_preserves_mkt6_decision_identity(local_container) -> None:
    canonical = local_container.consent.decide(_query("cust-sg-bank-1", "email"))
    canonical = replace(canonical, as_of="2026-08-13T00:00:00Z")
    result = _recommend(_service_with_consent(local_container, _ConsentReply(canonical)))
    email_decisions = [
        item.consent
        for item in result.recommendations
        if item.consent.channel and item.consent.channel.value == "email"
    ]
    assert email_decisions
    assert all(item.decision_id == canonical.id for item in email_decisions)
    assert all(item.as_of == canonical.as_of for item in email_decisions)
    assert all(
        item.citation and item.citation.source_id == canonical.id for item in email_decisions
    )


def test_denied_mkt6_decision_is_retained_in_the_worm_audit(local_container) -> None:
    canonical = local_container.consent.decide(_query("cust-sg-bank-1", "email"))
    denied = replace(
        canonical,
        id="cd-canonical-denial",
        outcome="denied",
        reasons=("consent_withdrawn",),
    )

    result = _recommend(_service_with_consent(local_container, _ConsentReply(denied)))

    assert not result.recommendations
    assert any(c.source_id == denied.id for c in result.citations)
    events = local_container.audit.read_all()
    assert any(
        citation.get("source_id") == denied.id for citation in events[-1].get("citations", [])
    )


def test_orchestrator_refuses_an_unknown_required_channel(local_container) -> None:
    adapter = local_container.recommendation
    original = adapter.catalog
    adapter.catalog = lambda market, vertical: tuple(
        replace(offer, required_consent_channel="carrier_pigeon")
        for offer in original(market, vertical)
    )
    result = _recommend(_service_with_consent(local_container, local_container.consent))
    assert not result.recommendations
    assert result.consent_suppressed
    assert all(
        "unknown required consent channel" in item.reason for item in result.consent_suppressed
    )
