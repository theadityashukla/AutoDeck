"""The scripted stand-in model (implemented in full by the lead) and the prepared script."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autodeck.providers.base import Message, ToolSpec
from autodeck.studio.models import Slide
from autodeck.studio.render_adapter import check_slide
from autodeck.studio.scripted import (
    EXHAUSTED_TEXT,
    ScriptedModel,
    load_script,
    scripted_binding,
)
from autodeck.studio.tool_args import ProposeArgs, ToolArgs
from autodeck.studio.tool_args import WriteSlideArgs as _WriteSlideArgs
from autodeck.studio.tools import TOOL_NAMES
from tests.studio.helpers import FONTS_AVAILABLE, TWO_THREADS_SCRIPT, dev_tokens

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


def test_the_prepared_script_uses_only_known_tools_with_valid_arguments() -> None:
    script = load_script(TWO_THREADS_SCRIPT)
    assert script.model_id == "scripted/two-threads"
    for step in script.steps:
        for call in step.tool_calls:
            assert call.name in TOOL_NAMES, step.label
            if call.name == "write_slide":
                _WriteSlideArgs.model_validate(call.arguments)
            if call.name == "propose":
                ProposeArgs.model_validate(call.arguments)
    # Every turn ends with a text-only step.
    assert script.steps[-1].tool_calls == [] and script.steps[-1].text


@pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")
def test_the_prepared_scripts_slides_pass_layout_qa() -> None:
    script = load_script(TWO_THREADS_SCRIPT)
    slides = []
    for step in script.steps:
        for call in step.tool_calls:
            if call.name == "write_slide":
                slides.append(call.arguments["slide"])
            if call.name == "propose":
                slides += [
                    c["slide"] for o in call.arguments["options"] for c in o.get("slides", [])
                ]
    assert len(slides) == 4
    for data in slides:
        assert check_slide(Slide.model_validate(data), dev_tokens()) == []
