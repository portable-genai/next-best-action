"""On-prem ConsentPort placeholder: bind the client's own preference centre."""

from __future__ import annotations

from consent_preference_kit import ConsentDecision, ConsentQuery

from ...config import Settings


class OnPremConsentAdapter:
    """Fail fast instead of inventing a consent decision during sovereign exit."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def decide(self, query: ConsentQuery) -> ConsentDecision:
        raise NotImplementedError(
            "on-prem consent lookup is a portability placeholder: bind the client's own "
            "preference centre. A decision nobody made is not consent."
        )
