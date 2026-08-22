"""R8 routing: an escalated recommendation set is routed to Hrz7 via the shared review-kit.

Every RecommendationSet requires human review (P-06), so rule R8 says it MUST be handed to the
Hrz7 maker-checker console rather than left as a boolean. These tests prove the producer half of
that loop end to end against the offline local router (an in-memory outbox), that the verified
tenant is carried onto the wire, and that the redact-before-wire boundary holds so no raw customer
identifier reaches the console. Fictional data only.
"""

from __future__ import annotations

import pytest

from next_best_action.adapters._review_payload import recommendation_set_to_review
from next_best_action.adapters.local.review_router import LocalReviewRouter
from next_best_action.api.deps import make_recommendation_service
from next_best_action.config import Container
from next_best_action.domain.identity import Principal
from next_best_action.domain.models import (
    Citation,
    ConsentChannel,
    ConsentDecision,
    EligibilityOutcome,
    EligibilityResult,
    Market,
    OfferKind,
    Recommendation,
    RecommendationRequest,
    RecommendationSet,
    SourceType,
    Vertical,
)
from next_best_action.domain.recommendation_service import RecommendationService

ACTOR = "analyst@bank.example"
TENANT = "demo-bank"


def _principal(tenant: str = TENANT) -> Principal:
    return Principal(subject=ACTOR, tenant=tenant, source="test")


def test_recommend_routes_escalated_set_to_outbox(local_container: Container) -> None:
    """A completed recommendation enqueues exactly one review carrying the verified tenant (R8)."""
    service = make_recommendation_service(local_container)
    router = local_container.review_router
    assert isinstance(router, LocalReviewRouter)
    assert not router.outbox.pending()

    result = service.recommend(
        RecommendationRequest(
            customer_id="cust-sg-bank-1", market=Market.SG, vertical=Vertical.BANKING
        ),
        _principal(),
    )
    assert result.requires_human_review

    pending = router.outbox.pending()
    assert len(pending) == 1, "the escalated set must be routed to Hrz7 exactly once"
    review = pending[0].review
    assert review.action == f"nba_recommendation:{result.vertical.value}"
    assert review.maker == ACTOR
    # The verified tenant is threaded onto the wire (never a client-asserted one).
    assert review.tenant == TENANT
    assert review.sod_group == "nba-maker-checker"


# A fictional internal customer key and a synthetic SG NRIC, both of which must be scrubbed.
_SECRET_CUSTOMER_ID = "cust-sg-bank-SECRET42"
_SYNTHETIC_NRIC = "S1234567D"


def _high_score_set_with_pii() -> RecommendationSet:
    # A citation whose provenance embeds the raw customer key AND a synthetic national id.
    cite = Citation(
        source_id=f"consent://{_SECRET_CUSTOMER_ID}/email",
        source_type=SourceType.CONSENT,
        title=f"Consent record for {_SECRET_CUSTOMER_ID}",
        url=f"https://example.test/{_SECRET_CUSTOMER_ID}",
        snippet=f"Customer {_SECRET_CUSTOMER_ID} (NRIC {_SYNTHETIC_NRIC}) opted in to email.",
    )
    top = Recommendation(
        offer_id="sg-bank-wealth-upgrade",
        name="Wealth upgrade",
        kind=OfferKind.UPGRADE,
        rank=1,
        score=0.92,  # >= 0.85 => CRITICAL band => dual control
        propensity=0.9,
        value_score=0.95,
        channel=ConsentChannel.EMAIL,
        eligibility=EligibilityResult(
            offer_id="sg-bank-wealth-upgrade", outcome=EligibilityOutcome.ELIGIBLE
        ),
        consent=ConsentDecision(
            offer_id="sg-bank-wealth-upgrade", allowed=True, channel=ConsentChannel.EMAIL
        ),
        explanation="Ranks #1 on propensity and value.",
        citations=(cite,),
    )
    return RecommendationSet(
        id=f"nba-sg-banking-{_SECRET_CUSTOMER_ID}",
        customer_id=_SECRET_CUSTOMER_ID,
        market=Market.SG,
        vertical=Vertical.BANKING,
        recommendations=(top,),
        summary=(
            f"1 next-best-action recommendation(s) for customer {_SECRET_CUSTOMER_ID}; "
            "top: Wealth upgrade."
        ),
        citations=(cite,),
    )


def test_payload_redacts_customer_id_and_pii_before_wire() -> None:
    """No raw customer key or national id survives into the payload the console receives (R1/R8)."""
    review = recommendation_set_to_review(_high_score_set_with_pii(), maker=ACTOR, tenant=TENANT)

    # The raw internal customer key is scrubbed everywhere it could appear.
    assert _SECRET_CUSTOMER_ID not in review.subject
    assert _SECRET_CUSTOMER_ID not in review.summary
    assert _SECRET_CUSTOMER_ID not in review.case_ref
    # case_ref is a stable, non-reversible pseudonym, not the raw key.
    assert review.case_ref.startswith("cust#")
    for citation in review.citations:
        assert _SECRET_CUSTOMER_ID not in citation.source_id
        assert _SECRET_CUSTOMER_ID not in citation.title
        assert _SECRET_CUSTOMER_ID not in citation.snippet
        # The synthetic national id is masked by pii-kit.
        assert _SYNTHETIC_NRIC not in citation.snippet


def test_high_score_set_is_dual_control() -> None:
    """The strongest customer-facing push maps to a HIGH+ severity and four-eyes control."""
    review = recommendation_set_to_review(_high_score_set_with_pii(), maker=ACTOR, tenant=TENANT)
    assert review.severity == "critical"
    assert review.required_approvals == 2


def test_no_router_still_assembles_set(local_container: Container) -> None:
    """Routing is optional: with no router bound, assessment still returns an escalated set."""
    # Build the service directly with the router omitted (defaults to None).
    service = RecommendationService(
        recommendations=local_container.recommendation,
        knowledge_base=local_container.knowledge_base,
        llm=local_container.llm,
        guardrail=local_container.guardrail,
        redaction=local_container.redaction,
        tracer=local_container.tracer,
        audit=local_container.audit,
        consent=local_container.consent,
    )
    result = service.recommend(
        RecommendationRequest(
            customer_id="cust-sg-bank-1", market=Market.SG, vertical=Vertical.BANKING
        ),
        _principal(),
    )
    assert result.requires_human_review


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
