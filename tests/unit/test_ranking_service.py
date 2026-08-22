"""Unit tests for the deterministic RankingService."""

from __future__ import annotations

from next_best_action.domain.models import (
    ConsentChannel,
    ConsentDecision,
    EligibilityOutcome,
    EligibilityResult,
    Market,
    Offer,
    OfferKind,
    PropensitySignal,
    Vertical,
)
from next_best_action.domain.ranking_service import RankingService


def _offer(oid: str, value: float) -> Offer:
    return Offer(
        id=oid,
        name=oid,
        kind=OfferKind.PRODUCT,
        market=Market.SG,
        vertical=Vertical.BANKING,
        base_value=value,
    )


def _elig(oid: str, eligible: bool = True) -> EligibilityResult:
    return EligibilityResult(
        offer_id=oid,
        outcome=EligibilityOutcome.ELIGIBLE if eligible else EligibilityOutcome.INELIGIBLE,
    )


def _consent(oid: str, allowed: bool = True) -> ConsentDecision:
    return ConsentDecision(offer_id=oid, allowed=allowed, channel=ConsentChannel.EMAIL)


def _prop(oid: str, score: float) -> PropensitySignal:
    return PropensitySignal(offer_id=oid, score=score)


def _rank(offers, elig, consent, prop):
    return RankingService().rank(
        customer_id="c1",
        market=Market.SG,
        vertical=Vertical.BANKING,
        offers=offers,
        eligibility={e.offer_id: e for e in elig},
        consent={c.offer_id: c for c in consent},
        propensity={p.offer_id: p for p in prop},
    )


def test_ranks_by_combined_score_descending():
    offers = [_offer("a", 100.0), _offer("b", 100.0)]
    ranking = _rank(
        offers,
        [_elig("a"), _elig("b")],
        [_consent("a"), _consent("b")],
        [_prop("a", 0.9), _prop("b", 0.2)],
    )
    assert [o.offer_id for o in ranking.offers] == ["a", "b"]
    assert ranking.offers[0].rank == 1 and ranking.offers[1].rank == 2


def test_excludes_ineligible_and_unconsented():
    offers = [_offer("a", 100.0), _offer("inelig", 100.0), _offer("noconsent", 100.0)]
    ranking = _rank(
        offers,
        [_elig("a"), _elig("inelig", eligible=False), _elig("noconsent")],
        [_consent("a"), _consent("inelig"), _consent("noconsent", allowed=False)],
        [_prop("a", 0.5), _prop("inelig", 0.9), _prop("noconsent", 0.9)],
    )
    assert [o.offer_id for o in ranking.offers] == ["a"]


def test_value_is_min_max_normalised():
    offers = [_offer("hi", 200.0), _offer("lo", 0.0)]
    ranking = RankingService(propensity_weight=0.0, value_weight=1.0).rank(
        customer_id="c1",
        market=Market.SG,
        vertical=Vertical.BANKING,
        offers=offers,
        eligibility={"hi": _elig("hi"), "lo": _elig("lo")},
        consent={"hi": _consent("hi"), "lo": _consent("lo")},
        propensity={"hi": _prop("hi", 0.0), "lo": _prop("lo", 0.0)},
    )
    by_id = {o.offer_id: o for o in ranking.offers}
    assert by_id["hi"].value_score == 1.0
    assert by_id["lo"].value_score == 0.0


def test_min_score_floor_drops_weak_offers():
    offers = [_offer("a", 100.0), _offer("b", 100.0)]
    ranking = RankingService(min_score=0.5).rank(
        customer_id="c1",
        market=Market.SG,
        vertical=Vertical.BANKING,
        offers=offers,
        eligibility={"a": _elig("a"), "b": _elig("b")},
        consent={"a": _consent("a"), "b": _consent("b")},
        propensity={"a": _prop("a", 0.9), "b": _prop("b", 0.0)},
    )
    # b: 0.6*0 + 0.4*value(1.0 since equal values) = 0.4 < 0.5 floor => dropped.
    assert [o.offer_id for o in ranking.offers] == ["a"]


def test_stable_tie_break_by_offer_id():
    offers = [_offer("z", 100.0), _offer("a", 100.0)]
    ranking = _rank(
        offers,
        [_elig("z"), _elig("a")],
        [_consent("z"), _consent("a")],
        [_prop("z", 0.5), _prop("a", 0.5)],
    )
    assert [o.offer_id for o in ranking.offers] == ["a", "z"]


def test_is_deterministic():
    offers = [_offer("a", 100.0), _offer("b", 50.0)]
    args = (
        offers,
        [_elig("a"), _elig("b")],
        [_consent("a"), _consent("b")],
        [_prop("a", 0.5), _prop("b", 0.5)],
    )
    assert _rank(*args) == _rank(*args)
