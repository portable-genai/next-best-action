#!/usr/bin/env python3
"""Offline synthetic-data demo for D5 (audit-first).

Runs the real ``RecommendationService`` over the local (offline) adapters for a few
(customer, market, vertical) scenarios, prints a readable, cited trace to stdout, and writes
the recommendation audit views to ``scripts/out/*.json`` for the dependency-free renderer /
screenshots. It is also the end-to-end smoke for the slice: deterministic, so screenshots
never drift.

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
