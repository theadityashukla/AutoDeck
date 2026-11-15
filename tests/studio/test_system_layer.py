"""Task 23.8: the system layer (`system_layer.py`): a direction in words → a checked
palette and roles, with refusals carrying the measured ratios."""

from __future__ import annotations

import copy
from typing import Any

from autodeck.studio.bindings import BoundModel
from autodeck.studio.design import DesignDirection
from autodeck.studio.scripted import ScriptedModel
from autodeck.studio.system_layer import (
    NUDGE_TEXT,
    REFUSED_PREFIX,
    REJECTED_PREFIX,
    make_design,
    make_designs,
    system_user_text,
)
from tests.studio.helpers import flow_brief, flow_directions, flow_palette_args


def direction(name: str = "Demand curve") -> DesignDirection:
    return DesignDirection.model_validate(
        next(d for d in flow_directions() if d["name"] == name)
    )


def bound(model: ScriptedModel) -> BoundModel:
    return BoundModel(
        role="system", model_id="scripted/system", model=model.for_role("system"), env="s"
    )


def palette_step(args: dict[str, Any], match: str | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {
        "role": "system",
        "tool_calls": [{"name": "set_palette", "arguments": args}],
    }
    if match:
        step["match"] = match
    return step


def test_the_user_text_is_exact() -> None:
    text = system_user_text(direction(), [flow_brief("s1"), flow_brief("s2")])
    assert text == (
        "# Design direction\nName: Demand curve\n"
        f"Concept: {direction().concept}\nRules:\n"
        + "".join(f"- {rule}\n" for rule in direction().rules)
        + "\n# What the deck is about\n"
        f"- {flow_brief('s1').header}\n- {flow_brief('s2').header}\n\n"
        "Make this direction concrete and call set_palette."
    )
    assert "(no slides yet)" in system_user_text(direction(), [])


def test_a_good_palette_is_accepted_first_time() -> None:
    model = ScriptedModel.from_steps([palette_step(flow_palette_args("Demand curve"))])
    result = make_design(bound(model), direction(), briefs=[flow_brief("s2")])
    assert result.draft is not None and result.attempts == 1 and result.findings == ()
    assert result.draft.name == "Demand curve" and result.draft.rules == direction().rules
    assert result.draft.palette.lt2 == "0F1D30" and result.draft.background == "lt2"
    assert result.draft.made_by == "scripted/system" and result.model_id == "scripted/system"
    call = model.calls_for("system")[0]
    assert call.tool_names == ["set_palette"] and "contrast" in (call.system or "")
    assert call.messages[0].content.startswith("# Design direction\nName: Demand curve")


def test_a_failing_palette_is_refused_with_the_ratios_and_corrected() -> None:
    bad = copy.deepcopy(flow_palette_args("Demand curve"))
    bad["palette"]["accent1"] = "#2B4466"
    model = ScriptedModel.from_steps(
        [palette_step(bad), palette_step(flow_palette_args("Demand curve"))]
    )
    result = make_design(bound(model), direction())
    assert result.draft is not None and result.attempts == 2
    refusal = model.calls_for("system")[1].messages[-1]
    assert refusal.role == "tool" and refusal.content.startswith(REFUSED_PREFIX)
    assert (
        "- accent1 on lt2: " in refusal.content and "needs 4.5:1 (text pair)" in refusal.content
    )


def test_structural_errors_and_prose_and_running_out() -> None:
    missing_roles = copy.deepcopy(flow_palette_args("Demand curve"))
    missing_roles["roles"] = {"lt2": "night"}
    model = ScriptedModel.from_steps(
        [
            palette_step(missing_roles),
            {"role": "system", "text": "A night-blue palette would suit it."},
            {"role": "system", "text": "Still prose."},
        ]
    )
    result = make_design(bound(model), direction(), attempts=3)
    assert result.draft is None and result.attempts == 3
    calls = model.calls_for("system")
    assert calls[1].messages[-1].content.startswith(REJECTED_PREFIX)
    assert calls[2].messages[-1].content == NUDGE_TEXT
    assert result.findings[0].startswith("[no_tool_call]")


def test_running_out_on_bad_palettes_keeps_the_last_findings() -> None:
    bad = copy.deepcopy(flow_palette_args("Demand curve"))
    bad["palette"]["dk2"] = "#1A2E4A"
    model = ScriptedModel.from_steps([palette_step(bad)] * 2)
    result = make_design(bound(model), direction(), attempts=2)
    assert result.draft is None
    assert any("charts draw labels in dk2" in f for f in result.findings)


def test_a_model_error_is_a_failed_result() -> None:
    class Down:
        def converse(self, messages, tools, *, system=None):
            raise ConnectionError("no route")

    result = make_design(BoundModel("system", "x/y", Down(), "s"), direction())
    assert result.draft is None and result.findings == ("[error] ConnectionError: no route",)


def test_directions_are_made_in_parallel_in_order() -> None:
    model = ScriptedModel.from_steps(
        [
            palette_step(flow_palette_args("Demand curve"), match="Name: Demand curve"),
            palette_step(flow_palette_args("Itemised"), match="Name: Itemised"),
        ]
    )
    results = make_designs(bound(model), [direction("Itemised"), direction("Demand curve")])
    assert [r.direction.name for r in results] == ["Itemised", "Demand curve"]
    assert [r.draft.background for r in results] == ["lt1", "lt2"]  # type: ignore[union-attr]
