"""The ``live`` laptop profile: ``local`` with the shared local model answering the llm port.

Offline: every model call here goes to a fake transport handed to the kit client, so the
suite needs no model server. What is proved is the adapter's mapping (messages, schema,
temperature, model id, failures) and that the profile builds and keeps the laptop posture.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest
from hex_service_kit.localmodel import (
    DEFAULT_LOCAL_MODEL,
    LocalModelClient,
    LocalModelSettings,
)
from tests.conftest import _settings

from next_best_action.adapters.live.llm import LocalModelLLMAdapter
from next_best_action.adapters.local.identity import LocalPersonaIdentityAdapter
from next_best_action.api.deps import make_recommendation_service
from next_best_action.config import Container, Settings
from next_best_action.domain.errors import ModelOutputError, ModelUnavailableError
from next_best_action.domain.identity import Principal
from next_best_action.domain.models import (
    LlmMessage,
    LlmRequest,
    Market,
    RecommendationRequest,
    Vertical,
)

_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


def _answer(content: str, model: str = "served-model-id") -> bytes:
    return json.dumps(
        {"model": model, "choices": [{"message": {"role": "assistant", "content": content}}]}
    ).encode()


class _FakeTransport:
    """Answers each chat call with the next scripted reply and records every request body."""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, url: str, body: bytes | None, timeout: float) -> bytes:
        assert body is not None
        self.bodies.append(json.loads(body))
        return _answer(self._replies.pop(0))


def _adapter(transport: Callable[[str, bytes | None, float], bytes]) -> LocalModelLLMAdapter:
    client = LocalModelClient(LocalModelSettings(), transport=transport)
    return LocalModelLLMAdapter(_settings("live"), client=client)


def test_a_fenced_invalid_first_answer_is_retried_and_the_valid_one_returned() -> None:
    transport = _FakeTransport('```json\n{"headline": "no summary"}\n```', '{"summary": "ok"}')
    request = LlmRequest(
        messages=(LlmMessage(role="user", content="narrate"),),
        system_instruction="be terse",
        temperature=0.3,
        max_output_tokens=321,
        response_schema=_SCHEMA,
    )

    response = _adapter(transport).generate(request)

    assert json.loads(response.text) == {"summary": "ok"}
    assert response.raw == {"summary": "ok"}
    assert response.model == "served-model-id", "the model id is the one that answered"
    assert len(transport.bodies) == 2, "the invalid first answer must be retried once"
    first = transport.bodies[0]
    assert first["temperature"] == 0.3, "the request's temperature passes through unchanged"
    assert first["max_tokens"] == 321
    assert first["messages"][0]["role"] == "system"
    assert "be terse" in first["messages"][0]["content"]
    assert '"summary"' in first["messages"][0]["content"], "the schema is stated in the prompt"
    assert first["messages"][1] == {"role": "user", "content": "narrate"}
    retry = transport.bodies[1]["messages"]
    assert "summary" in retry[-1]["content"], "the missing field is fed back to the model"


def test_a_request_without_a_schema_is_a_plain_completion() -> None:
    transport = _FakeTransport("plain prose")
    request = LlmRequest(messages=(LlmMessage(role="user", content="hello"),))

    response = _adapter(transport).generate(request)

    assert response.text == "plain prose"
    assert response.raw is None
    assert transport.bodies[0]["messages"] == [{"role": "user", "content": "hello"}]


def test_a_server_that_does_not_answer_is_model_unavailable() -> None:
    def refused(url: str, body: bytes | None, timeout: float) -> bytes:
        raise OSError("connection refused")

    request = LlmRequest(messages=(LlmMessage(role="user", content="x"),))
    with pytest.raises(ModelUnavailableError, match="mlx_vlm.server"):
        _adapter(refused).generate(request)


def test_an_answer_that_never_validates_is_a_model_output_error() -> None:
    transport = _FakeTransport("not json", "still not", "never")
    request = LlmRequest(messages=(LlmMessage(role="user", content="x"),), response_schema=_SCHEMA)
    with pytest.raises(ModelOutputError):
        _adapter(transport).generate(request)
    assert len(transport.bodies) == 3


def test_classify_matches_the_reply_to_a_label() -> None:
    transport = _FakeTransport(" Spike. ")
    assert _adapter(transport).classify("text", ["drop", "spike"]) == "spike"
    assert transport.bodies[0]["temperature"] == 0.0


def test_the_container_builds_every_port_under_live() -> None:
    settings = _settings("live")
    container = Container(settings)
    for port in settings.adapters:
        assert getattr(container, port) is not None, port
    assert isinstance(container.llm, LocalModelLLMAdapter)
    assert isinstance(container.identity, LocalPersonaIdentityAdapter)


def test_live_keeps_the_laptop_posture_and_names_the_local_model() -> None:
    settings = _settings("live")
    assert settings.laptop is True
    assert settings.bind_profile == "local", "live serves seeded personas, so it binds loopback"
    assert settings.runtime == "local"
    assert settings.generator_model == DEFAULT_LOCAL_MODEL
    unchosen = dataclasses.replace(settings, profile_explicit=False)
    assert unchosen.laptop is False


def test_a_live_recommendation_is_explained_by_the_local_model() -> None:
    settings = _settings("live")
    container = Container(settings)
    explanation = (
        '{"explanation": "Eligible, consented and top on propensity.", "used_source_ids": []}'
    )
    transport = _FakeTransport(*([explanation] * 10))
    container.__dict__["llm"] = _adapter(transport)

    result = make_recommendation_service(container).recommend(
        RecommendationRequest(
            customer_id="cust-sg-bank-1", market=Market.SG, vertical=Vertical.BANKING
        ),
        Principal(subject="test", tenant="demo-bank", source="test"),
    )

    assert result.recommendations
    assert transport.bodies, "the local model was never called"
    assert all(
        r.explanation == "Eligible, consented and top on propensity."
        for r in result.recommendations
    )
    assert result.requires_human_review is True


def test_the_settings_loader_accepts_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MKT_NBA_PROFILE", "live")
    settings = Settings.load("config/settings.yaml")
    assert settings.profile == "live"
    assert settings.profile_explicit is True
