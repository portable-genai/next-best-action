"""Remote-platform knowledge-base adapter (KnowledgeBasePort) — thin HTTP client to A2.

When D5 reuses the shared platform, the offer / policy corpus is the **A2 Enterprise
Knowledge Base**. This adapter implements the port by POSTing to A2's ``/v1/search`` (base
URL from ``KNOWLEDGE_BASE_URL``). Constructs cleanly with no Google Cloud SDK; the HTTP body is
wired in the platform phase.
"""

from __future__ import annotations

from ...domain.errors import NextBestActionError
from ...domain.models import RetrievalQuery, RetrievedPassage
from ...envread import setting_or_default

_DEFAULT_URL = "http://localhost:8082"
_PHASE = "RemoteKnowledgeBaseAdapter search() is wired in the platform phase."


class RemoteKnowledgeBaseError(NextBestActionError):
    """Raised when the A2 knowledge-base service returns a non-2xx response."""


class RemoteKnowledgeBaseAdapter:
    """HTTP client for the shared A2 enterprise knowledge base."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = setting_or_default("KNOWLEDGE_BASE_URL", _DEFAULT_URL).rstrip("/")

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        raise NotImplementedError(_PHASE)
