"""Domain exceptions for the Next-Best-Action system (D5).

Pure-Python exception hierarchy raised by the orchestration services. The domain layer
never imports Google Cloud, Vertex AI, or any framework: these errors let callers (API,
CLI, the agent runtime adapter) react to domain-level failures without coupling to any
vendor SDK error type.
"""

from __future__ import annotations


class NextBestActionError(Exception):
    """Base class for all domain-level errors raised by D5 services."""


class GuardrailBlockedError(NextBestActionError):
    """Raised when the A1 guardrail blocks an input or output.

    A blocked unsafe request must never yield a partial recommendation: the orchestrator
    raises this rather than assembling a result from screened-out content.
    """


class NoCandidatesError(NextBestActionError):
    """Raised when no candidate offers exist for the customer's market/vertical.

    A recommendation must be grounded in a real candidate set; an empty catalog after
    filtering is a hard error so a result is never built on no offers.
    """


class AuthorizationError(NextBestActionError):
    """Raised when a verified principal is not authorized for the requested object.

    Object-level authorization is **fail-closed**: if the customer carries a tenant that
    does not match the caller's verified tenant, the request is denied rather than served.
    This closes the cross-tenant object-reference leak (a demo-bank operator must never be
    able to pull an other-bank customer). The API maps this to HTTP 403.
    """


class UnknownCustomerError(NextBestActionError):
    """Raised when the requested customer id has no record in the profile store."""


class UnsupportedMarketError(NextBestActionError):
    """Raised when a requested market has no configured residency region / profile."""


class UnsupportedVerticalError(NextBestActionError):
    """Raised when a requested vertical has no configured seed / taxonomy."""
