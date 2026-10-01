"""GATE 3 surface (3b.10): `autodeck render`, `autodeck gate3`, and the final assessment.

Drive the CLI the way `tests/test_owner_run.py` does (fake providers, no live calls). The
aesthetic loop needs LibreOffice for its default rasteriser: CLI tests that reach it are
`render`-marked; the assessment and report tests are not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.audit.gate3 import (
    HUMAN_CHECKS,
    FinalAssessment,
    render_final_report,
)
from autodeck.audit.numeric_linter import NumericReport
from autodeck.audit.post_render import PostRenderFinding, PostRenderReport
from autodeck.design.grammar import GrammarFinding
from autodeck.design.headers.flow import HeaderFlowReport
from autodeck.ir.actions import facts_digest
from autodeck.ir.models import Deck
from autodeck.pipeline.orchestrator import (
    ApprovalState,
    ArtifactMissing,
    Gate,
    GateBlocked,
    Orchestrator,
)
from autodeck.render.qa.deterministic import QAFinding
from tests.test_actions import make_deck, make_icon_block

SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


def _presentation_only_change(deck: Deck) -> Deck:
    """What art direction and the aesthetic loop do: style, component, mode, icons."""
    copy = deck.model_copy(deep=True, update={"version": deck.version + 1})
    slide = copy.slides[0]
    slide.style.type_scale = "compact"
    slide.style.accent = "accent5"
    slide.component = "alt_layout"
    slide.communication_mode = "diagram_led"
    slide.blocks[0].slot = "renamed_slot"
    icon_block = next(block for block in slide.blocks if block.kind == "icon")
    assert icon_block.icon is not None
    icon_block.icon.glyph_id = "new-glyph"
    slide.blocks.append(make_icon_block("b9", slot="icon2"))
    return copy


def test_claims_approval_is_bound_to_facts_so_presentation_changes_keep_it(
    tmp_path: Path,
) -> None:
    """Approve claims; save a new IR version differing only in style/component/mode/icons →
    `approval_state(CLAIMS)` is CURRENT. Save one with a changed claim text → ArtifactMissing
    detail says the facts changed after validation; `require_gate` raises."""
    orchestrator = Orchestrator("r1", runs_root=tmp_path)
    validated = make_deck(run_id="r1")
    orchestrator.run_stage(
        "validate", lambda: f"wrote {orchestrator.save_ir(validated)}", force=True
    )
    orchestrator.approve(Gate.CLAIMS)
    assert orchestrator.approval_state(Gate.CLAIMS)[0] is ApprovalState.CURRENT

    presented = _presentation_only_change(validated)
    orchestrator.save_ir(presented)
    reopened = Orchestrator("r1", runs_root=tmp_path)
    assert reopened.ir.latest_version() == 2
    assert reopened.approval_state(Gate.CLAIMS) == (ApprovalState.CURRENT, "approved")
    reopened.require_gate(Gate.CLAIMS)  # must not raise

    changed = presented.model_copy(deep=True, update={"version": 3})
    changed_claim = changed.slides[0].blocks[0].claim
    assert changed_claim is not None
    changed_claim.text = "A different claim entirely."
    orchestrator.save_ir(changed)

    stale = Orchestrator("r1", runs_root=tmp_path)
    state, detail = stale.approval_state(Gate.CLAIMS)
    assert state is ApprovalState.NO_ARTIFACT
    assert "the facts changed after validation (IR v3)" in detail
    with pytest.raises(GateBlocked, match="facts changed after validation"):
        stale.require_gate(Gate.CLAIMS)
    with pytest.raises(ArtifactMissing, match="facts changed after validation"):
        stale.approve(Gate.CLAIMS)


def test_facts_digest_is_stable_and_sensitive() -> None:
    """Same deck twice → same digest; a deep copy → same; one changed citation quote,
    verdict, or framing text → different; changed style or an added icon block → same."""
    deck = make_deck()
    digest = facts_digest(deck)
    assert len(digest) == 64
    assert facts_digest(deck) == digest
    assert facts_digest(deck.model_copy(deep=True)) == digest
    assert facts_digest(make_deck()) == digest

    quote = deck.model_copy(deep=True)
    claim = quote.slides[0].blocks[0].claim
    assert claim is not None
    claim.citations[0].quote = "A different quote entirely."
    assert facts_digest(quote) != digest

    verdict = deck.model_copy(deep=True)
    claim = verdict.slides[0].blocks[0].claim
    assert claim is not None
    claim.verdict = "contradicted"
    assert facts_digest(verdict) != digest

    framing = deck.model_copy(deep=True)
    framing.slides[0].blocks[1].text = "A completely different framing sentence."
    assert facts_digest(framing) != digest

    assert facts_digest(_presentation_only_change(deck)) == digest


@SCAFFOLD
def test_render_refuses_without_a_current_claims_approval() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_gate3_refuses_before_render() -> None:
    raise NotImplementedError


def _assessment(
    *,
    post_render_findings: tuple[PostRenderFinding, ...] = (),
    qa: tuple[QAFinding, ...] = (),
    grammar_findings: tuple[GrammarFinding, ...] = (),
    diagrams: int = 1,
    icons: int = 3,
) -> FinalAssessment:
    return FinalAssessment(
        pptx=Path("runs/r1/deck.pptx"),
        deck_digest="d" * 64,
        post_render=PostRenderReport(numeric=NumericReport(), findings=post_render_findings),
        qa=list(qa),
        grammar=list(grammar_findings),
        flow=HeaderFlowReport(),
        diagram_count=diagrams,
        icon_count=icons,
    )


_POST_RENDER = PostRenderFinding(
    check="claim altered in render", slide_id="s2", detail="expected 'A', found 'B'"
)
_QA = QAFinding(
    check="below minimum size",
    slide_id="s3",
    shapes=("Text 4",),
    measured=9.0,
    threshold=12.0,
    remedy="token",
    remedy_detail="typography.minimum",
)
_BLOCKING_GRAMMAR = GrammarFinding(
    check="icon adjacent to text label", severity="blocking", detail="far from text"
)
_ADVISORY_GRAMMAR = GrammarFinding(check="word budget", severity="advisory", detail="long")


def test_checkable_criteria_and_their_order() -> None:
    """Build `FinalAssessment`s by hand: all clean → four PASS; one post-render finding,
    one QA finding, one blocking grammar finding, zero icons — each fails its own line only."""
    clean = _assessment()
    results = clean.checkable()
    assert [label for label, _passed, _detail in results] == [
        "Post-render audit passes (every claim on its slide, every number traced)",
        "No deterministic QA findings",
        "No blocking grammar findings",
        "At least one native diagram and one theme-recolourable icon",
    ]
    assert [passed for _label, passed, _detail in results] == [True] * 4
    assert clean.passes
    assert results[3][2] == "1 diagram(s), 3 icon(s)"

    broken = {
        0: _assessment(post_render_findings=(_POST_RENDER,)),
        1: _assessment(qa=(_QA,)),
        2: _assessment(grammar_findings=(_BLOCKING_GRAMMAR,)),
        3: _assessment(icons=0),
    }
    for index, assessment in broken.items():
        passed = [ok for _label, ok, _detail in assessment.checkable()]
        assert passed == [position != index for position in range(4)], index
        assert not assessment.passes
    assert "expected 'A', found 'B'" in broken[0].checkable()[0][2]
    assert "below minimum size" in broken[1].checkable()[1][2]
    assert "far from text" in broken[2].checkable()[2][2]
    assert broken[3].checkable()[3][2] == "1 diagram(s), 0 icon(s)"

    # Advisory grammar findings and header-flow findings are reported, never a criterion.
    advisory = _assessment(grammar_findings=(_ADVISORY_GRAMMAR,))
    assert advisory.passes
    assert _assessment(diagrams=0).passes is False


def test_the_report_lists_human_checks_unticked_and_says_nothing_checked_them() -> None:
    """Even for an assessment that passes every checkable criterion, every `HUMAN_CHECKS`
    item appears as `- [ ]`, and no `[x]` appears anywhere in the report."""
    assessment = _assessment(grammar_findings=(_ADVISORY_GRAMMAR,))
    assert assessment.passes
    report = render_final_report(assessment, audit_report="# Audit report - Demo\n")

    assert "[x]" not in report.lower()
    for check in HUMAN_CHECKS:
        assert f"- [ ] {check}" in report
    assert report.count("- [ ]") == len(HUMAN_CHECKS) == 5
    human_heading = report.index("Human checks")
    assert "by a person" in report[human_heading:]
    assert "Nothing in this report has checked them" in report[human_heading:]

    # Sections in the contracted order, human checks last.
    order = [
        report.index("Deck: "),
        report.index("Deck digest: "),
        report.index("## Checkable criteria"),
        report.index("## Findings"),
        report.index("## Header flow"),
        report.index("# Audit report - Demo"),
        human_heading,
    ]
    assert order == sorted(order)
    assert report.count("[PASS]") == 4
    assert "d" * 64 in report
    assert "[advisory] word budget: long" in report


def test_the_report_shows_every_failure_in_full_and_is_deterministic() -> None:
    assessment = _assessment(
        post_render_findings=(_POST_RENDER,),
        qa=(_QA,),
        grammar_findings=(_BLOCKING_GRAMMAR,),
        icons=0,
    )
    report = render_final_report(assessment, audit_report="audit")
    assert report.count("[FAIL]") == 4
    assert "4 of 4 checkable criteria fail." in report
    assert "slide s2: expected 'A', found 'B'" in report
    assert "measured 9 against 12; fix by token (typography.minimum)" in report
    assert "[BLOCKING] icon adjacent to text label: far from text" in report
    assert report == render_final_report(assessment, audit_report="audit")
    # Still unticked when everything fails.
    assert report.count("- [ ]") == 5


@SCAFFOLD
def test_assess_final_counts_diagrams_and_icons_from_the_rendered_file() -> None:
    raise NotImplementedError


@SCAFFOLD
@pytest.mark.render
def test_render_then_gate3_produces_deck_report_and_manifest_together(tmp_path: object) -> None:
    """Full CLI path with fakes on an approved fixture run: `render` writes deck.pptx,
    previews and new IR versions without voiding the claims approval; `gate3` writes
    final_audit_report.md and build_manifest.json and prints all three paths first; then
    `approve <run> final_render` records `canonical_pptx_digest(deck.pptx)`."""
    raise NotImplementedError


@SCAFFOLD
def test_neither_command_can_record_an_approval() -> None:
    """Extend the existing walk (`test_none_of_the_new_commands_can_record_an_approval` in
    tests/test_owner_run.py) to `render` and `gate3`, or assert here in the same way."""
    raise NotImplementedError
