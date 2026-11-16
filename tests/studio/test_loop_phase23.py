"""Task 23.13: the loop's Phase 2-3 additions (`loop.py`: folding the mechanic's lines for
the lead, stopping on a handoff, `SlideComposed` events) and the mechanic's one message
(`mechanic.py`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from autodeck.agents.tools.registry import Tool, ToolBox, ToolResult
from autodeck.providers.base import ToolCall
from autodeck.studio.conversation import (
    AssistantLine,
    SlideComposed,
    ThreadLine,
    ToolCallRecord,
    ToolLine,
    TurnEvent,
    UserLine,
)
from autodeck.studio.engagement import create_engagement
from autodeck.studio.loop import (
    MECHANIC_PREFIX,
    build_model_messages,
    fold_mechanic_lines,
    run_steps,
)
from autodeck.studio.mechanic import mechanic_messages, mechanic_request_text
from autodeck.studio.scripted import ScriptedModel, scripted_binding
from autodeck.studio.tools import ComposedSlide, TurnLedger
from autodeck.studio.views import deck_outline
from tests.studio.helpers import CLIENT, PROJECT, T0, T1, load_fixture_deck


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class Sink:
    events: list[TurnEvent] = field(default_factory=list)

    def assistant(self, **kw: Any) -> None:
        pass

    def tool(self, *, step: int, call: ToolCall, result: ToolResult) -> None:
        pass

    def event(self, event: TurnEvent) -> None:
        self.events.append(event)


def mechanic_turn() -> list[ThreadLine]:
    return [
        UserLine(seq=1, created_at=T0, turn_id="u0002", origin="owner", text="Retitle slide 2"),
        AssistantLine(
            seq=2,
            created_at=T0,
            turn_id="u0002",
            role="mechanic",
            step=1,
            model_id="scripted/mechanic",
            tool_calls=[ToolCallRecord(id="m1", name="retitle_slide", arguments={})],
        ),
        ToolLine(
            seq=3,
            created_at=T0,
            turn_id="u0002",
            role="mechanic",
            step=1,
            tool_call_id="m1",
            tool_name="retitle_slide",
            text="Recorded change c0011",
            summary="retitled s2: layout passed",
        ),
        AssistantLine(
            seq=4,
            created_at=T0,
            turn_id="u0002",
            role="mechanic",
            step=2,
            model_id="scripted/mechanic",
            text="Slide 2 is now titled\n'Quantisation cuts the bill by 38%'.",
        ),
    ]


def test_fold_mechanic_lines() -> None:
    lines = mechanic_turn()[1:]
    assert fold_mechanic_lines(lines) == (
        f"{MECHANIC_PREFIX}retitled s2: layout passed | reply: Slide 2 is now titled "
        "'Quantisation cuts the bill by 38%'."
    )
    errored = lines[1].model_copy(update={"error": True, "summary": "retitle_slide: refused"})
    assert fold_mechanic_lines([errored]) == f"{MECHANIC_PREFIX}retitle_slide: refused (error)"
    silent = AssistantLine(
        seq=1, created_at=T0, turn_id="u0001", role="mechanic", step=1, model_id="m"
    )
    assert fold_mechanic_lines([silent]) is None


def test_the_lead_sees_the_mechanics_turn_as_one_line() -> None:
    lines = [
        *mechanic_turn(),
        UserLine(seq=5, created_at=T1, turn_id="u0003", origin="owner", text="Why that word?"),
    ]
    messages, summaries = build_model_messages(lines)
    assert [m.role for m in messages] == ["user", "assistant", "user"]
    assert messages[1].content.startswith(MECHANIC_PREFIX) and messages[1].tool_calls == []
    assert summaries == {}
    # The mechanic's own view (role="mechanic") replays its calls; nothing else changes.
    own, own_summaries = build_model_messages(mechanic_turn(), role="mechanic")
    assert [m.role for m in own] == ["user", "assistant", "tool", "assistant"]
    assert own_summaries == {"m1": "retitled s2: layout passed"}


def test_a_handoff_stops_the_mechanics_steps() -> None:
    ledger = TurnLedger()

    def hand(_: Any) -> ToolResult:
        ledger.handoff = "a new slide is needed"
        return ToolResult("Handed to the lead: a new slide is needed", "handed to the lead")

    box = ToolBox([Tool(name="hand_to_lead", description="d", args_model=NoArgs, run=hand)])
    model = ScriptedModel.from_steps(
        [
            {"tool_calls": [{"name": "hand_to_lead", "arguments": {}}]},
            {"text": "never reached"},
        ]
    )
    from autodeck.providers.base import Message

    outcome = run_steps(
        scripted_binding(model),
        system="S",
        messages=[Message("user", "Add a slide about risks")],
        summaries={},
        toolbox=box,
        ledger=ledger,
        sink=Sink(),
        thread_id="t0001",
        turn_id="u0001",
        stop_when=lambda: ledger.handoff is not None,
    )
    assert outcome.stop_reason == "handed_off" and outcome.steps == 1
    assert model.remaining == 1


def test_composed_slides_stream_as_events() -> None:
    ledger = TurnLedger()

    def compose(_: Any) -> ToolResult:
        ledger.record_composed(
            "pilot-readout",
            ComposedSlide("s2", True, 2, (), "scripted/designer", 12.345, "c0004"),
        )
        return ToolResult("Composed 1 of 1 slides.", "composed 1/1 slides")

    box = ToolBox(
        [Tool(name="compose_slides", description="d", args_model=NoArgs, run=compose)]
    )
    model = ScriptedModel.from_steps(
        [{"tool_calls": [{"name": "compose_slides", "arguments": {}}]}, {"text": "Done."}]
    )
    from autodeck.providers.base import Message

    sink = Sink()
    run_steps(
        scripted_binding(model),
        system="S",
        messages=[Message("user", "go")],
        summaries={},
        toolbox=box,
        ledger=ledger,
        sink=sink,
        thread_id="t0001",
        turn_id="u0001",
    )
    composed = [e for e in sink.events if isinstance(e, SlideComposed)]
    assert len(composed) == 1
    event = composed[0]
    assert (event.slide_id, event.clean, event.attempts, event.seconds) == (
        "s2",
        True,
        2,
        12.35,
    )
    assert event.model_id == "scripted/designer" and event.artifact_id == "pilot-readout"
    assert ledger.touched_artifacts() == ["pilot-readout"]


def test_the_mechanic_gets_only_the_deck_and_the_message(
    knowledge_root: Path, workspace_root: Path
) -> None:
    engagement = create_engagement(
        CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )
    assert mechanic_request_text(engagement, "Swap slides 1 and 2") == (
        "# The deck\n\n(no deck yet)\n\n# The owner's message\n\nSwap slides 1 and 2"
    )
    deck = load_fixture_deck()
    engagement.create_artifact(deck)
    (message,) = mechanic_messages(engagement, "Swap slides 1 and 2")
    assert message.role == "user"
    assert message.content == (
        f"# The deck\n\n{deck_outline(deck)}\n\n# The owner's message\n\nSwap slides 1 and 2"
    )
