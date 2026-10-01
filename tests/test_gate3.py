"""GATE 3 surface (3b.10): `autodeck render`, `autodeck gate3`, and the final assessment.

Drive the CLI the way `tests/test_owner_run.py` does (fake providers, no live calls). The
aesthetic loop needs LibreOffice for its default rasteriser: CLI tests that reach it are
`render`-marked; the assessment and report tests are not.
"""

from __future__ import annotations

import pytest

SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


@SCAFFOLD
def test_claims_approval_is_bound_to_facts_so_presentation_changes_keep_it() -> None:
    """Approve claims; save a new IR version differing only in style/component/mode/icons →
    `approval_state(CLAIMS)` is CURRENT. Save one with a changed claim text → ArtifactMissing
    detail says the facts changed after validation; `require_gate` raises."""
    raise NotImplementedError


@SCAFFOLD
def test_facts_digest_is_stable_and_sensitive() -> None:
    """Same deck twice → same digest; a deep copy → same; one changed citation quote,
    verdict, or framing text → different; changed style or an added icon block → same."""
    raise NotImplementedError


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
