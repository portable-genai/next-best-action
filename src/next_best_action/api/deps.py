"""Service factories — build domain services from the DI container.

One place that wires the ports resolved by :class:`next_best_action.config.Container` into
the domain orchestrator, so the CLI, API and agent layers share identical wiring.
"""

from __future__ import annotations

from functools import lru_cache

from ..config import Container, build_container
from ..domain.candidate_service import CandidateFilterService
from ..domain.eligibility_service import EligibilityService
from ..domain.ranking_service import RankingService
from ..domain.services import RecommendationService


@lru_cache(maxsize=1)
def get_container() -> Container:
    return build_container()


def make_recommendation_service(container: Container | None = None) -> RecommendationService:
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
        review_router=container.review_router,
    )
