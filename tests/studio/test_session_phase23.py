"""Task 23.14: the session's Phase 2-3 turn (`session.py`): routing before the turn, the
mechanic and its handoff, the owner's override, and the layer and cost record."""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.studio.conversation import AssistantLine, ToolLine, TurnEndLine
from autodeck.studio.loop import MECHANIC_PREFIX
from autodeck.studio.scripted import ScriptedModel
from autodeck.studio.threads import ThreadStore
from autodeck.studio.usage import Price, Prices
from tests.studio.helpers import CLIENT, PROJECT, load_fixture_deck, make_studio

SWAP = "Swap slides 1 and 3"


def setup(tmp_path: Path, knowledge_root: Path, steps: list[dict], **kw: object):
    model = ScriptedModel.from_steps(
        steps,
        model_id="scripted/lead",
        model_ids={"mechanic": "scripted/mechanic", "router": "scripted/router"},
    )
    studio, bus, _ = make_studio(tmp_path, model, knowledge_root=knowledge_root, **kw)  # type: ignore[arg-type]
    engagement = studio.create_engagement(CLIENT, PROJECT)
    engagement.create_artifact(
        load_fixture_deck().model_copy(update={"client": CLIENT, "project": PROJECT})
    )
    thread = studio.create_thread(engagement)
    return model, studio, bus, engagement, thread


def test_a_small_edit_goes_to_the_mechanic_without_the_lead(
    tmp_path: Path, knowledge_root: Path
) -> None:
    model, studio, bus, engagement, thread = setup(
        tmp_path,
        knowledge_root,
        [
            {
                "role": "mechanic",
                "tool_calls": [
                    {"name": "swap_slides", "arguments": {"first": "s1", "second": "s3"}}
                ],
            },
            {"role": "mechanic", "text": "Slides 1 and 3 are swapped."},
        ],
        roles=True,
        prices=Prices({"scripted/mechanic": Price(3, 15)}),
    )
    finished = studio.run_turn(engagement, thread.id, text=SWAP)
    assert (finished.turn_kind, finished.stop_reason) == ("change", "replied")
    assert finished.model_id == "scripted/mechanic" and finished.steps == 2
    assert finished.route is not None
    assert (finished.route.route, finished.route.by, finished.route.reason) == (
        "mechanic",
        "rule",
        "swap two slides",
    )
    assert finished.usage is not None and finished.usage.roles() == ["mechanic"]
    assert finished.usage.total_cost_usd is not None
    assert model.calls_for("lead") == [] and model.calls_for("router") == []
    mechanic_call = model.calls_for("mechanic")[0]
    assert len(mechanic_call.messages) == 1  # the deck and the message only
    assert mechanic_call.messages[0].content.endswith(f"# The owner's message\n\n{SWAP}")
    assert "hand_to_lead" in mechanic_call.tool_names and "compose_slides" not in (
        mechanic_call.tool_names
    )
    lines = ThreadStore(engagement).read_lines(thread.id)
    assert {line.role for line in lines if isinstance(line, AssistantLine | ToolLine)} == {
        "mechanic"
    }
    end = lines[-1]
    assert isinstance(end, TurnEndLine) and end.route == finished.route
    assert end.usage == finished.usage
    entry = engagement.artifact_store("inference-readout").changelog().entries[-1]
    assert (entry.layer, entry.model_id) == ("mechanics", "scripted/mechanic")
    started = next(p.event for p in bus.replay(f"{CLIENT}/{PROJECT}/{thread.id}"))
    assert started.type == "turn_started" and started.model_id == "scripted/mechanic"


def test_the_mechanic_can_hand_the_turn_to_the_lead(
    tmp_path: Path, knowledge_root: Path
) -> None:
    model, studio, _, engagement, thread = setup(
        tmp_path,
        knowledge_root,
        [
            {
                "role": "mechanic",
                "tool_calls": [
                    {
                        "name": "hand_to_lead",
                        "arguments": {"reason": "the order is an argument"},
                    }
                ],
            },
            {"text": "Swapping them would put the ask last; shall I?"},
        ],
        roles=True,
    )
    finished = studio.run_turn(engagement, thread.id, text=SWAP)
    assert finished.stop_reason == "replied" and finished.model_id == "scripted/lead"
    assert finished.route is not None
    assert (finished.route.route, finished.route.handed_off) == ("mechanic", True)
    assert finished.usage is not None and finished.usage.roles() == ["mechanic", "lead"]
    lead_first = model.calls_for("lead")[0].messages
    assert any(
        m.role == "assistant"
        and m.content.startswith(MECHANIC_PREFIX)
        and "handed to the lead" in m.content
        for m in lead_first
    )
    lines = ThreadStore(engagement).read_lines(thread.id)
    roles = [line.role for line in lines if isinstance(line, AssistantLine)]
    assert roles == ["mechanic", "lead"]


def test_the_owner_can_pin_a_turn_to_the_lead(tmp_path: Path, knowledge_root: Path) -> None:
    model, studio, _, engagement, thread = setup(
        tmp_path, knowledge_root, [{"text": "Done as you asked."}], roles=True
    )
    finished = studio.run_turn(engagement, thread.id, text=SWAP, route="lead")
    assert finished.route is not None
    assert (finished.route.requested, finished.route.by) == ("lead", "override")
    assert model.calls_for("mechanic") == [] and model.calls_for("router") == []


def test_unclear_messages_ask_the_router_and_fall_back_to_the_lead(
    tmp_path: Path, knowledge_root: Path
) -> None:
    model, studio, _, engagement, thread = setup(
        tmp_path,
        knowledge_root,
        [{"role": "router", "text": "hmm"}, {"text": "Here is my view."}],
        roles=True,
    )
    finished = studio.run_turn(engagement, thread.id, text="Make it feel calmer")
    assert finished.route is not None
    assert (finished.route.route, finished.route.by) == ("lead", "fallback")
    assert finished.usage is not None and finished.usage.roles() == ["router", "lead"]
    assert model.calls_for("router")[0].tool_names == ["route"]


def test_the_phase_1_form_routes_by_rule_only(tmp_path: Path, knowledge_root: Path) -> None:
    model, studio, _, engagement, thread = setup(
        tmp_path, knowledge_root, [{"text": "A view."}]
    )
    finished = studio.run_turn(engagement, thread.id, text="Make it feel calmer")
    assert finished.route is not None
    assert (finished.route.by, finished.route.reason) == ("fallback", "no router model")
    assert finished.usage is not None and finished.usage.roles() == ["lead"]
    assert [c.role for c in model.calls] == ["lead"]
    assert finished.usage.total_cost_usd is None  # scripted ids are unpriced here


def test_a_mechanic_error_ends_the_turn_with_a_reason(
    tmp_path: Path, knowledge_root: Path
) -> None:
    class Down:
        def converse(self, messages, tools, *, system=None):
            raise RuntimeError("mechanic down")

    _, studio, _, engagement, thread = setup(
        tmp_path, knowledge_root, [{"text": "x"}], roles=True
    )
    from dataclasses import replace

    studio.bindings = replace(
        studio.bindings, mechanic=replace(studio.bindings.mechanic, model=Down())
    )
    finished = studio.run_turn(engagement, thread.id, text=SWAP)
    assert finished.stop_reason == "error" and finished.error == "RuntimeError: mechanic down"
    assert finished.route is not None and finished.route.route == "mechanic"


def test_construction_needs_exactly_one_of_lead_and_bindings(
    tmp_path: Path, knowledge_root: Path
) -> None:
    from autodeck.studio.session import Studio

    _, studio, _, _, _ = setup(tmp_path, knowledge_root, [{"text": "x"}], roles=True)
    with pytest.raises(ValueError, match="exactly one"):
        Studio(studio.settings, bus=studio.bus, previews=studio.previews)
    assert studio.use_router_model and studio.lead is studio.bindings.lead
