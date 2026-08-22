"""CandidateFilterService — deterministic candidate-offer filtering.

The first deterministic engine in the D5 pipeline (see the ``deterministic-domain-service``
skill): pure, stdlib-only, replayable. Given the offer catalog for a market/vertical and a
customer, it narrows the catalog to the candidate set the eligibility/ranking engines act
on: offers scoped to the customer's market and vertical, minus offers already held, minus
offers that conflict with a held offer (``excluded_if_held``), minus out-of-stock retail
offers. A propensity recall list may pre-rank, but the deterministic filter, not the model,
decides membership.

Determinism: same inputs -> same output. No LLM, no clock, no network, no randomness. The
LLM never decides which offers are candidates; this engine does, by transparent rules over
the catalog and the customer's holdings.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CandidateSet, Customer, Offer


@dataclass(frozen=True, slots=True)
class CandidateFilterService:
    """Pure, deterministic candidate-offer filtering.

    ``drop_out_of_stock`` gates retail availability; ``suppress_held`` removes offers the
    customer already holds and offers that conflict with a held offer. Both are tunable
    fields, not magic numbers, so the same engine serves banking and online retail.
    """

    drop_out_of_stock: bool = True
    suppress_held: bool = True

    def filter(
        self,
        customer: Customer,
        catalog: tuple[Offer, ...] | list[Offer],
    ) -> CandidateSet:
        """Return the candidate set for ``customer`` from ``catalog`` (stable order)."""
        held = set(customer.holdings)
        offers: list[Offer] = []
        for offer in catalog:
            if offer.market is not customer.market or offer.vertical is not customer.vertical:
                continue
            if self.suppress_held and offer.id in held:
                continue
            if self.suppress_held and any(x in held for x in offer.excluded_if_held):
                continue
            if self.drop_out_of_stock and offer.stock is not None and offer.stock <= 0:
                continue
            offers.append(offer)
        # Stable, deterministic order: highest base value first, then offer id.
        offers.sort(key=lambda o: (-o.base_value, o.id))
        return CandidateSet(
            customer_id=customer.id,
            market=customer.market,
            vertical=customer.vertical,
            offers=tuple(offers),
        )
