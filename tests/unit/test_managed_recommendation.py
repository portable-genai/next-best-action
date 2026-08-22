"""Managed recommendation mapping tests with no SDK, credentials or network."""

from __future__ import annotations

from dataclasses import replace

import pytest

from next_best_action.adapters.gcp.recommendation import VertexRecommendationAdapter
from next_best_action.config import Settings
from next_best_action.domain.errors import UnknownCustomerError
from next_best_action.domain.models import Market, OfferKind, Vertical


def _adapter() -> VertexRecommendationAdapter:
    settings = replace(
        Settings.load("config/settings.yaml"),
        profile="gcp",
        profile_explicit=True,
        project_id="fictional-nba-project",
    )
    return VertexRecommendationAdapter(settings)


def _rows(sql: str, _parameters: object) -> list[dict[str, object]]:
    if ".customers`" in sql:
        return [
            {
                "customer_id": "cust-1",
                "tenant": "demo-bank",
                "attributes_json": '{"kyc":"verified"}',
                "holdings": ["held-1"],
                "affinities_json": '{"savings":0.8}',
            }
        ]
    if ".offers`" in sql:
        return [
            {
                "offer_id": "offer-1",
                "name": "Fictional savings offer",
                "kind": "product",
                "category": "savings",
                "base_value": 120.0,
                "required_consent_channel": "email",
                "required_attributes_json": '{"kyc":"verified"}',
                "excluded_if_held": ["held-2"],
                "stock": None,
                "evidence_summary": "approved fictional catalog row",
            }
        ]
    if ".eligibility_rules`" in sql:
        return [
            {
                "rule_id": "rule-1",
                "effect": "require",
                "attribute": "kyc",
                "value": "verified",
                "applies_to_kind": "product",
                "applies_to_category": "savings",
                "description": "KYC must be verified",
                "citation_title": "Fictional product policy",
            }
        ]
    if ".propensity_signals`" in sql:
        return [{"offer_id": "offer-1", "score": 0.77, "model_version": "fictional-v1"}]
    raise AssertionError(f"unexpected query: {sql}")


def test_managed_rows_map_to_the_same_domain_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter()
    monkeypatch.setattr(adapter, "_query", _rows)

    customer = adapter.customer("cust-1", Market.SG, Vertical.BANKING)
    offers = adapter.catalog(Market.SG, Vertical.BANKING)
    rules = adapter.eligibility_rules(Market.SG, Vertical.BANKING)
    signals = adapter.propensity(customer, offers)

    assert customer.tenant == "demo-bank"
    assert customer.attributes == {"kyc": "verified"}
    assert offers[0].kind is OfferKind.PRODUCT and offers[0].citations
    assert rules[0].citation and rules[0].citation.source_id == "rule-1"
    assert signals[0].offer_id == "offer-1" and signals[0].score == 0.77
    assert signals[0].citation and signals[0].citation.score == 0.77


def test_customer_lookup_refuses_ambiguous_or_missing_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter()
    monkeypatch.setattr(adapter, "_query", lambda *_: [])
    with pytest.raises(UnknownCustomerError, match="found 0"):
        adapter.customer("missing", Market.SG, Vertical.BANKING)


def test_customer_lookup_refuses_an_unpartitioned_row(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter()
    monkeypatch.setattr(
        adapter,
        "_query",
        lambda *_: [
            {
                "tenant": "",
                "attributes_json": {},
                "holdings": [],
                "affinities_json": {},
            }
        ],
    )
    with pytest.raises(ValueError, match="tenant partition"):
        adapter.customer("cust-1", Market.SG, Vertical.BANKING)


def test_propensity_refuses_a_partial_model_response(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter()
    monkeypatch.setattr(adapter, "_query", _rows)
    customer = adapter.customer("cust-1", Market.SG, Vertical.BANKING)
    offers = adapter.catalog(Market.SG, Vertical.BANKING)
    extra = replace(offers[0], id="offer-2")
    with pytest.raises(RuntimeError, match="offer-2"):
        adapter.propensity(customer, (*offers, extra))


def test_table_identifiers_are_validated_before_query_construction() -> None:
    base = Settings.load("config/settings.yaml")
    adapter = VertexRecommendationAdapter(
        replace(base, project_id="not/a/project", profile="gcp", profile_explicit=True)
    )
    with pytest.raises(ValueError, match="valid IDs"):
        adapter.catalog(Market.SG, Vertical.BANKING)
