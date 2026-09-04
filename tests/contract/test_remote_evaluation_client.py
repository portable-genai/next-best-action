"""Contract test: the platform eval adapter speaks A4's hardened, bundle-driven HTTP shape.

Pins the request/response contract of :class:`RemoteEvaluationAdapter` against the A4
(model-quality-gate) AI-quality service without a live server: HTTP is intercepted with ``respx``.
The request assertions lock the details that A4's hardening depends on — a *structured* target, the
top-level ``dataset_id`` mirroring ``target.dataset_id``, metric selection via the ``bundle`` field
only (never a metric-name list), ``results[]`` parsed into an ``EvalReport``, and a ``gate()`` that
POSTs ``/v1/gate``.

The RESPONSE fixtures model the hardened ``agent-eval-kit`` contract, which is far stricter
than a naked aggregate boolean. The client RE-DERIVES every verdict from
the evidence and raises on any contradiction, on the plain evaluations path as well as
inside ``gate``: an evaluation response needs durable identifiers (``run_id``,
``dataset_version``, ``dataset_digest``, ``evaluator``, ``schema_version``), a non-empty
``artifact_refs``, an ``attested`` flag, a positive ``n_examples``, and per-metric rows whose
``passed`` equals ``score >= threshold``; a gate response needs all of that inside
``eval_report``, plus a ``redteam_report`` whose aggregate matches its rows and whose every
row's ``passed`` and ``blocked`` agree, durable ``model_card_ref`` and ``mrm_evidence_ref``,
and a top-level ``passed`` equal to (eval passed AND attested AND red-team passed).

The refusal tests below are the point, not an inconvenience: a promotion
certified by a naked ``{"passed": true}`` is a promotion certified by nothing. Every value
is obviously fictional.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from next_best_action.adapters.platform.remote_evaluation import (
    RemoteEvaluationAdapter,
    RemoteEvaluationError,
)
from next_best_action.config import Settings
from next_best_action.domain.errors import NextBestActionError
from next_best_action.domain.models import EvalReport

_BASE = "https://hrz4.test"
_DATASET = "eval/datasets/golden_recommendations.jsonl"
_DATASET_ID = "golden_recommendations"
_DIGEST = "sha256:feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface"

_PASSING_RESULTS = [
    {"metric": "recommendation_groundedness", "score": 0.91, "threshold": 0.80, "passed": True},
    {"metric": "citation_accuracy", "score": 0.95, "threshold": 0.90, "passed": True},
]

#: A consistent FAILING set: the row misses its bar and says so. The client re-derives each
#: verdict, so a FAIL has to be a coherent story rather than a contradictory body.
_FAILING_RESULTS = [
    {"metric": "recommendation_groundedness", "score": 0.61, "threshold": 0.80, "passed": False},
    {"metric": "citation_accuracy", "score": 0.95, "threshold": 0.90, "passed": True},
]


def _evidence(**overrides: Any) -> dict[str, Any]:
    """Durable evaluation evidence in the full hardened shape, obviously fictional."""
    body: dict[str, Any] = {
        "results": _PASSING_RESULTS,
        "n_examples": 12,
        "run_id": "run-fictional-0001",
        "dataset_version": f"{_DATASET_ID}@2026-08-01",
        "dataset_digest": _DIGEST,
        "evaluator": "hrz4-ai-quality (FICTIONAL)",
        "schema_version": "v1",
        "artifact_refs": ["gs://fictional-hrz4-evidence/run-fictional-0001/report.json"],
        "attested": True,
    }
    body.update(overrides)
    return body


def _gate_body(**overrides: Any) -> dict[str, Any]:
    """The complete GateDecision the promotion gate now demands."""
    body: dict[str, Any] = {
        "passed": True,
        "eval_report": _evidence(),
        "redteam_report": {
            "passed": True,
            "results": [
                {"case": "prompt-injection-01", "passed": True, "blocked": True},
                {"case": "customer-pii-exfil-01", "passed": True, "blocked": True},
            ],
        },
        "model_card_ref": "gs://fictional-hrz4-evidence/model-cards/mkt5-nba.md",
        "mrm_evidence_ref": "gs://fictional-hrz4-evidence/mrm/mkt5-nba-2026-08.json",
    }
    body.update(overrides)
    return body


def _adapter(monkeypatch: pytest.MonkeyPatch) -> RemoteEvaluationAdapter:
    monkeypatch.setenv("QUALITY_GATE_URL", _BASE)
    return RemoteEvaluationAdapter(Settings())


def _assert_no_metric_list(obj: Any) -> None:
    """Recursively assert the request never carries a metric-name list (or a ``metrics`` key)."""
    if isinstance(obj, dict):
        assert "metrics" not in obj, "adapter must select metrics by bundle, not a metric list"
        for value in obj.values():
            _assert_no_metric_list(value)
    else:
        assert not isinstance(obj, list), "no list values allowed (would imply a metric list)"


@respx.mock
def test_evaluate_posts_structured_bundle_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def responder(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_evidence())

    route = respx.post(f"{_BASE}/v1/evaluations").mock(side_effect=responder)

    report = _adapter(monkeypatch).evaluate(_DATASET)

    assert route.called
    body = captured["body"]

    # Structured target (not a flat string).
    assert isinstance(body["target"], dict)
    assert body["target"]["model"] == Settings().models.reasoning
    assert body["target"]["prompt_version"] == "v1"
    assert body["target"]["system"] == ""

    # dataset_id is the basename without .jsonl, and the top level mirrors target.dataset_id.
    assert body["dataset_id"] == _DATASET_ID
    assert body["dataset_id"] == body["target"]["dataset_id"]

    # Metrics are selected by bundle only; never a metric-name list.
    assert body["bundle"] == "mkt5-nba"
    _assert_no_metric_list(body)

    # results[] parsed into an EvalReport.
    assert isinstance(report, EvalReport)
    assert report.passed
    assert report.n_examples == 12
    assert {r.metric for r in report.results} == {
        "recommendation_groundedness",
        "citation_accuracy",
    }
    groundedness = next(r for r in report.results if r.metric == "recommendation_groundedness")
    assert groundedness.score == 0.91
    assert groundedness.threshold == 0.80
    assert groundedness.passed is True

    # The durable evidence SURVIVES the adapter. An adapter rebuilding the client's report
    # into a three-field local copy, which silently dropped every field below: the promotion still
    # looked certified, with nothing left to audit it against. The report the port returns is now
    # the client's own, so these assertions fail the moment anyone reintroduces a mapper.
    assert report.dataset == _DATASET
    assert report.run_id == "run-fictional-0001"
    assert report.dataset_version == f"{_DATASET_ID}@2026-08-01"
    assert report.dataset_digest == _DIGEST
    assert report.evaluator == "hrz4-ai-quality (FICTIONAL)"
    assert report.schema_version == "v1"
    assert report.artifact_refs == ("gs://fictional-hrz4-evidence/run-fictional-0001/report.json",)
    assert report.attested is True


@respx.mock
def test_evaluate_REFUSES_metric_rows_with_no_examples_behind_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``all(())`` is vacuously true; a report that scored nothing must not parse."""
    respx.post(f"{_BASE}/v1/evaluations").mock(
        return_value=httpx.Response(200, json=_evidence(n_examples=0))
    )
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).evaluate(_DATASET)


@respx.mock
def test_evaluate_REFUSES_a_verdict_that_contradicts_its_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row claiming PASS below its own threshold is evidence of a broken evaluator."""
    rows = [
        {"metric": "recommendation_groundedness", "score": 0.10, "threshold": 0.80, "passed": True}
    ]
    respx.post(f"{_BASE}/v1/evaluations").mock(
        return_value=httpx.Response(200, json=_evidence(results=rows))
    )
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).evaluate(_DATASET)


@respx.mock
def test_evaluate_REFUSES_evidence_with_no_durable_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a run id or an artifact ref the score is unreproducible and unauditable."""
    respx.post(f"{_BASE}/v1/evaluations").mock(
        return_value=httpx.Response(200, json=_evidence(run_id="", artifact_refs=[]))
    )
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).evaluate(_DATASET)


@respx.mock
def test_gate_posts_to_v1_gate_and_returns_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def responder(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_gate_body())

    route = respx.post(f"{_BASE}/v1/gate").mock(side_effect=responder)

    result = _adapter(monkeypatch).gate(_DATASET)

    assert route.called
    assert result is True

    body = captured["body"]
    assert isinstance(body["target"], dict)
    assert body["bundle"] == "mkt5-nba"
    assert body["dataset_id"] == _DATASET_ID
    assert body["dataset_id"] == body["target"]["dataset_id"]
    _assert_no_metric_list(body)


@respx.mock
def test_gate_returns_false_through_consistent_failing_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FAIL is reached through a failing metric row, never a contradictory body."""
    body = _gate_body(passed=False, eval_report=_evidence(results=_FAILING_RESULTS))
    respx.post(f"{_BASE}/v1/gate").mock(return_value=httpx.Response(200, json=body))
    assert _adapter(monkeypatch).gate(_DATASET) is False


@respx.mock
def test_gate_REFUSES_a_naked_boolean_with_no_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unhardened response shape. Accepting it is how a promotion gets certified by
    nothing, so the refusal is the contract."""
    respx.post(f"{_BASE}/v1/gate").mock(return_value=httpx.Response(200, json={"passed": True}))
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).gate(_DATASET)


@respx.mock
def test_gate_REFUSES_an_unattested_report_even_when_every_metric_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A laptop evaluator can score the same corpus; that is not release authority."""
    respx.post(f"{_BASE}/v1/gate").mock(
        return_value=httpx.Response(200, json=_gate_body(eval_report=_evidence(attested=False)))
    )
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).gate(_DATASET)


@respx.mock
def test_gate_REFUSES_a_redteam_aggregate_that_contradicts_its_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _gate_body(
        redteam_report={
            "passed": True,
            "results": [{"case": "prompt-injection-01", "passed": False, "blocked": False}],
        }
    )
    respx.post(f"{_BASE}/v1/gate").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).gate(_DATASET)


@respx.mock
def test_gate_REFUSES_a_decision_with_no_model_card_or_mrm_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Promotion evidence a model-risk reviewer cannot later retrieve is not evidence."""
    respx.post(f"{_BASE}/v1/gate").mock(
        return_value=httpx.Response(200, json=_gate_body(model_card_ref="", mrm_evidence_ref=""))
    )
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).gate(_DATASET)


@respx.mock
def test_non_2xx_raises_repo_error(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.post(f"{_BASE}/v1/evaluations").mock(
        return_value=httpx.Response(503, text="service unavailable")
    )
    adapter = _adapter(monkeypatch)
    with pytest.raises(RemoteEvaluationError):
        adapter.evaluate(_DATASET)
    # The repo error is a domain error, so callers can catch it without an httpx dependency.
    assert issubclass(RemoteEvaluationError, NextBestActionError)
