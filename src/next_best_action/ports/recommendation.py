"""RecommendationPort — customer profile, offer catalog, rules and propensity.

Primary GCP adapter: **Vertex AI recommendations + propensity models** over **BigQuery**
customer / offer feature tables. The port supplies the raw, vertical-specific inputs the
deterministic engines consume: the customer (shopper) profile, the offer catalog scoped to
a market/vertical, the per-market/vertical eligibility rules, and propensity signals per
candidate offer. Consent is deliberately a separate Mkt6-backed port. This port never ranks
or decides eligibility itself; deterministic engines do.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import (
    Customer,
    EligibilityRule,
    Market,
    Offer,
    PropensitySignal,
    Vertical,
)


@runtime_checkable
class RecommendationPort(Protocol):
    def customer(self, customer_id: str, market: Market, vertical: Vertical) -> Customer:
        """Return the customer / shopper profile for ``customer_id``."""
        ...

    def catalog(self, market: Market, vertical: Vertical) -> tuple[Offer, ...]:
        """Return the offer catalog scoped to ``market`` and ``vertical``."""
        ...

    def eligibility_rules(self, market: Market, vertical: Vertical) -> tuple[EligibilityRule, ...]:
        """Return the per-market, per-vertical eligibility rules (config + seed)."""
        ...

    def propensity(
        self, customer: Customer, offers: tuple[Offer, ...]
    ) -> tuple[PropensitySignal, ...]:
        """Return propensity / recommendation-model scores for the candidate offers."""
        ...
