"""Service factories — build domain services from the DI container.

One place that wires the ports resolved by :class:`next_best_action.config.Container` into
the domain orchestrator, so the CLI, API and agent layers share identical wiring.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends

from ..adapters.controls import RecordingReviewRouter
from ..config import Container, build_container
from ..domain.candidate_service import CandidateFilterService
from ..domain.eligibility_service import EligibilityService
from ..domain.ranking_service import RankingService
from ..domain.services import RecommendationService


@lru_cache(maxsize=1)
def get_container() -> Container:
    return build_container()


def get_request_review_router() -> RecordingReviewRouter:
    """The review router for ONE request, wrapped so the response reports the hand-off."""
    return RecordingReviewRouter(get_container().review_router)


#: Injected by FastAPI once per request, so the route reads the outcome of the same wrapper
#: its service handed the set to.
RequestReviewRouter = Annotated[RecordingReviewRouter, Depends(get_request_review_router)]


def make_recommendation_service(
    container: Container | None = None, *, review_router: Any = None
) -> RecommendationService:
    """Build the orchestrator; ``review_router`` is a caller's recording wrapper, if it has one."""
    container = container or get_container()
    ranking_cfg = container.settings.ranking
    return RecommendationService(
        recommendations=container.recommendation,
        knowledge_base=container.knowledge_base,
        llm=container.llm,
        guardrail=container.guardrail,
        redaction=container.redaction,
        tracer=container.tracer,
        audit=container.audit,
        consent=container.consent,
        candidate_filter=CandidateFilterService(),
        eligibility=EligibilityService(),
        ranking=RankingService(
            propensity_weight=ranking_cfg.propensity_weight,
            value_weight=ranking_cfg.value_weight,
            min_score=ranking_cfg.min_score,
        ),
        # Rule R8: route a requires_human_review set to the human-review-console maker-checker
        # console.
        review_router=review_router or container.review_router,
    )
