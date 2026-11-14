"""The bench's own provider layer: images in chat requests, the Responses adapter, usage."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import run

from autodeck.providers.base import ImageInput, Message, ToolCall

PNG = b"\x89PNG\r\n\x1a\nfake"


def history() -> list[Message]:
    return [
        Message(role="user", content="brief"),
        Message(
            role="assistant",
            content="ok",
            tool_calls=[ToolCall("call_1", "write_slide", {"slide": {"id": "x"}})],
        ),
        Message(role="tool", content="Accepted", tool_call_id="call_1"),
        run.ImageMessage(
            role="user", content="Here is the render.", images=(ImageInput(data=PNG),)
        ),
    ]


def test_chat_request_carries_the_image_after_the_tool_result_and_drops_temperature() -> None:
    provider = run.make_provider("openai:gpt-5.4-mini", max_output_tokens=1000, api_key="k")
    url, _headers, body = provider.build_converse_request(
        messages=history(), tools=[run.WRITE_SLIDE_TOOL], system="SYS"
    )
    assert url.endswith("/chat/completions") and "temperature" not in body
    assert body["max_completion_tokens"] == 1000
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "user"]
    parts = body["messages"][-1]["content"]
    assert parts[0] == {"type": "text", "text": "Here is the render."}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert body["messages"][3]["content"] == "Accepted"  # tool result stays text


def test_chat_usage_counts_reasoning_inside_completion_tokens() -> None:
    provider = run.make_provider("openai:gpt-5.4-mini", max_output_tokens=10, api_key="k")
    turn = provider.parse_converse_response(
        {
            "choices": [{"message": {"content": "", "tool_calls": []}}],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 700,
                "completion_tokens_details": {"reasoning_tokens": 500},
                "prompt_tokens_details": {"cached_tokens": 64},
            },
        }
    )
    assert (turn.usage.input_tokens, turn.usage.output_tokens) == (1000, 700)
    assert turn.usage.reasoning_tokens == 500  # type: ignore[attr-defined]
    # billed output is completion_tokens (700), not 700 + 500
    assert run.estimate_cost(run.Price(3, 15), 1000, 700) == pytest.approx(0.0135)


def test_routing_and_effective_reasoning() -> None:
    assert run.uses_responses("openai:gpt-5.6-luna")
    assert run.uses_responses("openai:gpt-5.6-sol")
    assert not run.uses_responses("openai:gpt-5.4-mini")
    assert run.uses_responses("openai:gpt-5.4-mini", "responses")
    assert not run.uses_responses("openai:gpt-5.6-luna", "chat")
    assert run.effective_reasoning("openai:gpt-5.6-luna", "high") == "high"
    assert run.effective_reasoning("openai:gpt-5.4-mini", "high") == "default"


@pytest.fixture
def responses_provider() -> Any:
    return run.make_provider(
        "openai:gpt-5.6-luna", max_output_tokens=4000, api_key="k", reasoning="high"
    )


def test_responses_request_shape(responses_provider: Any) -> None:
    url, _headers, body = responses_provider.build_converse_request(
        messages=history(), tools=[run.WRITE_SLIDE_TOOL], system="SYS"
    )
    assert url == "https://api.openai.com/v1/responses"
    assert body["instructions"] == "SYS" and body["store"] is False
    assert body["reasoning"] == {"effort": "high"}
    assert body["max_output_tokens"] == 4000 and "temperature" not in body
    assert body["tool_choice"] == "auto"
    tool = body["tools"][0]
    assert tool["type"] == "function" and tool["name"] == "write_slide"
    assert tool["strict"] is False and tool["parameters"]["type"] == "object"
    items = body["input"]
    assert items[0] == {"role": "user", "content": "brief"}
    assert items[1] == {"role": "assistant", "content": "ok"}
    assert items[2]["type"] == "function_call" and items[2]["call_id"] == "call_1"
    assert items[2]["arguments"] == '{"slide": {"id": "x"}}'
    assert items[3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "Accepted",
    }
    last = items[4]
    assert last["role"] == "user"
    assert last["content"][0] == {"type": "input_text", "text": "Here is the render."}
    assert last["content"][1]["type"] == "input_image"
    assert last["content"][1]["image_url"].startswith("data:image/png;base64,")
    assert "authorization" not in str(body).lower()


RESPONSE = {
    "id": "resp_1",
    "status": "completed",
    "output": [
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Designing."}],
        },
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_9",
            "name": "write_slide",
            "arguments": '{"slide": {"id": "s"}}',
        },
    ],
    "usage": {
        "input_tokens": 2000,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 3000,
        "output_tokens_details": {"reasoning_tokens": 2200},
        "total_tokens": 5000,
    },
}


def test_responses_parse_text_calls_and_usage(responses_provider: Any) -> None:
    turn = responses_provider.parse_converse_response(RESPONSE)
    assert turn.text == "Designing."
    assert [(c.id, c.name, c.arguments) for c in turn.tool_calls] == [
        ("call_9", "write_slide", {"slide": {"id": "s"}})
    ]
    assert (turn.usage.input_tokens, turn.usage.output_tokens) == (2000, 3000)
    assert turn.usage.reasoning_tokens == 2200  # included in the 3000, billed once


def test_responses_parse_bad_arguments_and_incomplete(responses_provider: Any) -> None:
    broken = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [
            {
                "type": "function_call",
                "call_id": "c",
                "name": "write_slide",
                "arguments": "{cut",
            }
        ],
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }
    turn = responses_provider.parse_converse_response(broken)
    assert turn.tool_calls[0].arguments == {"__invalid__": "{cut"}
    empty = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"type": "reasoning"}],
        "usage": {"input_tokens": 5, "output_tokens": 4000},
    }
    turn = responses_provider.parse_converse_response(empty)
    assert not turn.tool_calls and "incomplete: max_output_tokens" in turn.text
    assert turn.usage.output_tokens == 4000  # the billed tokens are still counted


def test_responses_error_payload_raises(responses_provider: Any) -> None:
    from autodeck.providers.base import ProviderResponseError

    with pytest.raises(ProviderResponseError):
        responses_provider.parse_converse_response(
            {"status": "failed", "error": {"message": "x"}}
        )


def test_responses_end_to_end_through_a_mock_transport() -> None:
    import httpx

    from autodeck.providers.base import ProviderConfig

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=RESPONSE)

    provider = run.make_provider("openai:gpt-5.6-luna", max_output_tokens=10, api_key="k")
    provider.config = ProviderConfig(
        model="gpt-5.6-luna", api_key="k", transport=httpx.MockTransport(handler)
    )
    turn = provider.converse(
        [Message(role="user", content="hi")], [run.WRITE_SLIDE_TOOL], system="S"
    )
    assert turn.tool_calls[0].name == "write_slide"
    assert seen[0].url.path == "/v1/responses"
