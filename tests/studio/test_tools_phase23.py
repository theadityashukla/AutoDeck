"""Task 23.12: the lead's and the mechanic's Phase 2-3 tools through v2's ToolBox, with the
scripted designer and system layer behind them (and `compose.py` doing the orchestration).
Needs Carlito: the designer's layout QA is real."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from autodeck.agents.tools.registry import ToolBox, ToolResult
from autodeck.ir.schema import export_schema
from autodeck.providers.base import ToolCall
from autodeck.studio import designer, tool_args, views
from autodeck.studio.design import DesignSystemStore, PaletteAttempt
from autodeck.studio.engagement import Engagement, create_engagement
from autodeck.studio.models import DeckArtifact, composition_status, effective_system
from autodeck.studio.proposals import ProposalStore
from autodeck.studio.scripted import ScriptedModel, scripted_bindings
from autodeck.studio.sources import SourceLibrary
from autodeck.studio.tools import (
    MECHANIC_TOOL_NAMES,
    RETIRED_TOOL_NAMES,
    TOOL_NAMES,
    ToolContext,
    TurnLedger,
    build_toolbox,
)
from tests.studio.helpers import (
    CLIENT,
    FONTS_AVAILABLE,
    PROJECT,
    T0,
    StepClock,
    dev_tokens,
    flow_brief,
    flow_call,
    flow_designed,
    flow_directions,
    flow_palette_args,
    write_slide_step,
)

pytestmark = pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")

DECK = "pilot-readout"
DARK = "Demand curve"


class Harness:
    def __init__(
        self,
        engagement: Engagement,
        corpus: Path,
        model: ScriptedModel | None,
        *,
        role: str = "lead",
    ) -> None:
        self.engagement = engagement
        self.model = model
        self.ledger = TurnLedger()
        self.ctx = ToolContext(
            engagement=engagement,
            thread_id="t0001",
            turn_id="u0001",
            instruction="Build the deck",
            model_id="scripted/mechanic" if role == "mechanic" else "scripted/lead",
            tokens=dev_tokens(),
            sources=SourceLibrary(engagement, corpus_root=corpus),
            proposals=ProposalStore(engagement),
            ledger=self.ledger,
            clock=StepClock(),
            role=role,
            bindings=scripted_bindings(model) if model is not None else None,
            designer_attempts=2,
        )
        self.box: ToolBox = build_toolbox(self.ctx)
        self.n = 0

    def call(self, tool: str, /, **arguments: Any) -> ToolResult:
        self.n += 1
        return self.box.dispatch(ToolCall(id=f"k{self.n}", name=tool, arguments=arguments))

    def deck(self) -> DeckArtifact:
        return self.engagement.artifact_store(DECK).load()

    def state(self, slide_id: str) -> str:
        deck = self.deck()
        return composition_status(deck.slide(slide_id), effective_system(deck)).state


def designer_model(*extra: dict[str, Any]) -> ScriptedModel:
    return ScriptedModel.from_steps(
        [write_slide_step("s1"), write_slide_step("s2"), write_slide_step("s3"), *extra],
        model_id="scripted/lead",
        model_ids={"designer": "scripted/designer", "system": "scripted/system"},
    )


def harness(
    tmp_path: Path, knowledge_root: Path, model: ScriptedModel | None, *, briefs: bool = True
) -> Harness:
    engagement = create_engagement(
        CLIENT,
        PROJECT,
        knowledge_root=knowledge_root,
        workspace_root=tmp_path / "workspace",
        now=T0,
    )
    h = Harness(engagement, tmp_path / "corpus", model)
    h.call("create_deck", artifact_id=DECK, title="Readout")
    if briefs:
        for sid in ("s1", "s2", "s3"):
            result = h.call("set_slide_brief", slide_id=sid, brief=flow_brief(sid).model_dump())
            assert not result.error, result.text
    return h


def test_the_vocabularies() -> None:
    from autodeck.studio import tool_args

    assert not set(RETIRED_TOOL_NAMES) & set(TOOL_NAMES)
    assert "hand_to_lead" not in TOOL_NAMES and "hand_to_lead" in MECHANIC_TOOL_NAMES
    lead_models = [
        tool_args.SetSlideBriefArgs,
        tool_args.ComposeSlidesArgs,
        tool_args.ProposeDesignArgs,
        tool_args.ApplyDesignArgs,
        tool_args.RetitleSlideArgs,
        tool_args.ProposeBriefsArgs,
    ]
    for model in lead_models:
        schema = json.dumps(export_schema(model, "strict"))
        assert '"layout"' not in schema and '"palette"' not in schema, model.__name__


def test_the_toolboxes_register_in_order(tmp_path: Path, knowledge_root: Path) -> None:
    h = harness(tmp_path, knowledge_root, None, briefs=False)
    assert [s.name for s in h.box.specs] == list(TOOL_NAMES)
    mech = Harness(h.engagement, tmp_path / "corpus", None, role="mechanic")
    assert [s.name for s in mech.box.specs] == list(MECHANIC_TOOL_NAMES)


def test_set_slide_brief_reports_the_slides_state(tmp_path: Path, knowledge_root: Path) -> None:
    h = harness(tmp_path, knowledge_root, None, briefs=False)
    new = h.call("set_slide_brief", slide_id="s2", brief=flow_brief("s2").model_dump())
    assert new.summary == "set brief of s2 (new, position 1)"
    assert new.text.endswith("Slide s2 is not designed yet; call compose_slides to design it.")
    assert h.ledger.changes[-1][1].layer == "direction"
    again = h.call(
        "set_slide_brief",
        slide_id="s2",
        brief={**flow_brief("s2").model_dump(), "notes": "Lead with 38%."},
        position=1,
    )
    assert again.summary == "set brief of s2 (updated, position 1)"


def test_compose_slides_designs_in_parallel_and_records_the_designer(
    tmp_path: Path, knowledge_root: Path
) -> None:
    h = harness(tmp_path, knowledge_root, designer_model())
    result = h.call("compose_slides")
    assert not result.error, result.text
    assert result.summary == "composed 3/3 slides"
    assert result.text.startswith("Composed 3 of 3 slides.\n- s1: clean in 1 attempt")
    entries = [e for _, e in h.ledger.changes][-3:]
    assert [(e.layer, e.model_id) for e in entries] == [
        ("composition", "scripted/designer")
    ] * 3
    assert [e.instruction for e in entries] == ["Build the deck"] * 3
    assert [r.slide_id for _, r in h.ledger.composed] == ["s1", "s2", "s3"]
    assert [h.state(s) for s in ("s1", "s2", "s3")] == ["fresh"] * 3
    assert h.deck().slide("s2").composed.model_id == "scripted/designer"  # type: ignore[union-attr]
    nothing = h.call("compose_slides")
    assert nothing.summary == "nothing to compose" and nothing.text.startswith(
        "Nothing to compose"
    )


def test_a_slide_that_cannot_be_made_clean_is_recorded_and_keeps_its_design(
    tmp_path: Path, knowledge_root: Path
) -> None:
    crowded = copy.deepcopy(flow_designed("s2"))
    for element in crowded["slide"]["layout"]["elements"]:
        if element.get("block_id") == "hero":
            element["size_pt"] = 240
    bad = {
        "role": "designer",
        "match": "Slide id: s2",
        "tool_calls": [{"name": "write_slide", "arguments": crowded}],
    }
    h = harness(tmp_path, knowledge_root, designer_model(bad, bad))
    h.call("compose_slides")
    before = h.deck().slide("s2")
    failed = h.call("compose_slides", slide_ids=["s2"])
    assert not failed.error and failed.summary == "composed 0/1 slides"
    assert "- s2: failed after 2 attempts: [text_fit] hero" in failed.text
    slide = h.deck().slide("s2")
    assert h.state("s2") == "failed" and slide.layout == before.layout
    assert slide.compose_failure is not None and slide.compose_failure.attempts == 2
    assert h.ledger.changes[-1][1].model_id == "scripted/designer"


def test_composition_tools_need_a_designer(tmp_path: Path, knowledge_root: Path) -> None:
    h = harness(tmp_path, knowledge_root, None)
    refused = h.call("compose_slides")
    assert refused.error and "no designer is bound" in refused.text


def design_model(*extra: dict[str, Any]) -> ScriptedModel:
    steps = [
        {
            "role": "system",
            "match": f"Name: {name}",
            "tool_calls": [{"name": "set_palette", "arguments": flow_palette_args(name)}],
        }
        for name in ("Itemised", DARK)
    ]
    samples = [
        {
            "role": "designer",
            "match": "Name: Itemised",
            "tool_calls": [{"name": "write_slide", "arguments": flow_designed("s2")}],
        },
        {
            "role": "designer",
            "match": f"Name: {DARK}",
            "tool_calls": [{"name": "write_slide", "arguments": flow_designed("s2", DARK)}],
        },
    ]
    return designer_model(*steps, *samples, *extra)


def test_propose_design_renders_each_direction_on_real_slides_and_changes_nothing(
    tmp_path: Path, knowledge_root: Path
) -> None:
    h = harness(tmp_path, knowledge_root, design_model())
    h.call("compose_slides")
    before = h.engagement.artifact_store(DECK).current_text()
    result = h.call("propose_design", **flow_call("t1 u2: propose two directions"))
    assert not result.error, result.text
    assert result.summary == "proposed p0001: 2 design directions"
    assert "- A. Itemised: 1 of 1 sample rendered" in result.text
    assert "Some samples failed" not in result.text
    record = ProposalStore(h.engagement).load("p0001")
    assert [o.label for o in record.options] == ["Itemised", DARK]
    option = record.options[1]
    assert option.design is not None and option.design.palette.lt2 == "0F1D30"
    assert option.design.made_by == "scripted/system"
    assert [(c.slide.id, c.replaces) for c in option.candidates] == [("s2", "s2")]
    assert h.engagement.artifact_store(DECK).current_text() == before
    assert DesignSystemStore(h.engagement, base=dev_tokens()).ids() == []
    assert h.ledger.proposals[-1].id == "p0001"


def failing_sample(monkeypatch: pytest.MonkeyPatch, *, slide: str, system: str) -> None:
    """Make the designer's sample of `slide` in the design named `system` fail (the other
    jobs run for real on the scripted designer), as `designer.design_slides` would report it."""
    real = designer.design_slides

    def wrapped(model: Any, jobs: Any, **kw: Any) -> Any:
        jobs = list(jobs)
        bad = {i for i, j in enumerate(jobs) if j.slide_id == slide and j.system.name == system}
        done = iter(real(model, [j for i, j in enumerate(jobs) if i not in bad], **kw))
        out = []
        for i, job in enumerate(jobs):
            if i in bad:
                findings = (
                    "[text_fit] hero: needs 310pt of height, has 200pt",
                    "[overlap] a, b",
                )
                out.append(
                    designer.DesignResult(
                        slide_id=job.slide_id,
                        clean=False,
                        slide=None,
                        attempts=tuple(designer.Attempt(n, "qa_findings") for n in range(1, 5)),
                        findings=findings,
                        input_tokens=0,
                        output_tokens=0,
                        seconds=0.0,
                        model_id="scripted/designer",
                    )
                )
            else:
                out.append(next(done))
        return out

    monkeypatch.setattr(designer, "design_slides", wrapped)


def test_a_failed_design_sample_is_recorded_and_reported(
    tmp_path: Path, knowledge_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extra = {
        "role": "designer",
        "match": f"Name: {DARK}",
        "tool_calls": [{"name": "write_slide", "arguments": flow_designed("s3", DARK)}],
    }
    h = harness(tmp_path, knowledge_root, design_model(extra))
    h.call("compose_slides")
    failing_sample(monkeypatch, slide="s3", system="Itemised")
    args = dict(flow_call("t1 u2: propose two directions"), sample_slide_ids=["s2", "s3"])
    result = h.call("propose_design", **args)
    assert not result.error, result.text
    lines = result.text.split("\n")
    assert lines[0].startswith(
        "Recorded proposal p0001 with 2 design directions, sampled on s2, s3."
    )
    assert lines[1].startswith("Some samples failed: tell the owner")
    assert lines[2] == (
        "- A. Itemised: 1 of 2 samples rendered; slide s3 could not be designed after 4 "
        "attempts: [text_fit] hero: needs 310pt of height, has 200pt; [overlap] a, b. "
        "INCOMPLETE: say so when you present it"
    )
    assert lines[3] == f"- B. {DARK}: 2 of 2 samples rendered"
    record = ProposalStore(h.engagement).load("p0001")
    a, b = record.options
    assert [(o.slide_id, o.clean, o.attempts) for o in a.samples] == [
        ("s2", True, 1),
        ("s3", False, 4),
    ]
    assert a.samples[1].findings == [
        "[text_fit] hero: needs 310pt of height, has 200pt",
        "[overlap] a, b",
    ]
    assert [c.replaces for c in a.candidates] == ["s2"]  # only the clean sample is a preview
    assert all(o.clean for o in b.samples)
    # the view the interface gets says the same
    view = views.proposal_view(record, deck=h.deck())
    assert view["options"][0]["samples_summary"] == (
        "1 of 2 samples rendered; slide 3 could not be designed: "
        "[text_fit] hero: needs 310pt of height, has 200pt"
    )
    assert view["options"][1]["samples_summary"] == "2 of 2 samples rendered"
    assert view["options"][0]["samples"][1]["clean"] is False


def test_a_direction_whose_samples_all_fail_is_dropped_loudly(
    tmp_path: Path, knowledge_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, knowledge_root, design_model())
    h.call("compose_slides")
    failing_sample(monkeypatch, slide="s2", system="Itemised")
    result = h.call("propose_design", **flow_call("t1 u2: propose two directions"))
    assert not result.error, result.text
    assert result.summary == "proposed p0001: 1 design directions"
    assert (
        "- Itemised: dropped (no sample came out clean: slide s2: [text_fit] hero"
        in result.text
    )
    assert "- A. Demand curve: 1 of 1 sample rendered" in result.text
    record = ProposalStore(h.engagement).load("p0001")
    assert [o.label for o in record.options] == [DARK]


def test_when_every_direction_fails_the_call_fails_with_every_reason(
    tmp_path: Path, knowledge_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, knowledge_root, design_model())
    h.call("compose_slides")
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(
        designer,
        "design_slides",
        lambda model, jobs, **kw: (
            asked.extend((j.system.name, j.slide_id) for j in jobs)
            or [
                designer.DesignResult(
                    slide_id=j.slide_id,
                    clean=False,
                    slide=None,
                    attempts=(designer.Attempt(1, "error"),),
                    findings=("[error] boom",),
                    input_tokens=0,
                    output_tokens=0,
                    seconds=0.0,
                    model_id="m",
                )
                for j in jobs
            ]
        ),
    )
    args = {k: v for k, v in flow_call("t1 u2: propose two directions").items()}
    args.pop("sample_slide_ids", None)  # the default: the opening and the chart slide
    result = h.call("propose_design", **args)
    assert result.error and "Itemised: no sample came out clean" in result.text
    assert DARK in result.text
    assert asked == [("Itemised", "s1"), ("Itemised", "s2"), (DARK, "s1"), (DARK, "s2")]


def refused_palette(name: str) -> dict[str, Any]:
    """The scripted palette of `name` with dk2 set to the background: refused (charts draw
    their labels in dk2)."""
    args = copy.deepcopy(flow_palette_args(name))
    args["palette"]["dk2"] = args["palette"][args["background"]]
    return args


def system_step(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "system",
        "match": f"Name: {name}",
        "tool_calls": [{"name": "set_palette", "arguments": args}],
    }


def test_a_palette_retry_is_recorded_and_noted_in_the_tool_results(
    tmp_path: Path, knowledge_root: Path
) -> None:
    steps = [
        system_step("Itemised", flow_palette_args("Itemised")),
        system_step(DARK, refused_palette(DARK)),
        system_step(DARK, flow_palette_args(DARK)),
        {
            "role": "designer",
            "match": "Name: Itemised",
            "tool_calls": [{"name": "write_slide", "arguments": flow_designed("s2")}],
        },
        {
            "role": "designer",
            "match": f"Name: {DARK}",
            "tool_calls": [{"name": "write_slide", "arguments": flow_designed("s2", DARK)}],
        },
    ]
    h = harness(tmp_path, knowledge_root, designer_model(*steps))
    h.call("compose_slides")
    result = h.call("propose_design", **flow_call("t1 u2: propose two directions"))
    assert not result.error, result.text
    b_line = next(line for line in result.text.split("\n") if line.startswith("- B."))
    assert b_line.startswith(f'- B. {DARK}: 1 of 1 sample rendered. Palette for "{DARK}" ')
    assert "needed 2 attempts; refused attempt 1: - dk2 on " in b_line
    assert ":1, needs 4.5:1" in b_line
    assert "Palette for" not in next(
        line for line in result.text.split("\n") if line.startswith("- A.")
    )
    record = ProposalStore(h.engagement).load("p0001")
    attempts = record.options[1].design.palette_attempts  # type: ignore[union-attr]
    assert [(a.attempt, a.accepted) for a in attempts] == [(1, False), (2, True)]
    assert attempts[0].findings and "dk2" in attempts[0].findings[0]
    assert record.options[0].design.palette_attempts == [  # type: ignore[union-attr]
        PaletteAttempt(attempt=1, accepted=True)
    ]
    view = views.proposal_view(record)
    assert view["options"][1]["design"]["palette_attempts"][0]["accepted"] is False
    # adopting it stores the attempts with the version, and apply_design says so too
    applied = h.call("apply_option", proposal_id="p0001", option_id="B")
    assert not applied.error, applied.text
    assert applied.text.split("\n")[-1].startswith(f'Palette for "{DARK}" needed 2 attempts')
    stored = DesignSystemStore(h.engagement, base=dev_tokens()).load("demand-curve", 1)
    assert [a.accepted for a in stored.palette_attempts] == [False, True]
    assert views.design_system_view(stored)["palette_attempts"][0]["findings"]


def test_apply_design_from_words_notes_a_palette_retry(
    tmp_path: Path, knowledge_root: Path
) -> None:
    steps = [
        system_step(DARK, refused_palette(DARK)),
        system_step(DARK, flow_palette_args(DARK)),
    ]
    h = harness(tmp_path, knowledge_root, designer_model(*steps))
    direction = next(d for d in flow_directions() if d["name"] == DARK)
    result = h.call("apply_design", direction=direction)
    assert not result.error, result.text
    assert f'Palette for "{DARK}" needed 2 attempts; refused attempt 1' in result.text


def test_propose_design_defaults_are_two_directions_and_two_samples() -> None:
    props = tool_args.ProposeDesignArgs.model_json_schema()["properties"]
    assert props["directions"]["minItems"] == 2 and props["directions"]["maxItems"] == 3
    assert "Two clearly different" in props["directions"]["description"]
    base = {"summary": "s", "directions": flow_directions()}
    with pytest.raises(ValueError):
        tool_args.ProposeDesignArgs.model_validate({**base, "sample_slide_ids": list("abcd")})
    assert tool_args.ProposeDesignArgs.model_validate({**base}).sample_slide_ids is None
    assert "default two" in props["sample_slide_ids"]["description"]


def test_a_slide_that_failed_and_then_composed_is_reported_as_having_failed(
    tmp_path: Path, knowledge_root: Path
) -> None:
    crowded = copy.deepcopy(flow_designed("s2"))
    for element in crowded["slide"]["layout"]["elements"]:
        if element.get("block_id") == "hero":
            element["size_pt"] = 240
    bad = {
        "role": "designer",
        "match": "Slide id: s2",
        "tool_calls": [{"name": "write_slide", "arguments": crowded}],
    }
    model = ScriptedModel.from_steps(
        [bad, bad, write_slide_step("s2")],
        model_id="scripted/lead",
        model_ids={"designer": "scripted/designer"},
    )
    h = harness(tmp_path, knowledge_root, model)
    first = h.call("compose_slides", slide_ids=["s2"])
    assert "- s2: failed after 2 attempts" in first.text
    assert "FAILED" not in first.text
    again = h.call("compose_slides", slide_ids=["s2"])
    assert (
        "- s2: clean in 1 attempt (it FAILED to compose 1 time earlier this turn" in again.text
    )
    assert h.ledger.composed[-1][1].failed_earlier == 1


def test_apply_design_adopts_it_and_makes_designed_slides_stale(
    tmp_path: Path, knowledge_root: Path
) -> None:
    h = harness(tmp_path, knowledge_root, design_model())
    h.call("compose_slides")
    h.call("propose_design", **flow_call("t1 u2: propose two directions"))
    result = h.call("apply_option", proposal_id="p0001", option_id="B")
    assert not result.error, result.text
    assert result.summary == "adopted design demand-curve v1; 3 slides stale"
    assert result.text.startswith('Adopted the design "Demand curve" (demand-curve v1)')
    assert "Now stale: s1, s2, s3." in result.text
    deck = h.deck()
    assert deck.design_system is not None and deck.design_system.marker == "decided"
    assert deck.design_system.palette.lt2 == "0F1D30"  # type: ignore[union-attr]
    assert [h.state(s) for s in ("s1", "s2", "s3")] == ["stale"] * 3
    assert h.ledger.changes[-1][1].layer == "direction"
    record = ProposalStore(h.engagement).load("p0001")
    assert (record.status, record.chosen, record.resolved_by) == ("accepted", "B", "chat")
    store = DesignSystemStore(h.engagement, base=dev_tokens())
    assert store.versions("demand-curve") == [1]


def test_apply_design_from_words_asks_the_system_layer(
    tmp_path: Path, knowledge_root: Path
) -> None:
    system = {
        "role": "system",
        "match": f"Name: {DARK}",
        "tool_calls": [{"name": "set_palette", "arguments": flow_palette_args(DARK)}],
    }
    h = harness(tmp_path, knowledge_root, designer_model(system))
    direction = next(d for d in flow_directions() if d["name"] == DARK)
    result = h.call("apply_design", direction=direction)
    assert not result.error, result.text
    assert "No slide was designed yet." in result.text
    assert h.deck().design_system.id == "demand-curve"  # type: ignore[union-attr]


def test_retitle_and_text_changes_keep_the_design_or_are_refused(
    tmp_path: Path, knowledge_root: Path
) -> None:
    h = harness(tmp_path, knowledge_root, designer_model())
    h.call("compose_slides")
    ok = h.call("retitle_slide", slide_id="s2", header="Quantisation cuts the bill by 38%")
    assert not ok.error and ok.summary == "retitled s2: layout passed"
    assert h.state("s2") == "fresh"
    assert h.ledger.changes[-1][1].layer == "composition"
    entries = len(h.ledger.changes)
    long = "Quantisation alone cuts the monthly serving cost of the assistant by 38% " * 2
    refused = h.call("retitle_slide", slide_id="s2", header=long.strip()[:160])
    assert refused.error and "does not fit slide s2" in refused.text
    assert len(h.ledger.changes) == entries
    point = h.call("set_block_text", slide_id="s2", block_id="p1", text="8-bit weights, not 16")
    assert not point.error and point.summary == "set text of s2/p1: layout passed"
    assert h.deck().slide("s2").brief.content.points[0] == "8-bit weights, not 16"  # type: ignore[union-attr]


def test_the_mechanics_edits_record_the_mechanics_layer_and_it_can_hand_off(
    tmp_path: Path, knowledge_root: Path
) -> None:
    h = harness(tmp_path, knowledge_root, designer_model())
    h.call("compose_slides")
    mech = Harness(h.engagement, tmp_path / "corpus", None, role="mechanic")
    swapped = mech.call("swap_slides", first="s1", second="s3")
    assert swapped.summary == "swapped slides s1 and s3"
    assert "Slide order now: 1. s3" in swapped.text
    assert mech.ledger.changes[-1][1].layer == "mechanics"
    assert mech.ledger.changes[-1][1].model_id == "scripted/mechanic"
    handed = mech.call("hand_to_lead", reason="the owner wants a new slide")
    assert handed.summary == "handed to the lead: the owner wants a new slide"
    assert mech.ledger.handoff == "the owner wants a new slide"


def test_propose_with_candidate_briefs_composes_them_and_apply_option_applies_them(
    tmp_path: Path, knowledge_root: Path
) -> None:
    candidate = write_slide_step("s1")
    h = harness(tmp_path, knowledge_root, designer_model(candidate))
    h.call("compose_slides")
    brief = {**flow_brief("s1").model_dump(), "notes": "Lead with $2.60."}
    result = h.call(
        "propose",
        summary="Another opening",
        options=[
            {
                "label": "Price first",
                "text": "Open on the new price.",
                "slides": [{"slide_id": "s1", "brief": brief, "replaces": "s1"}],
            },
            {"label": "Keep it", "text": "Keep the current opening."},
        ],
    )
    assert not result.error, result.text
    assert result.summary == "proposed p0001: 2 options"
    record = ProposalStore(h.engagement).load("p0001")
    slide = record.options[0].candidates[0].slide
    assert slide.composed is not None and slide.layout is not None
    applied = h.call("apply_option", proposal_id="p0001", option_id="A")
    assert not applied.error, applied.text
    assert h.deck().slide("s1").brief.notes == "Lead with $2.60."  # type: ignore[union-attr]
    assert h.state("s1") == "fresh"
