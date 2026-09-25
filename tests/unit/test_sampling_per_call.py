"""Sampling is decided per call: pinned where output is compared, free everywhere else.

**History.** This file was ``test_grounded_requests_do_not_sample.py`` and asserted that the
request type defaulted to ``temperature=0.0``. That came from a real finding in
`cdd-sow-research`: on 2026-08-26 two runs of one identical case against the deployment returned
`score` 0.5 then 0.0, because a shared request builder defaulted to ``0.2`` and every grounded
call, scoring included, sampled. Pinning the default fixed the scores and also pinned every
narration call that nobody compares.

**What changed (owner decision, 2026-09-23).** Temperature is pinned (``0.0``) only where
reproducibility matters: extraction, classification, scoring or labelling, anything whose output
is compared or feeds a deterministic check. Drafting, summarising, narrating, explaining and
judging are FREE, and free means the parameter is ABSENT, never ``1.0``: some models (Opus 5,
Fable 5) reject it outright. So the type's default is now ``None``, every pinned call site pins
explicitly, and the lesson of the original finding survives as the per-call assertions below.

In this repository no model computes a number: eligibility, consent and ranking are
deterministic engines. So the pinned calls are the classification helpers and the File Search
retrieval (its passages become the citations), and the freed ones are the "why recommended"
explanation and the ADK agent's conversation.

**Temperature 0 is not a promise of determinism, and nothing here asserts one.** A hosted model
can still vary across batching and model revisions.
"""

from __future__ import annotations

import ast
import sys
import types as pytypes
from pathlib import Path
from typing import Any

import pytest

from next_best_action.adapters.gcp.file_search_kb import FileSearchKnowledgeBaseAdapter
from next_best_action.adapters.gcp.gemini_llm import GeminiLLMAdapter
from next_best_action.api.deps import make_recommendation_service
from next_best_action.config import Container
from next_best_action.domain.identity import Principal
from next_best_action.domain.models import (
    LlmMessage,
    LlmRequest,
    LlmResponse,
    Market,
    RecommendationRequest,
    RetrievalQuery,
    Vertical,
)


def test_the_request_type_samples_freely_unless_a_call_site_pins_it() -> None:
    assert LlmRequest.__dataclass_fields__["temperature"].default is None


class _RecordingLlm:
    """An LlmPort that answers like the local stub and records every request it was handed."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.requests: list[LlmRequest] = []

    def generate(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        return self._inner.generate(request)

    def classify(self, text: str, labels: list[str]) -> str:
        return self._inner.classify(text, labels)


def test_the_explanation_is_narration_and_is_not_pinned(local_container: Container) -> None:
    """The "why recommended" call explains a ranking already fixed, so it samples freely."""
    recording = _RecordingLlm(local_container.llm)
    local_container.__dict__["llm"] = recording
    result = make_recommendation_service(local_container).recommend(
        RecommendationRequest(
            customer_id="cust-sg-bank-1", market=Market.SG, vertical=Vertical.BANKING
        ),
        Principal(subject="test", tenant="demo-bank", source="test"),
    )
    assert result.recommendations, "nothing was explained, so nothing was checked"
    assert recording.requests, "the service never called the model"
    assert all(r.temperature is None for r in recording.requests), [
        r.temperature for r in recording.requests
    ]


# --------------------------------------------------------------------------- #
# The managed adapters, driven against a faked SDK: no google-genai installed.
# --------------------------------------------------------------------------- #
class _Recorder:
    """Stands in for every ``google.genai.types`` constructor and records its kwargs."""

    def __init__(self, name: str, log: list[tuple[str, dict[str, Any]]]) -> None:
        self._name = name
        self._log = log

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._log.append((self._name, kwargs))
        return kwargs

    def __getattr__(self, attr: str) -> Any:
        return _Recorder(f"{self._name}.{attr}", self._log)


@pytest.fixture
def genai_types(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    log: list[tuple[str, dict[str, Any]]] = []
    fake_types = pytypes.ModuleType("google.genai.types")
    for name in ("Content", "Part", "GenerateContentConfig", "ThinkingConfig", "Tool"):
        setattr(fake_types, name, _Recorder(name, log))
    fake_types.FileSearch = _Recorder("FileSearch", log)  # type: ignore[attr-defined]
    fake_types.ThinkingLevel = pytypes.SimpleNamespace(LOW="LOW", HIGH="HIGH")  # type: ignore[attr-defined]
    fake_genai = pytypes.ModuleType("google.genai")
    fake_genai.types = fake_types  # type: ignore[attr-defined]
    google = sys.modules.get("google") or pytypes.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setattr(google, "genai", fake_genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    return log


class _FakeClient:
    def __init__(self, text: str = '{"explanation": "x"}') -> None:
        self.calls: list[dict[str, Any]] = []
        self._text = text
        self.models = self

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return pytypes.SimpleNamespace(text=self._text, usage_metadata=None, candidates=[])


def _config_kwargs(log: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    configs = [kwargs for name, kwargs in log if name == "GenerateContentConfig"]
    assert len(configs) == 1, configs
    return configs[0]


def _gemini(local_settings: Any, client: _FakeClient) -> GeminiLLMAdapter:
    adapter = GeminiLLMAdapter(local_settings)
    adapter._client = client
    adapter._get_client = lambda: client  # type: ignore[method-assign]
    return adapter


def _request(temperature: float | None = None) -> LlmRequest:
    return LlmRequest(messages=(LlmMessage(role="user", content="why"),), temperature=temperature)


def test_the_managed_adapter_omits_temperature_when_the_call_is_free(
    local_settings: Any, genai_types: list[tuple[str, dict[str, Any]]]
) -> None:
    _gemini(local_settings, _FakeClient()).generate(_request())
    assert "temperature" not in _config_kwargs(genai_types), (
        "free must mean ABSENT: a model that rejects the parameter refuses a sent 1.0 or None"
    )


def test_the_managed_adapter_keeps_a_pinned_temperature(
    local_settings: Any, genai_types: list[tuple[str, dict[str, Any]]]
) -> None:
    _gemini(local_settings, _FakeClient()).generate(_request(temperature=0.0))
    assert _config_kwargs(genai_types)["temperature"] == 0.0


def test_classification_is_pinned(
    local_settings: Any, genai_types: list[tuple[str, dict[str, Any]]]
) -> None:
    """A label is matched against a fixed set, so it is compared, not read."""
    label = _gemini(local_settings, _FakeClient(text="spike")).classify("t", ["drop", "spike"])
    assert label == "spike"
    assert _config_kwargs(genai_types)["temperature"] == 0.0


def test_file_search_retrieval_is_pinned(
    local_settings: Any, genai_types: list[tuple[str, dict[str, Any]]]
) -> None:
    """Retrieval feeds the citations the explanation is checked against."""
    client = _FakeClient()
    adapter = FileSearchKnowledgeBaseAdapter(local_settings)
    adapter._get_client = lambda: client  # type: ignore[method-assign]
    adapter.search(RetrievalQuery(text="offer terms"))
    assert _config_kwargs(genai_types)["temperature"] == 0.0


def test_the_conversational_agent_is_not_pinned() -> None:
    """The ADK agent converses and relays numbers the tools computed, so it samples freely.

    Read from source because building the agent needs the ADK, which the offline gate never
    installs. Every ``GenerateContentConfig`` built in the agent module is checked, so a
    temperature added to any of them turns this red.
    """
    source = Path("src/next_best_action/agent/root_agent.py").read_text(encoding="utf-8")
    configs = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "GenerateContentConfig"
    ]
    assert configs, "the agent builds no generation config, so this checked nothing"
    for call in configs:
        assert "temperature" not in {kw.arg for kw in call.keywords}
