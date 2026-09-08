#!/usr/bin/env python3
"""Re-render the propensity table of the shipped book from its recorded formula.

The customers, the offers and the rules in ``data/demo_book/`` are hand-maintained: they are
the demo's subject matter and a person decides what they say. The propensity signals are not.
They are what a model would write in production, and for this fictional book they come from
the formula the local adapter used to evaluate at request time, before both profiles moved to
reading stored rows:

    score = clamp(0.9 * affinity(offer.category) + 0.1 * min(offer.base_value / 600, 1))

Keeping that formula HERE rather than in the adapter is the point of the change it records.
An adapter that computes a score is answering a question a model owns, and it meant the
laptop could rank an offer the deployment refuses to score, because the managed adapter has
always read a feature table and refused an offer with no row in it. Now both read rows, this
script is how the rows get made, and ``model_version`` on each row says what made them.

Usage::

    python scripts/render_demo_book.py            # rewrite propensity_signals.ndjson
    python scripts/render_demo_book.py --check    # non-zero when the committed file is stale

``--check`` runs in the offline gate, so an edit to a customer's affinities or an offer's
value that was never re-rendered fails the build rather than leaving the book carrying scores
for a catalog that has moved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from next_best_action import demo_book  # noqa: E402

_OUTPUT = (
    _REPO_ROOT / "src" / "next_best_action" / "data" / "demo_book" / "propensity_signals.ndjson"
)

#: Stamped on every row so a reader can tell which model produced a score. A change to the
#: formula above is a change to this string, or the rows claim to come from something else.
MODEL_VERSION = "demo-affinity-v1"

#: The affinity assumed for a category the customer has no recorded affinity for. Named
#: rather than inlined because it is the one number here that is a judgement.
_DEFAULT_AFFINITY = 0.3

#: The offer value at which the value prior saturates.
_VALUE_CEILING = 600.0


def score(affinity: float, base_value: float) -> float:
    """The recorded formula: mostly affinity, with a small prior for a high-value offer."""
    value_prior = min(base_value / _VALUE_CEILING, 1.0)
    return round(max(0.0, min(0.9 * affinity + 0.1 * value_prior, 1.0)), 4)


def render() -> str:
    """The propensity table as text, one JSON object per line, in customer then offer order."""
    customers = demo_book.BOOK.rows("customers")
    offers = demo_book.BOOK.rows("offers")
    updated = str(demo_book.BOOK.manifest()["as_of_date"]) + "T00:00:00Z"

    rows: list[dict[str, Any]] = []
    for customer in customers:
        affinities = json.loads(customer["affinities_json"])
        scope = (customer["market"], customer["vertical"])
        for offer in offers:
            if (offer["market"], offer["vertical"]) != scope or not offer.get("active", True):
                continue
            affinity = float(affinities.get(offer.get("category") or "", _DEFAULT_AFFINITY))
            rows.append(
                {
                    "customer_id": customer["customer_id"],
                    "offer_id": offer["offer_id"],
                    "market": customer["market"],
                    "vertical": customer["vertical"],
                    "score": score(affinity, float(offer.get("base_value") or 0.0)),
                    "model_version": MODEL_VERSION,
                    "computed_at": updated,
                }
            )
    return "".join(json.dumps(row) + "\n" for row in rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the committed propensity table is not what this renders",
    )
    args = parser.parse_args(argv)
    rendered = render()
    if args.check:
        current = _OUTPUT.read_text(encoding="utf-8") if _OUTPUT.exists() else ""
        if current != rendered:
            print(
                f"{_OUTPUT.relative_to(_REPO_ROOT)} is stale: a customer's affinities or an "
                "offer's value changed. Run: python scripts/render_demo_book.py",
                file=sys.stderr,
            )
            return 1
        print(f"{_OUTPUT.relative_to(_REPO_ROOT)} matches the recorded formula")
        return 0
    _OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"rendered {_OUTPUT.relative_to(_REPO_ROOT)}: {rendered.count(chr(10))} signals")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
