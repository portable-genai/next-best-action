"""API request/response schemas (thin Pydantic models at the HTTP boundary)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..domain.models import AgentCard


class RecommendRequestModel(BaseModel):
    customer_id: str = Field(..., description="The customer / shopper id.")
    market: str = Field("SG", description="Market: JP | AU | SG.")
    vertical: str = Field("banking", description="Vertical: banking | online_retail.")
    max_recommendations: int = 5
    channel: str | None = Field(
        None, description="Restrict to one consent channel (email|sms|push|in_app|phone)."
    )


class HealthModel(BaseModel):
    status: str = "ok"
    profile: str
    market: str
    vertical: str
    #: Provenance the UI banner states on every page: where the runtime sits and which model
    #: answers. Both are read off the service because the browser cannot know either.
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"


class AgentSkillModel(BaseModel):
    id: str
    name: str
    description: str


class AgentCardModel(BaseModel):
    """A2A AgentCard served at ``/.well-known/agent-card.json`` (agent-registry discovery shape)."""

    name: str
    description: str
    url: str
    version: str
    skills: list[AgentSkillModel] = Field(default_factory=list)
    provider: str

    @classmethod
    def from_domain(cls, card: AgentCard) -> AgentCardModel:
        return cls(
            name=card.name,
            description=card.description,
            url=card.url,
            version=card.version,
            skills=[
                AgentSkillModel(id=s.id, name=s.name, description=s.description)
                for s in card.skills
            ],
            provider=card.provider,
        )
