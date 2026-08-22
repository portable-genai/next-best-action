"""Remote-platform redaction adapter (PIIRedactionPort) — thin HTTP client to A1.

Delegates PII de-identification to the shared **A1 Guardrail Gateway** service's
``/v1/redact`` endpoint (backed by DLP) instead of calling DLP directly, so customer PII is
removed at the boundary before any model, index or audit call (R1, P-04). Constructs
cleanly with no Google Cloud SDK; like the other ``platform`` adapters in this repo, the
HTTP body is wired in the platform phase. The base URL is read from ``HRZ_GUARDRAIL_URL``.
"""

from __future__ import annotations

from ...domain.models import RedactionResult
from ...envread import setting_or_default

_DEFAULT_URL = "http://localhost:8081"
_PHASE = "RemoteRedactionAdapter redact() (/v1/redact) is wired in the platform phase."


class RemoteRedactionAdapter:
    """HTTP client for the shared A1 guardrail-gateway ``/v1/redact`` endpoint."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = setting_or_default("HRZ_GUARDRAIL_URL", _DEFAULT_URL).rstrip("/")

    def redact(self, text: str) -> RedactionResult:
        raise NotImplementedError(_PHASE)
