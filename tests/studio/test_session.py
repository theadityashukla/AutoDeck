"""The studio: threads open from state, turns run in a fixed order, owner actions between
turns are recorded and told to the model."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from autodeck.providers.base import AssistantTurn, Message
from autodeck.studio.bindings import BoundModel
from autodeck.studio.conversation import (
    AssistantLine,
    NoteLine,
    ToolLine,
    TurnEndLine,
    UserLine,
)
from autodeck.studio.errors import ProposalStateError, TurnInProgressError
from autodeck.studio.prompt import CONTEXT_SEPARATOR, RECAP_REQUEST, system_prompt
from autodeck.studio.proposals import ProposalStore
from autodeck.studio.scripted import ScriptedModel
from autodeck.studio.threads import ThreadStore
from tests.studio.helpers import CLIENT, PROJECT, make_studio

CHANNEL = f"{CLIENT}/{PROJECT}/t0001"  # events.channel_key, spelled out (pinned in test_events)


def _types(bus: Any, channel: str = CHANNEL) -> list[str]:
    return [p.event.type for p in bus.replay(channel)]


def test_a_fresh_thread_runs_nothing(tmp_path: Path, knowledge_root: Path) -> None:
    model = ScriptedModel.from_steps([{"text": "unused"}])
    studio, bus, _ = make_studio(tmp_path, model, knowledge_root=knowledge_root)
    engagement = studio.create_engagement(CLIENT, PROJECT)
    record, recap = studio.open_thread(engagement, title="First")
    assert record.id == "t0001" and record.opening == "fresh" and record.title == "First"
    assert recap is None and model.calls == [] and bus.replay(CHANNEL) == []
    assert ThreadStore(engagement).read_lines("t0001") == []
    assert record.model_id == "scripted"


def test_a_talk_turn_writes_lines_and_events_in_order(
    tmp_path: Path, knowledge_root: Path
) -> None:
    model = ScriptedModel.from_steps(
        [{"tool_calls": [{"name": "list_sources"}]}, {"text": "There are four sources."}]
    )
    studio, bus, _ = make_studio(tmp_path, model, knowledge_root=knowledge_root)
    engagement = studio.create_engagement(CLIENT, PROJECT)
    studio.open_thread(engagement)
    finished = studio.run_turn(engagement, "t0001", text="What can you read?")
    assert (finished.turn_kind, finished.stop_reason, finished.steps) == ("talk", "replied", 2)
    lines = ThreadStore(engagement).read_lines("t0001")
    assert [type(line).__name__ for line in lines] == [
        "UserLine",
        "UserLine",
        "AssistantLine",
        "ToolLine",
        "AssistantLine",
        "TurnEndLine",
    ]
    context, owner = lines[0], lines[1]
    assert isinstance(context, UserLine) and context.origin == "context"
    assert context.text == ThreadStore(engagement).context_text("t0001")
    assert isinstance(owner, UserLine) and owner.text == "What can you read?"
    assert {line.turn_id for line in lines if not isinstance(line, NoteLine)} == {"u0001"}
    assistant = lines[2]
    assert isinstance(assistant, AssistantLine) and assistant.model_id == "scripted"
    tool = lines[3]
    assert isinstance(tool, ToolLine) and tool.summary == "4 sources" and not tool.error
    end = lines[5]
    assert isinstance(end, TurnEndLine) and end.turn_kind == "talk"
    assert _types(bus) == [
        "turn_started",
        "tool_called",
        "tool_finished",
        "assistant_text",
        "turn_finished",
    ]
    sent = model.calls[0].messages
    assert len(sent) == 1 and sent[0].role == "user"
    assert sent[0].content == f"{context.text}{CONTEXT_SEPARATOR}What can you read?"
    assert model.calls[0].system == system_prompt()


def test_a_change_turn_requests_previews_after_it_finishes(
    tmp_path: Path, knowledge_root: Path
) -> None:
    model = ScriptedModel.from_steps(
        [
            {"tool_calls": [{"name": "create_deck", "arguments": {"artifact_id": "deck"}}]},
            {"tool_calls": [{"name": "set_brief", "arguments": {"audience": "Board"}}]},
            {"text": "Started."},
        ]
    )
    studio, bus, renderer = make_studio(tmp_path, model, knowledge_root=knowledge_root)
    engagement = studio.create_engagement(CLIENT, PROJECT)
    studio.open_thread(engagement)
    finished = studio.run_turn(engagement, "t0001", text="Start a deck for the board")
    assert finished.turn_kind == "change" and finished.change_ids == ["c0001"]
    assert finished.created_artifacts == ["deck"]
    assert _types(bus) == [
        "turn_started",
        "tool_called",
        "tool_finished",
        "artifact_created",
        "tool_called",
        "tool_finished",
        "change_recorded",
        "assistant_text",
        "turn_finished",
        "previews_ready",
    ]
    entry = engagement.artifact_store("deck").changelog().entries[0]
    assert (entry.instruction, entry.thread_id, entry.model_id, entry.layer) == (
        "Start a deck for the board",
        "t0001",
        "scripted",
        "direction",
    )
    assert len(renderer.calls) == 1  # type: ignore[attr-defined]


def test_a_returning_thread_opens_with_a_recap(tmp_path: Path, knowledge_root: Path) -> None:
    model = ScriptedModel.from_steps(
        [
            {"tool_calls": [{"name": "create_deck", "arguments": {"artifact_id": "deck"}}]},
            {"text": "Created."},
            {"text": "Recap: one empty deck."},
        ]
    )
    studio, bus, _ = make_studio(tmp_path, model, knowledge_root=knowledge_root)
    engagement = studio.create_engagement(CLIENT, PROJECT)
    studio.open_thread(engagement)
    studio.run_turn(engagement, "t0001", text="Make a deck")
    record, recap = studio.open_thread(engagement)
    assert record.id == "t0002" and record.opening == "returning"
    assert recap is not None and recap.turn_kind == "talk"
    lines = ThreadStore(engagement).read_lines("t0002")
    assert isinstance(lines[1], UserLine) and lines[1].origin == "recap"
    assert lines[1].text == RECAP_REQUEST
    started = bus.replay(f"{CLIENT}/{PROJECT}/t0002")[0].event
    assert started.type == "turn_started" and started.model_dump()["text"] == ""


class FailingModel:
    def converse(
        self, messages: list[Message], tools: Any, *, system: Any = None
    ) -> AssistantTurn:
        raise RuntimeError("provider down")


def test_an_error_ends_the_turn_with_a_reason(tmp_path: Path, knowledge_root: Path) -> None:
    studio, bus, _ = make_studio(
        tmp_path, ScriptedModel.from_steps([{"text": "x"}]), knowledge_root=knowledge_root
    )
    studio.lead = BoundModel(role="lead", model_id="broken", model=FailingModel(), env="test")
    engagement = studio.create_engagement(CLIENT, PROJECT)
    studio.open_thread(engagement)
    finished = studio.run_turn(engagement, "t0001", text="Hello")
    assert finished.stop_reason == "error" and finished.error == "RuntimeError: provider down"
    end = ThreadStore(engagement).read_lines("t0001")[-1]
    assert isinstance(end, TurnEndLine) and end.stop_reason == "error"
    assert _types(bus)[-1] == "turn_finished"
    # The engagement is free again.
    studio.lead = BoundModel(
        role="lead",
        model_id="scripted",
        model=ScriptedModel.from_steps([{"text": "Back."}]),
        env="test",
    )
    assert studio.run_turn(engagement, "t0001", text="Again").stop_reason == "replied"


class BlockingModel:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def converse(
        self, messages: list[Message], tools: Any, *, system: Any = None
    ) -> AssistantTurn:
        self.entered.set()
        self.release.wait(10)
        return AssistantTurn(text="Done.")


def test_one_turn_at_a_time_per_engagement(tmp_path: Path, knowledge_root: Path) -> None:
    blocking = BlockingModel()
    studio, bus, _ = make_studio(
        tmp_path, ScriptedModel.from_steps([{"text": "x"}]), knowledge_root=knowledge_root
    )
    studio.lead = BoundModel(role="lead", model_id="blocking", model=blocking, env="test")
    engagement = studio.create_engagement(CLIENT, PROJECT)
    studio.open_thread(engagement)
    turn_id = studio.begin_turn(engagement, "t0001", text="Slow one")
    assert turn_id == "u0001"
    assert blocking.entered.wait(5)
    assert studio.running_turn(engagement) == "t0001/u0001"
    with pytest.raises(TurnInProgressError):
        studio.run_turn(engagement, "t0001", text="Second")
    with pytest.raises(TurnInProgressError):
        studio.create_thread(engagement)
    blocking.release.set()
    for _ in range(100):
        if "turn_finished" in _types(bus):
            break
        threading.Event().wait(0.05)
    assert "turn_finished" in _types(bus)
    for _ in range(100):
        if studio.running_turn(engagement) is None:
            break
        threading.Event().wait(0.05)
    assert studio.running_turn(engagement) is None


def _proposing_studio(tmp_path: Path, knowledge_root: Path, extra: list[dict[str, Any]]):
    model = ScriptedModel.from_steps(
        [
            {"tool_calls": [{"name": "create_deck", "arguments": {"artifact_id": "deck"}}]},
            {
                "tool_calls": [
                    {
                        "name": "propose",
                        "arguments": {
                            "summary": "Two tones",
                            "options": [
                                {"label": "Plain", "text": "Plain words."},
                                {"label": "Bold", "text": "Bold words."},
                            ],
                        },
                    }
                ]
            },
            {"text": "Two tones to choose from."},
            *extra,
        ]
    )
    studio, bus, _ = make_studio(tmp_path, model, knowledge_root=knowledge_root)
    engagement = studio.create_engagement(CLIENT, PROJECT)
    studio.open_thread(engagement)
    finished = studio.run_turn(engagement, "t0001", text="Which tone?")
    assert finished.proposal_ids == ["p0001"] and finished.turn_kind == "change"
    return studio, bus, engagement, model


def test_dismissal_is_recorded_and_told_to_the_model_next_turn(
    tmp_path: Path, knowledge_root: Path
) -> None:
    studio, bus, engagement, model = _proposing_studio(
        tmp_path, knowledge_root, [{"text": "Understood."}]
    )
    record = studio.dismiss_proposal(engagement, "t0001", "p0001")
    assert record.status == "dismissed" and record.resolved_by == "owner"
    note = ThreadStore(engagement).read_lines("t0001")[-1]
    assert isinstance(note, NoteLine) and note.note == "proposal_dismissed"
    assert note.text == "The owner dismissed proposal p0001: Two tones"
    assert _types(bus)[-1] == "proposal_resolved"
    finished = studio.run_turn(engagement, "t0001", text="Keep it as is")
    assert finished.turn_kind == "talk"
    last_user = model.calls[-1].messages[-1]
    assert last_user.role == "user"
    assert last_user.content == (
        f"[Note: The owner dismissed proposal p0001: Two tones]{CONTEXT_SEPARATOR}Keep it as is"
    )
    with pytest.raises(ProposalStateError):
        studio.dismiss_proposal(engagement, "t0001", "p0001")


def test_picking_an_option_accepts_it_and_sends_the_choice(
    tmp_path: Path, knowledge_root: Path
) -> None:
    studio, bus, engagement, model = _proposing_studio(
        tmp_path, knowledge_root, [{"text": "Plain it is."}]
    )
    finished = studio.pick_option(engagement, "t0001", "p0001", "A")
    assert finished.turn_kind == "talk"
    record = ProposalStore(engagement).load("p0001")
    assert (record.status, record.chosen, record.resolved_by) == ("accepted", "A", "owner")
    choice = [
        line
        for line in ThreadStore(engagement).read_lines("t0001")
        if isinstance(line, UserLine)
    ][-1]
    assert choice.origin == "choice" and choice.text == "I pick option A of p0001: Plain."
    assert model.calls[-1].messages[-1].content == "I pick option A of p0001: Plain."
    types = _types(bus)
    assert (
        types.index("proposal_resolved")
        < len(types) - types[::-1].index("turn_started") - 1 + 1
    )


def test_owner_undo_and_redo_are_noted_for_the_thread(
    tmp_path: Path, knowledge_root: Path
) -> None:
    model = ScriptedModel.from_steps(
        [
            {"tool_calls": [{"name": "create_deck", "arguments": {"artifact_id": "deck"}}]},
            {"tool_calls": [{"name": "set_brief", "arguments": {"goal": "Approve"}}]},
            {"text": "Set."},
        ]
    )
    studio, bus, _ = make_studio(tmp_path, model, knowledge_root=knowledge_root)
    engagement = studio.create_engagement(CLIENT, PROJECT)
    studio.open_thread(engagement)
    studio.run_turn(engagement, "t0001", text="Set the goal")
    undone = studio.owner_undo(engagement, "deck", thread_id="t0001")
    assert undone.id == "c0001" and undone.undone
    note = ThreadStore(engagement).read_lines("t0001")[-1]
    assert isinstance(note, NoteLine) and note.note == "owner_undo" and note.ref == "c0001"
    assert note.text == "The owner undid c0001 on deck: Set the goal"
    assert _types(bus)[-2:] == ["change_reverted", "previews_ready"]
    redone = studio.owner_redo(engagement, "deck")
    assert not redone.undone
    assert engagement.artifact_store("deck").changelog().head == "c0001"
