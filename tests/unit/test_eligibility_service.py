"""Unit tests for the deterministic EligibilityService (suitability + availability)."""

from __future__ import annotations

from next_best_action.domain.eligibility_service import EligibilityService
from next_best_action.domain.models import (
    Customer,
    EligibilityRule,
    Market,
    Offer,
    OfferKind,
    RuleEffect,
    Vertical,
)


def _customer(attrs: dict[str, str]) -> Customer:
    return Customer(id="c1", market=Market.SG, vertical=Vertical.BANKING, attributes=attrs)


def _offer(**kw) -> Offer:
    base = dict(
        id="o1", name="o1", kind=OfferKind.PRODUCT, market=Market.SG, vertical=Vertical.BANKING
    )
    base.update(kw)
    return Offer(**base)  # type: ignore[arg-type]


def _rule(**kw) -> EligibilityRule:
    base = dict(id="r1", market=Market.SG, vertical=Vertical.BANKING)
    base.update(kw)
    return EligibilityRule(**base)  # type: ignore[arg-type]


def test_require_rule_passes_and_fails():
    svc = EligibilityService()
    rule = _rule(effect=RuleEffect.REQUIRE, attribute="kyc", value="verified")
    ok = svc.evaluate(_customer({"kyc": "verified"}), _offer(), [rule])
    assert ok.eligible
    bad = svc.evaluate(_customer({"kyc": "pending"}), _offer(), [rule])
    assert not bad.eligible
    assert "r1" in bad.failed_rule_ids


def test_exclude_rule_disqualifies():
    svc = EligibilityService()
    rule = _rule(
        id="excl",
        effect=RuleEffect.EXCLUDE,
        attribute="credit_flag",
        value="adverse",
        applies_to_category="lending",
    )
    offer = _offer(category="lending")
    res = svc.evaluate(_customer({"credit_flag": "adverse"}), offer, [rule])
    assert not res.eligible
    # A clear flag is fine.
    res_ok = svc.evaluate(_customer({"credit_flag": "clear"}), offer, [rule])
    assert res_ok.eligible


def test_exclude_rule_scoped_by_category():
    svc = EligibilityService()
    rule = _rule(
        effect=RuleEffect.EXCLUDE,
        attribute="credit_flag",
        value="adverse",
        applies_to_category="lending",
    )
    # Offer is in a different category => rule does not apply.
    deposits = _offer(category="deposits")
    res = svc.evaluate(_customer({"credit_flag": "adverse"}), deposits, [rule])
    assert res.eligible


def test_require_stock_for_retail():
    svc = EligibilityService()
    rule = _rule(market=Market.SG, vertical=Vertical.ONLINE_RETAIL, effect=RuleEffect.REQUIRE_STOCK)
    in_stock = _offer(market=Market.SG, vertical=Vertical.ONLINE_RETAIL, stock=4)
    out = _offer(market=Market.SG, vertical=Vertical.ONLINE_RETAIL, stock=0)
    cust = Customer(id="c", market=Market.SG, vertical=Vertical.ONLINE_RETAIL)
    assert svc.evaluate(cust, in_stock, [rule]).eligible
    assert not svc.evaluate(cust, out, [rule]).eligible


def test_offer_required_attributes_are_enforced():
    svc = EligibilityService()
    offer = _offer(required_attributes={"tier": "gold"})
    assert svc.evaluate(_customer({"tier": "gold"}), offer, []).eligible
    assert not svc.evaluate(_customer({"tier": "silver"}), offer, []).eligible


def test_rule_market_vertical_scope():
    svc = EligibilityService()
    # Rule for a different market should not apply.
    rule = _rule(market=Market.JP, effect=RuleEffect.REQUIRE, attribute="kyc", value="verified")
    res = svc.evaluate(_customer({"kyc": "pending"}), _offer(), [rule])
    assert res.eligible


def test_is_deterministic():
    svc = EligibilityService()
    rule = _rule(effect=RuleEffect.REQUIRE, attribute="kyc", value="verified")
    a = svc.evaluate(_customer({"kyc": "verified"}), _offer(), [rule])
    b = svc.evaluate(_customer({"kyc": "verified"}), _offer(), [rule])
    assert a == b
