#!/usr/bin/env python3
"""Offline evaluation gate for the D5 Next-Best-Action system (A4).

This is the **promotion gate**: CI runs it on every change and the build fails if the
agent's next-best-action recommendations fall below the model-risk thresholds agreed for a
recommendation / cross-sell agent (see ``eval/rubrics/*.yaml``)::

    recommendation_groundedness >= 0.80   (every recommendation carries citations)
    citation_accuracy           >= 0.90   (cites only catalog / rule / propensity sources)
    eligibility_accuracy        >= 0.90   (the deterministic eligibility / consent gate is
                                           consistent: the recommended top offer matches the
                                           expected eligible offer)
    review_safety               >= 0.99   (every result requires human review; maker-checker)

Two evaluators, one gate
------------------------
* **Production evaluator** — the **Gen AI evaluation service** on the Gemini Enterprise
  Agent Platform, wired in as ``EvaluationGatePort`` ->
  ``next_best_action.adapters.gcp.genai_eval:GenAiEvalAdapter``. It needs GCP credentials.
  Select it with ``--use-gcp``.

* **Offline evaluator (default)** — a deterministic gate in this file. It needs **no GCP
  credentials and no Google Cloud SDK**, runs the real ``RecommendationService`` against the
  local (offline) adapters over the golden set, and computes the four metrics. This is what
  guards the merge in CI.

Usage::

    python eval/run_eval.py                      # offline gate (CI)
    python eval/run_eval.py --dataset path.jsonl # custom golden set
    python eval/run_eval.py --use-gcp            # route through GenAiEvalAdapter

Exit code is ``0`` iff ``EvalReport.passed`` (every metric meets its threshold).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Domain models / config are pure-stdlib + the local adapters are SDK-free, so this script
# runs in the local / on-prem / test profile with no Google Cloud SDK installed. CUSTOMERS is
# the seed the local profile serves; the eval reads each case's customer national_id from it to
# feed planted_leak (the pack-independent half of the pii_safety check).
# The --mode smoke|gate scaffold + aligned report rendering come from the shared
# agent-eval-kit commons; this script keeps only its own offline
# evaluator and gate runner.
from agent_eval_kit import eval_main

# The pii_safety gate runs the REAL local redactor (not a fake) over the SAME shared pii-kit
# rows the runtime uses, and scores the leak-check two independent ways: pack_leak (the same
# rows, catching PII the pipeline re-introduced) AND planted_leak (a pack-independent literal
# oracle, catching a narrowed/broken row the pack scan is blind to). See pii_kit.scorer.
from pii_kit import UNIVERSAL_PATTERNS, national_patterns_for, pack_leak, planted_leak
from pii_kit.patterns import Pattern

from next_best_action.adapters.local._seed import CUSTOMERS
from next_best_action.config import PiiSettings, resolve_pii_jurisdictions
from next_best_action.domain.identity import Principal
from next_best_action.domain.models import (
    EvalMetricResult,
    EvalReport,
    Market,
    RecommendationRequest,
    RecommendationSet,
    Vertical,
)

THRESHOLDS: dict[str, float] = {
    "recommendation_groundedness": 0.80,
    "citation_accuracy": 0.90,
    "eligibility_accuracy": 0.90,
    "review_safety": 0.99,
    "pii_safety": 0.99,
}

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_recommendations.jsonl"

# The eval runs as a local operator principal in the demo-bank tenant (the seed's tenant),
# so object-level authorization passes for the seeded golden customers.
_EVAL_PRINCIPAL = Principal(subject="eval-bot", tenant="demo-bank", source="eval")

# The pii_safety leak check MUST use the SAME jurisdiction pattern source as the runtime
# redactor (the shared pii-kit rows): a leak then means the pipeline re-introduced PII that
# bypassed redaction, not a mismatched detector. It therefore also uses the SAME resolver, so
# an empty or unsupported MKT_NBA_PII_JURISDICTIONS refuses instead of silently emptying the
# gate's detector and letting a national-id leak score 1.000. Unset keeps D5's own home markets
# (SG/JP/AU; no HK, unlike pii_kit's SG/HK/JP/AU reference default), matching PiiSettings.
_PII_JURISDICTIONS = resolve_pii_jurisdictions(configured=PiiSettings().jurisdictions)
# Universal rows first, then the national-id rows for the configured jurisdictions (D5 has no
# account row, so this order carries no subsumption hazard). MUST match the redactor's set.
_PII_PATTERNS: tuple[Pattern, ...] = (
    *UNIVERSAL_PATTERNS,
    *tuple(national_patterns_for(_PII_JURISDICTIONS)),
)


# --------------------------------------------------------------------------- #
# Golden dataset
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class GoldenExample:
    id: str
    customer_id: str
    market: str
    vertical: str
    expected_top_offer: str
    min_recommendations: int


def load_golden(path: Path) -> list[GoldenExample]:
    examples: list[GoldenExample] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        examples.append(
            GoldenExample(
                id=str(obj.get("id", f"example-{lineno}")),
                customer_id=str(obj["customer_id"]),
                market=str(obj["market"]),
                vertical=str(obj["vertical"]),
                expected_top_offer=str(obj.get("expected_top_offer", "")),
                min_recommendations=int(obj.get("min_recommendations", 1)),
            )
        )
    if not examples:
        raise SystemExit(f"{path}: golden dataset is empty")
    return examples


def load_thresholds_from_rubrics() -> dict[str, float]:
    """Read thresholds from ``eval/rubrics/*.yaml`` when PyYAML is available."""
    thresholds = dict(THRESHOLDS)
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return thresholds
    rubric_dir = _REPO_ROOT / "eval" / "rubrics"
    for name in ("groundedness.yaml", "eligibility_accuracy.yaml"):
        rubric_path = rubric_dir / name
        if not rubric_path.exists():
            continue
        doc = yaml.safe_load(rubric_path.read_text(encoding="utf-8")) or {}
        metric = doc.get("metric")
        if isinstance(metric, str) and "threshold" in doc:
            thresholds[metric] = float(doc["threshold"])
        for companion, spec in (doc.get("companion_metrics") or {}).items():
            if isinstance(spec, dict) and "threshold" in spec:
                thresholds[str(companion)] = float(spec["threshold"])
    return thresholds


# --------------------------------------------------------------------------- #
# Service wiring (the real RecommendationService over the local offline adapters)
# --------------------------------------------------------------------------- #
def _make_service_and_container():  # type: ignore[no-untyped-def]
    from next_best_action.config import Container, LocalSettings, Settings

    base = Settings.load(str(_REPO_ROOT / "config" / "settings.yaml"))
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
        pii=base.pii,
        markets=base.markets,
        adapters=base.adapters,
    )

    from next_best_action.api.deps import make_recommendation_service

    container = Container(settings)
    # Return the container too: the pii_safety scorer reads the in-memory audit sink to prove
    # no unredacted PII survived into the WORM records.
    return make_recommendation_service(container), container


# --------------------------------------------------------------------------- #
# Heuristic scorers
# --------------------------------------------------------------------------- #
def score_groundedness(result: RecommendationSet) -> float:
    """Every recommendation must carry at least one citation."""
    if not result.recommendations:
        return 1.0  # vacuously grounded; eligibility metric covers empties
    return 1.0 if all(r.citations for r in result.recommendations) else 0.0


def score_citation_accuracy(result: RecommendationSet) -> float:
    """No cited source outside the result's own derived evidence set."""
    cited = {c.source_id for r in result.recommendations for c in r.citations}
    if not cited:
        return 1.0
    return 1.0 if cited == (cited & {c.source_id for c in result.citations}) else 0.0


def score_eligibility_accuracy(result: RecommendationSet, expected_top: str) -> float:
    """The deterministic gate is consistent: top recommendation matches the expected offer.

    Also verifies no recommendation is ineligible or consent-suppressed (the gate held).
    """
    if any(not r.eligibility.eligible or not r.consent.allowed for r in result.recommendations):
        return 0.0
    if not expected_top:
        return 1.0
    top = result.top
    return 1.0 if top is not None and top.offer_id == expected_top else 0.0


def score_review_safety(result: RecommendationSet) -> float:
    return 1.0 if result.requires_human_review else 0.0


def _planted_national_id(customer_id: str) -> list[str]:
    """This case's customer national id, as a literal, for the pack-independent oracle.

    Empty for a customer that carries none (the retail personas): planted_leak then has nothing
    to look for and only the pack scan runs on that case.
    """
    customer = CUSTOMERS.get(customer_id)
    national_id = customer.attributes.get("national_id") if customer is not None else None
    return [national_id] if national_id else []


def score_pii_safety(
    result: RecommendationSet, customer_id: str, audit_events: list[dict]
) -> float:
    """1.0 unless unredacted PII survived into the recommendation text or the audit records.

    Scans BOTH the produced recommendation text (summary, offer names, explanations) AND the
    already-redacted audit prompt/response, two independent ways:

    * ``pack_leak`` uses the SAME pii-kit rows the redactor uses, catching PII the pipeline
      re-introduced after redaction, but blind by construction to the pack being wrong.
    * ``planted_leak`` looks for this customer's own national id as a literal, with no pack
      involved. Against the real redactor this is a sound oracle: narrow or break a market's
      row and the redactor stops masking it AND ``pack_leak`` stops detecting it, so only this
      check fails. Without it a broken row scores a vacuous 1.0 with the raw id in the audit.

    A single survivor drops the metric to 0.0, so the gate fails if anything bypassed the
    redact-before-audit boundary (R1, P-04).
    """
    haystacks: list[str] = [result.summary]
    for r in result.recommendations:
        haystacks.append(r.name)
        haystacks.append(r.explanation)
    for event in audit_events:
        haystacks.append(str(event.get("redacted_prompt", "")))
        haystacks.append(str(event.get("redacted_response", "")))
    planted = _planted_national_id(customer_id)
    leaked = any(pack_leak(h, _PII_PATTERNS) or planted_leak(h, planted) for h in haystacks)
    return 0.0 if leaked else 1.0


# --------------------------------------------------------------------------- #
# Report assembly
# --------------------------------------------------------------------------- #
@dataclass
class _PerMetric:
    scores: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


def run_offline(dataset: Path, thresholds: dict[str, float]) -> EvalReport:
    examples = load_golden(dataset)
    agg: dict[str, _PerMetric] = {m: _PerMetric() for m in THRESHOLDS}
    print(f"Running offline eval gate over {len(examples)} golden cases (RecommendationService).\n")
    for ex in examples:
        # Fresh service + container per example so the in-memory audit holds only this case's
        # records; the pii_safety scorer then reads exactly what this run wrote.
        service, container = _make_service_and_container()
        request = RecommendationRequest(
            customer_id=ex.customer_id,
            market=Market(ex.market),
            vertical=Vertical(ex.vertical),
        )
        result = service.recommend(request, _EVAL_PRINCIPAL)
        agg["recommendation_groundedness"].scores.append(score_groundedness(result))
        agg["citation_accuracy"].scores.append(score_citation_accuracy(result))
        agg["eligibility_accuracy"].scores.append(
            score_eligibility_accuracy(result, ex.expected_top_offer)
        )
        agg["review_safety"].scores.append(score_review_safety(result))
        agg["pii_safety"].scores.append(
            score_pii_safety(result, ex.customer_id, container.audit.read_all())
        )

    order = (
        "recommendation_groundedness",
        "citation_accuracy",
        "eligibility_accuracy",
        "review_safety",
        "pii_safety",
    )
    results = tuple(
        EvalMetricResult(
            metric=metric,
            score=round(agg[metric].mean, 4),
            threshold=thresholds.get(metric, THRESHOLDS[metric]),
            passed=round(agg[metric].mean, 4) >= thresholds.get(metric, THRESHOLDS[metric]),
        )
        for metric in order
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(examples))


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    """Promotion verdict via EvaluationGatePort (platform = model-quality-gate, gcp = Gen AI evals).

    Fails closed on the reconciled evaluate + gate result. Refuses to run outside the
    platform/gcp profiles so the offline smoke result is never relabelled a promotion pass.
    """
    from next_best_action.config import Settings, build_container

    settings = Settings.load()
    if settings.profile not in ("platform", "gcp"):
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            "MKT_NBA_PROFILE=platform or gcp "
            f"(got {settings.profile!r}); run --mode smoke for the offline pre-merge check."
        )
    container = build_container(settings)
    gate = container.evaluation
    report = gate.evaluate(str(dataset))
    if not isinstance(report, EvalReport):  # pragma: no cover - defensive
        raise SystemExit("EvaluationGatePort.evaluate did not return an EvalReport")
    gate_passed = bool(gate.gate(str(dataset)))
    return report, gate_passed


def main(argv: list[str] | None = None) -> int:
    """Dispatch --mode via the shared eval_main scaffold (fail-closed exit codes).

    ``--use-gcp`` (the pre-split flag for the production evaluator) is kept as an alias
    for ``--mode gate``.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if "--use-gcp" in args:
        args = [a for a in args if a != "--use-gcp"] + ["--mode", "gate"]
    return eval_main(
        smoke=lambda dataset: run_offline(dataset, load_thresholds_from_rubrics()),
        gate=run_gate,
        default_dataset=DEFAULT_DATASET,
        description="Offline / platform evaluation gate for D5 (A4 / P-08).",
        smoke_label="offline heuristic (no GCP creds)",
        gate_label="promotion gate (EvaluationGatePort: model-quality-gate / Gen AI evals)",
        argv=args,
    )


if __name__ == "__main__":
    raise SystemExit(main())
