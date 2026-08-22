"""Safety ports — the A1 Guardrail Gateway concerns, expressed as interfaces (R1).

Primary GCP adapters: **Model Armor** (prompt-injection / jailbreak / unsafe-content
screening) and **Sensitive Data Protection / DLP** (``deidentifyContent``) for PII
redaction before any model call, trace span or audit write. The mandatory boundary order
is redact then guardrail(INPUT), and guardrail(OUTPUT) then audit the already-redacted
record, so customer PII is minimised to the model and never reaches the audit sink (P-04).

Each port ships adapters per profile: local (heuristic / regex), GCP (Model Armor / DLP),
platform (delegate to the shared guardrail gateway) and an on-prem fail-closed placeholder.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import Direction, GuardrailVerdict, RedactionResult


@runtime_checkable
class GuardrailPort(Protocol):
    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        """Screen ``text`` (INPUT or OUTPUT) and return an allow/block verdict."""
        ...


@runtime_checkable
class PIIRedactionPort(Protocol):
    def redact(self, text: str) -> RedactionResult:
        """De-identify PII so the result is safe to send to a model or audit sink."""
        ...
