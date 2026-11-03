"""OpenAI-compatible providers (mistral, openai, nebius), claude, and multi-turn tool calling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from autodeck.ir.schema import export_schema
from autodeck.providers.base import (
    BaseProvider,
    Message,
    ProviderConfig,
    ToolCall,
    ToolSpec,
)
from autodeck.providers.cache import ResponseCache
from autodeck.providers.claude import ClaudeProvider
from autodeck.providers.guard import ProviderGuard
from autodeck.providers.mistral import MistralProvider
from autodeck.providers.nebius import NebiusProvider
from autodeck.providers.openai import OpenAIProvider
from autodeck.providers.registry import ModelRegistry


class Answer(BaseModel):
    city: str
    population: int


class SearchArgs(BaseModel):
    query: str


TOOLS = [ToolSpec(name="search", description="Search the corpus.", args_model=SearchArgs)]


class Scripted(httpx.BaseTransport):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("more requests than scripted")
        return httpx.Response(200, json=self._responses.pop(0))

    def body(self, i: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[i].content)


def _oa(content: Any = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {
        "choices": [{"message": msg}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    }


def _oa_call(args: str) -> dict[str, Any]:
    return _oa(
        tool_calls=[
            {"id": "c1", "type": "function", "function": {"name": "search", "arguments": args}}
        ]
    )


def _claude_text(text: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }


def _claude_call(args: Any) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": "looking"},
            {"type": "tool_use", "id": "tu1", "name": "search", "input": args},
        ],
        "stop_reason": "tool_use",
    }


def make(
    cls: type[BaseProvider], responses: list[dict[str, Any]], cache: ResponseCache | None = None
):
    transport = Scripted(responses)
    provider = cls(
        ProviderConfig(model="m", api_key="secret", transport=transport, cache=cache)
    )
    return provider, transport


OA_CLASSES = [MistralProvider, OpenAIProvider, NebiusProvider]
ALL = [*OA_CLASSES, ClaudeProvider]


def _final(cls: type[BaseProvider]) -> dict[str, Any]:
    return _claude_text("done") if cls is ClaudeProvider else _oa("done")


def _call(cls: type[BaseProvider], args: Any = None) -> dict[str, Any]:
    if cls is ClaudeProvider:
        return _claude_call({"query": "q"} if args is None else args)
    return _oa_call(json.dumps({"query": "q"}) if args is None else args)


# -- structured requests ---------------------------------------------------


@pytest.mark.parametrize(
    ("cls", "url", "field"),
    [
        (MistralProvider, "https://api.mistral.ai/v1/chat/completions", "max_tokens"),
        (OpenAIProvider, "https://api.openai.com/v1/chat/completions", "max_completion_tokens"),
        (
            NebiusProvider,
            "https://api.tokenfactory.nebius.com/v1/chat/completions",
            "max_tokens",
        ),
    ],
)
def test_openai_compat_structured_request(
    cls: type[BaseProvider], url: str, field: str
) -> None:
    provider, transport = make(cls, [_oa('{"city": "Oslo", "population": 1}')])
    assert provider.complete_structured("hi", Answer, system="sys") == Answer(
        city="Oslo", population=1
    )
    request = transport.requests[0]
    assert str(request.url) == url
    assert request.headers["authorization"] == "Bearer secret"
    body = transport.body()
    assert field in body
    assert ({"max_tokens", "max_completion_tokens"} - {field}).isdisjoint(body)
    fmt = body["response_format"]["json_schema"]
    assert fmt["strict"] is True
    assert fmt["schema"] == export_schema(Answer, "strict")
    system_text = body["messages"][0]["content"]
    assert system_text.startswith("sys")
    if cls is NebiusProvider:
        assert "Respond with JSON matching this schema:" in system_text
        assert '"population"' in system_text
    else:
        assert system_text == "sys"


def test_image_part_shapes() -> None:
    from autodeck.providers.base import ImageInput

    img = [ImageInput(data=b"x")]
    for cls, is_obj in [
        (OpenAIProvider, True),
        (NebiusProvider, True),
        (MistralProvider, False),
    ]:
        provider, _ = make(cls, [])
        _, _, body = provider.build_request(prompt="p", system=None, schema=None, images=img)
        part = body["messages"][0]["content"][1]
        assert isinstance(part["image_url"], dict) is is_obj


def test_content_chunks_are_concatenated() -> None:
    provider, _ = make(
        OpenAIProvider,
        [
            _oa(
                [
                    {"type": "thinking", "thinking": "x"},
                    {"type": "text", "text": "a"},
                    {"type": "text", "text": "b"},
                ]
            )
        ],
    )
    assert provider.complete("hi") == "ab"


def test_claude_structured_request() -> None:
    provider, transport = make(
        ClaudeProvider,
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "emit_structured_response",
                        "input": {"city": "O", "population": 1},
                    }
                ]
            }
        ],
    )
    provider.complete_structured("hi", Answer)
    assert str(transport.requests[0].url) == "https://api.anthropic.com/v1/messages"
    assert transport.requests[0].headers["x-api-key"] == "secret"
    assert transport.body()["tool_choice"]["name"] == "emit_structured_response"


# -- converse round trip ---------------------------------------------------


@pytest.mark.parametrize("cls", OA_CLASSES)
def test_openai_compat_converse_round_trip(cls: type[BaseProvider]) -> None:
    provider, transport = make(cls, [_oa_call('{"query": "q"}'), _oa("done")])
    messages = [Message(role="user", content="find it")]
    turn = provider.converse(messages, TOOLS, system="sys")
    assert turn.tool_calls == [ToolCall(id="c1", name="search", arguments={"query": "q"})]
    body = transport.body(0)
    assert body["tools"][0] == {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the corpus.",
            "parameters": export_schema(SearchArgs, "strict"),
        },
    }
    assert body["tool_choice"] == "auto"
    assert body["messages"][0] == {"role": "system", "content": "sys"}

    messages += [
        Message(role="assistant", content=turn.text, tool_calls=turn.tool_calls),
        Message(role="tool", content="result", tool_call_id="c1"),
    ]
    final = provider.converse(messages, TOOLS, system="sys")
    assert final.text == "done" and final.tool_calls == []
    sent = transport.body(1)["messages"]
    assert sent[2]["role"] == "assistant"
    assert sent[2]["tool_calls"] == [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "search", "arguments": '{"query":"q"}'},
        }
    ]
    assert sent[3] == {"role": "tool", "tool_call_id": "c1", "content": "result"}


def test_claude_converse_round_trip() -> None:
    provider, transport = make(
        ClaudeProvider, [_claude_call({"query": "q"}), _claude_text("done")]
    )
    messages = [Message(role="user", content="find it")]
    turn = provider.converse(messages, TOOLS, system="sys")
    assert turn.text == "looking"
    assert turn.tool_calls == [ToolCall(id="tu1", name="search", arguments={"query": "q"})]
    body = transport.body(0)
    assert body["system"] == "sys"
    assert body["tools"][0]["name"] == "search"
    assert body["tools"][0]["input_schema"] == export_schema(SearchArgs, "standard")

    messages += [
        Message(role="assistant", content=turn.text, tool_calls=turn.tool_calls),
        Message(role="tool", content="result", tool_call_id="tu1"),
    ]
    final = provider.converse(messages, TOOLS, system="sys")
    assert final.text == "done"
    sent = transport.body(1)["messages"]
    assert sent[1]["content"][1] == {
        "type": "tool_use",
        "id": "tu1",
        "name": "search",
        "input": {"query": "q"},
    }
    assert sent[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "result"}],
    }


# -- invalid arguments -----------------------------------------------------


@pytest.mark.parametrize("cls", OA_CLASSES)
def test_invalid_tool_arguments_do_not_raise(cls: type[BaseProvider]) -> None:
    provider, _ = make(cls, [_oa_call("{not json")])
    turn = provider.converse([Message(role="user", content="x")], TOOLS)
    assert turn.tool_calls[0].arguments == {"__invalid__": "{not json"}


# -- caching ---------------------------------------------------------------


@pytest.mark.parametrize("cls", ALL)
def test_converse_is_cached(cls: type[BaseProvider], tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    provider, transport = make(cls, [_call(cls)], cache=cache)
    messages = [Message(role="user", content="find it")]
    first = provider.converse(messages, TOOLS)
    second = provider.converse(messages, TOOLS)
    assert len(transport.requests) == 1
    assert second == first and second.tool_calls[0].arguments == {"query": "q"}


def test_converse_cache_key_covers_tools_system_and_history(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path)
    provider, transport = make(
        OpenAIProvider, [_oa("a"), _oa("b"), _oa("c"), _oa("d")], cache=cache
    )
    m = [Message(role="user", content="x")]
    provider.converse(m, TOOLS)
    provider.converse(m, TOOLS, system="other")
    provider.converse(
        m, [ToolSpec(name="search", description="changed", args_model=SearchArgs)]
    )
    provider.converse([*m, Message(role="user", content="more")], TOOLS)
    assert len(transport.requests) == 4


# -- guard -----------------------------------------------------------------


def test_role_bound_forwards_converse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "k")
    registry = ModelRegistry.load("dev-mistral")
    guard = ProviderGuard(registry, cache=None)
    bound = guard.provider("planner")
    seen: dict[str, Any] = {}

    def fake(messages: Any, tools: Any, *, system: Any = None) -> str:
        seen.update(messages=messages, tools=tools, system=system)
        return "turn"

    monkeypatch.setattr(bound._inner, "converse", fake)
    assert bound.converse(["m"], ["t"], system="s") == "turn"
    assert seen == {"messages": ["m"], "tools": ["t"], "system": "s"}


# -- config ----------------------------------------------------------------


def test_config_default_env_and_providers() -> None:
    import yaml

    from autodeck.providers.registry import DEFAULT_CONFIG_PATH, PROVIDERS

    raw = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text())
    assert ModelRegistry.load().env == raw["default_env"]
    assert {"nebius", "openai", "mistral", "claude"} <= set(PROVIDERS)
    for env in raw["environments"]:
        ModelRegistry.load(env)  # every environment must load
