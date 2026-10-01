"""GATE 3 integrity follow-ups, found by verifying the owner guide against the real CLI."""

from __future__ import annotations

import pytest

SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


@SCAFFOLD
def test_gate3_refuses_when_the_claims_approval_is_not_current() -> None:
    """Approved claims, render, then a fact-changing content pass → `gate3` exits 3 and
    writes no report."""
    raise NotImplementedError


@SCAFFOLD
def test_final_render_cannot_be_approved_over_stale_claims() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_final_render_cannot_be_approved_without_gate3_on_this_deck() -> None:
    """No assessment → refused; assessment for a different digest (deck re-rendered after
    gate3) → refused; refusal writes nothing to state."""
    raise NotImplementedError


@SCAFFOLD
def test_final_render_cannot_be_approved_over_a_failed_final_audit() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_final_render_approval_succeeds_when_claims_are_current_and_gate3_passed() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_other_gates_keep_their_approval_behaviour() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_the_aesthetic_loop_never_reports_target_reached_with_an_open_qa_finding() -> None:
    """Critic scores 9 while `run_deterministic_qa` returns one finding → not
    `target_reached`; the actions are applied; a later clean look at 9 → `target_reached`."""
    raise NotImplementedError


@SCAFFOLD
def test_gate3_terminal_output_points_to_the_claim_audit_instead_of_repeating_it() -> None:
    """Printed output has no claim rows; it names `final_audit_report.md`; the file still
    contains the full claim-level audit."""
    raise NotImplementedError
