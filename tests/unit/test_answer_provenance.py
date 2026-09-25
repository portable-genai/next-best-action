"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the model adapters NOTED as
they called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``,
so that value must be the model the bound adapter calls, never one a configuration flag names
while the adapter calls another.

No adapter here attaches an online search tool: the managed knowledge base is File Search over
this repository's own private corpus, which is not one. So the Search half is proved by standing
a noting model in for the real one on the real route.
"""

from __future__ import annotations

import dataclasses
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance
from tests.conftest import LOOPBACK_PEER, _settings

from next_best_action.adapters.gcp.gemini_llm import GeminiLLMAdapter
from next_best_action.adapters.local.llm import LocalDeterministicLLMAdapter
from next_best_action.api import deps
from next_best_action.api.app import app
from next_best_action.config import STUB_GENERATOR_MODEL, Container, ModelSettings, Settings
from next_best_action.domain.models import LlmMessage, LlmRequest, LlmResponse

_REPO_ROOT = Path(__file__).resolve().parents[2]

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"


def _recommend(monkeypatch: pytest.MonkeyPatch, container: Container) -> Any:
    monkeypatch.setattr(deps, "get_container", lambda: container)
    response = TestClient(app, client=LOOPBACK_PEER).post(
        "/v1/recommend",
        json={"customer_id": "cust-sg-bank-1", "market": "SG", "vertical": "banking"},
        headers={"X-Dev-Persona": "analyst"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["recommendations"], "nothing was explained, so no model was asked"
    return response


def test_the_recommend_route_names_the_stub_that_answered_under_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pill's answered value and its configured value are the same word offline."""
    container = Container(_settings("local"))
    response = _recommend(monkeypatch, container)
    assert response.headers[ANSWERED_BY] == container.settings.generator_model
    assert container.settings.generator_model == STUB_GENERATOR_MODEL
    assert SEARCH_USED not in response.headers
    # The console calls this service cross-origin, so the two headers must be readable there.
    exposed = response.headers["access-control-expose-headers"].lower()
    assert ANSWERED_BY in exposed and SEARCH_USED in exposed


def test_a_request_no_model_answered_names_no_model() -> None:
    response = TestClient(app, client=LOOPBACK_PEER).get("/healthz")
    assert response.status_code == 200
    assert ANSWERED_BY not in response.headers
    assert SEARCH_USED not in response.headers


class _SearchingLLM(LocalDeterministicLLMAdapter):
    """The real offline explainer, plus what an adapter that searched would note."""

    def generate(self, request: LlmRequest) -> LlmResponse:
        response = super().generate(request)
        provenance.note_model("fake-searching-model")
        provenance.note_search()
        return response


def test_a_call_that_searched_is_reported_and_does_not_leak_into_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = Container(_settings("local"))
    container.__dict__["llm"] = _SearchingLLM(container.settings)
    response = _recommend(monkeypatch, container)
    assert response.headers[ANSWERED_BY] == f"{STUB_GENERATOR_MODEL}, fake-searching-model"
    assert response.headers[SEARCH_USED] == "true"

    fresh = _recommend(monkeypatch, Container(_settings("local")))
    assert SEARCH_USED not in fresh.headers
    assert fresh.headers[ANSWERED_BY] == STUB_GENERATOR_MODEL


# --------------------------------------------------------------------------- #
# The managed adapter, against a stand-in for the lazily imported SDK.
# --------------------------------------------------------------------------- #
class _Config:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return types.SimpleNamespace(text="spike", usage_metadata=None)


def _fake_genai(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk_types = types.SimpleNamespace(
        GenerateContentConfig=_Config,
        ThinkingConfig=lambda **kwargs: kwargs,
        ThinkingLevel=types.SimpleNamespace(LOW="LOW", HIGH="HIGH"),
        Content=lambda **kwargs: kwargs,
        Part=types.SimpleNamespace(from_text=lambda text: text),
    )
    genai = types.ModuleType("google.genai")
    genai.types = sdk_types  # type: ignore[attr-defined]
    google = types.ModuleType("google")
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)


def _gemini(monkeypatch: pytest.MonkeyPatch) -> tuple[GeminiLLMAdapter, _FakeModels, Settings]:
    _fake_genai(monkeypatch)
    settings = dataclasses.replace(Settings.load("config/settings.yaml"), profile="gcp")
    adapter = GeminiLLMAdapter(settings)
    fake = _FakeModels()
    adapter._client = types.SimpleNamespace(models=fake)
    adapter._get_client = lambda: adapter._client  # type: ignore[method-assign,assignment,return-value]
    return adapter, fake, settings


def test_the_gemini_adapter_notes_the_model_it_called_which_is_generator_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, fake, settings = _gemini(monkeypatch)
    with provenance.scope() as record:
        adapter.generate(LlmRequest(messages=(LlmMessage(role="user", content="why"),)))
    assert fake.calls[0]["model"] == settings.generator_model
    assert record.models == [settings.generator_model]
    assert record.search_used is False


def test_the_gemini_triage_call_notes_the_model_it_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, fake, settings = _gemini(monkeypatch)
    with provenance.scope() as record:
        assert adapter.classify("text", ["drop", "spike"]) == "spike"
    assert fake.calls[0]["model"] == settings.models.triage
    assert record.models == [settings.models.triage]
    assert record.search_used is False


def test_generator_model_is_the_setting_the_adapter_reads_and_no_flag_exists() -> None:
    """The latent false banner: a flag that moved the pill but not the model that answered.

    ``generator_model`` once named ``models.hard_reasoning`` when ``models.use_hard_reasoning``
    was set, while the Gemini adapter called ``request.model or models.reasoning`` and never
    read the flag. The flag is gone, from the settings type, the settings file and the source.
    """
    settings = dataclasses.replace(Settings.load("config/settings.yaml"), profile="gcp")
    assert settings.generator_model == settings.models.reasoning
    fields = {f.name for f in dataclasses.fields(ModelSettings)}
    assert "use_hard_reasoning" not in fields and "hard_reasoning" not in fields
    assert "use_hard_reasoning" not in (_REPO_ROOT / "config" / "settings.yaml").read_text()
    for source in sorted((_REPO_ROOT / "src").rglob("*.py")):
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
