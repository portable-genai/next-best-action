"""Local recommendation adapter (RecommendationPort) — deterministic offline profile store.

The ``local`` profile's stand-in for **Vertex AI recommendations + propensity + BigQuery**: a
deterministic, seedable store over the bundled fictional seed (``_seed.py``), with no model and no
network. It serves the customer profile, the offer catalog, the per-market/ vertical eligibility
rules and propensity signals derived deterministically from customer affinity and offer value.
Consent is served by the separate local marketing-compliance-gate stand-in. SDK-free and
unconditional (there is no emulator for Vertex), reproducible so the offline CLI and the unit tests
agree.

The local propensity is intentionally simple and transparent: ``affinity(category)`` blended
with a small value prior, clamped to 0..1. The deterministic ranking engine, not this
signal, decides the final order.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.errors import UnknownCustomerError
from ...domain.models import (
    Citation,
    Customer,
    EligibilityRule,
    Market,
    Offer,
    PropensitySignal,
    SourceType,
    Vertical,
)
from ._seed import (
    CUSTOMERS,
    ELIGIBILITY_RULES,
    OFFER_CATALOG,
)


class LocalRecommendationAdapter:
    """Deterministic profile / catalog / propensity store over the seeded fictional data."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def customer(self, customer_id: str, market: Market, vertical: Vertical) -> Customer:
        customer = CUSTOMERS.get(customer_id)
        if customer is None:
            raise UnknownCustomerError(
                f"unknown customer '{customer_id}'; seed customers: {sorted(CUSTOMERS)}"
            )
        return customer

    def catalog(self, market: Market, vertical: Vertical) -> tuple[Offer, ...]:
        return OFFER_CATALOG.get((market, vertical), ())

    def eligibility_rules(self, market: Market, vertical: Vertical) -> tuple[EligibilityRule, ...]:
        return ELIGIBILITY_RULES.get((market, vertical), ())

    def propensity(
        self, customer: Customer, offers: tuple[Offer, ...]
    ) -> tuple[PropensitySignal, ...]:
        signals: list[PropensitySignal] = []
        for offer in offers:
            affinity = customer.affinities.get(offer.category, 0.3)
            # Blend affinity (90%) with a small value prior (10%) so a high-value offer with
            # no affinity still gets a non-zero, deterministic propensity.
            value_prior = min(offer.base_value / 600.0, 1.0)
            score = max(0.0, min(0.9 * affinity + 0.1 * value_prior, 1.0))
            signals.append(
                PropensitySignal(
                    offer_id=offer.id,
                    score=round(score, 4),
                    citation=Citation(
                        source_id=f"propensity-{offer.id}",
                        source_type=SourceType.PROPENSITY,
                        title=f"Propensity signal for {offer.name}",
                        snippet=(
                            f"affinity({offer.category})={affinity:.2f}, "
                            f"value_prior={value_prior:.2f} (FICTIONAL local model)."
                        ),
                        score=round(score, 4),
                    ),
                )
            )
        return tuple(signals)
