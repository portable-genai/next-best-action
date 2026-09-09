#!/usr/bin/env python3
"""Offline synthetic-data demo for D5 (audit-first).

Runs the real ``RecommendationService`` over the local (offline) adapters for a few
(customer, market, vertical) scenarios, prints a readable, cited trace to stdout, and writes
the recommendation audit views to ``scripts/out/*.json`` for the dependency-free renderer /
screenshots. It is also the end-to-end smoke for the slice: deterministic, so screenshots
never drift.

The last act is the eval, and it is not a summary of one. A demo that shows six good answers
has shown that the system can be right, which is the easy half and the half an audience will
believe anyway. What it has not shown is how anyone would know when it is wrong. So the act
runs the SHIPPED scorers over the results the audience just watched being produced, then
breaks each one on purpose and shows it going red, and finishes by naming what the gate does
not measure at all. A metric that never went red in front of the room is a claim, not
evidence.

Usage::

    MKT_NBA_PROFILE=local python scripts/demo.py
"""

from __future__ import annotations

import json
from pathlib import Path

from next_best_action.api.deps import make_recommendation_service
from next_best_action.config import Container, LocalSettings, Settings
from next_best_action.domain.identity import Principal
from next_best_action.domain.models import Market, RecommendationRequest, Vertical
from next_best_action.domain.serialization import to_jsonable

# The offline demo runs as a local operator principal in the demo-bank tenant (the seed's
# tenant), so object-level authorization passes for the seeded customers.
_DEMO_PRINCIPAL = Principal(subject="demo", tenant="demo-bank", source="demo")

_OUT = Path(__file__).resolve().parent / "out"

_SCENARIOS = [
    ("cust-sg-bank-1", Market.SG, Vertical.BANKING),
    ("cust-jp-bank-1", Market.JP, Vertical.BANKING),
    ("cust-au-bank-1", Market.AU, Vertical.BANKING),
    ("cust-sg-retail-1", Market.SG, Vertical.ONLINE_RETAIL),
    ("cust-jp-retail-1", Market.JP, Vertical.ONLINE_RETAIL),
    ("cust-au-retail-1", Market.AU, Vertical.ONLINE_RETAIL),
]


def _service():  # type: ignore[no-untyped-def]
    base = Settings.load("config/settings.yaml")
    settings = Settings(
        project_id=base.project_id,
        region=base.region,
        profile="local",
        vertical=base.vertical,
        market=base.market,
        models=base.models,
        recommendation=base.recommendation,
        knowledge_base=base.knowledge_base,
        model_armor=base.model_armor,
        logging=base.logging,
        agent_engine=base.agent_engine,
        ranking=base.ranking,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        markets=base.markets,
        adapters=base.adapters,
    )
    return make_recommendation_service(Container(settings))


def _step_eval() -> None:
    """The scorers that gate this repo, run live, and each one shown failing on purpose."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
    from agent_eval_kit import load_rubrics  # noqa: PLC0415
    from run_eval import (  # noqa: PLC0415 - the eval is a script, imported only for this act
        DEFAULT_DATASET,
        RUBRICS,
        SCORED,
        _red_case_proofs,
        load_thresholds_from_rubrics,
        run_offline,
    )

    print("\n=== the eval that gates this system ===")
    thresholds = load_thresholds_from_rubrics()
    report = run_offline(DEFAULT_DATASET, thresholds)
    print(
        f"  {report.n_examples} golden cases, {len(SCORED)} metrics, "
        f"dataset {report.dataset_digest[:12]}"
    )
    for row in report.results:
        verdict = "PASS" if row.passed else "FAIL"
        print(f"    {row.metric:28s} {row.score:.3f}  bar {row.threshold:.2f}  {verdict}")

    print("\n  each of those, broken on purpose, to show the bar can actually be missed:")
    for proof in _red_case_proofs():
        proof()  # raises if the degraded case still scores above the bar
        print(f"    {proof.__name__:28s} goes RED on its own defect")

    print("\n  the bars, and why they are where they are:")
    for rubric in sorted(load_rubrics(RUBRICS), key=lambda r: r.metric):
        print(f"    {rubric.metric:28s} {rubric.threshold:.2f}  {rubric.description.strip()[:88]}")

    print("\n  what this gate does NOT measure, said out loud rather than left to be assumed:")
    for line in _UNMEASURED:
        print(f"    - {line}")


#: The honest half of the eval act. Each of these is a real limit of the offline gate, and a
#: demo that stops at the passing table invites the room to assume none of them exist.
_UNMEASURED = (
    "whether an offer SHOULD exist for a customer. The gate checks the catalogue is fully "
    "accounted for, not that the catalogue is the right one.",
    "the ranking weights. 4 of the 13 adjacent pairs have propensity and value disagreeing; "
    "the book cannot decide those, so ranking_order stays silent and the weights are "
    "unexamined by this gate.",
    "whether the propensity model is any good. The scores are read from the book, and the "
    "book's formula is fictional; a real deployment gates the model separately.",
    "the explanation text. It is generated after the ranking is fixed, and no metric here "
    "reads it for anything except citations and PII.",
)


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    service = _service()
    for customer_id, market, vertical in _SCENARIOS:
        request = RecommendationRequest(customer_id=customer_id, market=market, vertical=vertical)
        result = service.recommend(request, _DEMO_PRINCIPAL)
        print(f"\n=== {customer_id} | {market.value} / {vertical.value} ===")
        print(f"  {result.summary}")
        for r in result.recommendations:
            print(
                f"    #{r.rank} {r.name} — score {r.score:.2f} (channel {r.channel.value if r.channel else 'n/a'})"
            )
        out_path = _OUT / f"{market.value.lower()}_{vertical.value}_{customer_id}.json"
        out_path.write_text(json.dumps(to_jsonable(result), indent=2), encoding="utf-8")
        print(f"  wrote {out_path}")
    _step_eval()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
