"""The lead loop with the scripted model and stand-in tools: a turn ends on a text reply,
caps stop it, tool errors come back as results, ledger items become events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from autodeck.agents.tools.registry import Tool, ToolBox, ToolError, ToolResult
from autodeck.providers.base import AssistantTurn, Message, ToolCall
from autodeck.studio.bindings import BoundModel
from autodeck.studio.conversation import THREAD_LINE, ThreadLine, TurnEvent
from autodeck.studio.loop import (
    INTERRUPTED_RESULT,
    STALL_NUDGE,
    LoopLimits,
    build_model_messages,
    run_steps,
)
from autodeck.studio.models import ChangeEntry, DiffItem
from autodeck.studio.prompt import CONTEXT_SEPARATOR
from autodeck.studio.scripted import ScriptedModel, scripted_binding
from autodeck.studio.tools import TurnLedger
from tests.studio.helpers import T1


class ToolBug(Exception):
    """Not a RuntimeError, so a NotImplementedError can never satisfy the test."""


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


@dataclass
class Sink:
    assistants: list[dict[str, Any]] = field(default_factory=list)
    tools: list[tuple[int, ToolCall, ToolResult]] = field(default_factory=list)
    events: list[TurnEvent] = field(default_factory=list)

    def assistant(self, **kw: Any) -> None:
        self.assistants.append(kw)

    def tool(self, *, step: int, call: ToolCall, result: ToolResult) -> None:
        self.tools.append((step, call, result))

    def event(self, event: TurnEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]


def _entry() -> ChangeEntry:
    return ChangeEntry(
        id="c0001",
        diff=[DiffItem(path="title", kind="changed", before="a", after="b")],
        instruction="Rename it",
        thread_id="t0001",
        layer="direction",
        model_id="scripted/t",
        created_at=T1,
        before_digest="a" * 64,
        after_digest="b" * 64,
    )


def _toolbox(ledger: TurnLedger) -> ToolBox:
    def look(_: NoArgs) -> ToolResult:
        return ToolResult("the deck", "looked")

    def rename(args: TextArgs) -> ToolResult:
        if not args.text.strip():
            raise ToolError("the title is blank")
        ledger.record_change("deck", _entry())
        return ToolResult("renamed", "renamed the deck")

    def explode(_: NoArgs) -> ToolResult:
        raise ToolBug("bug in a tool")

    return ToolBox(
        [
            Tool("look", "Look.", NoArgs, look),
            Tool("rename", "Rename.", TextArgs, rename),
            Tool("explode", "Bug.", NoArgs, explode),
        ],
        state_key=lambda: ledger.version,
    )


def _run(steps: list[dict[str, Any]], limits: LoopLimits = LoopLimits()):  # noqa: B008
    model = ScriptedModel.from_steps(steps, model_id="scripted/t")
    ledger = TurnLedger()
    sink = Sink()
    messages = [Message(role="user", content="Please")]
    summaries: dict[str, str] = {}
    outcome = run_steps(
        scripted_binding(model),
        system="SYSTEM",
        messages=messages,
        summaries=summaries,
        toolbox=_toolbox(ledger),
        ledger=ledger,
        sink=sink,
        thread_id="t0001",
        turn_id="u0001",
        limits=limits,
    )
    return outcome, sink, messages, summaries, model


def test_a_text_reply_ends_the_turn() -> None:
    outcome, sink, messages, _, model = _run([{"text": "Hello."}])
    assert (outcome.stop_reason, outcome.steps, outcome.final_text) == ("replied", 1, "Hello.")
    assert sink.types() == ["assistant_text"]
    assert [m.role for m in messages] == ["user", "assistant"]
    assert model.calls[0].system == "SYSTEM" and model.calls[0].tool_names == [
        "look",
        "rename",
        "explode",
    ]


def test_tool_calls_then_reply_with_events_in_order() -> None:
    outcome, sink, messages, summaries, _ = _run(
        [
            {
                "text": "Let me look.",
                "tool_calls": [
                    {"name": "look"},
                    {"name": "rename", "arguments": {"text": "New"}},
                ],
            },
            {"text": "Renamed."},
        ]
    )
    assert outcome.stop_reason == "replied" and outcome.steps == 2
    assert sink.types() == [
        "assistant_text",
        "tool_called",
        "tool_finished",
        "tool_called",
        "tool_finished",
        "change_recorded",
        "assistant_text",
    ]
    change = sink.events[5]
    assert change.model_dump()["entry_id"] == "c0001"
    assert change.model_dump()["lines"] == ["~ title: 'a' -> 'b'"]
    assert [m.role for m in messages] == ["user", "assistant", "tool", "tool", "assistant"]
    assert summaries == {"call-001-0": "looked", "call-001-1": "renamed the deck"}
    assert [a["step"] for a in sink.assistants] == [1, 2]
    assert [t[0] for t in sink.tools] == [1, 1]


def test_bad_calls_come_back_as_error_results_and_the_turn_continues() -> None:
    outcome, sink, _, _, _ = _run(
        [
            {"tool_calls": [{"name": "rename", "arguments": {"text": "  "}}]},
            {"tool_calls": [{"name": "rename", "arguments": {"title": "x"}}]},
            {"tool_calls": [{"name": "nope"}]},
            {"text": "Sorry, I could not rename it."},
        ]
    )
    assert outcome.stop_reason == "replied"
    results = [t[2] for t in sink.tools]
    assert all(r.error for r in results)
    assert results[0].text == "ERROR: the title is blank"
    assert "change_recorded" not in sink.types()
    finished = [e for e in sink.events if e.type == "tool_finished"]
    assert all(e.model_dump()["error"] for e in finished)


def test_step_cap() -> None:
    outcome, _, _, _, model = _run(
        [{"tool_calls": [{"name": "look"}]}] * 5, limits=LoopLimits(max_steps=3)
    )
    assert outcome.stop_reason == "step_cap" and outcome.steps == 3 and model.remaining == 2


def test_token_cap() -> None:
    outcome, _, _, _, _ = _run(
        [{"tool_calls": [{"name": "look"}]}] * 3, limits=LoopLimits(max_input_tokens=1)
    )
    assert outcome.stop_reason == "token_cap" and outcome.steps == 1


class EmptyModel:
    """Returns no text and no tool call (a step a script cannot express)."""

    def __init__(self) -> None:
        self.seen: list[list[Message]] = []

    def converse(
        self, messages: list[Message], tools: Any, *, system: Any = None
    ) -> AssistantTurn:
        self.seen.append(list(messages))
        return AssistantTurn()


def test_an_empty_reply_is_nudged_once_then_stalls() -> None:
    empty = EmptyModel()
    ledger = TurnLedger()
    sink = Sink()
    outcome = run_steps(
        BoundModel(role="lead", model_id="m", model=empty, env="test"),
        system="S",
        messages=[Message(role="user", content="Hi")],
        summaries={},
        toolbox=_toolbox(ledger),
        ledger=ledger,
        sink=sink,
        thread_id="t0001",
        turn_id="u0001",
    )
    assert outcome.stop_reason == "stalled" and outcome.steps == 2
    assert empty.seen[1][-1] == Message(role="user", content=STALL_NUDGE)
    assert sink.events == [] and len(sink.assistants) == 2


def test_a_tool_bug_propagates() -> None:
    with pytest.raises(ToolBug, match="bug in a tool"):
        _run([{"tool_calls": [{"name": "explode"}]}, {"text": "never"}])


def test_old_tool_results_are_compacted() -> None:
    _, _, _, _, model = _run(
        [
            {"tool_calls": [{"name": "look"}]},
            {"tool_calls": [{"name": "look"}]},
            {"text": "ok"},
        ],
        limits=LoopLimits(keep_recent_results=1),
    )
    third = model.calls[2].messages
    tool_contents = [m.content for m in third if m.role == "tool"]
    assert tool_contents[0].endswith("looked") and tool_contents[0] != "the deck"
    assert tool_contents[1] == "the deck"


# -- rebuilding a thread's conversation -------------------------------------------------


def _lines(raw: list[dict[str, Any]]) -> list[ThreadLine]:
    return [
        THREAD_LINE.validate_python({**line, "seq": i, "created_at": T1})
        for i, line in enumerate(raw, start=1)
    ]


def test_build_model_messages_merges_user_text_and_notes() -> None:
    lines = _lines(
        [
            {"kind": "user", "turn_id": "u0001", "origin": "context", "text": "CONTEXT"},
            {"kind": "user", "turn_id": "u0001", "origin": "owner", "text": "Build it"},
            {
                "kind": "assistant",
                "turn_id": "u0001",
                "step": 1,
                "tool_calls": [{"id": "k1", "name": "look", "arguments": {}}],
                "model_id": "m",
            },
            {
                "kind": "tool",
                "turn_id": "u0001",
                "step": 1,
                "tool_call_id": "k1",
                "tool_name": "look",
                "text": "the deck",
                "summary": "looked",
            },
            {
                "kind": "assistant",
                "turn_id": "u0001",
                "step": 2,
                "text": "Done.",
                "model_id": "m",
            },
            {
                "kind": "turn_end",
                "turn_id": "u0001",
                "turn_kind": "talk",
                "stop_reason": "replied",
                "model_id": "m",
                "steps": 2,
            },
            {
                "kind": "note",
                "note": "proposal_dismissed",
                "ref": "p0001",
                "text": "Dismissed p0001",
            },
            {"kind": "user", "turn_id": "u0002", "origin": "owner", "text": "Next"},
        ]
    )
    messages, summaries = build_model_messages(lines)
    assert [m.role for m in messages] == ["user", "assistant", "tool", "assistant", "user"]
    assert messages[0].content == f"CONTEXT{CONTEXT_SEPARATOR}Build it"
    assert messages[1].tool_calls == [ToolCall(id="k1", name="look", arguments={})]
    assert messages[2] == Message(role="tool", content="the deck", tool_call_id="k1")
    assert messages[4].content == f"[Note: Dismissed p0001]{CONTEXT_SEPARATOR}Next"
    assert summaries == {"k1": "looked"}


def test_build_model_messages_repairs_interrupted_calls_and_skips_empty_replies() -> None:
    lines = _lines(
        [
            {"kind": "user", "turn_id": "u0001", "origin": "owner", "text": "Go"},
            {"kind": "assistant", "turn_id": "u0001", "step": 1, "model_id": "m"},
            {
                "kind": "assistant",
                "turn_id": "u0001",
                "step": 2,
                "tool_calls": [
                    {"id": "k1", "name": "look", "arguments": {}},
                    {"id": "k2", "name": "rename", "arguments": {"text": "x"}},
                ],
                "model_id": "m",
            },
            {
                "kind": "tool",
                "turn_id": "u0001",
                "step": 2,
                "tool_call_id": "k1",
                "tool_name": "look",
                "text": "the deck",
                "summary": "looked",
            },
            {
                "kind": "turn_end",
                "turn_id": "u0001",
                "turn_kind": "talk",
                "stop_reason": "error",
                "model_id": "m",
                "steps": 2,
                "error": "RuntimeError: boom",
            },
            {"kind": "user", "turn_id": "u0002", "origin": "owner", "text": "Again"},
        ]
    )
    messages, summaries = build_model_messages(lines)
    assert [m.role for m in messages] == ["user", "assistant", "tool", "tool", "user"]
    assert messages[3] == Message(role="tool", content=INTERRUPTED_RESULT, tool_call_id="k2")
    assert summaries == {"k1": "looked", "k2": "rename: interrupted"}
