"""Span ATTRIBUTES carry structure, never content, and this is the test that can tell.

The pipeline tests wire the real ``LocalNoopTracerAdapter``, whose ``span`` is a
``nullcontext``: it observes nothing, so a span that started carrying the customer's
national id, the internal customer key or an offer name would keep every existing test
green. A trace backend is not the WORM audit trail. It has no redaction stage, a wider read
audience and no retention rule written against a regulator's requirement, so an attribute is
OUTSIDE the boundary redact-before-audit (C3) holds: the sibling test
``test_audit_redacts_pii_and_pseudonymizes_customer_id`` proves the audit sink masks the
NRIC and pseudonymizes the customer key, and none of that machinery runs on a span.

The recording tracer here keeps ``dict(attributes)`` and drives the real request path,
``RecommendationService.recommend``, for ``cust-sg-bank-1``, whose seeded profile carries the
planted NRIC ``S1234567A``. A leak therefore fails on a planted literal rather than on a
subtlety.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext

import pytest

from next_best_action.api.deps import make_recommendation_service
from next_best_action.config import Container
from next_best_action.domain.identity import Principal
from next_best_action.domain.models import (
    Market,
    RecommendationRequest,
    TokenUsage,
    Vertical,
)

#: The seeded SG banking customer whose profile carries the planted NRIC.
CUSTOMER_ID = "cust-sg-bank-1"
PLANTED_NRIC = "S1234567A"

#: The complete attribute key set an next-best-action span may carry, per span name. Widening one of
#: these is a decision about what leaves the trust boundary, so it is made here rather
#: than at a call site.
_ALLOWED = {
    "nba.recommend": {"market"},
}


class _AttributeRecordingTracer:
    """Keeps (name, attributes) per span; the local adapter records nothing at all."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    def span(self, name: str, **attributes: str) -> AbstractContextManager[None]:
        self.spans.append((name, dict(attributes)))
        return nullcontext()

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        return None


@pytest.fixture
def tracer(local_container: Container) -> _AttributeRecordingTracer:
    """Swap the container's cached tracer BEFORE the service factory reads it."""
    recorder = _AttributeRecordingTracer()
    local_container.tracer = recorder  # type: ignore[misc]
    return recorder


def _recommend(container: Container) -> None:
    make_recommendation_service(container).recommend(
        RecommendationRequest(customer_id=CUSTOMER_ID, market=Market.SG, vertical=Vertical.BANKING),
        Principal(subject="test", tenant="demo-bank", source="test"),
    )


def test_the_request_path_opens_exactly_the_known_spans(
    local_container: Container, tracer: _AttributeRecordingTracer
) -> None:
    _recommend(local_container)
    names = {name for name, _ in tracer.spans}
    assert names == set(_ALLOWED), (
        "the set of spans this request path opens changed; a new span site is a "
        "trust-boundary decision, so record it in _ALLOWED here deliberately"
    )


def test_every_span_carries_allowlisted_keys_only(
    local_container: Container, tracer: _AttributeRecordingTracer
) -> None:
    _recommend(local_container)
    assert tracer.spans, "the request path opened no span at all"
    for name, attributes in tracer.spans:
        assert name in _ALLOWED, f"unexpected span {name!r}; add it here deliberately"
        assert set(attributes) == _ALLOWED[name], (
            f"span {name!r} attribute keys changed; widening the set is a trust-boundary "
            "decision, so update _ALLOWED here deliberately"
        )


def test_no_span_attribute_carries_the_planted_identifiers(
    local_container: Container, tracer: _AttributeRecordingTracer
) -> None:
    """The seeded NRIC and the internal customer key both stay out of the trace."""
    _recommend(local_container)
    emitted = " ".join(value for _, attributes in tracer.spans for value in attributes.values())
    assert PLANTED_NRIC not in emitted, "the customer's national id reached a span attribute"
    assert CUSTOMER_ID not in emitted, "the internal customer key reached a span attribute"


def test_no_span_attribute_carries_the_seeded_offer_catalog(
    local_container: Container, tracer: _AttributeRecordingTracer
) -> None:
    """Offer names and explanations are recommendation content, not span structure."""
    _recommend(local_container)
    emitted = " ".join(value for _, attributes in tracer.spans for value in attributes.values())
    assert "FICTIONAL" not in emitted, (
        "every seeded offer name is stamped FICTIONAL; seeing one in a span attribute "
        "means catalog content reached the trace"
    )


def test_every_attribute_value_is_a_string(
    local_container: Container, tracer: _AttributeRecordingTracer
) -> None:
    """The port declares str values; a structured object smuggles content past a grep."""
    _recommend(local_container)
    for name, attributes in tracer.spans:
        for key, value in attributes.items():
            assert isinstance(value, str), f"span {name!r} attribute {key!r} is not a str"


def test_the_recorder_satisfies_the_tracer_port() -> None:
    """The guard is only evidence if the service accepts the recorder as its tracer."""
    from next_best_action.ports.observability import ObservabilityTracerPort

    assert isinstance(_AttributeRecordingTracer(), ObservabilityTracerPort)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
