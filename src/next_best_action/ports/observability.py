"""Observability ports — the A5 (audit/trace) and A4 (eval gate) concerns.

Primary GCP adapters: a **Cloud Logging locked WORM bucket** for immutable audit, **Cloud
Trace via OpenTelemetry** for the reasoning-loop traces, and the **Gen AI evaluation
service** plus the A4 promotion gate for model risk.

``ObservabilityTracerPort`` (with its ``TokenUsage``) and ``EvaluationGatePort`` are
**re-exported, not redeclared**. Hand-copied Protocol bodies in this file, and in every sibling
repository, drift: one copy drops the evaluation port entirely, another drops its ``gate``
method and keeps only ``evaluate`` (the half that cannot refuse a promotion), another returns
``str`` from an audit ``record`` that returns ``None`` everywhere else. A Protocol copied into N
repositories is N Protocols, and only one of them gets fixed when a defect is found. So they
come from the commons packages that own the types they speak in: the tracer beside its
``TokenUsage``, the gate beside its ``EvalReport``.

``AuditSinkPort`` stays declared here, deliberately: it is typed in THIS repo's vocabulary
(:class:`~next_best_action.domain.models.AuditEvent`), so it is not a shared shape.

Both imports are typing-only and cost the offline profile nothing: no OpenTelemetry, no cloud
SDK. The OpenTelemetry implementation lives in ``hex_service_kit.tracing`` behind the ``otel``
extra and is reached only by the GCP adapter.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_eval_kit import EvaluationGatePort as EvaluationGatePort
from hex_service_kit.observability import ObservabilityTracerPort as ObservabilityTracerPort
from hex_service_kit.observability import TokenUsage as TokenUsage

from ..domain.models import AuditEvent

__all__ = [
    "AuditSinkPort",
    "EvaluationGatePort",
    "ObservabilityTracerPort",
    "TokenUsage",
]


@runtime_checkable
class AuditSinkPort(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Write an immutable audit record (WORM)."""
        ...
