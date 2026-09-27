"""The Model Armor adapter allows ONLY a complete, clean screen, and fails closed otherwise.

The allow rule is ``filterMatchState == "NO_MATCH_FOUND"`` AND ``invocationResult ==
"SUCCESS"``. Everything else blocks: ``MATCH_FOUND``, ``FILTER_MATCH_STATE_UNSPECIFIED``, a
missing or empty ``sanitizationResult``, and ``NO_MATCH_FOUND`` with ``PARTIAL`` or
``FAILURE`` (a skipped filter reports no match, so padding a prompt past the prompt-injection
filter's token limit would otherwise get it through unscreened). HTTP errors and timeouts
propagate, and every call carries the configured deadline.

The previous mapping allowed whenever ``filterMatchState`` was anything but ``MATCH_FOUND``,
and fell back to "no findings" when it was absent, so it passed UNSPECIFIED, a missing result
and an incomplete screen. Each of those cases below fails against it.

This adapter speaks REST, so the wire form is JSON with each enum carried as its member name.
The module tests at two levels:

* **SDK-free** (always runs, including the SDK-free ``make check``): responses are JSON dicts
  written from ``_MirrorState`` / ``_MirrorInvocation``, stdlib enums with the real member
  names and numbers.
* **Real SDK** (runs where ``google-cloud-modelarmor`` is installed, skips otherwise): responses
  are real ``modelarmor_v1`` messages serialised by the SDK's own ``to_json`` (the REST wire
  form) and screened through ``screen()`` with a fake HTTP client, so nothing touches the
  network. The first of these tests pins the mirror to the real enums, so the SDK-free half
  cannot drift.
"""

from __future__ import annotations

import enum
import json
from typing import Any

import httpx
import pytest

from next_best_action.adapters.gcp.model_armor_guardrail import ModelArmorGuardrailAdapter
from next_best_action.config import Settings
from next_best_action.domain.models import Direction

TEXT = "Which offer should this customer see next?"
DIRECTIONS = [Direction.INPUT, Direction.OUTPUT]


class _MirrorState(enum.IntEnum):
    """``modelarmor_v1.FilterMatchState``'s members, by name and number."""

    FILTER_MATCH_STATE_UNSPECIFIED = 0
    NO_MATCH_FOUND = 1
    MATCH_FOUND = 2


class _MirrorInvocation(enum.IntEnum):
    """``modelarmor_v1.InvocationResult``'s members, by name and number."""

    INVOCATION_RESULT_UNSPECIFIED = 0
    SUCCESS = 1
    PARTIAL = 2
    FAILURE = 3


class _FakeResponse:
    def __init__(self, body: Any, status: int = 200) -> None:
        self._body = body
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            request = httpx.Request("POST", "https://modelarmor.test")
            raise httpx.HTTPStatusError(
                f"HTTP {self._status}",
                request=request,
                response=httpx.Response(self._status, request=request),
            )

    def json(self) -> Any:
        return self._body


class _FakeHttpClient:
    """Stands in for ``httpx.Client``: returns a canned body, or raises the canned error."""

    def __init__(
        self, body: Any = None, *, status: int = 200, error: Exception | None = None
    ) -> None:
        self._body = body
        self._status = status
        self._error = error
        self.urls: list[str] = []
        self.timeouts: list[Any] = []

    def post(self, url: str, *, json: Any, headers: Any, timeout: Any) -> _FakeResponse:
        self.urls.append(url)
        self.timeouts.append(timeout)
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._body, self._status)


def _adapter(
    client: _FakeHttpClient, monkeypatch: pytest.MonkeyPatch
) -> ModelArmorGuardrailAdapter:
    adapter = ModelArmorGuardrailAdapter(Settings(project_id="p"))
    adapter._client = client  # skip the real client; the mapping is what is under test
    monkeypatch.setattr(adapter, "_bearer_token", lambda: "token")
    return adapter


def _map(response: Any, direction: Direction = Direction.INPUT) -> Any:
    adapter = ModelArmorGuardrailAdapter(Settings(project_id="p"))
    return adapter._parse(response, direction, TEXT)


def _mirror_body(
    state: _MirrorState | None, invocation: _MirrorInvocation | None = _MirrorInvocation.SUCCESS
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if state is not None:
        result["filterMatchState"] = state.name
    if invocation is not None:
        result["invocationResult"] = invocation.name
    return {"sanitizationResult": result}


# --------------------------------------------------------------------------- #
# SDK-free: the mapping itself, on the REST JSON wire form
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("direction", DIRECTIONS)
def test_match_found_blocks_sdk_free(direction: Direction) -> None:
    verdict = _map(_mirror_body(_MirrorState.MATCH_FOUND), direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert verdict.findings


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_no_match_found_with_success_allows_sdk_free(direction: Direction) -> None:
    verdict = _map(_mirror_body(_MirrorState.NO_MATCH_FOUND), direction)
    assert verdict.allowed is True
    assert verdict.sanitized_text == TEXT
    assert verdict.findings == ()


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize("invocation", list(_MirrorInvocation), ids=lambda m: m.name)
def test_match_found_blocks_however_many_filters_ran_sdk_free(
    direction: Direction, invocation: _MirrorInvocation
) -> None:
    verdict = _map(_mirror_body(_MirrorState.MATCH_FOUND, invocation), direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize(
    "invocation",
    [
        _MirrorInvocation.PARTIAL,
        _MirrorInvocation.FAILURE,
        _MirrorInvocation.INVOCATION_RESULT_UNSPECIFIED,
        None,
    ],
    ids=["PARTIAL", "FAILURE", "UNSPECIFIED", "absent"],
)
def test_no_match_from_an_incomplete_screen_blocks_sdk_free(
    direction: Direction, invocation: _MirrorInvocation | None
) -> None:
    """A skipped filter reports no match. That is not a pass: the text was not screened."""
    verdict = _map(_mirror_body(_MirrorState.NO_MATCH_FOUND, invocation), direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert "no complete filter decision" in verdict.reason


def test_exactly_one_combination_allows_sdk_free() -> None:
    allowed = [
        (state.name, invocation.name)
        for state in _MirrorState
        for invocation in _MirrorInvocation
        if _map(_mirror_body(state, invocation)).allowed
    ]
    assert allowed == [("NO_MATCH_FOUND", "SUCCESS")]


@pytest.mark.parametrize(
    "response",
    [
        _mirror_body(_MirrorState.FILTER_MATCH_STATE_UNSPECIFIED),
        _mirror_body(None),
        {"sanitizationResult": {}},
        {"sanitizationResult": None},
        {},
        {"sanitizationResult": {"filterMatchState": 1, "invocationResult": 1}},
        {
            "sanitizationResult": {
                "filterMatchState": "no_match_found",
                "invocationResult": "SUCCESS",
            }
        },
        None,
        [],
    ],
    ids=[
        "unspecified-state",
        "state-absent",
        "empty-result",
        "null-result",
        "no-result-key",
        "integer-enums",
        "lower-case-name",
        "null-body",
        "list-body",
    ],
)
def test_no_verdict_fails_closed_sdk_free(response: Any) -> None:
    verdict = _map(response)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert verdict.findings


def test_a_clean_screen_is_not_inferred_from_absent_findings_sdk_free() -> None:
    """The old fallback: no ``filterMatchState`` and no filter hits read as an allow."""
    body = {"sanitizationResult": {"filterResults": {}, "invocationResult": "SUCCESS"}}
    assert _map(body).allowed is False


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_every_call_carries_the_deadline(
    direction: Direction, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _FakeHttpClient(_mirror_body(_MirrorState.NO_MATCH_FOUND))
    verdict = _adapter(client, monkeypatch).screen(TEXT, direction)
    assert verdict.allowed is True
    assert client.timeouts == [Settings().model_armor.timeout_seconds]
    assert client.timeouts[0] > 0


@pytest.mark.parametrize(
    "client",
    [
        _FakeHttpClient(status=503),
        _FakeHttpClient(status=403),
        _FakeHttpClient(error=httpx.ReadTimeout("deadline exceeded")),
        _FakeHttpClient(error=httpx.ConnectError("unreachable")),
    ],
    ids=["503", "403", "timeout", "connect-error"],
)
def test_api_errors_propagate(client: _FakeHttpClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """An API failure must not turn into an allow; it reaches the caller, which refuses."""
    with pytest.raises(httpx.HTTPError):
        _adapter(client, monkeypatch).screen(TEXT, Direction.INPUT)


# --------------------------------------------------------------------------- #
# Real SDK: real modelarmor_v1 messages, serialised to the REST wire form
# --------------------------------------------------------------------------- #
def _ma() -> Any:
    return pytest.importorskip("google.cloud.modelarmor_v1")


def _real_body(
    direction: Direction,
    state_name: str | None,
    invocation_name: str = "SUCCESS",
    *,
    skipped: bool = False,
    integer_enums: bool = False,
) -> Any:
    """A real sanitize response as REST JSON; ``state_name=None`` leaves the result unset.

    ``skipped`` adds the prompt-injection filter as not having run, the shape a prompt padded
    past that filter's token limit produces.
    """
    ma = _ma()
    cls = (
        ma.SanitizeUserPromptResponse
        if direction is Direction.INPUT
        else ma.SanitizeModelResponseResponse
    )
    if state_name is None:
        message = cls()
    else:
        filter_results = {}
        if skipped:
            filter_results["pi_and_jailbreak"] = ma.FilterResult(
                pi_and_jailbreak_filter_result=ma.PiAndJailbreakFilterResult(
                    execution_state=ma.FilterExecutionState.EXECUTION_SKIPPED,
                    match_state=ma.FilterMatchState.NO_MATCH_FOUND,
                )
            )
        message = cls(
            sanitization_result=ma.SanitizationResult(
                filter_match_state=ma.FilterMatchState[state_name],
                invocation_result=ma.InvocationResult[invocation_name],
                filter_results=filter_results,
            )
        )
    return json.loads(cls.to_json(message, use_integers_for_enums=integer_enums))


@pytest.mark.parametrize(
    ("mirror", "real_name"),
    [(_MirrorState, "FilterMatchState"), (_MirrorInvocation, "InvocationResult")],
    ids=["FilterMatchState", "InvocationResult"],
)
def test_the_mirror_matches_the_real_enum(mirror: Any, real_name: str) -> None:
    real = getattr(_ma(), real_name)
    assert {m.name: int(m) for m in real} == {m.name: int(m) for m in mirror}


def test_the_real_wire_form_is_what_the_mirror_writes() -> None:
    body = _real_body(Direction.INPUT, "NO_MATCH_FOUND", "PARTIAL")
    result = body["sanitizationResult"]
    assert result["filterMatchState"] == "NO_MATCH_FOUND"
    assert result["invocationResult"] == "PARTIAL"


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_match_found_blocks(direction: Direction, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeHttpClient(_real_body(direction, "MATCH_FOUND"))
    verdict = _adapter(client, monkeypatch).screen(TEXT, direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert len(client.urls) == 1


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_no_match_found_with_success_allows(
    direction: Direction, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _FakeHttpClient(_real_body(direction, "NO_MATCH_FOUND"))
    verdict = _adapter(client, monkeypatch).screen(TEXT, direction)
    assert verdict.allowed is True
    assert verdict.sanitized_text == TEXT


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize(
    "state_name",
    [None, "FILTER_MATCH_STATE_UNSPECIFIED"],
    ids=["missing-result", "unspecified-state"],
)
def test_no_verdict_fails_closed(
    direction: Direction, state_name: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _FakeHttpClient(_real_body(direction, state_name))
    verdict = _adapter(client, monkeypatch).screen(TEXT, direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize("invocation_name", ["PARTIAL", "FAILURE", "INVOCATION_RESULT_UNSPECIFIED"])
def test_no_match_from_a_screen_where_filters_did_not_run_blocks(
    direction: Direction, invocation_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _real_body(direction, "NO_MATCH_FOUND", invocation_name, skipped=True)
    verdict = _adapter(_FakeHttpClient(body), monkeypatch).screen(TEXT, direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert "no complete filter decision" in verdict.reason


def test_integer_enum_encoding_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """``enum-encoding=int`` puts numbers on the wire; an unrecognised form never allows."""
    body = _real_body(Direction.INPUT, "NO_MATCH_FOUND", integer_enums=True)
    verdict = _adapter(_FakeHttpClient(body), monkeypatch).screen(TEXT, Direction.INPUT)
    assert verdict.allowed is False
