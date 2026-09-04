"""ReviewRouterPort: the boundary that routes an escalated recommendation set to
human-review-console (rule R8).

Every :class:`RecommendationSet` is consequential decision-support and always requires human review
(maker-checker, P-06): the agent is the maker, a qualified operator is the checker who disposes
before any offer is surfaced to a customer. Rule R8 says a producer that sets
``requires_human_review`` MUST route the item to the human-review-console Human-Review &
Maker-Checker Console rather than terminate the escalation in a per-repo boolean. This port is that
hand-off. The domain stays pure: the adapter (not this port) depends on the shared ``review-kit``
client and does the S2S submission, and the adapter redacts the per-customer PII before the wire.

The ``tenant`` is the server-verified tenant of the caller's :class:`Principal` (never a
client-asserted one); the domain threads it into ``route`` so a routed review is partitioned to
the tenant that actually owns the recommendation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import RecommendationSet


@runtime_checkable
class ReviewRouterPort(Protocol):
    def route(self, result: RecommendationSet, *, maker: str, tenant: str = "") -> None:
        """Route an escalated recommendation set to human-review-console (idempotent per customer is
        ideal).
        """
        ...
