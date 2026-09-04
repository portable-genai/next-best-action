"""Remote-platform evaluation adapter : thin HTTP client to model-quality-gate.

At promotion this vertical's quality is checked against the shared **model-quality-gate AI Quality /
model-risk** service (``model-quality-gate``). This adapter implements
:class:`EvaluationGatePort` against model-quality-gate's hardened contract:

* ``evaluate`` -> ``POST /v1/evaluations {target, dataset_id, bundle}`` -> EvalReport.
* ``gate``     -> ``POST /v1/gate {target, dataset_id, bundle}`` -> ``{passed}``.

**Sourced from the shared ``agent-eval-kit`` commons.** The HTTP contract
is ``agent_eval_kit.gate_client.PromotionGateClient``; this adapter configures it (the
registered ``mkt5-nba`` bundle, the reasoning model, and this repo's S2S auth
headers), returns its :class:`EvalReport` UNCHANGED, and re-raises its errors as
:class:`RemoteEvaluationError`.

Unchanged is the load-bearing word. A ``_to_domain`` mapper rebuilding a locally declared
``EvalReport`` from three of the client's fields is a lossy identity function, because the
domain re-exports the commons type: it drops exactly the attested evidence (run id, dataset
version and digest, evaluator, schema version, trace and correlation ids, artifact refs, the
``attested`` flag) that the client has just validated on the way in, and a promotion is only as
good as the evidence that reaches the caller. So there is no mapper.
"""

from __future__ import annotations

from agent_eval_kit.gate_client import GateClientError, PromotionGateClient

from ...config import Settings
from ...domain.errors import NextBestActionError
from ...domain.models import EvalReport
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8084"

#: The registered model-quality-gate metric bundle for this vertical (model-quality-gate owns the
#: metrics + bars).
_BUNDLE = "mkt5-nba"
#: Prompt/agent version tag; bump when the prompt corpus changes, or source it from a registry.
_PROMPT_VERSION = "v1"


class RemoteEvaluationError(NextBestActionError):
    """Raised when the model-quality-gate quality service returns a non-2xx response."""


class RemoteEvaluationAdapter:
    """HTTP client for the model-quality-gate ``model-quality-gate`` service (via
    PromotionGateClient).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = PromotionGateClient(
            setting_or_default("QUALITY_GATE_URL", _DEFAULT_URL),
            bundle=_BUNDLE,
            model=settings.models.reasoning,
            prompt_version=_PROMPT_VERSION,
            auth_headers=lambda: _s2s.headers(),
        )

    def evaluate(self, dataset_path: str) -> EvalReport:
        """Score ``dataset_path`` via model-quality-gate and return the report model-quality-gate
        attested, unaltered.
        """
        try:
            return self._client.evaluate(dataset_path)
        except GateClientError as exc:
            raise RemoteEvaluationError(str(exc)) from exc

    def gate(self, target: str) -> bool:
        """Promotion gate: True iff model-quality-gate reports ``target`` passes."""
        try:
            return self._client.gate(target)
        except GateClientError as exc:
            raise RemoteEvaluationError(str(exc)) from exc
