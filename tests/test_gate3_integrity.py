"""GATE 3 integrity follow-ups, found by verifying the owner guide against the real CLI.

The CLI tests here drive `gate3` and `approve` with a deck rendered straight from the fixture
IR (`render_deck` needs no LibreOffice), so none of them is `render`-marked; the full
`render` command is exercised in `tests/test_gate3.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import Result

import autodeck.render.qa.aesthetic as aesthetic
from autodeck.audit.manifest import canonical_pptx_digest
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.actions import SetAccent, SetTypeScale, fact_fingerprint
from autodeck.ir.models import Deck
from autodeck.ir.store import IRStore
from autodeck.pipeline.orchestrator import (
    ApprovalRefused,
    ApprovalState,
    ArtifactMissing,
    Gate,
    Orchestrator,
)
from autodeck.providers.base import RateLimitError
from autodeck.providers.cache import ResponseCache
from autodeck.render.renderer import render_deck
from tests.gate_artifacts import seed_artifact
from tests.test_aesthetic import FakeCritic, _deck, _qa_finding, _run, reply
from tests.test_art_direction import FakeArtModel
from tests.test_gate3 import (
    _deck_with_icons,
    _gate3,
    _invoke,
    _tamper_claim,
    make_gate3_run,
    patch_roles,
)

# ---------------------------------------------------------------------------
# A run with a rendered deck, without LibreOffice
# ---------------------------------------------------------------------------


def make_rendered_run(tmp_path: Path) -> tuple[Path, Path]:
    """`(runs_root, knowledge_root)` for a run with approved claims and `deck.pptx` rendered
    from the directed fixture deck (icons assigned, as art direction would)."""
    runs_root, knowledge = make_gate3_run(tmp_path)
    orchestrator = Orchestrator("r1", runs_root=runs_root)
    directed = _deck_with_icons().model_copy(update={"version": 2})
    orchestrator.ir.save(directed)
    render_deck(
        directed,
        tokens=DesignTokens.load(Path(directed.theme_ref)),
        out_path=orchestrator.paths.deck_pptx,
    )
    orchestrator.run_stage("render", lambda: "rendered", force=True)
    return runs_root, knowledge


def change_a_claim(runs_root: Path) -> None:
    """Save a newer IR whose first claim differs: the approved claims table is gone."""
    store = IRStore(runs_root, "r1")
    latest = store.latest_version()
    assert latest is not None
    changed = store.load(latest).model_copy(deep=True, update={"version": latest + 1})
    claim = changed.slides[0].blocks[0].claim
    assert claim is not None
    claim.text = "A claim nobody approved."
    store.save(changed)


def state_bytes(runs_root: Path) -> bytes:
    return (runs_root / "r1" / "state.json").read_bytes()


def approve_final(runs_root: Path) -> Result:
    return _invoke(runs_root, "approve", "r1", "final_render")


# ---------------------------------------------------------------------------
# gate3 needs current claims
# ---------------------------------------------------------------------------


def test_gate3_refuses_when_the_claims_approval_is_not_current(tmp_path: Path) -> None:
    """Approved claims, render, then a fact-changing content pass → `gate3` exits 3 and
    writes no report."""
    runs_root, knowledge = make_rendered_run(tmp_path)
    change_a_claim(runs_root)
    before = state_bytes(runs_root)

    refused = _gate3(runs_root, knowledge)

    assert refused.exit_code == 3, refused.output
    assert "facts changed after validation" in refused.output
    assert "autodeck approve r1 claims" in refused.output
    assert "[PASS]" not in refused.output
    run_dir = runs_root / "r1"
    assert not (run_dir / "final_audit_report.md").exists()
    assert not (run_dir / "build_manifest.json").exists()
    assert state_bytes(runs_root) == before  # nothing recorded either

    # A run whose claims were never approved is refused the same way.
    unapproved_root, unapproved_knowledge = make_gate3_run(tmp_path / "other", approve=False)
    never = _gate3(unapproved_root, unapproved_knowledge)
    assert never.exit_code == 3, never.output
    assert "GATE 'claims'" in never.output


# ---------------------------------------------------------------------------
# approve final_render preconditions
# ---------------------------------------------------------------------------


def test_final_render_cannot_be_approved_over_stale_claims(tmp_path: Path) -> None:
    runs_root, knowledge = make_rendered_run(tmp_path)
    assert _gate3(runs_root, knowledge).exit_code == 0

    change_a_claim(runs_root)
    before = state_bytes(runs_root)
    refused = approve_final(runs_root)

    assert refused.exit_code == 1, refused.output
    assert "Traceback" not in refused.output
    assert "cannot approve GATE 'final_render'" in refused.output
    assert "claims approval does not count" in refused.output
    assert "facts changed after validation" in refused.output
    assert "Nothing was recorded" in refused.output
    assert state_bytes(runs_root) == before
    assert not Orchestrator("r1", runs_root=runs_root).state.is_approved(Gate.FINAL_RENDER)

    # The library call raises the dedicated exception.
    with pytest.raises(ApprovalRefused, match="claims approval"):
        Orchestrator("r1", runs_root=runs_root).approve(Gate.FINAL_RENDER)


def test_final_render_cannot_be_approved_without_gate3_on_this_deck(tmp_path: Path) -> None:
    """No assessment → refused; assessment for a different digest (deck re-rendered after
    gate3) → refused; refusal writes nothing to state."""
    runs_root, knowledge = make_rendered_run(tmp_path)
    run_dir = runs_root / "r1"
    before = state_bytes(runs_root)

    never_assessed = approve_final(runs_root)
    assert never_assessed.exit_code == 1, never_assessed.output
    assert "final audit has not been run on this deck" in never_assessed.output
    assert "autodeck gate3 r1" in never_assessed.output
    assert state_bytes(runs_root) == before

    # gate3 on this deck, then the deck is rendered again and differs.
    assert _gate3(runs_root, knowledge).exit_code == 0
    assessed_digest = canonical_pptx_digest(run_dir / "deck.pptx")
    restyled = apply_accent(IRStore(runs_root, "r1").load(2))
    render_deck(
        restyled,
        tokens=DesignTokens.load(Path(restyled.theme_ref)),
        out_path=run_dir / "deck.pptx",
    )
    assert canonical_pptx_digest(run_dir / "deck.pptx") != assessed_digest
    before = state_bytes(runs_root)

    stale = approve_final(runs_root)
    assert stale.exit_code == 1, stale.output
    assert "final audit has not been run on this deck" in stale.output
    assert state_bytes(runs_root) == before
    assert "final_render" not in json.loads(state_bytes(runs_root))["approvals"]

    # Running gate3 again on the new deck is what unblocks it.
    assert _gate3(runs_root, knowledge).exit_code == 0
    assert approve_final(runs_root).exit_code == 0


def apply_accent(deck: Deck) -> Deck:
    from autodeck.ir.actions import apply_action
    from autodeck.render.qa.aesthetic import catalog_slot_lookup, library_concept_lookup

    return apply_action(
        deck,
        SetAccent(slide_id="s1", accent="accent2"),
        slots_of=catalog_slot_lookup(),
        glyph_for=library_concept_lookup(),
    )


def test_final_render_cannot_be_approved_over_a_failed_final_audit(tmp_path: Path) -> None:
    runs_root, knowledge = make_rendered_run(tmp_path)
    _tamper_claim(runs_root / "r1" / "deck.pptx")

    failed = _gate3(runs_root, knowledge)
    assert failed.exit_code == 4, failed.output
    recorded = json.loads(state_bytes(runs_root))["final_assessment"]
    assert recorded["passes"] is False
    assert recorded["digest"] == canonical_pptx_digest(runs_root / "r1" / "deck.pptx")
    before = state_bytes(runs_root)

    refused = approve_final(runs_root)

    assert refused.exit_code == 1, refused.output
    assert "final audit did not pass" in refused.output
    assert "autodeck render r1" in refused.output and "autodeck gate3 r1" in refused.output
    assert state_bytes(runs_root) == before
    assert not Orchestrator("r1", runs_root=runs_root).state.is_approved(Gate.FINAL_RENDER)


def test_final_render_approval_succeeds_when_claims_are_current_and_gate3_passed(
    tmp_path: Path,
) -> None:
    runs_root, knowledge = make_rendered_run(tmp_path)
    gate3 = _gate3(runs_root, knowledge)
    assert gate3.exit_code == 0, gate3.output
    deck_path = runs_root / "r1" / "deck.pptx"

    approved = approve_final(runs_root)

    assert approved.exit_code == 0, approved.output
    assert "approved final_render for r1" in approved.output
    state = json.loads(state_bytes(runs_root))
    assert state["fingerprints"]["final_render"] == canonical_pptx_digest(deck_path)
    assert state["final_assessment"]["digest"] == canonical_pptx_digest(deck_path)
    assert state["final_assessment"]["passes"] is True
    orchestrator = Orchestrator("r1", runs_root=runs_root)
    assert orchestrator.approval_state(Gate.FINAL_RENDER) == (ApprovalState.CURRENT, "approved")
    assert orchestrator.pending_gates() == [
        Gate.BRIEF,
        Gate.OUTLINE,
    ]


def test_other_gates_keep_their_approval_behaviour(tmp_path: Path) -> None:
    """Brief, outline and claims approve with no final assessment on record, exactly as
    before; a missing artifact is still `ArtifactMissing` (checked before the new
    preconditions), and a recorded assessment grants nothing by itself."""
    orchestrator = Orchestrator("r1", runs_root=tmp_path)
    assert orchestrator.state.final_assessment == {}
    for gate in (Gate.BRIEF, Gate.OUTLINE, Gate.CLAIMS):
        seed_artifact(orchestrator, gate)
        orchestrator.approve(gate, approver="aditya")
        assert orchestrator.approval_state(gate) == (ApprovalState.CURRENT, "approved")
    assert orchestrator.state.final_assessment == {}

    # No rendered deck at all: still the old exception, not the new one.
    with pytest.raises(ArtifactMissing, match="no rendered deck"):
        orchestrator.approve(Gate.FINAL_RENDER)

    # Recording an assessment is not an approval.
    seed_artifact(orchestrator, Gate.FINAL_RENDER)
    orchestrator.record_final_assessment("a" * 64, True)
    assert not orchestrator.state.is_approved(Gate.FINAL_RENDER)
    assert orchestrator.pending_gates() == [Gate.FINAL_RENDER]


def test_the_final_assessment_survives_a_restart_and_old_state_files_load(
    tmp_path: Path,
) -> None:
    orchestrator = Orchestrator("r1", runs_root=tmp_path)
    orchestrator.record_final_assessment("d" * 64, False)
    reopened = Orchestrator("r1", runs_root=tmp_path)
    assert reopened.state.final_assessment["digest"] == "d" * 64
    assert reopened.state.final_assessment["passes"] is False
    assert reopened.state.final_assessment["at"]
    orchestrator.record_final_assessment("e" * 64, True)  # the latest call wins
    assert Orchestrator("r1", runs_root=tmp_path).state.final_assessment["passes"] is True

    # A state.json from before this field existed loads with it empty.
    state_file = orchestrator.paths.state_file
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    del payload["final_assessment"]
    state_file.write_text(json.dumps(payload), encoding="utf-8")
    assert Orchestrator("r1", runs_root=tmp_path).state.final_assessment == {}


# ---------------------------------------------------------------------------
# The aesthetic loop's target
# ---------------------------------------------------------------------------


def test_the_aesthetic_loop_never_reports_target_reached_with_an_open_qa_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Critic scores 9 while `run_deterministic_qa` returns one finding → not
    `target_reached`; the actions are applied; a later clean look at 9 → `target_reached`."""
    counts = [1, 0]  # the first look has one open finding, the applied candidate has none
    monkeypatch.setattr(
        aesthetic,
        "run_deterministic_qa",
        lambda pptx, tokens: [_qa_finding() for _ in range(counts.pop(0))],
    )
    prompt = tmp_path / "aesthetic_critique.md"
    prompt.write_text("You are the aesthetic critic. (test prompt)", encoding="utf-8")
    deck = _deck()
    critic = FakeCritic(
        reply(9.0, SetTypeScale(slide_id="s1", scale="compact")),
        reply(9.0),
    )

    result = _run(deck, critic, tmp_path / "run", prompt)

    assert result.stopped == "target_reached"
    assert critic.calls == 2  # a 9 over an open finding did not stop the loop
    first, second = result.iterations
    assert (first.score, first.qa_findings, len(first.applied)) == (9.0, 1, 1)
    assert (second.score, second.qa_findings) == (9.0, 0)
    assert result.best_score == 9.0
    # Ties keep the earlier deck, so the returned deck is the one the first look scored.
    assert fact_fingerprint(result.deck) == fact_fingerprint(deck)

    # With the finding never cleared and nothing left to propose, the loop ends without
    # claiming the target.
    counts[:] = [1]
    stuck = _run(deck, FakeCritic(reply(9.0)), tmp_path / "stuck", prompt)
    assert stuck.stopped == "no_actions"


# ---------------------------------------------------------------------------
# The terminal output
# ---------------------------------------------------------------------------


def test_gate3_terminal_output_points_to_the_claim_audit_instead_of_repeating_it(
    tmp_path: Path,
) -> None:
    """Printed output has no claim rows; it names `final_audit_report.md`; the file still
    contains the full claim-level audit."""
    runs_root, knowledge = make_rendered_run(tmp_path)

    result = _gate3(runs_root, knowledge)

    assert result.exit_code == 0, result.output
    report = (runs_root / "r1" / "final_audit_report.md").read_text(encoding="utf-8")
    assert "# Audit report" in report
    assert "The kernel rewrite cut cost per token by 41%." in report
    assert "# Audit report" not in result.output
    # The claim is still quoted where the header flow reads it, but the audit's own
    # sections (summary, claim rows) are only in the file.
    claim = "The kernel rewrite cut cost per token by 41%."
    assert "## Summary" in report and "## Summary" not in result.output
    assert result.output.count(claim) < report.count(claim)
    assert "final_audit_report.md" in result.output
    assert "claim-level audit is in" in result.output
    assert len(result.output.splitlines()) < len(report.splitlines())
    # Everything else the owner reads is still printed.
    for kept in ("[PASS]", "Header flow", "- [ ]", "build_manifest.json", "deck.pptx"):
        assert kept in result.output
    assert result.output.count("- [ ]") == 5


# ---------------------------------------------------------------------------
# Wording a non-programmer hit
# ---------------------------------------------------------------------------


def test_a_spent_art_direction_quota_explains_the_missing_icons_in_plain_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The icon slide has no icons because the call that chooses them failed: say that, and
    say what to run, instead of printing the renderer's own `icon_pillars has 0 ...`."""
    runs_root, _knowledge = make_gate3_run(tmp_path)
    patch_roles(
        monkeypatch,
        outline=FakeArtModel(RateLimitError("gemini: rate limited (429)")),
        aesthetic=FakeCritic(),
    )

    result = _invoke(runs_root, "render", "r1")

    assert result.exit_code == 5, result.output
    assert "role 'outline'" in result.output
    assert "the icon slide (s3) could not get its icons" in result.output
    assert "art-direction call above failed" in result.output
    assert "Re-run `autodeck render r1` later" in result.output
    for jargon in ("RenderStageError", "pillar_icon", "pillar_label", "block(s)"):
        assert jargon not in result.output
    assert not (runs_root / "r1" / "deck.pptx").exists()


def test_a_render_error_with_no_missing_icons_is_still_shown_as_it_is() -> None:
    from autodeck.cli import _undrawn_deck_note

    note = _undrawn_deck_note(_deck(), "r1", "RenderStageError: something else")
    assert "RenderStageError: something else" in note
    assert "icon" not in note


def test_the_saved_line_does_not_claim_no_call_was_made_when_the_cache_is_empty(
    tmp_path: Path,
) -> None:
    """The cache only knows what providers wrote to it; a provider that does not write there
    (a stand-in model, in the owner guide's fixtures) leaves it empty after making calls. The
    line may say the cache is empty; it may not say no call completed."""
    from autodeck.cli import _cache_note

    orchestrator = Orchestrator("r1", runs_root=tmp_path)
    empty = _cache_note(orchestrator)
    assert "cache is empty" in empty
    assert "nothing is cached" not in empty and "No provider call" not in empty

    cache = ResponseCache(orchestrator.paths.llm_cache)
    cache.put(cache.make_key("one"), "reply")
    cache.put(cache.make_key("two"), "reply")
    saved = _cache_note(orchestrator)
    assert saved.startswith("2 completed provider call(s) are saved under")
    assert "replays them at no cost" in saved


def test_the_cache_note_is_what_the_render_command_prints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root, _knowledge = make_gate3_run(tmp_path)
    patch_roles(
        monkeypatch,
        outline=FakeArtModel(RateLimitError("gemini: rate limited (429)")),
        aesthetic=FakeCritic(),
    )
    result = _invoke(runs_root, "render", "r1")
    assert "Saved: IR versions up to v2 were written." in result.output
    assert "response cache is empty" in result.output
    assert "nothing is cached" not in result.output
