"""A2A AgentCard for the D5 Next-Best-Action agent (A3 Registry & Governance).

This builds the agent's discovery card (the same minimal A2A shape the ``agent-registry``
service stores and serves, SPEC §6). It is published at ``/.well-known/agent-card.json``;
:func:`agent_card_document` returns the JSON-safe body the API layer serves there, and the
``platform`` registry adapter registers the same card in Hrz3 (rule R4).

The card advertises the skill D5 produces (recommend_next_best_action), mirroring the ADK
FunctionTool so a peer agent or the registry sees one consistent capability surface.

This module is pure (domain models only) and imports without ADK or any Google Cloud SDK
installed (SPEC §4).
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..domain.models import AgentCard, AgentSkill

SKILLS: tuple[AgentSkill, ...] = (
    AgentSkill(
        id="recommend_next_best_action",
        name="Next-best-action recommendations",
        description=(
            "Recommend per-customer next-best offers and cross-sell / up-sell for a market "
            "(JP / AU / SG) and vertical (banking / online retail): propensity plus "
            "deterministic eligibility / suitability ranking with consent checks, each offer "
            "cited and explained. Identity is server-verified and a customer outside the "
            "caller's tenant is denied. Always flagged for human review (P-06)."
        ),
    ),
)

_DESCRIPTION = (
    "Per-customer next-best-action agent for a bank or online retailer. Ranks next-best offers "
    "and cross-sell / up-sell with propensity plus deterministic eligibility / suitability "
    "rules and consent checks, and explains each recommendation, generic across banking and "
    "online retail and the JP / AU / SG markets. Built ports-and-adapters on the Gemini "
    "Enterprise Agent Platform. Customer PII is redacted at the model boundary; identity is "
    "server-verified with a fail-closed cross-tenant ACL; every recommendation carries a "
    "citation and the model only explains the deterministic ranking."
)


def build_agent_card(settings: Settings) -> AgentCard:
    """Construct the A2A :class:`AgentCard` for this agent."""
    return AgentCard(
        name="next-best-action",
        description=_DESCRIPTION,
        url=_resolve_url(settings),
        version="0.1.0",
        skills=SKILLS,
        provider="next-best-action",
    )


def agent_card_document(settings: Settings) -> dict[str, Any]:
    """Return the JSON-safe body to serve at ``/.well-known/agent-card.json``."""
    from ..domain.serialization import to_jsonable

    return to_jsonable(build_agent_card(settings))


def _resolve_url(settings: Settings) -> str:
    """Best-effort public URL for the card, region-pinned to the active market."""
    resource = settings.agent_engine.resource_name
    if resource:
        return f"https://aiplatform.googleapis.com/v1/{resource}"
    return "https://next-best-action.mkt.internal/a2a"
