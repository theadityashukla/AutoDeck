"""Task 23.3: the studio's own Responses-endpoint path (`responses.py`), moved from the
bench's proven adapter. No network: request bodies and payload parsing only."""

from __future__ import annotations

import json

import pytest

from autodeck.providers.base import (
    ImageInput,
    Message,
    ProviderAuthError,
    ProviderResponseError,
    ToolCall,
    ToolSpec,
)
from autodeck.studio.bindings import RoleBinding
from autodeck.studio.errors import StudioConfigError
from autodeck.studio.responses import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    ImageMessage,
    build_request_body,
    make_responses_model,
    parse_response,
    uses_responses,
)
from autodeck.studio.tool_args import RouteArgs

PNG = b"\x89PNG\r\n\x1a\nfake"
ROUTE = ToolSpec(name="route", description="Route it.", args_model=RouteArgs)


def history() -> list[Message]:
    return [
        Message(role="user", content="brief"),
        Message(
            role="assistant",
            content="ok",
            tool_calls=[ToolCall("call_1", "write_slide", {"slide": {"id": "x"}})],
        ),
        Message(role="tool", content="Accepted", tool_call_id="call_1"),
        Message(role="assistant", content="", tool_calls=[ToolCall("call_2", "route", {})]),
        ImageMessage(
            role="user", content="Here is the render.", images=(ImageInput(data=PNG),)
        ),
    ]


def test_which_bindings_use_the_responses_endpoint() -> None:
    def b(model: str, api: str = "auto", provider: str = "openai") -> RoleBinding:
        return RoleBinding(provider=provider, model=model, api=api)  # type: ignore[arg-type]

    assert uses_responses(b("gpt-5.6-luna"))
    assert not uses_responses(b("gpt-5.4-mini"))
    assert uses_responses(b("gpt-5.4-mini", api="responses"))
    assert not uses_responses(b("gpt-5.6-terra", api="chat"))
    assert not uses_responses(b("ministral-14b-2512", api="responses", provider="mistral"))


def test_the_request_body_matches_the_bench_wire_format() -> None:
    body = build_request_body(
        model="gpt-5.6-luna",
        messages=history(),
        tools=[ROUTE],
        system="SYS",
        reasoning="high",
        max_output_tokens=1234,
        image_url=lambda image: "data:image/png;base64,AAAA",
    )
    assert body["model"] == "gpt-5.6-luna" and body["instructions"] == "SYS"
    assert body["reasoning"] == {"effort": "high"} and body["store"] is False
    assert body["max_output_tokens"] == 1234 and "temperature" not in body
    items = body["input"]
    assert items[0] == {"role": "user", "content": "brief"}
    assert items[1] == {"role": "assistant", "content": "ok"}
    assert items[2] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "write_slide",
        "arguments": json.dumps({"slide": {"id": "x"}}),
    }
    assert items[3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "Accepted",
    }
    assert items[4]["type"] == "function_call" and items[4]["call_id"] == "call_2"
    assert items[5] == {
        "role": "user",
        "content": [
            {"type": "input_text", "text": "Here is the render."},
            {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
        ],
    }
    (tool,) = body["tools"]
    assert tool["type"] == "function" and tool["name"] == "route" and tool["strict"] is False
    assert "to" in tool["parameters"]["properties"]
    assert body["tool_choice"] == "auto"
    bare = build_request_body(
        model="m",
        messages=[Message(role="user", content="x")],
        tools=[],
        system=None,
        reasoning="low",
        max_output_tokens=10,
        image_url=lambda image: "",
    )
    assert "tools" not in bare and "tool_choice" not in bare and "instructions" not in bare


def test_parsing_text_tool_calls_usage_and_failures() -> None:
    turn = parse_response(
        {
            "status": "completed",
            "output": [
                {"type": "reasoning", "summary": []},
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Done"},
                        {"type": "refusal", "refusal": "no"},
                    ],
                },
                {
                    "type": "function_call",
                    "call_id": "c1",
                    "name": "route",
                    "arguments": '{"to": "lead"}',
                },
                {"type": "function_call", "id": "c2", "name": "route", "arguments": "{bad"},
            ],
            "usage": {
                "input_tokens": 900,
                "output_tokens": 400,
                "output_tokens_details": {"reasoning_tokens": 300},
                "input_tokens_details": {"cached_tokens": 64},
            },
        }
    )
    assert turn.text == "Done[refusal] no"
    assert [(c.id, c.name, c.arguments) for c in turn.tool_calls] == [
        ("c1", "route", {"to": "lead"}),
        ("c2", "route", {"__invalid__": "{bad"}),
    ]
    assert (turn.usage.input_tokens, turn.usage.output_tokens) == (900, 400)
    assert turn.usage.reasoning_tokens == 300  # type: ignore[attr-defined]
    assert turn.usage.cached_tokens == 64  # type: ignore[attr-defined]
    cut = parse_response(
        {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
    )
    assert cut.text == "[response incomplete: max_output_tokens]"
    assert cut.usage.input_tokens == 0
    with pytest.raises(ProviderResponseError, match="responses API error"):
        parse_response({"status": "failed", "error": {"message": "boom"}})


def test_the_model_posts_to_responses_with_the_bindings_settings() -> None:
    binding = RoleBinding(
        provider="openai", model="gpt-5.6-luna", reasoning="high", max_output_tokens=9000
    )
    model = make_responses_model(binding, api_key="k")
    url, headers, body = model.build_converse_request(
        messages=[Message(role="user", content="x")], tools=[ROUTE], system="S"
    )
    assert url == "https://api.openai.com/v1/responses"
    assert headers["authorization"] == "Bearer k"
    assert body["reasoning"] == {"effort": "high"} and body["max_output_tokens"] == 9000
    assert type(model).__name__.startswith("Responses")
    default = make_responses_model(
        RoleBinding(provider="openai", model="gpt-5.6-terra"), api_key="k"
    )
    _, _, body = default.build_converse_request(messages=history()[:1], tools=[], system=None)
    assert body["reasoning"] == {"effort": "medium"}
    assert body["max_output_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS
    turn = default.parse_converse_response(
        {"output": [{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}]}
    )
    assert turn.text == "hi"


def test_unsupported_providers_and_missing_keys() -> None:
    with pytest.raises(StudioConfigError):
        make_responses_model(RoleBinding(provider="mistral", model="m"), api_key="k")
    with pytest.raises(ProviderAuthError):
        make_responses_model(RoleBinding(provider="openai", model="gpt-5.6-luna"), api_key="")
