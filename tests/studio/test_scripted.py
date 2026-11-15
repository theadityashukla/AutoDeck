"""The scripted stand-in model (implemented in full by the lead) and the prepared script.

Phase 2-3: roles, matching, and `design_flow.json` (which replaced `two_threads.json`)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from autodeck.providers.base import Message, ToolSpec
from autodeck.studio import tool_args
from autodeck.studio.design import DesignDraft
from autodeck.studio.models import Slide
from autodeck.studio.render_adapter import check_slide
from autodeck.studio.scripted import (
    EXHAUSTED_TEXT,
    ScriptedModel,
    load_script,
    scripted_binding,
    scripted_bindings,
)
from autodeck.studio.tool_args import ToolArgs
from autodeck.studio.tools import MECHANIC_TOOL_NAMES, TOOL_NAMES
from tests.studio.helpers import DESIGN_FLOW_SCRIPT, FONTS_AVAILABLE, dev_tokens

SPEC = ToolSpec(name="view_deck", description="d", args_model=ToolArgs)


def test_plays_steps_in_order_and_records_calls() -> None:
    model = ScriptedModel.from_steps(
        [
            {"tool_calls": [{"name": "view_deck", "arguments": {"artifact_id": "d"}}]},
            {"text": "Done."},
        ],
        model_id="scripted/test",
    )
    first = model.converse([Message(role="user", content="hello")], [SPEC], system="sys")
    assert first.text == "" and first.tool_calls[0].name == "view_deck"
    assert first.tool_calls[0].id == "call-001-0"
    assert first.tool_calls[0].arguments == {"artifact_id": "d"}
    second = model.converse([Message(role="user", content="again")], [], system=None)
    assert second.text == "Done." and second.tool_calls == []
    assert model.remaining == 0 and model.overrun == 0
    assert [c.system for c in model.calls] == ["sys", None]
    assert model.calls[0].tool_names == ["view_deck"]
    assert "hello" in model.calls[0].text()


def test_running_out_answers_with_a_note_and_counts_overrun() -> None:
    model = ScriptedModel.from_steps([{"text": "only"}])
    model.converse([Message(role="user", content="a")], [])
    turn = model.converse([Message(role="user", content="b")], [])
    assert turn.text == EXHAUSTED_TEXT and model.overrun == 1


def test_usage_is_deterministic() -> None:
    model = ScriptedModel.from_steps([{"text": "12345678"}])
    turn = model.converse([Message(role="user", content="x" * 40)], [])
    assert (turn.usage.input_tokens, turn.usage.output_tokens) == (10, 2)


def test_a_step_must_do_something() -> None:
    with pytest.raises(ValidationError):
        ScriptedModel.from_steps([{"text": "  "}])
    with pytest.raises(ValueError, match="at least one message"):
        ScriptedModel.from_steps([{"text": "x"}]).converse([], [])


def test_binding_is_the_lead_role_in_the_scripted_env() -> None:
    model = ScriptedModel.from_steps([{"text": "x"}], model_id="scripted/abc")
    bound = scripted_binding(model)
    assert (bound.role, bound.model_id, bound.env) == ("lead", "scripted/abc", "scripted")
    assert bound.model is model


def test_roles_have_their_own_queues_and_model_ids() -> None:
    model = ScriptedModel.from_steps(
        [
            {"label": "r", "role": "router", "text": "lead"},
            {"label": "l", "text": "lead reply"},
            {"label": "d", "role": "designer", "text": "designed"},
        ],
        model_id="scripted/lead",
        model_ids={"designer": "scripted/designer"},
    )
    bindings = scripted_bindings(model)
    msg = [Message(role="user", content="x")]
    assert bindings.designer.model.converse(msg, []).text == "designed"
    assert bindings.lead.model.converse(msg, []).text == "lead reply"
    assert bindings.router.model.converse(msg, []).text == "lead"
    assert bindings.designer.model_id == "scripted/designer"
    assert bindings.router.model_id == "scripted/lead-router"
    assert bindings.lead.model is model and bindings.lead.role == "lead"
    assert [c.role for c in model.calls] == ["designer", "lead", "router"]
    assert bindings.system.model.converse(msg, []).text == EXHAUSTED_TEXT
    assert model.overrun_by_role == {"system": 1} and model.remaining == 0


def test_match_picks_the_step_for_this_call_even_in_parallel() -> None:
    steps = [
        {"label": f"slide {i}", "role": "designer", "match": f"Slide id: s{i}", "text": f"s{i}"}
        for i in (1, 2, 3)
    ]
    model = ScriptedModel.from_steps(steps)
    designer = model.for_role("designer")

    def call(i: int) -> str:
        return designer.converse([Message(role="user", content=f"Slide id: s{i}\n")], []).text

    with ThreadPoolExecutor(3) as pool:
        assert list(pool.map(call, (3, 1, 2))) == ["s3", "s1", "s2"]
    labels = {c.step_label for c in model.calls_for("designer")}
    assert labels == {"slide 1", "slide 2", "slide 3"}


def test_match_also_reads_the_system_prompt() -> None:
    model = ScriptedModel.from_steps(
        [{"role": "system", "match": "Name: Demand curve", "text": "B"}]
    )
    turn = model.for_role("system").converse(
        [Message(role="user", content="x")], [], system="... Name: Demand curve ..."
    )
    assert turn.text == "B"


_ARGS = {
    "create_deck": tool_args.CreateDeckArgs,
    "set_slide_brief": tool_args.SetSlideBriefArgs,
    "compose_slides": tool_args.ComposeSlidesArgs,
    "propose_design": tool_args.ProposeDesignArgs,
    "apply_design": tool_args.ApplyDesignArgs,
    "retitle_slide": tool_args.RetitleSlideArgs,
    "write_slide": tool_args.DesignerWriteArgs,
    "set_palette": tool_args.SetPaletteArgs,
    "route": tool_args.RouteArgs,
}


def test_the_design_flow_script_uses_each_roles_own_tools_with_valid_arguments() -> None:
    script = load_script(DESIGN_FLOW_SCRIPT)
    assert script.model_id == "scripted/lead"
    allowed = {
        "lead": set(TOOL_NAMES),
        "mechanic": set(MECHANIC_TOOL_NAMES),
        "designer": {"write_slide"},
        "system": {"set_palette"},
        "router": {"route"},
    }
    for step in script.steps:
        for call in step.tool_calls:
            assert call.name in allowed[step.role], step.label
            _ARGS[call.name].model_validate(call.arguments)
    # The lead never sends a layout or a colour.
    for step in script.steps:
        if step.role == "lead":
            for call in step.tool_calls:
                assert '"layout"' not in json.dumps(call.arguments), step.label
                assert "#" not in json.dumps(call.arguments), step.label
    assert script.steps[-1].role == "mechanic" and script.steps[-1].text


def test_the_design_flow_palettes_are_well_formed_drafts() -> None:
    script = load_script(DESIGN_FLOW_SCRIPT)
    palettes = [c for s in script.steps for c in s.tool_calls if c.name == "set_palette"]
    assert len(palettes) == 2
    for call in palettes:
        args = tool_args.SetPaletteArgs.model_validate(call.arguments)
        DesignDraft(
            name="x",
            palette=args.palette,
            roles=dict(args.roles),
            background=args.background,
            text_pairs=args.text_pairs,
            made_by="scripted/system",
        )


@pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")
def test_the_design_flow_slides_pass_layout_qa_in_their_palettes() -> None:
    from autodeck.design.theme.tokens import Palette

    script = load_script(DESIGN_FLOW_SCRIPT)
    palettes = {
        step.match: tool_args.SetPaletteArgs.model_validate(c.arguments).palette
        for step in script.steps
        for c in step.tool_calls
        if c.name == "set_palette"
    }
    base = dev_tokens()

    def tokens(palette: object) -> object:
        if palette is None:
            return base
        merged = base.palette.model_dump() | palette.model_dump()  # type: ignore[attr-defined]
        return base.model_copy(update={"palette": Palette.model_validate(merged)})

    dark = palettes["Name: Demand curve"]
    checked = 0
    for step in script.steps:
        if step.role != "designer":
            continue
        data = step.tool_calls[0].arguments["slide"]
        slide = Slide.model_validate(
            {"id": data["id"], "blocks": data["blocks"], "layout": data["layout"]}
        )
        in_dark = data["layout"]["background"] == "lt2"
        palette = (
            dark
            if in_dark
            else (palettes["Name: Itemised"] if "Itemised" in (step.match or "") else None)
        )
        assert check_slide(slide, tokens(palette)) == [], step.label  # type: ignore[arg-type]
        checked += 1
    assert checked == 8
