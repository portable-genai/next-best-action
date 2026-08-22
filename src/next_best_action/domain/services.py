"""Domain services aggregator — one import surface for the wiring layers.

The API, CLI and agent layers import services from here so that adding or renaming a
service is a single-file change at the boundary. The orchestrator
(:class:`RecommendationService`) composes three deterministic engines and the ports.
"""

from __future__ import annotations

from .candidate_service import CandidateFilterService
from .eligibility_service import EligibilityService
from .ranking_service import RankingService
from .recommendation_service import RecommendationService

__all__ = [
    "RecommendationService",
    "CandidateFilterService",
    "EligibilityService",
    "RankingService",
]
