"""ConsentPort: the boundary onto Mkt6, the catalog's consent system of record.

The versioned wire types come from ``consent-preference-kit``. The recommendation domain asks
this port instead of reading consent rows from its own recommendation store, so local, managed,
and exit profiles exercise the same legal-decision contract.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from consent_preference_kit import Citation as ConsentCitation
from consent_preference_kit import ConsentDecision, ConsentQuery


class ConsentUnavailableError(RuntimeError):
    """Raised when no consent decision can be obtained."""


@runtime_checkable
class ConsentPort(Protocol):
    """Ask whether a subject may receive one marketing contact."""

    def decide(self, query: ConsentQuery) -> ConsentDecision:
        """Return the cited decision or raise :class:`ConsentUnavailableError`."""
        ...


__all__ = [
    "ConsentCitation",
    "ConsentDecision",
    "ConsentPort",
    "ConsentQuery",
    "ConsentUnavailableError",
]
