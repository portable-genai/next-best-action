"""KnowledgeBasePort — the offer / policy corpus (File Search).

D5 grounds the explanation and the suitability rationale on an internal corpus: the offer
catalog descriptions, product disclosure / suitability notes and the per-market consent
policy. The primary GCP adapter is **File Search / Agent Search** over that corpus; the
``platform`` adapter is a thin HTTP client to the shared A2 Enterprise Knowledge Base; the
local adapter is an in-process SQLite FTS5 index over the seeded fictional corpus.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import RetrievalQuery, RetrievedPassage


@runtime_checkable
class KnowledgeBasePort(Protocol):
    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        """Retrieve ranked passages from the offer / policy corpus."""
        ...
