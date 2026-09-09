#!/usr/bin/env python3
"""Regenerate the derived half of ``docs/evals.md`` from the rubrics and a real scored run.

A page that lists metrics, bars and corpus sizes by hand goes stale the first time one of
them moves, and nothing notices. The numbers here are read from the artifacts instead: the
bars from ``eval/rubrics/``, the denominators from a run of the gate itself.

    make evals-doc          # rewrite the generated sections
    make evals-doc-check    # non-zero when the page and the artifacts disagree (runs in gate)

Only the sections named in :data:`BLOCKS` are generated. Everything else on the page is
hand-written prose addressed to a reviewer, and this script does not touch it: the point is a
document a person wrote, whose FACTS cannot drift from the artifacts they describe.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agent_eval_kit import load_rubrics, render_main

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "eval"))
sys.path.insert(0, str(_REPO_ROOT / "src"))

DOC = _REPO_ROOT / "docs" / "evals.md"
RUBRICS = _REPO_ROOT / "eval" / "rubrics"

#: The headings this script owns. Each runs from its heading to the next `\n## `.
BLOCKS = (
    "## What is measured, and against what bar",
    "## What is exercised",
)


def _scored_run() -> tuple[object, dict[str, int]]:
    """One real run of the gate, for the numbers below. Not a model of one."""
    import run_eval

    report = run_eval.run_offline(run_eval.DEFAULT_DATASET, run_eval.load_thresholds_from_rubrics())
    return report, dict(run_eval.SCORED_DECISIONS)


def _metrics_block() -> list[str]:
    report, decisions = _scored_run()
    rubrics = load_rubrics(RUBRICS)
    lines = [
        BLOCKS[0],
        "",
        "Every bar below lives in `eval/rubrics/*.yaml` next to the argument for it, and the",
        "runner reads it from there. There is no dict of thresholds in the runner any more: a",
        "metric scored with no reviewed bar fails the build, and so does a bar that names no",
        "metric, which is the direction that rots quietly because it rots toward looking well",
        "governed.",
        "",
        "The third column is the denominator, MEASURED on a real run rather than assumed to be",
        "the case count. It is the case count for five of these metrics and is not for the two",
        "ranking ones, which score a decision per adjacent pair and per catalogue offer. The",
        "rule it answers: a bar `t` tolerates a single miss only over at least `1/(1-t)` scored",
        "decisions, so a bar below 1.0 on a short corpus is 1.0 wearing a friendlier number. The",
        "bracket says what the loosest non-vacuous bar over that many decisions would be. Every",
        "bar here is 1.0, and the rubric beside each one says whether that is the corpus being",
        "short or the failure being intolerable.",
        "",
        "| Metric | Bar | Decisions scored | What it measures |",
        "|---|---|---|---|",
    ]
    for rubric in rubrics:
        scored = decisions.get(rubric.metric, 0)
        tolerance = (
            "too few for any bar below 1.0 to mean anything"
            if scored < 2
            else f"the loosest bar that tolerates one miss is {(scored - 1) / scored:.2f}"
        )
        lines.append(
            f"| `{rubric.metric}` | {rubric.threshold:g} | {scored} ({tolerance}) | "
            f"{' '.join(rubric.description.split())} |"
        )
    lines += [
        "",
        f"Scored over {report.n_examples} golden cases, dataset digest "
        f"`{report.dataset_digest[:12]}`, by `{report.evaluator}`.",
        "",
    ]
    return lines


def _exercised_block() -> list[str]:
    import run_eval

    from next_best_action import demo_book

    examples = run_eval.load_golden(run_eval.DEFAULT_DATASET)
    offers = [row for row in demo_book.BOOK.rows("offers") if row["active"]]
    customers = demo_book.BOOK.rows("customers")
    signals = demo_book.BOOK.rows("propensity_signals")
    scopes = {(row["market"], row["vertical"]) for row in offers}
    labelled = sum(1 for e in examples if e.expected_top_offer)
    return [
        BLOCKS[1],
        "",
        f"- **{len(examples)} golden cases** in `eval/datasets/golden_recommendations.jsonl`,",
        f"  {labelled} of them carrying an expected top offer. The INPUTS are the shipped demo",
        "  book, so the customers the gate measures are the customers the demo shows. The",
        "  EXPECTATIONS are hand-written, and each was checked against the book's own dominance",
        "  rule before being written down: an oracle read off the thing under test agrees with",
        "  it by construction and measures nothing.",
        f"- **{len(offers)} active offers** across {len(scopes)} market/vertical scopes, with",
        f"  {len(customers)} customers and {len(signals)} propensity signals, in",
        "  `src/next_best_action/data/demo_book/`. Every scope ships at least three offers,",
        "  asserted in `tests/contract/test_demo_book.py`. That is not decoration: with one or",
        "  two candidates per customer, most golden cases returned a list of one, and a list of",
        "  one makes no ordering claim at all.",
        "- **The falsification proofs run first.** `eval/run_eval.py` calls",
        "  `prove_before_scoring` as the opening statement of the scored run, so every metric is",
        "  shown going red on its own planted defect in the same process, against the same",
        "  thresholds, before any golden score is trusted. `tests/unit/test_not_falsely_green.py`",
        "  runs the same proof objects and adds the one thing a proof cannot say about itself:",
        "  that there is one for every metric the gate scores.",
        "",
    ]


def render() -> str:
    """The page, with the generated blocks replaced and the hand-written prose untouched."""
    text = DOC.read_text(encoding="utf-8")
    missing = [heading for heading in BLOCKS if heading not in text]
    if missing:
        raise SystemExit(
            f"{DOC}: missing generated section(s) {missing}. This script replaces named "
            "headings; it does not invent them, because a page it could create from nothing "
            "would silently replace one a person wrote."
        )
    generated = {BLOCKS[0]: _metrics_block(), BLOCKS[1]: _exercised_block()}
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line in generated:
            out.extend(generated[line])
            skipping = True
            continue
        if skipping:
            if line.startswith("## "):
                skipping = False
            else:
                continue
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


if __name__ == "__main__":
    raise SystemExit(
        render_main(
            output=DOC,
            render=render,
            description="Regenerate docs/evals.md from the rubrics and a real scored run.",
            argv=sys.argv[1:],
        )
    )
