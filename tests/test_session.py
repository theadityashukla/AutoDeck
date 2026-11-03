"""The agent loop (B71): scripted models, no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from autodeck.agents.session import (
    NUDGE,
    SessionLimits,
    SessionState,
    TranscriptLog,
    compact,
    run_session,
    timeline,
)
from autodeck.agents.tools.registry import Tool, ToolBox, ToolResult
from autodeck.providers.base import (
    AssistantTurn,
    Message,
    ProviderConfig,
    ToolCall,
    ToolSpec,
    Usage,
)
from autodeck.providers.cache import ResponseCache
from autodeck.providers.mistral import MistralProvider


class NArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = 0


class Counter:
    """A tool that bumps `revision` on `bump`, so the repeat guard can be tested."""

    def __init__(self) -> None:
        self.revision = 0
        self.runs = 0

    def tools(self) -> list[Tool]:
        def look(_: NArgs) -> ToolResult:
            self.runs += 1
            return ToolResult(f"looked {self.runs}", f"look #{self.runs}")

        def bump(_: NArgs) -> ToolResult:
            self.revision += 1
            return ToolResult("bumped", "bump")

        def finish(_: NArgs) -> ToolResult:
            return ToolResult("done", "finished", finished=True)

        return [
            Tool("look", "d", NArgs, look),
            Tool("bump", "d", NArgs, bump),
            Tool("finish", "d", NArgs, finish),
        ]


class ScriptedConverse:
    def __init__(self, *turns: AssistantTurn) -> None:
        self.turns = list(turns)
        self.seen: list[list[Message]] = []

    def converse(self, messages, tools, *, system=None):  # type: ignore[no-untyped-def]
        self.seen.append(list(messages))
        return self.turns.pop(0)


def tc(name: str, i: int, **args: Any) -> AssistantTurn:
    return AssistantTurn(
        tool_calls=[ToolCall(id=f"c{i}", name=name, arguments=args)], usage=Usage(10, 2)
    )


def fresh() -> SessionState:
    return SessionState(messages=[Message(role="user", content="start")])


def make(counter: Counter) -> ToolBox:
    return ToolBox(counter.tools(), state_key=lambda: counter.revision)


def test_stops_at_finish_and_reports_steps() -> None:
    counter = Counter()
    steps: list[dict[str, Any]] = []
    model = ScriptedConverse(tc("look", 1), tc("finish", 2))
    state = run_session(
        model, system="s", state=fresh(), toolbox=make(counter), on_step=steps.append
    )
    assert state.stop_reason == "finished" and state.steps == 2 and state.provider_calls == 2
    assert state.input_tokens == 20 and state.output_tokens == 4
    assert state.messages[0].content == "start"
    assert [s["role"] for s in steps] == ["assistant", "tool", "assistant", "tool"]
    assert steps[1]["tool"] == "look" and steps[1]["summary"] == "look #1"


def test_step_cap() -> None:
    counter = Counter()
    model = ScriptedConverse(*[tc("bump", i) for i in range(5)])
    state = run_session(
        model,
        system="s",
        state=fresh(),
        toolbox=make(counter),
        limits=SessionLimits(max_steps=3),
    )
    assert state.stop_reason == "step_cap" and state.steps == 3


def test_token_cap() -> None:
    counter = Counter()
    model = ScriptedConverse(*[tc("bump", i) for i in range(5)])
    state = run_session(
        model,
        system="s",
        state=fresh(),
        toolbox=make(counter),
        limits=SessionLimits(max_input_tokens=15),
    )
    assert state.stop_reason == "token_cap" and state.steps == 2


def test_text_only_is_nudged_then_stalled() -> None:
    counter = Counter()
    model = ScriptedConverse(AssistantTurn(text="hm"), AssistantTurn(text="still hm"))
    state = run_session(model, system="s", state=fresh(), toolbox=make(counter))
    assert state.stop_reason == "stalled"
    assert [m.role for m in state.messages] == ["user", "assistant", "user", "assistant"]
    assert state.messages[2].content == NUDGE


def test_nudge_resets_after_a_tool_turn() -> None:
    counter = Counter()
    model = ScriptedConverse(
        AssistantTurn(text="hm"), tc("look", 1), AssistantTurn(text="hm"), tc("finish", 2)
    )
    state = run_session(model, system="s", state=fresh(), toolbox=make(counter))
    assert state.stop_reason == "finished"


def test_repeat_guard_and_state_key() -> None:
    counter = Counter()
    model = ScriptedConverse(
        tc("look", 1),
        tc("look", 2),
        tc("look", 3),
        tc("bump", 4),
        tc("look", 5),
        tc("finish", 6),
    )
    state = run_session(model, system="s", state=fresh(), toolbox=make(counter))
    results = {m.tool_call_id: m.content for m in state.messages if m.role == "tool"}
    assert results["c3"].startswith("ERROR: ") and "nothing has changed" in results["c3"]
    assert results["c5"] == "looked 3"  # allowed again after the workspace changed
    assert counter.runs == 3 - 1 + 1


def test_invalid_json_and_unknown_tool_are_error_results() -> None:
    counter = Counter()
    model = ScriptedConverse(
        AssistantTurn(tool_calls=[ToolCall("c1", "look", {"__invalid__": "{oops"})]),
        tc("nope", 2),
        tc("finish", 3),
    )
    state = run_session(model, system="s", state=fresh(), toolbox=make(counter))
    tools = [m.content for m in state.messages if m.role == "tool"]
    assert "not valid JSON: {oops" in tools[0]
    assert "no tool 'nope'" in tools[1] and "look, bump, finish" in tools[1]


def test_compaction_keeps_recent_verbatim_and_is_deterministic() -> None:
    messages = [Message(role="user", content="u")]
    summaries = {}
    for i in range(5):
        messages.append(Message(role="assistant", tool_calls=[ToolCall(f"c{i}", "look", {})]))
        messages.append(Message(role="tool", content=f"full {i}", tool_call_id=f"c{i}"))
        summaries[f"c{i}"] = f"sum {i}"
    out = compact(messages, summaries, 2)
    assert out == compact(messages, summaries, 2)
    tool_contents = [m.content for m in out if m.role == "tool"]
    assert tool_contents[:3] == [f"[earlier result, shortened] sum {i}" for i in range(3)]
    assert tool_contents[3:] == ["full 3", "full 4"]
    assert messages[1].content == "" and messages[2].content == "full 0"  # input untouched
    assert compact(messages[:2], {}, 0)[1:] == messages[1:2]
    assert "(no summary)" in compact(messages, {}, 0)[2].content


def test_transcript_round_trip(tmp_path: Path) -> None:
    counter = Counter()
    log = TranscriptLog(tmp_path / "s" / "t.jsonl")
    model = ScriptedConverse(
        tc("look", 1), AssistantTurn(text="thinking"), tc("nope", 2), tc("finish", 3)
    )
    state = run_session(model, system="s", state=fresh(), toolbox=make(counter), log=log)
    loaded = TranscriptLog.load(log.path)
    # the opening user message was not logged by run_session
    assert loaded.messages == state.messages[1:]
    assert loaded.steps == state.steps and loaded.provider_calls == state.provider_calls
    assert loaded.input_tokens == state.input_tokens
    assert loaded.output_tokens == state.output_tokens
    assert loaded.summaries == state.summaries
    rows = timeline(log.path)
    assert rows[1] == {
        "step": 1,
        "role": "tool",
        "tool": "look",
        "summary": "look #1",
        "error": False,
    }
    assert any(r["error"] for r in rows)
    first = json.loads(log.path.read_text().splitlines()[0])
    assert set(first) == {"message", "summary", "step", "meta"} and "at" in first["meta"]


def test_resumed_session_hits_the_provider_cache(tmp_path: Path) -> None:
    def oa_call(i: int, name: str) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"c{i}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps({"n": i})},
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
        }

    class Transport(httpx.BaseTransport):
        def __init__(self) -> None:
            self.responses = [oa_call(1, "look"), oa_call(2, "bump"), oa_call(3, "finish")]
            self.requests = 0

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            request.read()
            self.requests += 1
            return httpx.Response(200, json=self.responses.pop(0))

    transport = Transport()
    provider = MistralProvider(
        ProviderConfig(
            model="m", api_key="k", transport=transport, cache=ResponseCache(tmp_path)
        )
    )
    log = TranscriptLog(tmp_path / "t.jsonl")
    counter = Counter()
    first = run_session(
        provider,
        system="s",
        state=fresh(),
        toolbox=make(counter),
        log=log,
        limits=SessionLimits(keep_recent_results=1),
    )
    assert first.stop_reason == "finished" and transport.requests == 3

    # Resume: the loaded state compacts exactly as before; replaying the turns from the
    # opening message sends the same requests, all served from the cache.
    loaded = TranscriptLog.load(log.path)
    assert loaded.messages == first.messages[1:]
    replay = run_session(
        provider,
        system="s",
        state=fresh(),
        toolbox=make(Counter()),
        limits=SessionLimits(keep_recent_results=1),
    )
    assert replay.stop_reason == "finished" and transport.requests == 3
    assert replay.messages == first.messages


def test_toolspec_names_unique_and_ordered() -> None:
    assert [s.name for s in make(Counter()).specs] == ["look", "bump", "finish"]
    assert isinstance(make(Counter()).specs[0], ToolSpec)
