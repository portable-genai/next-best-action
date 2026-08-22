"""Unit tests for the deterministic CandidateFilterService."""

from __future__ import annotations

from next_best_action.domain.candidate_service import CandidateFilterService
from next_best_action.domain.models import Customer, Market, Offer, OfferKind, Vertical


def _offer(oid: str, value: float, stock: int | None = None, excluded=()) -> Offer:
    return Offer(
        id=oid,
        name=oid,
        kind=OfferKind.PRODUCT,
        market=Market.SG,
        vertical=Vertical.BANKING,
        base_value=value,
        stock=stock,
        excluded_if_held=excluded,
    )


def _customer(holdings=()) -> Customer:
    return Customer(id="c1", market=Market.SG, vertical=Vertical.BANKING, holdings=tuple(holdings))


def test_scopes_to_market_and_vertical():
    other = Offer(
        id="b", name="b", kind=OfferKind.PRODUCT, market=Market.JP, vertical=Vertical.BANKING
    )
    catalog = [_offer("a", 10.0), other]
    cs = CandidateFilterService().filter(_customer(), catalog)
    assert [o.id for o in cs.offers] == ["a"]


def test_suppresses_held_and_conflicting_offers():
    catalog = [
        _offer("held", 10.0),
        _offer("conflict", 20.0, excluded=("held",)),
        _offer("ok", 5.0),
    ]
    cs = CandidateFilterService().filter(_customer(holdings=["held"]), catalog)
    assert [o.id for o in cs.offers] == ["ok"]


def test_drops_out_of_stock_retail_offers():
    catalog = [_offer("in", 10.0, stock=3), _offer("out", 20.0, stock=0), _offer("untracked", 5.0)]
    cs = CandidateFilterService().filter(_customer(), catalog)
    assert "out" not in [o.id for o in cs.offers]
    assert {"in", "untracked"} == {o.id for o in cs.offers}


def test_stable_order_by_value_then_id():
    catalog = [_offer("z", 10.0), _offer("a", 10.0), _offer("hi", 50.0)]
    cs = CandidateFilterService().filter(_customer(), catalog)
    assert [o.id for o in cs.offers] == ["hi", "a", "z"]


def test_is_deterministic():
    catalog = [_offer("a", 10.0), _offer("b", 20.0)]
    svc = CandidateFilterService()
    first = svc.filter(_customer(), catalog)
    second = svc.filter(_customer(), catalog)
    assert first == second
