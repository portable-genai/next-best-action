"""Prove every eval metric can go RED, using the SAME proofs the scored run runs.

A metric that cannot fail proves nothing. This module used to carry its own copy of each
red case, which meant the suite could prove one thing and the gate another: the copies were
free to drift, and the direction they drift in is always the direction that passes.

``eval.run_eval._red_case_proofs`` is now the one set, run as the first statement of the
scored run (``prove_before_scoring``) and again here. What this file adds is what a proof
cannot say about itself: that there is one for every metric the gate scores.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from agent_eval_kit import load_rubrics
from agent_eval_kit.rubrics import RubricError
from eval.run_eval import (
    RUBRICS,
    SCORED,
    _red_case_proofs,
    load_thresholds_from_rubrics,
)

#: The reviewed bars, read from `eval/rubrics/*.yaml` exactly as the gate reads them. The
#: module-level dict this used to import is gone: having both was two homes for one number.
THRESHOLDS = load_thresholds_from_rubrics()


@pytest.mark.parametrize("proof", _red_case_proofs(), ids=lambda p: p.__name__)
def test_metric_can_go_red(proof: Callable[[], None]) -> None:
    """Each proof feeds its scorer the same result twice, clean and with its own defect."""
    proof()


def test_there_is_a_proof_for_every_scored_metric() -> None:
    """The direction that rots: a metric added to SCORED with no red case behind it.

    Nothing else notices. The gate prints the new metric, it scores 1.000 because whatever it
    measures happens to hold, and the run that would have caught it going wrong was never
    written. Each proof is named after its metric, which is what makes this checkable.
    """
    proven = {proof.__name__ for proof in _red_case_proofs()}
    assert proven == set(SCORED), (
        "the scored metrics and the falsification proofs are not the same set: "
        f"scored with no proof {sorted(set(SCORED) - proven)}, "
        f"proved but not scored {sorted(proven - set(SCORED))}. Each proof in "
        "eval.run_eval._red_case_proofs is named after the metric it falsifies."
    )


def test_every_scored_metric_has_a_reviewed_bar_and_every_bar_is_scored() -> None:
    """Both directions. The second is the one nobody writes by hand, and the one that rots."""
    load_rubrics(RUBRICS).assert_covers(SCORED)
    with pytest.raises(RubricError, match="reads as governance"):
        load_rubrics(RUBRICS).assert_covers(SCORED[:-1])


def test_every_bar_is_one_point_zero_because_the_corpus_cannot_express_less() -> None:
    """A guard on the arithmetic the rubrics claim, not a restatement of the numbers.

    Each of these is scored as 0/1 decisions and averaged. A bar of t tolerates one failure
    only when the run makes at least 1/(1-t) decisions, so at 8 cases every bar above 0.875
    is 8-of-8 however it is written. The rubrics say 1.0 for that reason among others; this
    fails if someone lowers one back to a number that reads as tolerance and is not.
    """
    from agent_eval_kit import required_positives

    for metric, threshold in sorted(THRESHOLDS.items()):
        if threshold >= 1.0:
            continue
        needed = required_positives(threshold)
        assert needed <= 8, (
            f"{metric}: a bar of {threshold} needs {needed} scored decisions before it "
            "tolerates a single failure, and this corpus has fewer; it is 1.0 in disguise"
        )
