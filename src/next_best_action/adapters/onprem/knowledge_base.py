"""On-prem placeholder for ``KnowledgeBasePort`` — the sovereign migration target.

Constructs cleanly with no external dependencies and structurally satisfies the same
Protocol as the managed File Search / Agent Search adapter.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import RetrievalQuery, RetrievedPassage

_MESSAGE = (
    "On-prem KnowledgeBasePort adapter is a migration placeholder; implement against your "
    "on-premise corpus search. Core domain logic is unchanged."
)


class OnPremKnowledgeBaseAdapter:
    """Placeholder offer/policy-corpus adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        raise NotImplementedError(_MESSAGE)
