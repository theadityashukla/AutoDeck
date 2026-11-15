"""Task 23.7: the designer (`designer.py`): the bench's loop in the product. Every model
here is the scripted designer; layout QA is real (needs Carlito)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from autodeck.providers.base import AssistantTurn, ToolCall
from autodeck.studio import render_adapter
from autodeck.studio.bindings import BoundModel
from autodeck.studio.design import DesignSystem, default_design_system, design_tokens
from autodeck.studio.designer import (
    ACCEPTED_TEXT,
    FINDINGS_PREFIX,
    NUDGE_TEXT,
    OTHER_WRITE_TEXT,
    REJECTED_PREFIX,
    DesignJob,
    answer_calls,
    conformance_findings,
    design_slide,
    design_slides,
)
from autodeck.studio.models import Slide, brief_digest
from autodeck.studio.scripted import ScriptedModel
from tests.studio.helpers import (
    FONTS_AVAILABLE,
    dev_tokens,
    flow_brief,
    flow_designed,
    flow_draft,
    write_slide_step,
)

pytestmark = pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")


def bound(model: ScriptedModel) -> BoundModel:
    return BoundModel(
        role="designer", model_id="scripted/designer", model=model.for_role("designer"), env="s"
    )


def default_job(slide_id: str = "s2") -> DesignJob:
    system = default_design_system(dev_tokens())
    return DesignJob(slide_id, flow_brief(slide_id), system, design_tokens(None, dev_tokens()))


def dark_job(slide_id: str = "s2") -> DesignJob:
    draft = flow_draft("Demand curve")
    system = DesignSystem(id="demand-curve", version=1, marker="decided", **draft.model_dump())
    return DesignJob(
        slide_id, flow_brief(slide_id), system, design_tokens(draft.palette, dev_tokens())
    )


def slide_args(slide_id: str = "s2", design: str = "default") -> dict[str, Any]:
    return copy.deepcopy(flow_designed(slide_id, design))


def step(arguments: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "role": "designer",
        "tool_calls": [{"name": "write_slide", "arguments": arguments}],
        **extra,
    }


def test_a_clean_slide_in_one_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real = render_adapter.check_slide

    def spy(slide: Slide, tokens: Any) -> Any:
        seen.append(tokens.palette.lt2)
        return real(slide, tokens)

    monkeypatch.setattr(render_adapter, "check_slide", spy)
    model = ScriptedModel.from_steps([write_slide_step("s2", "Demand curve")])
    result = design_slide(bound(model), dark_job())
    assert result.clean and result.error == ""
    assert result.attempt_count == 1 and result.attempts[0].outcome == "clean"
    assert result.slide is not None and result.slide.id == "s2"
    assert (
        result.slide.brief == flow_brief("s2")
        and result.slide.intent == flow_brief("s2").intent
    )
    assert result.slide.composed is None and result.slide.layout is not None
    assert (result.system_id, result.system_version) == ("demand-curve", 1)
    assert result.brief_digest == brief_digest(flow_brief("s2"))
    assert result.model_id == "scripted/designer" and result.input_tokens > 0
    assert seen == ["0F1D30"]  # QA ran in the design system's tokens
    call = model.calls_for("designer")[0]
    assert call.tool_names == ["write_slide"]
    assert call.messages[0].content.startswith("# Slide brief\nSlide id: s2\n")
    assert call.system is not None and "- lt2: #0F1D30" in call.system


def test_findings_go_back_to_the_model_and_a_fix_comes_clean() -> None:
    crowded = slide_args()
    for element in crowded["slide"]["layout"]["elements"]:
        if element.get("block_id") == "hero":
            element["size_pt"] = 240
    model = ScriptedModel.from_steps([step(crowded), write_slide_step("s2")])
    result = design_slide(bound(model), default_job())
    assert result.clean and [a.outcome for a in result.attempts] == ["qa_findings", "clean"]
    assert any("[text_fit] hero" in f for f in result.attempts[0].findings)
    second = model.calls_for("designer")[1].messages
    assert second[-1].role == "tool" and second[-1].content.startswith(FINDINGS_PREFIX)
    assert "hero" in second[-1].content


def test_the_header_must_be_on_the_slide_word_for_word() -> None:
    args = slide_args()
    for block in args["slide"]["blocks"]:
        if block["id"] == "header":
            block["text"] = "Quantisation cuts serving cost"
    model = ScriptedModel.from_steps([step(args)] * 1)
    result = design_slide(bound(model), default_job(), attempts=1)
    assert not result.clean and result.slide is None
    assert result.attempts[0].outcome == "conformance"
    assert result.findings == (
        "[brief] the header must appear word for word in one text block: "
        '"Quantisation alone cuts serving cost by 38%"',
    )


def test_conformance_checks_the_chart_data_and_allows_line_breaks() -> None:
    brief = flow_brief("s2")
    data = slide_args()["slide"]
    for block in data["blocks"]:
        if block["id"] == "header":
            block["text"] = "Quantisation alone cuts\nserving cost by 38%"
    slide = Slide.model_validate(
        {"id": "s2", "blocks": data["blocks"], "layout": data["layout"]}
    )
    assert conformance_findings(slide, brief) == []
    for block in data["blocks"]:
        if block["kind"] == "chart":
            block["chart"]["series"][0]["values"] = [412, 250]
    wrong = Slide.model_validate(
        {"id": "s2", "blocks": data["blocks"], "layout": data["layout"]}
    )
    (finding,) = conformance_findings(wrong, brief)
    assert finding.startswith("[brief] chart chart must use the brief's data exactly")
    no_chart = flow_brief("s3")
    findings = conformance_findings(slide, no_chart.model_copy(update={"header": brief.header}))
    assert findings == ["[brief] chart chart: the brief has no chart data; remove the chart"]


def test_invalid_arguments_are_rejected_with_the_errors() -> None:
    args = slide_args()
    args["slide"]["layout"]["elements"].append(
        copy.deepcopy(args["slide"]["layout"]["elements"][1])
    )
    model = ScriptedModel.from_steps(
        [step(args), step({"__invalid__": "{bad"}), write_slide_step("s2")]
    )
    result = design_slide(bound(model), default_job())
    assert [a.outcome for a in result.attempts] == [
        "validation_error",
        "validation_error",
        "clean",
    ]
    assert result.attempts[0].findings[0].startswith("[validation]")
    messages = model.calls_for("designer")[1].messages
    assert messages[-1].content.startswith(REJECTED_PREFIX)
    assert result.attempts[1].findings == ("[validation] invalid JSON",)


def test_prose_is_nudged_once_then_the_slide_fails() -> None:
    model = ScriptedModel.from_steps(
        [{"role": "designer", "text": "I would use a big number."}] * 2
    )
    result = design_slide(bound(model), default_job())
    assert not result.clean and [a.outcome for a in result.attempts] == [
        "no_tool_call",
        "no_tool_call",
    ]
    assert model.calls_for("designer")[1].messages[-1].content == NUDGE_TEXT
    assert result.findings and result.findings[0].startswith("[no_tool_call]")


def test_attempts_run_out_and_the_last_findings_are_kept() -> None:
    crowded = slide_args()
    for element in crowded["slide"]["layout"]["elements"]:
        if element.get("block_id") == "hero":
            element["size_pt"] = 240
    model = ScriptedModel.from_steps([step(crowded)] * 3)
    result = design_slide(bound(model), default_job(), attempts=3)
    assert not result.clean and result.attempt_count == 3
    assert any("hero" in f for f in result.findings) and len(result.findings) <= 12


def test_a_slide_the_renderer_would_replace_is_a_finding() -> None:
    args = slide_args()
    args["slide"]["blocks"].append(
        {
            "id": "ic",
            "kind": "icon",
            "icon": {"concept": "x", "glyph_id": "no-such-glyph", "color_token": "accent1"},
        }
    )
    args["slide"]["layout"]["elements"].append(
        {"type": "icon", "block_id": "ic", "frame": {"x": 37, "y": 88, "w": 3, "h": 5}}
    )
    model = ScriptedModel.from_steps([step(args)])
    result = design_slide(bound(model), default_job(), attempts=1)
    assert result.attempts[0].outcome == "render"
    assert result.findings[0].startswith("[render] slide:")


def test_a_model_failure_fails_only_that_slide() -> None:
    class Down:
        def converse(self, messages, tools, *, system=None):
            raise RuntimeError("timeout")

    broken = BoundModel(role="designer", model_id="x/y", model=Down(), env="s")
    result = design_slide(broken, default_job())
    assert not result.clean and result.error == "RuntimeError: timeout"
    assert result.findings == ("[error] RuntimeError: timeout",)
    assert result.attempts[0].outcome == "error"


def test_answer_calls() -> None:
    first = ToolCall("a", "write_slide", {})
    turn = AssistantTurn(
        text="", tool_calls=[first, ToolCall("b", "write_slide", {}), ToolCall("c", "zoom", {})]
    )
    answers = answer_calls(turn, first, ACCEPTED_TEXT)
    assert [(m.role, m.tool_call_id, m.content) for m in answers] == [
        ("tool", "a", ACCEPTED_TEXT),
        ("tool", "b", OTHER_WRITE_TEXT),
        ("tool", "c", f"No such tool 'zoom'. {ACCEPTED_TEXT}"),
    ]


def test_slides_are_designed_in_parallel_and_returned_in_job_order() -> None:
    model = ScriptedModel.from_steps(
        [write_slide_step("s3"), write_slide_step("s1"), write_slide_step("s2")]
    )
    jobs = [default_job("s1"), default_job("s2"), default_job("s3")]
    results = design_slides(bound(model), jobs, max_parallel=3)
    assert [r.slide_id for r in results] == ["s1", "s2", "s3"]
    assert all(r.clean for r in results)
    assert design_slides(bound(model), []) == []
