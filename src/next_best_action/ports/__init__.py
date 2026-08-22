"""Ports — the abstract interfaces (the hexagon boundary).

Every port is a ``typing.Protocol`` (``@runtime_checkable``) so adapters need only
structural conformance and the contract test can verify any adapter family (GCP,
remote-platform, on-prem placeholder, or local) satisfies the same contract.
"""

from .consent import ConsentPort, ConsentUnavailableError
from .generation import LlmPort
from .governance import AgentRegistryPort, ToolCatalogPort
from .identity import IdentityPort
from .knowledge_base import KnowledgeBasePort
from .observability import (
    AuditSinkPort,
    EvaluationGatePort,
    ObservabilityTracerPort,
    TokenUsage,
)
from .recommendation import RecommendationPort
from .review_router import ReviewRouterPort
from .safety import GuardrailPort, PIIRedactionPort

__all__ = [
    "ConsentPort",
    "ConsentUnavailableError",
    "RecommendationPort",
    "LlmPort",
    "KnowledgeBasePort",
    "GuardrailPort",
    "PIIRedactionPort",
    "AuditSinkPort",
    "ObservabilityTracerPort",
    "TokenUsage",
    "EvaluationGatePort",
    "AgentRegistryPort",
    "ToolCatalogPort",
    "IdentityPort",
    "ReviewRouterPort",
]
