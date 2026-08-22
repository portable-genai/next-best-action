from next_best_action.domain import kernel, models


def test_kernel_is_stable_and_excludes_vertical_aggregates() -> None:
    assert models.ThinkingLevel is kernel.ThinkingLevel
    assert {"RecommendationSet", "Recommendation", "Offer", "Customer"}.isdisjoint(kernel.__all__)
