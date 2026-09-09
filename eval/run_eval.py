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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Domain models / config are pure-stdlib + the local adapters are SDK-free, so this script
# runs in the local / on-prem / test profile with no Google Cloud SDK installed. CUSTOMERS is
# the seed the local profile serves; the eval reads each case's customer national_id from it to
# feed planted_leak (the pack-independent half of the pii_safety check).
# The --mode smoke|gate scaffold + aligned report rendering come from the shared
# agent-eval-kit commons; this script keeps only its own offline
# evaluator and gate runner.
from agent_eval_kit import (
    NotFalselyGreenError,
    assert_can_go_red,
    assert_denominator_supports,
    dataset_digest,
    eval_main,
    load_rubrics,
    prove_before_scoring,
)

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
    EligibilityOutcome,
    EvalMetricResult,
    EvalReport,
    Market,
    RecommendationRequest,
    RecommendationSet,
    Vertical,
)

#: Where every bar lives. Not a dict here: a threshold written as a Python literal carries no
#: argument. The rubric files carry the reasoning beside the number, and
#: `agent_eval_kit.load_rubrics` reads them.

#: The metrics this runner scores, in report order. Named so `assert_covers` can compare them
#: with the rubric set in BOTH directions.
SCORED: tuple[str, ...] = (
    "recommendation_groundedness",
    "citation_accuracy",
    "eligibility_accuracy",
    "ranking_order",
    "ranking_completeness",
    "review_safety",
    "pii_safety",
)

#: Named on the report and stamped on every EvalReport, so a stored result says what
#: produced it rather than leaving a reader to assume the production evaluator did.
_EVALUATOR = "offline heuristic (no GCP creds)"

#: How many 0/1 decisions each metric actually scored on the last run. Written by
#: `run_offline`, read by `scripts/render_evals_doc.py`, and the reason the denominator
#: column in docs/evals.md is measured rather than asserted: this is the one number a
#: hand-written page gets wrong first, and getting it wrong makes every bar beside it
#: unreadable.
SCORED_DECISIONS: dict[str, int] = {}

_REPO_ROOT = Path(__file__).resolve().parent.parent
RUBRICS = _REPO_ROOT / "eval" / "rubrics"
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
    """Read every metric's reviewed bar out of ``eval/rubrics/*.yaml``. No fallback, by design."""
    return load_rubrics(RUBRICS).thresholds()


def book_offers() -> dict[str, dict[str, Any]]:
    """The SHIPPED offer rows, by offer id. The book is the oracle, not the engine."""
    from next_best_action import demo_book

    return {str(row["offer_id"]): dict(row) for row in demo_book.BOOK.rows("offers")}


def book_propensities() -> dict[tuple[str, str], float]:
    """Per (customer, offer), the propensity score the SHIPPED book publishes."""
    from next_best_action import demo_book

    return {
        (str(row["customer_id"]), str(row["offer_id"])): float(row["score"])
        for row in demo_book.BOOK.rows("propensity_signals")
    }


def in_scope_offers(offers: dict, customer_id: str, market: str, vertical: str) -> dict:
    """The active book offers for this market and vertical. Nothing about the engine here."""
    from next_best_action.adapters.local._seed import CUSTOMERS

    del customer_id, CUSTOMERS  # kept out on purpose: scope is the catalog's, not the customer's
    return {
        oid: row
        for oid, row in offers.items()
        if row.get("active", True) and row["market"] == market and row["vertical"] == vertical
    }


def score_ranking_order(
    result: RecommendationSet, customer_id: str, offers: dict, propensities: dict
) -> list[float]:
    """One 0/1 per adjacent pair whose order the SHIPPED book already decides.

    `eligibility_accuracy` reads `result.top` and the gate flags. It says nothing about rank
    two and below, so a service that returned the right first offer and then anything at all,
    in any order, scored a perfect 1.000. A customer sees the list; rank two is the offer a
    relationship manager reaches for when the first is declined.

    The oracle is deliberately NOT the engine's own score, and not the published propensity
    order either. It is DOMINANCE: where an offer has both a higher published propensity and
    a higher published value than the one below it, every weighting with non-negative weights
    must rank it higher, so the book decides that pair on its own and a violation is a defect
    under any tuning. Where propensity and value disagree, the weights resolve it, the weights
    are a business choice rather than a correctness claim, and this metric stays silent: that
    pair contributes no score at all rather than a guess.

    Returned as a list because a case with three offers makes two ordering claims and a case
    with one makes none. Averaging per case would give a case that asserts nothing the same
    weight as a case that asserts two things.
    """
    ids = [rec.offer_id for rec in result.recommendations]
    scores: list[float] = []
    for upper, lower in zip(ids, ids[1:], strict=False):
        pair = [(upper, 1), (lower, 0)]
        if any(oid not in offers or (customer_id, oid) not in propensities for oid, _ in pair):
            # An offer the book does not publish, or publishes no signal for. Not an ordering
            # question: it is a recommendation nobody scored, which is worse than a wrong order.
            scores.append(0.0)
            continue
        p_up, p_low = propensities[(customer_id, upper)], propensities[(customer_id, lower)]
        v_up, v_low = float(offers[upper]["base_value"]), float(offers[lower]["base_value"])
        if p_up >= p_low and v_up >= v_low:
            scores.append(1.0)  # dominance respected
        elif p_low >= p_up and v_low >= v_up:
            scores.append(0.0)  # the dominated offer was ranked above the one that dominates it
        # else: propensity and value disagree; the weights decide, and this metric does not.
    return scores


def score_ranking_completeness(
    result: RecommendationSet, customer_id: str, offers: dict
) -> list[float]:
    """One 0/1 per in-scope book offer: is its disposition the one the book requires?

    A conservation law over the whole catalog, not over the list the engine chose to return,
    which is what makes it able to see the failure that matters here. An offer that quietly
    stops being a candidate leaves a SHORTER list, and a shorter list is invisible to every
    metric that scores what is in it: groundedness, citation accuracy and eligibility accuracy
    all read the returned recommendations and would score a truncated list 1.000.

    Each offer the customer could see must appear exactly once across recommendations,
    `suppressed` and `consent_suppressed`. Each offer the book itself removes (already held,
    conflicting with a holding, out of stock) must appear in none of them.
    """
    from next_best_action.adapters.local._seed import CUSTOMERS

    customer = CUSTOMERS.get(customer_id)
    held = set(customer.holdings) if customer is not None else set()
    placed: dict[str, int] = {}
    for offer_id in (
        [rec.offer_id for rec in result.recommendations]
        + [item.offer_id for item in result.suppressed]
        + [item.offer_id for item in result.consent_suppressed]
    ):
        placed[offer_id] = placed.get(offer_id, 0) + 1

    scores: list[float] = []
    for offer_id, row in sorted(offers.items()):
        stock = row.get("stock")
        removed_by_book = (
            offer_id in held
            or any(conflict in held for conflict in (row.get("excluded_if_held") or ()))
            or (stock is not None and int(stock) <= 0)
        )
        expected = 0 if removed_by_book else 1
        scores.append(1.0 if placed.get(offer_id, 0) == expected else 0.0)
    return scores


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
        # book_path too, and that is not cosmetic. It defaulted to ~/.next_best_action/
        # book.duckdb, a store the kit seeds ONCE and then leaves alone however far the
        # shipped book moves. So the gate scored whatever rows this laptop happened to cache
        # the first time anyone ran the demo, and only a machine that had never run it
        # scored what the repository actually ships. In memory, the run reads the book.
        local=LocalSettings(db_path=":memory:", audit_path=":memory:", book_path=":memory:"),
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
def _red_case_proofs() -> tuple[Callable[[], None], ...]:
    """One proof per scored metric: the same input, once clean and once with the defect.

    These use the scorers this module is about to run, not copies, so a scorer that became a
    constant 1.0 during a refactor fails here rather than certifying the release.
    """
    from dataclasses import replace

    thresholds = load_rubrics(RUBRICS).thresholds()
    offers = book_offers()
    propensities = book_propensities()

    # One real result off the local stack: the green half of every proof below.
    service, container = _make_service_and_container()
    example = load_golden(DEFAULT_DATASET)[0]
    clean = service.recommend(
        RecommendationRequest(
            customer_id=example.customer_id,
            market=Market(example.market),
            vertical=Vertical(example.vertical),
        ),
        _EVAL_PRINCIPAL,
    )
    scope = in_scope_offers(offers, example.customer_id, example.market, example.vertical)
    audit = container.audit.read_all()

    def _uncited() -> RecommendationSet:
        return replace(
            clean,
            recommendations=tuple(replace(r, citations=()) for r in clean.recommendations),
        )

    def _fabricated() -> RecommendationSet:
        first = clean.recommendations[0]
        forged = replace(first.citations[0], source_id="fabricated-source-not-in-evidence")
        return replace(
            clean,
            recommendations=(replace(first, citations=(forged,)), *clean.recommendations[1:]),
        )

    def recommendation_groundedness() -> None:
        assert_can_go_red(
            score_groundedness,
            green=clean,
            red=_uncited(),
            threshold=thresholds["recommendation_groundedness"],
            metric="recommendation_groundedness",
        )

    def citation_accuracy() -> None:
        assert_can_go_red(
            score_citation_accuracy,
            green=clean,
            red=_fabricated(),
            threshold=thresholds["citation_accuracy"],
            metric="citation_accuracy",
        )

    def eligibility_accuracy() -> None:
        # The gate letting an ineligible offer through, which is the first thing this metric
        # claims. Reversing the list would not do: the first golden case returns one offer,
        # so a reversed list is the same list and the proof would pass on a dead metric.
        first = clean.recommendations[0]
        ineligible = replace(
            first,
            eligibility=replace(first.eligibility, outcome=EligibilityOutcome.INELIGIBLE),
        )
        assert_can_go_red(
            lambda r: score_eligibility_accuracy(r, example.expected_top_offer),
            green=clean,
            red=replace(clean, recommendations=(ineligible, *clean.recommendations[1:])),
            threshold=thresholds["eligibility_accuracy"],
            metric="eligibility_accuracy",
        )

    def review_safety() -> None:
        assert_can_go_red(
            score_review_safety,
            green=clean,
            red=replace(clean, requires_human_review=False),
            threshold=thresholds["review_safety"],
            metric="review_safety",
        )

    def pii_safety() -> None:
        leaked = _planted_national_id(example.customer_id)
        assert_can_go_red(
            lambda r: score_pii_safety(r, example.customer_id, audit),
            green=clean,
            red=replace(clean, summary=f"{clean.summary} {leaked[0] if leaked else 'x@y.test'}"),
            threshold=thresholds["pii_safety"],
            metric="pii_safety",
        )

    def ranking_order() -> None:
        # A real list with the two offers the book's dominance rule decides, and the same
        # list with exactly those two swapped. Built from a DECIDABLE pair rather than from
        # the first case, whose list is a single offer: that list asserts no order, so the
        # proof would pass against a metric that had stopped looking at order altogether.
        customer_id, decided, index = _decidable_case(offers, propensities)
        pair_scope = in_scope_offers(
            offers,
            customer_id,
            str(decided.market.value),
            str(decided.vertical.value),
        )
        swapped = list(decided.recommendations)
        swapped[index], swapped[index + 1] = swapped[index + 1], swapped[index]
        assert_can_go_red(
            lambda r: _mean(score_ranking_order(r, customer_id, pair_scope, propensities)),
            green=decided,
            red=replace(decided, recommendations=tuple(swapped)),
            threshold=thresholds["ranking_order"],
            metric="ranking_order",
        )

    def ranking_completeness() -> None:
        # One offer dropped from every list: the shape of a candidate that quietly stopped
        # being one. Nothing else in this gate reads the offers that are NOT in the result.
        assert_can_go_red(
            lambda r: _mean(score_ranking_completeness(r, example.customer_id, scope)),
            green=clean,
            red=replace(clean, consent_suppressed=(), suppressed=()),
            threshold=thresholds["ranking_completeness"],
            metric="ranking_completeness",
        )

    # Named exactly after the metric each one falsifies, so tests/ can check that the set
    # of proofs and the set of scored metrics are the same set.
    return (
        recommendation_groundedness,
        citation_accuracy,
        eligibility_accuracy,
        ranking_order,
        ranking_completeness,
        review_safety,
        pii_safety,
    )


def _mean(scores: list[float]) -> float:
    """Empty scores 0.0, not 1.0: a metric that measured nothing has not passed."""
    return sum(scores) / len(scores) if scores else 0.0


def _decidable_case(offers: dict, propensities: dict) -> tuple[str, RecommendationSet, int]:
    """The first golden result holding an adjacent pair the book decides, and where it sits.

    Refuses when the corpus holds none. A corpus in which the book decides no pair cannot
    falsify `ranking_order`, and scoring it anyway would report a bar nothing tested.
    """
    for example in load_golden(DEFAULT_DATASET):
        service, _ = _make_service_and_container()
        result = service.recommend(
            RecommendationRequest(
                customer_id=example.customer_id,
                market=Market(example.market),
                vertical=Vertical(example.vertical),
            ),
            _EVAL_PRINCIPAL,
        )
        scope = in_scope_offers(offers, example.customer_id, example.market, example.vertical)
        ids = [rec.offer_id for rec in result.recommendations]
        for index in range(len(ids) - 1):
            decided = score_ranking_order(
                _only(result, index), example.customer_id, scope, propensities
            )
            if decided:
                return example.customer_id, result, index
    raise NotFalselyGreenError(
        "no golden case has two adjacent offers the book's dominance rule decides, so "
        "ranking_order cannot be falsified against this corpus"
    )


def _only(result: RecommendationSet, index: int) -> RecommendationSet:
    """The same result narrowed to one adjacent pair, so a single pair can be asked about."""
    from dataclasses import replace

    return replace(result, recommendations=result.recommendations[index : index + 2])


@dataclass
class _PerMetric:
    scores: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


def run_offline(dataset: Path, thresholds: dict[str, float]) -> EvalReport:
    # The rubrics and the scored set must agree in BOTH directions before anything is scored.
    load_rubrics(RUBRICS).assert_covers(SCORED)
    examples = load_golden(dataset)
    # Falsification first, as the opening statement of the scored run and not only under
    # tests/: a metric that cannot go red is not evidence, and a suite that proves it
    # somewhere else proves it about a run nobody shipped.
    prove_before_scoring(*_red_case_proofs())
    agg: dict[str, _PerMetric] = {metric: _PerMetric() for metric in SCORED}
    propensities = book_propensities()
    offers = book_offers()
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
        scope = in_scope_offers(offers, ex.customer_id, ex.market, ex.vertical)
        agg["ranking_order"].scores.extend(
            score_ranking_order(result, ex.customer_id, scope, propensities)
        )
        agg["ranking_completeness"].scores.extend(
            score_ranking_completeness(result, ex.customer_id, scope)
        )
        agg["review_safety"].scores.append(score_review_safety(result))
        agg["pii_safety"].scores.append(
            score_pii_safety(result, ex.customer_id, container.audit.read_all())
        )

    # Every bar is checked against the denominator that actually reached it, not against the
    # case count. Most of these are scored once per example; the two ranking metrics are not,
    # and using 8 for them would have certified a bar the run cannot support.
    SCORED_DECISIONS.clear()
    SCORED_DECISIONS.update({metric: len(agg[metric].scores) for metric in SCORED})
    for metric in SCORED:
        assert_denominator_supports(thresholds[metric], len(agg[metric].scores), metric=metric)

    results = tuple(
        EvalMetricResult(
            metric=metric,
            score=round(agg[metric].mean, 4),
            threshold=thresholds[metric],
            passed=round(agg[metric].mean, 4) >= thresholds[metric],
        )
        for metric in SCORED
    )
    return EvalReport(
        dataset=str(dataset),
        results=results,
        n_examples=len(examples),
        dataset_digest=dataset_digest(dataset),
        evaluator=_EVALUATOR,
    )


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
