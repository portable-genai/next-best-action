"""LlmPort — LLM text/reasoning for explaining "why recommended".

Primary GCP adapter: Gemini models on the Gemini Enterprise Agent Platform
(``gemini-3.5-flash`` for explanation, ``gemini-3.5-flash`` for triage). The LLM only
explains the already-computed deterministic recommendation; it never decides the score, the
eligibility, the consent or the ranking.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import LlmRequest, LlmResponse


@runtime_checkable
class LlmPort(Protocol):
    def generate(self, request: LlmRequest) -> LlmResponse:
        """Generate a completion for ``request`` using the configured model."""
        ...

    def classify(self, text: str, labels: list[str]) -> str:
        """Cheap single-label classification (triage/routing tier model)."""
        ...
