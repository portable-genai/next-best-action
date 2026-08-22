"""On-prem placeholder for ``RecommendationPort`` — the sovereign migration target.

A reversibility (no-lock-in) placeholder: in the managed profile this port binds to the
Vertex AI recommendations + propensity adapter; switching ``profile`` to ``onprem`` rebinds
it here. The adapter constructs cleanly with **no external dependencies** and structurally
satisfies the same Protocol, so the contract tests prove interface parity. Porting D5
on-premise is only a matter of filling these bodies in; the domain orchestration does not
change.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import (
    Customer,
    EligibilityRule,
    Market,
    Offer,
    PropensitySignal,
    Vertical,
)

_MESSAGE = (
    "On-prem RecommendationPort adapter is a migration placeholder; implement against your "
    "on-premise recommendation / propensity stack. Core domain logic is unchanged."
)


class OnPremRecommendationAdapter:
    """Placeholder recommendation adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def customer(self, customer_id: str, market: Market, vertical: Vertical) -> Customer:
        raise NotImplementedError(_MESSAGE)

    def catalog(self, market: Market, vertical: Vertical) -> tuple[Offer, ...]:
        raise NotImplementedError(_MESSAGE)

    def eligibility_rules(self, market: Market, vertical: Vertical) -> tuple[EligibilityRule, ...]:
        raise NotImplementedError(_MESSAGE)

    def propensity(
        self, customer: Customer, offers: tuple[Offer, ...]
    ) -> tuple[PropensitySignal, ...]:
        raise NotImplementedError(_MESSAGE)
