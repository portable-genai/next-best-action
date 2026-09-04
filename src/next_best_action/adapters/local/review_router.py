"""Local ReviewRouterPort: enqueue the routed review to an in-memory outbox (no live
human-review-console).

Exercises the R8 routing path offline: an escalated recommendation set is converted to a review and
enqueued (the same transactional outbox the platform adapter flushes to human-review-console), so
tests and the offline demo can assert that an escalation is routed without a running console.
"""

from __future__ import annotations

from review_kit import InMemoryOutbox

from ...config import Settings
from ...domain.models import RecommendationSet
from .._review_payload import recommendation_set_to_review


class LocalReviewRouter:
    """Record routed reviews in an in-memory outbox for the SDK-free ``local`` profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._outbox = InMemoryOutbox()

    def route(self, result: RecommendationSet, *, maker: str, tenant: str = "") -> None:
        self._outbox.enqueue(
            recommendation_set_to_review(result, maker=maker, tenant=tenant), actor="mkt5-nba"
        )

    @property
    def outbox(self) -> InMemoryOutbox:
        """Expose the outbox for inspection in tests and the demo."""
        return self._outbox
