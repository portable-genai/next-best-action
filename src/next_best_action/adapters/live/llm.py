"""Live LLM adapter (LlmPort): the shared local open-weight model, through the kit client.

The ``live`` profile's model port. It builds the same conversation the Gemini adapter sends
(system instruction, then the request messages) and hands it to
:class:`hex_service_kit.localmodel.LocalModelClient`, which owns the endpoint, the model id,
the structured-output contract (schema in the prompt, validated and retried) and the start
recipe a failure message carries. ``LOCAL_MODEL_URL`` and ``LOCAL_MODEL`` choose the server and
model, read in three states by the kit.

The model explains the already-computed deterministic recommendation; it never decides one.
A server that does not answer maps to :class:`ModelUnavailableError` and an answer that never
satisfied the schema to :class:`ModelOutputError`, so the API answers 503 and 502 rather than
an unexplained 500.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit.localmodel import (
    LocalCompletion,
    LocalModelClient,
    LocalModelOutputError,
    LocalModelSettings,
    LocalModelUnavailable,
)

from ...config import Settings
from ...domain.errors import ModelOutputError, ModelUnavailableError
from ...domain.models import LlmRequest, LlmResponse, TokenUsage

_ROLES = {"model": "assistant", "system": "system"}


class LocalModelLLMAdapter:
    """Generate completions and triage labels from the shared local model."""

    def __init__(self, settings: Settings, *, client: LocalModelClient | None = None) -> None:
        self._settings = settings
        self._client = client or LocalModelClient(LocalModelSettings.from_env())

    # ------------------------------------------------------------------ #
    # LlmPort
    # ------------------------------------------------------------------ #
    def generate(self, request: LlmRequest) -> LlmResponse:
        """Generate a completion; a request with a schema gets validated JSON back."""
        messages = self._messages(request)
        try:
            if request.response_schema is not None:
                completion = self._client.complete_json(
                    messages,
                    schema=request.response_schema,
                    temperature=request.temperature,
                    max_tokens=request.max_output_tokens,
                )
            else:
                completion = self._client.complete(
                    messages,
                    temperature=request.temperature,
                    max_tokens=request.max_output_tokens,
                )
        except LocalModelUnavailable as exc:
            raise ModelUnavailableError(str(exc)) from exc
        except LocalModelOutputError as exc:
            raise ModelOutputError(str(exc)) from exc
        return LlmResponse(
            text=completion.text,
            usage=_usage(completion),
            model=completion.model,
            raw=completion.data if isinstance(completion.data, dict) else None,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        """Single-label classification, at temperature 0 as the managed triage call runs."""
        label_list = ", ".join(labels)
        prompt = (
            f"Classify the text into exactly one of these labels: {label_list}.\n"
            "Reply with the single label only, no punctuation or explanation.\n\n"
            f"Text:\n{text}"
        )
        try:
            completion = self._client.complete(
                [{"role": "user", "content": prompt}], temperature=0.0, max_tokens=16
            )
        except LocalModelUnavailable as exc:
            raise ModelUnavailableError(str(exc)) from exc
        return _match_label(completion.text.strip(), labels)

    # ------------------------------------------------------------------ #
    # Mapping
    # ------------------------------------------------------------------ #
    @staticmethod
    def _messages(request: LlmRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": request.system_instruction})
        for message in request.messages:
            messages.append({"role": _ROLES.get(message.role, "user"), "content": message.content})
        return messages


def _usage(completion: LocalCompletion) -> TokenUsage:
    """The kit's usage, or an empty :class:`TokenUsage` when the server reported none.

    ``LlmResponse.usage`` is not optional in this repository's domain model, so a server that
    reports no usage (MLX) is carried as zeros here; nothing in the service reads the figure.
    """
    return completion.usage if completion.usage is not None else TokenUsage()


def _match_label(raw: str, labels: list[str]) -> str:
    """Coerce the model's reply to one of ``labels`` (case-insensitive)."""
    if not labels:
        return raw
    lowered = raw.lower()
    for label in labels:
        if label.lower() == lowered:
            return label
    for label in labels:
        if label.lower() in lowered:
            return label
    return labels[0]
