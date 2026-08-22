"""Prove every eval metric can go RED: a degraded result must score below its threshold.

A metric that cannot fail proves nothing. Each scorer in ``eval/run_eval.py`` is fed the SAME
recommendation set twice: once as the pipeline produced it (green) and once carrying exactly
the defect the metric exists to catch (red). The scorers are imported rather than
re-implemented, so a scorer that silently became a constant 1.0 breaks this build.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from agent_eval_kit import assert_can_go_red
from eval.run_eval import (
    _EVAL_PRINCIPAL,
    DEFAULT_DATASET,
    THRESHOLDS,
    _make_service_and_container,
    load_golden,
    score_citation_accuracy,
    score_eligibility_accuracy,
    score_groundedness,
    score_pii_safety,
    score_review_safety,
)

from next_best_action.domain.models import (
    Market,
    RecommendationRequest,
    RecommendationSet,
    Vertical,
)

#: The customer whose national id is planted in the golden set, so pii_safety has a target.
_CASE = load_golden(DEFAULT_DATASET)[0]


@pytest.fixture(scope="module")
def scored() -> tuple[RecommendationSet, list[dict]]:
    """One real recommendation set off the local (SDK-free) stack, plus what it audited."""
    service, container = _make_service_and_container()
    result = service.recommend(
        RecommendationRequest(
            customer_id=_CASE.customer_id,
            market=Market(_CASE.market),
            vertical=Vertical(_CASE.vertical),
        ),
        _EVAL_PRINCIPAL,
    )
    assert result.recommendations, "the proof needs a case that actually recommends something"
    return result, container.audit.read_all()


def test_recommendation_groundedness_can_go_red(
    scored: tuple[RecommendationSet, list[dict]],
) -> None:
    result, _ = scored
    assert_can_go_red(
        score_groundedness,
        green=result,
        red=replace(
            result,
            recommendations=tuple(replace(r, citations=()) for r in result.recommendations),
        ),  # recommended with nothing behind it
        threshold=THRESHOLDS["recommendation_groundedness"],
        metric="recommendation_groundedness",
    )


def test_citation_accuracy_can_go_red(scored: tuple[RecommendationSet, list[dict]]) -> None:
    result, _ = scored
    fabricated = replace(result.recommendations[0].citations[0], source_id="fabricated-source")
    assert_can_go_red(
        score_citation_accuracy,
        green=result,
        red=replace(
            result,
            recommendations=tuple(
                replace(r, citations=(fabricated,)) for r in result.recommendations
            ),
        ),  # cites a source the result never derived
        threshold=THRESHOLDS["citation_accuracy"],
        metric="citation_accuracy",
    )


def test_eligibility_accuracy_can_go_red(scored: tuple[RecommendationSet, list[dict]]) -> None:
    result, _ = scored
    assert_can_go_red(
        lambda expected: score_eligibility_accuracy(result, expected),
        green=_CASE.expected_top_offer,
        red="offer-that-was-never-top",  # the gate no longer agrees with the golden label
        threshold=THRESHOLDS["eligibility_accuracy"],
        metric="eligibility_accuracy",
    )


def test_review_safety_can_go_red(scored: tuple[RecommendationSet, list[dict]]) -> None:
    result, _ = scored
    assert_can_go_red(
        score_review_safety,
        green=result,
        red=replace(result, requires_human_review=False),  # the human gate quietly dropped
        threshold=THRESHOLDS["review_safety"],
        metric="review_safety",
    )


def test_pii_safety_can_go_red(scored: tuple[RecommendationSet, list[dict]]) -> None:
    """The red case re-introduces the customer's own national id AFTER redaction ran."""
    result, events = scored
    assert_can_go_red(
        lambda res: score_pii_safety(res, _CASE.customer_id, events),
        green=result,
        red=replace(result, summary=f"{result.summary} national id S1234567A"),
        threshold=THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )
