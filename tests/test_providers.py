"""Provider abstraction: repair-retry, backoff, caching, and request shape.

Everything here runs against a mocked httpx transport, so CI exercises the paths that
matter without credentials or cost. The live three-provider proof is in
`test_providers_live.py` behind the `live` marker.

The repair tests are the important ones. `complete_structured` returning a
partially-valid object would put a dropped citation into the IR looking legitimate, and
nothing downstream would catch it — the object would be well-formed, just wrong.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import Field

from autodeck.ir.models import IRModel
from autodeck.providers.base import (
    BaseProvider,
    ImageInput,
    ProviderAuthError,
    ProviderConfig,
    ProviderError,
    ProviderResponseError,
    RateLimitError,
    StructuredOutputError,
)
from autodeck.providers.cache import ResponseCache
from autodeck.providers.claude import ClaudeProvider
from autodeck.providers.gemini import GeminiProvider
from autodeck.providers.groq import GroqProvider


class Answer(IRModel):
    """Trivial schema, per the 0.3 exit criterion."""

    city: str
    population: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class ScriptedTransport(httpx.BaseTransport):
    """Replays a scripted list of responses and records every request."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("transport received more requests than were scripted")
        return self._responses.pop(0)

    def body(self, index: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def gemini_reply(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7},
        },
    )


def make_provider(
    responses: list[httpx.Response], **overrides: Any
) -> tuple[GeminiProvider, ScriptedTransport, list[float]]:
    """A Gemini provider over a scripted transport, with sleeps recorded not taken."""
    transport = ScriptedTransport(responses)
    config = ProviderConfig(model="gemini-test", api_key="test-key", transport=transport)
    for key, value in overrides.items():
        setattr(config, key, value)

    slept: list[float] = []

    class Instrumented(GeminiProvider):
        def _sleep(self, seconds: float) -> None:
            slept.append(seconds)

    return Instrumented(config), transport, slept


# ---------------------------------------------------------------------------
# Structured output — the happy path
# ---------------------------------------------------------------------------


def test_structured_output_validates_against_the_model() -> None:
    provider, _, _ = make_provider([gemini_reply('{"city": "Oslo", "population": 709000}')])
    answer = provider.complete_structured("Name a city.", Answer)
    assert answer == Answer(city="Oslo", population=709000)


def test_a_fenced_json_block_is_unwrapped() -> None:
    fenced = '```json\n{"city": "Oslo", "population": 709000}\n```'
    provider, _, _ = make_provider([gemini_reply(fenced)])
    assert provider.complete_structured("Name a city.", Answer).city == "Oslo"


def test_the_schema_is_sent_to_the_provider() -> None:
    provider, transport, _ = make_provider([gemini_reply('{"city": "Oslo", "population": 1}')])
    provider.complete_structured("Name a city.", Answer)
    config = transport.body()["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert set(config["responseSchema"]["properties"]) == {"city", "population"}


# ---------------------------------------------------------------------------
# Repair-retry — N attempts, then hard-fail, never a silent drop
# ---------------------------------------------------------------------------


def test_malformed_json_triggers_a_repair_attempt_that_can_succeed() -> None:
    provider, transport, _ = make_provider(
        [
            gemini_reply("not json at all"),
            gemini_reply('{"city": "Oslo", "population": 709000}'),
        ]
    )
    assert provider.complete_structured("Name a city.", Answer).city == "Oslo"
    assert len(transport.requests) == 2


def test_the_repair_prompt_names_the_validation_error() -> None:
    """A bare 'try again' mostly reproduces the same output."""
    provider, transport, _ = make_provider(
        [gemini_reply('{"city": "Oslo"}'), gemini_reply('{"city": "Oslo", "population": 1}')]
    )
    provider.complete_structured("Name a city.", Answer)
    repair = transport.body(1)["contents"][0]["parts"][0]["text"]
    assert "population" in repair
    assert "omitting a field is not an acceptable way" in repair.lower()


def test_repair_exhaustion_hard_fails() -> None:
    provider, transport, _ = make_provider([gemini_reply("nope")] * 3)
    with pytest.raises(StructuredOutputError) as excinfo:
        provider.complete_structured("Name a city.", Answer)
    assert excinfo.value.attempts == 3
    assert len(transport.requests) == 3


def test_a_missing_field_is_never_silently_dropped() -> None:
    """The failure that matters: a well-formed object missing a required field."""
    provider, _, _ = make_provider([gemini_reply('{"city": "Oslo"}')] * 3)
    with pytest.raises(StructuredOutputError):
        provider.complete_structured("Name a city.", Answer)


def test_an_invented_field_is_rejected_rather_than_ignored() -> None:
    """IR models forbid extras, so a hallucinated field fails instead of vanishing."""
    payload = '{"city": "Oslo", "population": 1, "confidence": "high"}'
    provider, _, _ = make_provider([gemini_reply(payload)] * 3)
    with pytest.raises(StructuredOutputError):
        provider.complete_structured("Name a city.", Answer)


def test_a_constraint_violation_is_rejected() -> None:
    provider, _, _ = make_provider([gemini_reply('{"city": "Oslo", "population": -5}')] * 3)
    with pytest.raises(StructuredOutputError):
        provider.complete_structured("Name a city.", Answer)


def test_the_repair_budget_is_configurable() -> None:
    provider, transport, _ = make_provider([gemini_reply("nope")] * 5, max_repair_attempts=5)
    with pytest.raises(StructuredOutputError):
        provider.complete_structured("Name a city.", Answer)
    assert len(transport.requests) == 5


# ---------------------------------------------------------------------------
# Backoff — free tiers make 429 the normal case (B8)
# ---------------------------------------------------------------------------


def test_a_rate_limit_is_retried_and_can_succeed() -> None:
    provider, transport, slept = make_provider(
        [httpx.Response(429), gemini_reply('{"city": "Oslo", "population": 1}')]
    )
    assert provider.complete_structured("Name a city.", Answer).city == "Oslo"
    assert len(transport.requests) == 2
    assert len(slept) == 1


def test_retry_after_is_honoured_when_supplied() -> None:
    provider, _, slept = make_provider(
        [
            httpx.Response(429, headers={"retry-after": "7"}),
            gemini_reply('{"city": "Oslo", "population": 1}'),
        ]
    )
    provider.complete_structured("Name a city.", Answer)
    assert slept == [7.0]


def test_backoff_grows_between_attempts() -> None:
    provider, _, slept = make_provider([httpx.Response(429)] * 4, max_rate_limit_retries=3)
    with pytest.raises(RateLimitError):
        provider.complete("Name a city.")
    assert len(slept) == 3
    assert slept[0] < slept[-1]


def test_a_sleep_is_capped() -> None:
    provider, _, slept = make_provider(
        [
            httpx.Response(429, headers={"retry-after": "99999"}),
            gemini_reply('{"city": "Oslo", "population": 1}'),
        ]
    )
    provider.complete_structured("Name a city.", Answer)
    assert slept == [60.0]


def test_rate_limiting_beyond_the_budget_raises() -> None:
    provider, transport, _ = make_provider([httpx.Response(429)] * 3, max_rate_limit_retries=2)
    with pytest.raises(RateLimitError):
        provider.complete("Name a city.")
    assert len(transport.requests) == 3


def test_bad_credentials_are_not_retried() -> None:
    """Retrying a rejected key only burns time and quota."""
    provider, transport, slept = make_provider([httpx.Response(401)])
    with pytest.raises(ProviderAuthError, match="GEMINI_API_KEY"):
        provider.complete("Name a city.")
    assert len(transport.requests) == 1
    assert slept == []


def test_a_missing_key_fails_at_construction() -> None:
    with pytest.raises(ProviderAuthError, match="GEMINI_API_KEY"):
        GeminiProvider(ProviderConfig(model="gemini-test", api_key=""))


def test_a_server_error_is_retried() -> None:
    provider, transport, _ = make_provider(
        [httpx.Response(503), gemini_reply('{"city": "Oslo", "population": 1}')]
    )
    assert provider.complete_structured("Name a city.", Answer).city == "Oslo"
    assert len(transport.requests) == 2


def test_a_safety_block_surfaces_the_reason_and_is_not_retried() -> None:
    """An empty candidate list would otherwise fail later as a confusing JSON error.

    It is also deterministic: re-sending the identical request gets the identical block,
    so retrying it is free-tier quota spent to learn nothing.
    """
    blocked = httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
    provider, transport, slept = make_provider([blocked])
    with pytest.raises(ProviderResponseError, match="SAFETY"):
        provider.complete("Name a city.")
    assert len(transport.requests) == 1
    assert slept == []


def test_an_unusable_response_body_does_not_escape_as_a_raw_parsing_error() -> None:
    """An adapter bug must surface as a ProviderError, not a stack trace about dicts."""
    provider, _, _ = make_provider([httpx.Response(200, json={"candidates": "not-a-list"})])
    with pytest.raises(ProviderError):
        provider.complete("Name a city.")


# ---------------------------------------------------------------------------
# Resumability
# ---------------------------------------------------------------------------


def test_a_cached_response_skips_the_api_call(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    payload = '{"city": "Oslo", "population": 709000}'

    first, first_transport, _ = make_provider([gemini_reply(payload)], cache=cache)
    assert first.complete_structured("Name a city.", Answer).city == "Oslo"
    assert len(first_transport.requests) == 1

    # A second provider over an empty transport: any network call would now fail.
    second, second_transport, _ = make_provider([], cache=cache)
    assert second.complete_structured("Name a city.", Answer).city == "Oslo"
    assert second_transport.requests == []


def test_a_changed_schema_invalidates_the_cache(tmp_path: Path) -> None:
    """A resumed run must not reuse a reply produced under a different contract."""

    class Wider(IRModel):
        city: str
        population: int
        country: str

    cache = ResponseCache(tmp_path)
    provider, _, _ = make_provider(
        [gemini_reply('{"city": "Oslo", "population": 1}')], cache=cache
    )
    provider.complete_structured("Name a city.", Answer)

    other, transport, _ = make_provider(
        [gemini_reply('{"city": "Oslo", "population": 1, "country": "Norway"}')], cache=cache
    )
    other.complete_structured("Name a city.", Wider)
    assert len(transport.requests) == 1  # not served from cache


def test_a_repair_attempt_is_not_served_the_cached_failure(tmp_path: Path) -> None:
    """Otherwise every repair attempt replays the reply that just failed to validate."""
    cache = ResponseCache(tmp_path)
    provider, transport, _ = make_provider(
        [gemini_reply("not json"), gemini_reply('{"city": "Oslo", "population": 1}')],
        cache=cache,
    )
    assert provider.complete_structured("Name a city.", Answer).city == "Oslo"
    assert len(transport.requests) == 2


def test_an_interrupted_cache_write_leaves_no_partial_entry(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    cache.put("abc123", "value")
    assert cache.get("abc123") == "value"
    assert list(tmp_path.rglob("*.tmp")) == []
    assert len(cache) == 1


# ---------------------------------------------------------------------------
# Per-provider request shape
# ---------------------------------------------------------------------------


def _shape(
    provider_class: type[BaseProvider], schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    provider = provider_class(ProviderConfig(model="m", api_key="k"))
    _, headers, body = provider.build_request(
        prompt="hello", system="be terse", schema=schema, images=[]
    )
    return {"headers": headers, "body": body}


def test_groq_uses_openai_strict_json_schema() -> None:
    from autodeck.ir.schema import export_schema

    shape = _shape(GroqProvider, export_schema(Answer, "strict"))
    response_format = shape["body"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert shape["body"]["messages"][0]["role"] == "system"


def test_claude_forces_a_single_tool_call() -> None:
    from autodeck.ir.schema import export_schema

    shape = _shape(ClaudeProvider, export_schema(Answer, "standard"))
    assert shape["body"]["tool_choice"] == {
        "type": "tool",
        "name": "emit_structured_response",
    }
    assert len(shape["body"]["tools"]) == 1
    assert shape["headers"]["anthropic-version"] == "2023-06-01"


def test_claude_reads_the_object_out_of_the_tool_use_block() -> None:
    provider = ClaudeProvider(ProviderConfig(model="m", api_key="k"))
    parsed = provider.parse_response(
        {
            "content": [
                {
                    "type": "tool_use",
                    "name": "emit_structured_response",
                    "input": {"city": "Oslo", "population": 709000},
                }
            ],
            "usage": {"input_tokens": 3, "output_tokens": 4},
        }
    )
    assert Answer.model_validate_json(parsed.text).city == "Oslo"
    assert parsed.usage.output_tokens == 4


def test_groq_surfaces_a_refusal_instead_of_returning_empty_text() -> None:
    provider = GroqProvider(ProviderConfig(model="m", api_key="k"))
    with pytest.raises(ProviderResponseError, match="refused"):
        provider.parse_response({"choices": [{"message": {"refusal": "I cannot help"}}]})


@pytest.mark.parametrize("provider_class", [GeminiProvider, GroqProvider, ClaudeProvider])
def test_every_provider_accepts_images(provider_class: type[BaseProvider]) -> None:
    provider = provider_class(ProviderConfig(model="m", api_key="k"))
    _, _, body = provider.build_request(
        prompt="describe", system=None, schema=None, images=[ImageInput(data=b"\x89PNG")]
    )
    assert "iVBORw==" in json.dumps(body) or "PNG" in json.dumps(body)
