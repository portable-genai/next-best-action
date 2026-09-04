"""Managed ConsentPort: ask marketing-compliance-gate through the pinned consent client contract."""

from __future__ import annotations

from consent_preference_kit import (
    ConsentClient,
    ConsentClientError,
    ConsentDecision,
    ConsentQuery,
)

from ...config import Settings
from ...ports.consent import ConsentUnavailableError

_SERVICE_ACTOR = "next-best-action"


class RemoteConsentAdapter:
    """Obtain a fail-closed consent decision from the configured
    marketing-compliance-gate service.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client(self) -> ConsentClient:
        base_url = self._settings.consent_url.strip()
        if not base_url:
            raise ConsentUnavailableError(
                "consent_url is not configured. Set MKT_CONSENT_STORE_URL to "
                "marketing-compliance-gate; the "
                "managed profile has no private consent-store fallback."
            )
        audience = self._settings.consent_audience.strip()
        if not audience:
            raise ConsentUnavailableError(
                "consent_audience is not configured. Set MKT_CONSENT_STORE_AUDIENCE to the "
                "custom audience marketing-compliance-gate verifies."
            )
        return ConsentClient(base_url, token_provider=lambda: self._id_token(audience))

    @staticmethod
    def _id_token(audience: str) -> str:
        """Mint a fresh Google-signed ID token lazily through Workload Identity."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.id_token import fetch_id_token
        except ImportError as exc:  # pragma: no cover - local gate deliberately has no SDK
            raise ConsentUnavailableError(
                "Google auth SDK is unavailable for the managed consent hop"
            ) from exc
        return str(fetch_id_token(Request(), audience))

    def decide(self, query: ConsentQuery) -> ConsentDecision:
        try:
            return self._client().decide(query, actor=_SERVICE_ACTOR)
        except (ConsentClientError, ValueError) as exc:  # pragma: no cover - live/config path
            raise ConsentUnavailableError(f"the consent store could not answer: {exc}") from exc
