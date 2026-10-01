"""GATE 3 surface (3b.10): `autodeck render`, `autodeck gate3`, and the final assessment.

Drive the CLI the way `tests/test_owner_run.py` does (fake providers, no live calls). The
aesthetic loop needs LibreOffice for its default rasteriser: CLI tests that reach it are
`render`-marked; the assessment and report tests are not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.ir.actions import facts_digest
from autodeck.ir.models import Deck
from autodeck.pipeline.orchestrator import (
    ApprovalState,
    ArtifactMissing,
    Gate,
    GateBlocked,
    Orchestrator,
)
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


@SCAFFOLD
def test_checkable_criteria_and_their_order() -> None:
    """Build `FinalAssessment`s by hand: all clean → four PASS; one post-render finding,
    one QA finding, one blocking grammar finding, zero icons — each fails its own line only."""
    raise NotImplementedError


@SCAFFOLD
def test_the_report_lists_human_checks_unticked_and_says_nothing_checked_them() -> None:
    """Even for an assessment that passes every checkable criterion, every `HUMAN_CHECKS`
    item appears as `- [ ]`, and no `[x]` appears anywhere in the report."""
    raise NotImplementedError


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
