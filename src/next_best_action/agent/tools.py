"""ADK FunctionTools that expose the D5 domain services to the agent.

The tool is a thin, side-effect-honest wrapper: it builds the :class:`RecommendationService`
from a :class:`~next_best_action.config.Container` (so every port is bound to the adapter
selected by the active profile), resolves a **server-verified** :class:`Principal` via the
IdentityPort (never a model-supplied identity), invokes the domain method, and returns a
JSON-safe dict via :func:`~next_best_action.domain.serialization.to_jsonable`.

Security note (fail-closed, cross-tenant ACL)
---------------------------------------------
Unlike the other marketing agents, D5 recommends over **per-customer** data, so its object
authorization is load-bearing (a demo-bank operator must never pull an other-bank customer).
Identity is therefore resolved through ``container.identity.resolve`` exactly as the API does,
not taken from tool arguments the model controls: the ``persona`` argument only selects a
seeded dev identity under the no-auth **local** profile and is ignored by the verified (IAP)
adapters. The domain then DENIES any customer whose tenant differs from the resolved
principal's (``AuthorizationError``), which surfaces as an exception the agent must not swallow.

Design notes
------------
* The domain service owns orchestration and every consequential decision (candidate filter,
  eligibility / suitability, consent, deterministic ranking; SPEC §5). The model only explains
  each recommendation; it never produces the ranking.
* ``google.adk`` is imported lazily inside :func:`build_function_tools` so this module imports
  cleanly under the on-prem / local / test profile with no ADK installed (SPEC §4). The plain
  Python tool callable is importable and unit-testable without ADK at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Container, Settings, build_container

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool


def _container(settings: Settings | None) -> Container:
    return build_container(settings)


def recommend_next_best_action(
    customer_id: str,
    market: str = "SG",
    vertical: str = "banking",
    max_recommendations: int = 5,
    channel: str = "",
    persona: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Recommend the next-best offers for a customer, with eligibility and consent checks.

    Returns a ``RecommendationSet``: deterministically-ranked, eligibility- and
    consent-checked offers, each with a citation and an explanation, plus the consent-suppressed
    candidates. Always flagged for human review (maker-checker). Identity is resolved
    server-side (there is deliberately no ``actor`` argument); a customer outside the caller's
    tenant is denied (``AuthorizationError``).

    Args:
      customer_id: The customer / shopper id.
      market: Market code: "JP", "AU" or "SG".
      vertical: "banking" or "online_retail".
      max_recommendations: Maximum offers to return.
      channel: Optional consent channel to restrict to ("email", "sms", "push", "in_app",
        "phone"); empty means all channels.
      persona: Seeded dev-identity selector, honoured ONLY under the no-auth local profile
        (ignored by the verified IAP adapters). Never a security control.

    Returns:
      A JSON-safe ``RecommendationSet`` dict.
    """
    from ..api.deps import make_recommendation_service
    from ..domain.identity import RequestContext
    from ..domain.models import ConsentChannel, Market, RecommendationRequest, Vertical
    from ..domain.serialization import to_jsonable

    c = _container(settings)
    ctx = RequestContext(headers={"x-dev-persona": persona} if persona else {})
    principal = c.identity.resolve(ctx)
    request = RecommendationRequest(
        customer_id=customer_id,
        market=Market(market),
        vertical=Vertical(vertical),
        max_recommendations=max_recommendations,
        channel=ConsentChannel(channel) if channel else None,
    )
    return to_jsonable(make_recommendation_service(c).recommend(request, principal))


TOOL_FUNCTIONS = (recommend_next_best_action,)


def governed_tool_names() -> frozenset[str]:
    """The tool names this agent exposes (mirrors the governed MCP catalog, rule R4)."""
    return frozenset(fn.__name__ for fn in TOOL_FUNCTIONS)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each domain-service callable as an ADK ``FunctionTool``.

    ADK introspects each function's signature and docstring to derive the tool name,
    description and parameter JSON schema. ``google.adk`` is imported here (lazily) so the
    module is import-safe without ADK installed (SPEC §4).
    """
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=fn) for fn in TOOL_FUNCTIONS]
