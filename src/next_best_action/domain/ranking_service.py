"""RankingService — deterministic offer ranking / scoring.

The fourth deterministic engine (see the ``deterministic-domain-service`` skill): pure,
stdlib-only, replayable. Given the eligible, consented offers, each offer's propensity
signal (from the recommendation/propensity model) and the candidate offers' business value,
it computes a deterministic combined score (propensity x value) and ranks the offers. The
score that decides which offer is surfaced to a customer must be auditable, so it is code,
not an LLM guess. The LLM only explains "why recommended" after the ranking is fixed.

Determinism: same inputs -> same output. No LLM, no clock, no randomness, no network.
Weights (propensity vs value) and the tie-break are tunable fields, not magic numbers.
Business value is normalised across the candidate set so the score is a 0..1 quantity.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    Citation,
    ConsentChannel,
    ConsentDecision,
    EligibilityResult,
    Market,
    Offer,
    PropensitySignal,
    RankedOffer,
    Ranking,
    Vertical,
)


@dataclass(frozen=True, slots=True)
class RankingService:
    """Pure, deterministic ranking by ``propensity_weight*propensity + value_weight*value``.

    Weights sum to 1. ``min_score`` drops offers below a floor so a weak recommendation is
    never surfaced. Business value is min-max normalised across the candidate offers.
    """

    propensity_weight: float = 0.6
    value_weight: float = 0.4
    min_score: float = 0.0

    def rank(
        self,
        customer_id: str,
        market: Market,
        vertical: Vertical,
        offers: tuple[Offer, ...] | list[Offer],
        eligibility: dict[str, EligibilityResult],
        consent: dict[str, ConsentDecision],
        propensity: dict[str, PropensitySignal],
    ) -> Ranking:
        """Rank the offers that are eligible AND consented, by combined score."""
        eligible_offers = [
            o
            for o in offers
            if eligibility.get(o.id) is not None
            and eligibility[o.id].eligible
            and consent.get(o.id) is not None
            and consent[o.id].allowed
        ]
        value_norm = self._normalise_values(eligible_offers)

        scored: list[RankedOffer] = []
        for offer in eligible_offers:
            prop = propensity.get(offer.id)
            prop_score = prop.score if prop is not None else 0.0
            v = value_norm.get(offer.id, 0.0)
            score = self.propensity_weight * prop_score + self.value_weight * v
            if score < self.min_score:
                continue
            decision = consent[offer.id]
            scored.append(
                RankedOffer(
                    offer_id=offer.id,
                    name=offer.name,
                    kind=offer.kind,
                    rank=0,  # assigned after sort
                    score=round(score, 4),
                    propensity=round(prop_score, 4),
                    value_score=round(v, 4),
                    channel=decision.channel,
                    rationale=(
                        f"score {score:.2f} = {self.propensity_weight:.1f}*propensity "
                        f"{prop_score:.2f} + {self.value_weight:.1f}*value {v:.2f}"
                    ),
                    citations=self._citations(offer, prop, decision),
                )
            )

        # Sort by score descending, then offer id for a stable, replayable order.
        scored.sort(key=lambda r: (-r.score, r.offer_id))
        ranked = tuple(
            RankedOffer(
                offer_id=r.offer_id,
                name=r.name,
                kind=r.kind,
                rank=i + 1,
                score=r.score,
                propensity=r.propensity,
                value_score=r.value_score,
                channel=r.channel,
                rationale=r.rationale,
                citations=r.citations,
            )
            for i, r in enumerate(scored)
        )
        return Ranking(customer_id=customer_id, market=market, vertical=vertical, offers=ranked)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalise_values(offers: list[Offer]) -> dict[str, float]:
        """Min-max normalise base_value across the candidate set into 0..1."""
        if not offers:
            return {}
        values = [o.base_value for o in offers]
        lo, hi = min(values), max(values)
        if hi <= lo:
            return {o.id: 1.0 for o in offers}
        return {o.id: (o.base_value - lo) / (hi - lo) for o in offers}

    @staticmethod
    def _citations(
        offer: Offer, prop: PropensitySignal | None, decision: ConsentDecision
    ) -> tuple[Citation, ...]:
        cits: list[Citation] = [offer.to_citation()]
        if prop is not None and prop.citation is not None:
            cits.append(prop.citation)
        if decision.citation is not None:
            cits.append(decision.citation)
        # De-duplicate by source_id, keep first-seen order.
        seen: set[str] = set()
        out: list[Citation] = []
        for c in cits:
            if c.source_id not in seen:
                seen.add(c.source_id)
                out.append(c)
        return tuple(out)


def merge_citations(citations: tuple[Citation, ...]) -> tuple[Citation, ...]:
    """De-duplicate citations by (source_id, page), keeping first-seen order."""
    seen: set[tuple[str, int | None]] = set()
    out: list[Citation] = []
    for c in citations:
        key = (c.source_id, c.page)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return tuple(out)


def consent_channel_or_default(value: str | None) -> ConsentChannel | None:
    """Parse a channel string into a :class:`ConsentChannel`, or None if blank/invalid."""
    if not value:
        return None
    try:
        return ConsentChannel(value)
    except ValueError:
        return None
