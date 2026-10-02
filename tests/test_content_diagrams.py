"""B37: the content writer authors process-flow diagrams, and A5 fences their labels."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from autodeck.agents.content import (
    ContentDraft,
    ProposedBlock,
    ProposedChart,
    ProposedChartSeries,
    ProposedCitation,
    ProposedClaim,
    ProposedDiagram,
    ProposedStep,
    write_slide,
)
from autodeck.audit.framing_linter import lint_framing
from autodeck.ir.models import (
    Block,
    Deck,
    DiagramSpec,
    LabelFraming,
    LabelReason,
    ProcessFlowSpec,
    ProcessStep,
    Slide,
)
from autodeck.pipeline.orchestrator import assess_render_safety
from autodeck.retrieval.hybrid import build_index
from tests.test_content import (
    PROMPT,
    QUOTE,
    Scripted,
    brief,
    context,
    draft_with,
    element,
    slide,
    store_with,
    tokens_for,
)


def framed_step(step_id: str, order: int, label: str, **overrides) -> ProposedStep:  # type: ignore[no-untyped-def]
    payload: dict[str, object] = {
        "id": step_id,
        "order": order,
        "label": label,
        "status": "framing",
        "framing_reason": "stage_name",
    }
    payload.update(overrides)
    return ProposedStep(**payload)  # type: ignore[arg-type]


def claim_step(
    step_id: str = "n2",
    order: int = 2,
    label: str = "Halve memory",
    *,
    quote: str = QUOTE,
    **overrides,  # type: ignore[no-untyped-def]
) -> ProposedStep:
    payload: dict[str, object] = {
        "id": step_id,
        "order": order,
        "label": label,
        "status": "claim",
        "framing_reason": "",
        "claim": ProposedClaim(
            text="Quantisation cuts the memory needed for inference by half.",
            citations=[ProposedCitation(doc_id="paper-1", quote=quote)],
        ),
    }
    payload.update(overrides)
    return ProposedStep(**payload)  # type: ignore[arg-type]


def diagram_block(*steps: ProposedStep, block_id: str = "d1", title: str = "") -> ProposedBlock:
    return ProposedBlock(
        id=block_id,
        kind="diagram",
        slot="diagram",
        diagram=ProposedDiagram(relationship="sequence", title=title, steps=list(steps)),
    )


def headline_block() -> ProposedBlock:
    return ProposedBlock(
        id="h1", kind="framing", slot="headline", text="Serve better before you buy more."
    )


def chart_block(block_id: str = "c1", title: str = "Memory Usage") -> ProposedBlock:
    return ProposedBlock(
        id=block_id,
        kind="chart",
        slot="chart",
        chart=ProposedChart(
            chart_type="bar",
            title=title,
            categories=["FP16", "INT8"],
            series=[ProposedChartSeries(name="Memory (GB)", values=[26.0, 13.0])],
            source_citations=[ProposedCitation(doc_id="paper-1", quote=QUOTE)],
        ),
    )


def three_steps() -> list[ProposedStep]:
    return [framed_step("n1", 1, "Profile"), claim_step(), framed_step("n3", 3, "Scale")]


def run(tmp_path: Path, draft: ContentDraft, *, component: str = "closing_cta"):  # type: ignore[no-untyped-def]
    store = store_with(tmp_path, element("e1", QUOTE, page=4))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(draft)
    result = write_slide(
        slide(component=component),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )
    return result, model


def test_a_proposed_flow_with_cited_and_framed_steps_resolves_to_a_diagram_block(
    tmp_path: Path,
) -> None:
    """Steps: one `claim` (quote resolves), two `framing` (stage_name) → a `Block(kind=
    "diagram")` whose ProcessFlowSpec has the three steps in order, the claim's citation
    resolved to the real span, `transition` '' → None."""
    result, _ = run(tmp_path, draft_with(diagram_block(*three_steps())))

    assert not result.rejections
    [block] = result.blocks
    assert block.kind == "diagram"
    assert block.diagram is not None
    assert block.diagram.kind == "process_flow"
    assert block.diagram.relationship == "sequence"
    assert block.diagram.title is None
    steps = block.diagram.payload_as(ProcessFlowSpec).steps_in_order()
    assert [(s.id, s.order, s.label) for s in steps] == [
        ("n1", 1, "Profile"),
        ("n2", 2, "Halve memory"),
        ("n3", 3, "Scale"),
    ]
    assert all(s.transition is None for s in steps)
    assert steps[0].framing == LabelFraming(reason="stage_name")
    assert steps[0].claim is None
    claimed = steps[1]
    assert claimed.framing is None
    assert claimed.claim is not None
    [citation] = claimed.claim.citations
    assert citation.page == 4  # the store's page, not anything the model typed
    assert citation.quote == QUOTE
    assert citation.retrieved_by == "writer"


def test_one_unresolvable_step_drops_the_whole_diagram_with_a_reason(tmp_path: Path) -> None:
    """A claim step whose quote does not resolve → no diagram block; `rejections` names the
    block and the step. No partial flow is ever produced."""
    steps = [
        framed_step("n1", 1, "Profile"),
        claim_step(quote="LLM.int8() halves memory usage."),
        framed_step("n3", 3, "Scale"),
    ]
    result, _ = run(tmp_path, draft_with(diagram_block(*steps)))

    assert result.blocks == []
    [rejection] = result.rejections
    assert "'d1'" in rejection
    assert "step 'n2'" in rejection
    assert "whole diagram" in rejection


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (claim_step(claim=None), "status='claim' with no claim payload"),
        (
            claim_step(framing_reason="stage_name"),
            "status='claim' but framing_reason='stage_name'",
        ),
        (
            framed_step("n2", 2, "Pilot", framing_reason=""),
            "status='framing' with no framing_reason",
        ),
        (
            framed_step(
                "n2",
                2,
                "Pilot",
                claim=ProposedClaim(
                    text="x", citations=[ProposedCitation(doc_id="paper-1", quote=QUOTE)]
                ),
            ),
            "status='framing' but a claim was supplied",
        ),
    ],
    ids=[
        "claim-without-claim",
        "claim-with-reason",
        "framing-without-reason",
        "framing-with-claim",
    ],
)
def test_status_and_payload_must_agree(
    tmp_path: Path, step: ProposedStep, expected: str
) -> None:
    """status='claim' without claim; status='framing' with framing_reason ''; status=
    'framing' with a claim → each drops the block with a reason."""
    steps = [framed_step("n1", 1, "Profile"), step, framed_step("n3", 3, "Scale")]
    result, _ = run(tmp_path, draft_with(diagram_block(*steps)))

    assert result.blocks == []
    [rejection] = result.rejections
    assert "step 'n2'" in rejection
    assert expected in rejection


def test_non_contiguous_orders_drop_the_block_via_the_ir_validator(tmp_path: Path) -> None:
    steps = [framed_step("n1", 1, "Profile"), framed_step("n2", 3, "Scale")]
    result, _ = run(tmp_path, draft_with(diagram_block(*steps)))

    assert result.blocks == []
    [rejection] = result.rejections
    assert "failed IR validation" in rejection
    assert "step orders" in rejection


def test_a_label_over_the_geometry_word_budget_drops_the_block(tmp_path: Path) -> None:
    """The label budget is the geometry's, enforced by `DiagramSpec` — one check, not two."""
    steps = [
        framed_step("n1", 1, "Profile the whole workload first"),
        framed_step("n2", 2, "Scale"),
    ]
    result, _ = run(tmp_path, draft_with(diagram_block(*steps)))

    assert result.blocks == []
    [rejection] = result.rejections
    assert "word budget" in rejection
    assert "node n1" in rejection


@pytest.mark.parametrize("component", ["framework_diagram", "timeline"])
def test_write_slide_fills_a_framework_diagram_and_a_timeline_slot(
    tmp_path: Path, component: str
) -> None:
    """A scripted ContentModel returning a diagram block for each component's diagram slot →
    `write_slide` returns it, budgets checked, no incomplete_slots for `diagram`."""
    result, model = run(
        tmp_path,
        draft_with(headline_block(), diagram_block(*three_steps())),
        component=component,
    )

    assert not result.rejections
    assert result.budgets_checked
    assert result.incomplete_slots == []
    assert sorted(b.kind for b in result.blocks) == ["diagram", "framing"]
    # The writer is told the geometry's label budget for the slot it must fill.
    assert "diagram: ONE block of kind 'diagram'" in model.prompts[0]
    assert "at most 4 words" in model.prompts[0]


def test_a_component_that_takes_a_diagram_reports_it_missing_when_none_survives(
    tmp_path: Path,
) -> None:
    """The catalog's text table cannot see an absent diagram; the writer-side check does, so
    the gap surfaces as `incomplete_slots` (as any required slot does), not at render."""
    steps = [framed_step("n1", 1, "Profile"), claim_step(quote="not a real quote")]
    result, _ = run(
        tmp_path, draft_with(headline_block(), diagram_block(*steps)), component="timeline"
    )

    assert [b.kind for b in result.blocks] == ["framing"]
    assert len(result.rejections) == 1
    assert result.incomplete_slots == ["timeline.diagram: required slot is missing or empty"]


# ---------------------------------------------------------------------------
# Chart slots — same principle as diagram slots
# ---------------------------------------------------------------------------


def test_write_slide_fills_a_chart_focus_slot(tmp_path: Path) -> None:
    """A scripted ContentModel returning a chart block for `chart_focus`'s chart slot →
    `write_slide` returns it, budgets checked, no incomplete_slots for `chart`."""
    result, model = run(
        tmp_path, draft_with(headline_block(), chart_block()), component="chart_focus"
    )

    assert not result.rejections
    assert result.budgets_checked
    assert result.incomplete_slots == []
    assert sorted(b.kind for b in result.blocks) == ["chart", "framing"]
    # The writer is told a chart is required for this slot.
    assert "chart: ONE block of kind 'chart'" in model.prompts[0]


def test_a_component_that_takes_a_chart_reports_it_missing_when_none_survives(
    tmp_path: Path,
) -> None:
    """The catalog's text table cannot see an absent chart; the writer-side check does, so
    the gap surfaces as `incomplete_slots` (as any required slot does), not at render."""
    result, _ = run(tmp_path, draft_with(headline_block()), component="chart_focus")

    assert [b.kind for b in result.blocks] == ["framing"]
    assert result.incomplete_slots == ["chart_focus.chart: required slot is missing or empty"]


def flow_deck(*, labels: list[str], title: str = "", transition: str | None = None) -> Deck:
    steps = [
        ProcessStep(
            id=f"n{i}",
            order=i,
            label=label,
            transition=transition if i == 1 else None,
            framing=LabelFraming(reason="category_name"),
        )
        for i, label in enumerate(labels, start=1)
    ]
    diagram = DiagramSpec(
        relationship="sequence",
        kind="process_flow",
        title=title or None,
        process_flow=ProcessFlowSpec(steps=steps),
    )
    return Deck(
        run_id="r1",
        project="p",
        client="northwind-retail",
        audience="CTO",
        version=1,
        theme_ref="t",
        component_lib_version="1",
        slides=[
            Slide(
                id="s1",
                narrative_role="position",
                component="timeline",
                blocks=[Block(id="d1", kind="diagram", slot="diagram", diagram=diagram)],
            )
        ],
    )


def test_a5_fences_diagram_labels_titles_and_transitions() -> None:
    """A framed step label "40% cheaper than Oracle" (category_name), a title with a
    superlative, and a transition with a number → each is a blocking demotion of that
    diagram block in `lint_framing`, and `assess_render_safety` blocks the render."""
    cases = {
        "node n1": flow_deck(labels=["40% cheaper than Oracle", "Pilot"]),
        "title": flow_deck(labels=["Pilot", "Scale"], title="The best-proven approach"),
        "step n1 transition": flow_deck(labels=["Pilot", "Scale"], transition="in 3 weeks"),
    }
    for site, deck in cases.items():
        report = lint_framing(deck)
        assert report.blocks_build, site
        [demotion] = report.demotions
        assert (demotion.slide_id, demotion.block_id, demotion.from_kind) == (
            "s1",
            "d1",
            "diagram",
        )
        assert demotion.sites == (site,)
        assert report.blocking, site
        assert all(f.location == f"slide s1 block d1 {site}" for f in demotion.reasons)

        safety = assess_render_safety(deck)
        assert not safety.safe, site
        assert any(
            reason.startswith("A5 slide s1 block d1:") and site in reason
            for reason in safety.reasons
        ), safety.reasons


def test_clean_framed_labels_pass_a5() -> None:
    """ "Discovery", "Pilot", "Scale" as stage_name labels → no findings;
    `text_blocks_checked` counts the diagram once."""
    deck = flow_deck(labels=["Discovery", "Pilot", "Scale"])
    report = lint_framing(deck)

    assert report.demotions == []
    assert not report.blocks_build
    assert report.text_blocks_checked == 1
    assert assess_render_safety(deck).framing.demotions == []


def test_the_prompt_file_documents_the_diagram_schema() -> None:
    """`prompts/content.md` mentions `kind: "diagram"`, `status`, `framing_reason` and the
    five LabelReason values — so the prompt and the schema cannot silently drift."""
    prompt = PROMPT.read_text(encoding="utf-8")

    assert 'kind: "diagram"' in prompt
    assert "`status`" in prompt
    assert "framing_reason" in prompt
    for reason in get_args(LabelReason):
        assert reason in prompt


# ---------------------------------------------------------------------------
# End to end: an outline that chooses a diagram component now yields a diagram
# ---------------------------------------------------------------------------


class _PerSlide:
    """A `content` model answering each slide's call from a script keyed by call order."""

    def __init__(self, *drafts: ContentDraft) -> None:
        self._drafts = list(drafts)

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        return self._drafts.pop(0)


def _flow_for_cli(claim_text: str) -> ContentDraft:
    from tests.test_cli_gate2 import DOC_ID
    from tests.test_cli_gate2 import QUOTE as CLI_QUOTE

    steps = [
        framed_step("n1", 1, "Profile"),
        claim_step(
            "n2",
            2,
            "Throughput rose",
            claim=ProposedClaim(
                text=claim_text, citations=[ProposedCitation(doc_id=DOC_ID, quote=CLI_QUOTE)]
            ),
        ),
        framed_step("n3", 3, "Scale"),
    ]
    return draft_with(headline_block(), diagram_block(*steps))


def _chart_for_cli() -> ContentDraft:
    from autodeck.agents.content import ProposedChart, ProposedChartSeries
    from tests.test_cli_gate2 import DOC_ID
    from tests.test_cli_gate2 import QUOTE as CLI_QUOTE

    chart = ProposedChart(
        chart_type="bar",
        title="Sequences per second",
        categories=["Before", "After"],
        series=[ProposedChartSeries(name="Throughput", values=[412.0, 671.0])],
        x_axis_label="",
        y_axis_label="",
        source_citations=[ProposedCitation(doc_id=DOC_ID, quote=CLI_QUOTE)],
    )
    return draft_with(
        headline_block(), ProposedBlock(id="c1", kind="chart", slot="chart", chart=chart)
    )


def _pillars_for_cli() -> ContentDraft:
    labels = [
        ProposedBlock(id=f"p{n}", kind="framing", slot="pillar_label", text=text)
        for n, text in enumerate(("Fast", "Safe", "Cheap"), start=1)
    ]
    return draft_with(headline_block(), *labels)


@pytest.mark.render
def test_an_outline_choosing_timeline_and_framework_diagram_reaches_gate3_with_diagrams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`content` -> `validate` -> `approve claims` -> `render` -> `gate3`, all through the CLI
    with scripted providers, on an approved outline of a `framework_diagram`, a `timeline`,
    a `chart_focus` and an `icon_pillars` slide. Before B37 the writer could not author a
    diagram, so the first two could not be filled and GATE 3's criterion 4 (chart, diagram
    and icon) could not pass on a pipeline-built deck. Nothing here is hand-assembled IR."""
    from autodeck.agents.art_direction import ArtDirectionPlan
    from autodeck.audit.verdicts import VerdictJudgement
    from autodeck.ir.actions import AssignIcons
    from autodeck.ir.store import IRStore
    from autodeck.pipeline.orchestrator import Gate, Orchestrator
    from tests.test_aesthetic import FakeCritic, reply
    from tests.test_art_direction import FakeArtModel
    from tests.test_cli_gate2 import QUOTE as CLI_QUOTE
    from tests.test_cli_gate2 import make_run, run_content, run_validate
    from tests.test_gate3 import _gate3, _invoke, patch_roles
    from tests.test_validation import Scripted as ScriptedValidator

    knowledge_root, corpus_root, runs_root = make_run(tmp_path)
    orchestrator = Orchestrator("r1", runs_root=runs_root, env="dev")
    outline = orchestrator.ir.load(1)
    template = outline.slides[0]
    plan = (
        ("s1", "framework_diagram", "plan", "Show the kernel rewrite rollout as a sequence."),
        ("s2", "timeline", "plan", "Show the kernel rewrite throughput gain over time."),
        ("s3", "chart_focus", "evidence", "Chart the kernel rewrite throughput gain."),
        ("s4", "icon_pillars", "capabilities", "Name what the kernel rewrite buys."),
    )
    slides = [
        template.model_copy(
            update={"id": sid, "component": component, "intent": intent, "narrative_role": role}
        )
        for sid, component, role, intent in plan
    ]
    three = outline.model_copy(update={"slides": slides})
    orchestrator.run_stage(
        "outline", lambda: f"wrote {orchestrator.save_ir(three, overwrite=True)}", force=True
    )
    orchestrator.approve(Gate.OUTLINE)

    text = "The kernel rewrite raised training throughput, per the cited benchmark."
    patch_roles(
        monkeypatch,
        content=_PerSlide(
            _flow_for_cli(text), _flow_for_cli(text), _chart_for_cli(), _pillars_for_cli()
        ),
    )
    content = run_content(runs_root, knowledge_root, corpus_root)
    assert content.exit_code == 0, content.output
    written = IRStore(runs_root, "r1").load()
    assert [[b.kind for b in s.blocks] for s in written.slides] == [
        ["framing", "diagram"],
        ["framing", "diagram"],
        ["framing", "chart"],
        ["framing", "framing", "framing", "framing"],
    ]

    judgement = VerdictJudgement(
        verdict="supported", verdict_notes="scripted for the test", supporting_quote=CLI_QUOTE
    )
    patch_roles(
        monkeypatch,
        validation=ScriptedValidator({"s1:d1:n2": judgement, "s2:d1:n2": judgement}),
    )
    validated = run_validate(runs_root, corpus_root)
    assert validated.exit_code == 0, validated.output
    approved = _invoke(runs_root, "approve", "r1", "claims", "--by", "tester")
    assert approved.exit_code == 0, approved.output

    icons = AssignIcons(
        slide_id="s4", slot="pillar_icon", concepts=["speed", "security", "growth"]
    )
    patch_roles(
        monkeypatch,
        outline=FakeArtModel(ArtDirectionPlan(rationale="Give s4 its icons.", actions=[icons])),
        aesthetic=FakeCritic(reply(9.0, rationale="good")),
    )
    rendered = _invoke(runs_root, "render", "r1")
    assert rendered.exit_code == 0, rendered.output

    result = _gate3(runs_root, knowledge_root)

    assert result.exit_code == 0, result.output
    criterion = next(line for line in result.output.splitlines() if "native diagram" in line)
    assert criterion.startswith("[PASS]")
    assert "2 diagram(s)" in criterion
    print(criterion)
