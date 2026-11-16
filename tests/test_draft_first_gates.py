"""A7 on a draft-first run (B43, B48): approvals bind to what they cover, in any order.

A draft-first run is one whose `compose` stage completed: that stage wrote outline and slide
text into one IR version and the brief into `draft_brief.json`. These tests build such runs by
hand (no model, no rendering) and pin the rules that keep the four approvals a person's:

- the outline approval binds to the outline digest, so rewording survives and re-shaping voids;
- the brief approval binds to the draft brief's substance, and a thin message is carried only
  when the approver names it as a risk;
- the final render needs brief, outline and claims all current, whatever order they came in;
- the CLI and the UI route refuse what the library refuses, and no draft path writes
  `deck.pptx`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx import Presentation
from typer.testing import CliRunner

from autodeck.agents.planner import Draft
from autodeck.cli import app
from autodeck.ir.actions import outline_digest
from autodeck.ir.models import Block, Deck, KeyMessage, Slide
from autodeck.pipeline.draft import (
    DraftBriefError,
    finalise_draft_brief,
    load_draft_brief,
    save_draft_brief,
)
from autodeck.pipeline.orchestrator import (
    ApprovalRefused,
    ApprovalState,
    Gate,
    Orchestrator,
)
from autodeck.render import draft as render_draft_module
from autodeck.render.qa.libreoffice import RenderError
from autodeck.ui import profile
from autodeck.ui.api import Roots, UIError
from autodeck.ui.approvals import approve_gate
from autodeck.ui.server import App
from tests.gate_artifacts import seed_artifact, seed_passing_final_assessment
from tests.test_renderer import tokens_for
from tests.test_ui import fake_jobs

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _slide(
    slide_id: str,
    *,
    text: str = "Words.",
    intent: str = "Say something.",
    message_ids: tuple[str, ...] = ("km1",),
    component: str = "bullets_supporting",
    mode: str | None = None,
) -> Slide:
    return Slide(
        id=slide_id,
        narrative_role="argument",
        component=component,
        communication_mode=mode,  # type: ignore[arg-type]
        intent=intent,
        message_ids=list(message_ids),
        blocks=[Block(id=f"{slide_id}-b1", kind="framing", slot="headline", text=text)],
    )


def _deck(*slides: Slide, version: int = 1, run_id: str = "r1") -> Deck:
    return Deck(
        run_id=run_id,
        project="p",
        client="c",
        audience="CTO",
        version=version,
        slides=list(slides) or [_slide("s1"), _slide("s2", message_ids=("km2",))],
        theme_ref="config/tokens/dev.json",
        component_lib_version="test",
    )


def _draft_brief() -> Draft:
    return Draft(
        objective="Decide whether to adopt the platform.",
        audience="CTO",
        length_target=2,
        must_include=["pricing"],
        must_avoid=["roadmap"],
        key_messages=[
            KeyMessage(id="km1", text="Costs fall.", evidence_status="supported"),
            KeyMessage(
                id="km2",
                text="Adoption is easy.",
                evidence_status="thin",
                probe_notes="one vendor blog post",
            ),
        ],
    )


def draft_first_run(
    runs_root: Path, run_id: str = "r1", deck: Deck | None = None
) -> Orchestrator:
    """A run whose compose stage wrote IR v1 and a draft brief, with nothing approved."""
    orch = Orchestrator(run_id, runs_root=runs_root, env="dev")
    composed = (deck or _deck(run_id=run_id)).model_copy(update={"run_id": run_id})
    orch.run_stage("compose", lambda: f"wrote {orch.save_ir(composed)}")
    save_draft_brief(orch, _draft_brief())
    return orch


def new_ir_version(orch: Orchestrator, *slides: Slide) -> Deck:
    """Save the next IR version holding `slides`, as a revision or art direction would."""
    version = orch.ir.next_version()
    deck = _deck(*slides, version=version, run_id=orch.run_id)
    orch.save_ir(deck)
    return deck


def validated(orch: Orchestrator) -> None:
    """Record a `validate` stage over the composed slides (same facts, next IR version)."""
    latest = orch.ir.load()
    copy = latest.model_copy(update={"version": orch.ir.next_version()})
    orch.run_stage("validate", lambda: f"wrote {orch.save_ir(copy)}")


def approve_brief(orch: Orchestrator, by: str = "Ada") -> None:
    finalise_draft_brief(orch, approver=by, accepted_risks={"km2": ""})
    orch.approve(Gate.BRIEF, approver=by)


def state_of(orch: Orchestrator, gate: Gate) -> ApprovalState:
    return orch.approval_state(gate)[0]


# ---------------------------------------------------------------------------
# 1-3. The outline approval
# ---------------------------------------------------------------------------


def test_outline_approval_survives_changes_that_are_not_the_outline(tmp_path: Path) -> None:
    orch = draft_first_run(tmp_path)
    assert orch.is_draft_first
    orch.approve(Gate.OUTLINE, approver="Ada")
    assert state_of(orch, Gate.OUTLINE) is ApprovalState.CURRENT

    # Reworded block text.
    new_ir_version(
        orch, _slide("s1", text="Different words."), _slide("s2", message_ids=("km2",))
    )
    assert state_of(orch, Gate.OUTLINE) is ApprovalState.CURRENT
    # Another component and another communication mode (art direction's business).
    new_ir_version(
        orch,
        _slide("s1", component="hero_statement", mode="icon_anchored"),
        _slide("s2", message_ids=("km2",), mode="diagram_led"),
    )
    assert state_of(orch, Gate.OUTLINE) is ApprovalState.CURRENT
    orch.require_gate(Gate.OUTLINE)


@pytest.mark.parametrize(
    "slides",
    [
        pytest.param(
            [_slide("s1"), _slide("s2", message_ids=("km2",)), _slide("s3")], id="add"
        ),
        pytest.param([_slide("s1")], id="remove"),
        pytest.param([_slide("s2", message_ids=("km2",)), _slide("s1")], id="reorder"),
        pytest.param(
            [_slide("s1", intent="Say something else."), _slide("s2", message_ids=("km2",))],
            id="intent",
        ),
        pytest.param(
            [_slide("s1", message_ids=("km1", "km2")), _slide("s2")], id="message_ids"
        ),
    ],
)
def test_outline_approval_is_voided_by_reshaping_the_outline(
    tmp_path: Path, slides: list[Slide]
) -> None:
    orch = draft_first_run(tmp_path)
    orch.approve(Gate.OUTLINE, approver="Ada")
    new_ir_version(orch, *slides)
    state, detail = orch.approval_state(Gate.OUTLINE)
    assert state is not ApprovalState.CURRENT, detail
    assert Gate.OUTLINE in orch.pending_gates()


def test_outline_digest_ignores_presentation_and_is_order_sensitive() -> None:
    base = _deck(_slide("s1"), _slide("s2", message_ids=("km2",)))
    presentation_only = _deck(
        _slide("s1", text="Other.", component="hero_statement", mode="text_led"),
        _slide("s2", message_ids=("km2",), mode="diagram_led"),
        version=7,
    )
    assert outline_digest(base) == outline_digest(presentation_only)
    reordered = _deck(_slide("s2", message_ids=("km2",)), _slide("s1"))
    assert outline_digest(base) != outline_digest(reordered)
    assert outline_digest(base) == outline_digest(base)


def test_a_gate_first_outline_approval_is_still_bound_to_its_file(tmp_path: Path) -> None:
    orch = Orchestrator("r1", runs_root=tmp_path, env="dev")
    seed_artifact(orch, Gate.OUTLINE)
    assert not orch.is_draft_first
    orch.approve(Gate.OUTLINE, approver="Ada")
    assert state_of(orch, Gate.OUTLINE) is ApprovalState.CURRENT

    # The same stage re-run writes another file: the file-bound approval no longer counts.
    seed_artifact(orch, Gate.OUTLINE, marker="again")
    assert state_of(orch, Gate.OUTLINE) is ApprovalState.CHANGED


# ---------------------------------------------------------------------------
# 4. The brief approval
# ---------------------------------------------------------------------------


def test_a_thin_message_without_an_accepted_risk_is_refused_and_writes_nothing(
    tmp_path: Path,
) -> None:
    orch = draft_first_run(tmp_path)
    with pytest.raises(DraftBriefError, match="km2"):
        finalise_draft_brief(orch, approver="Ada")
    with pytest.raises(DraftBriefError, match="km2"):
        finalise_draft_brief(orch, approver="Ada", accepted_risks={"km1": "irrelevant"})
    assert orch.ir.latest_brief_version() is None
    assert "brief" not in orch.state.approvals


def test_an_accepted_risk_records_the_probe_note_and_the_approver(tmp_path: Path) -> None:
    orch = draft_first_run(tmp_path)
    brief = finalise_draft_brief(orch, approver="Ada", accepted_risks={"km2": ""})
    assert [(r.message_id, r.description, r.accepted_by) for r in brief.open_risks] == [
        ("km2", "one vendor blog post", "Ada")
    ]
    assert brief.approved_by == "Ada"
    assert orch.ir.latest_brief_version() == brief.version
    # Finalising records a brief; it approves nothing by itself.
    assert "brief" not in orch.state.approvals
    orch.approve(Gate.BRIEF, approver="Ada")
    assert state_of(orch, Gate.BRIEF) is ApprovalState.CURRENT


def test_a_reworded_risk_description_is_kept(tmp_path: Path) -> None:
    orch = draft_first_run(tmp_path)
    brief = finalise_draft_brief(
        orch, approver="Ada", accepted_risks={"km2": "  only one trial  "}
    )
    assert brief.open_risks[0].description == "only one trial"


def test_a_revised_key_message_voids_the_brief_approval(tmp_path: Path) -> None:
    orch = draft_first_run(tmp_path)
    approve_brief(orch)

    draft = load_draft_brief(orch)
    draft.key_messages[0] = draft.key_messages[0].model_copy(update={"text": "Costs fell."})
    save_draft_brief(orch, draft)

    state, detail = orch.approval_state(Gate.BRIEF)
    assert state is not ApprovalState.CURRENT, detail
    assert Gate.BRIEF in orch.pending_gates()


def test_other_substance_changes_also_void_the_brief_approval(tmp_path: Path) -> None:
    orch = draft_first_run(tmp_path)
    approve_brief(orch)
    draft = load_draft_brief(orch)
    draft.must_avoid = ["roadmap", "headcount"]
    save_draft_brief(orch, draft)
    assert state_of(orch, Gate.BRIEF) is not ApprovalState.CURRENT


def test_changing_only_open_risks_or_nothing_keeps_the_brief_approval(tmp_path: Path) -> None:
    from autodeck.ir.models import OpenRisk

    orch = draft_first_run(tmp_path)
    approve_brief(orch)
    assert state_of(orch, Gate.BRIEF) is ApprovalState.CURRENT

    save_draft_brief(orch, load_draft_brief(orch))  # rewritten unchanged
    assert state_of(orch, Gate.BRIEF) is ApprovalState.CURRENT

    draft = load_draft_brief(orch)
    draft.open_risks.append(OpenRisk(message_id="km2", description="x", accepted_by="Ada"))
    save_draft_brief(orch, draft)
    assert state_of(orch, Gate.BRIEF) is ApprovalState.CURRENT


# ---------------------------------------------------------------------------
# 5. The final render needs all three
# ---------------------------------------------------------------------------


def _seed_final(orch: Orchestrator) -> None:
    seed_artifact(orch, Gate.FINAL_RENDER)
    seed_passing_final_assessment(orch)


def test_final_render_is_approved_when_brief_outline_and_claims_are_current(
    tmp_path: Path,
) -> None:
    orch = draft_first_run(tmp_path)
    validated(orch)
    approve_brief(orch)
    orch.approve(Gate.OUTLINE, approver="Ada")
    orch.approve(Gate.CLAIMS, approver="Ada")
    _seed_final(orch)
    orch.approve(Gate.FINAL_RENDER, approver="Ada")
    assert orch.pending_gates() == []


@pytest.mark.parametrize("missing", ["brief", "outline"])
def test_final_render_is_refused_when_brief_or_outline_is_not_approved(
    tmp_path: Path, missing: str
) -> None:
    orch = draft_first_run(tmp_path)
    validated(orch)
    if missing != "brief":
        approve_brief(orch)
    if missing != "outline":
        orch.approve(Gate.OUTLINE, approver="Ada")
    orch.approve(Gate.CLAIMS, approver="Ada")
    assert state_of(orch, Gate.CLAIMS) is ApprovalState.CURRENT
    _seed_final(orch)

    with pytest.raises(ApprovalRefused, match=missing):
        orch.approve(Gate.FINAL_RENDER, approver="Ada")
    assert "final_render" not in orch.state.approvals


def test_final_render_is_refused_when_an_approved_brief_or_outline_went_stale(
    tmp_path: Path,
) -> None:
    orch = draft_first_run(tmp_path)
    validated(orch)
    approve_brief(orch)
    orch.approve(Gate.OUTLINE, approver="Ada")
    orch.approve(Gate.CLAIMS, approver="Ada")
    _seed_final(orch)

    draft = load_draft_brief(orch)
    draft.objective = "Decide something else."
    save_draft_brief(orch, draft)
    assert state_of(orch, Gate.CLAIMS) is ApprovalState.CURRENT
    with pytest.raises(ApprovalRefused, match="brief"):
        orch.approve(Gate.FINAL_RENDER, approver="Ada")

    approve_brief(orch)  # the person re-approves the brief as it now stands
    # Re-shape the outline while keeping the facts, so claims stay current.
    latest = orch.ir.load()
    reshaped = latest.model_copy(
        update={"version": orch.ir.next_version(), "slides": list(reversed(latest.slides))}
    )
    orch.save_ir(reshaped)
    with pytest.raises(ApprovalRefused, match="outline"):
        orch.approve(Gate.FINAL_RENDER, approver="Ada")


# ---------------------------------------------------------------------------
# 6. The CLI
# ---------------------------------------------------------------------------


def _cli(*args: str) -> object:
    return CliRunner().invoke(app, list(args))


def test_cli_approves_a_draft_first_brief_with_an_accepted_risk(tmp_path: Path) -> None:
    draft_first_run(tmp_path)
    result = _cli(
        "approve",
        "r1",
        "brief",
        "--accept-risk",
        "km2",
        "--by",
        "Ada",
        "--runs-root",
        str(tmp_path),
    )
    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    orch = Orchestrator("r1", runs_root=tmp_path, create=False)
    assert "Ada" in orch.state.approvals["brief"]
    brief = orch.ir.load_brief()
    assert [(r.message_id, r.accepted_by) for r in brief.open_risks] == [("km2", "Ada")]


def test_cli_accept_risk_may_carry_a_description(tmp_path: Path) -> None:
    draft_first_run(tmp_path)
    result = _cli(
        "approve", "r1", "brief", "--accept-risk", "km2=one trial only", "--by", "Ada",
        "--runs-root", str(tmp_path),
    )  # fmt: skip
    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    brief = Orchestrator("r1", runs_root=tmp_path, create=False).ir.load_brief()
    assert brief.open_risks[0].description == "one trial only"


def test_cli_refuses_a_thin_message_without_accept_risk_and_records_nothing(
    tmp_path: Path,
) -> None:
    draft_first_run(tmp_path)
    result = _cli("approve", "r1", "brief", "--by", "Ada", "--runs-root", str(tmp_path))
    assert result.exit_code == 1  # type: ignore[attr-defined]
    orch = Orchestrator("r1", runs_root=tmp_path, create=False)
    assert orch.state.approvals == {}
    assert orch.ir.latest_brief_version() is None


def test_cli_accept_risk_is_ignored_on_a_gate_first_run(tmp_path: Path) -> None:
    orch = Orchestrator("r1", runs_root=tmp_path, env="dev")
    seed_artifact(orch, Gate.BRIEF)
    assert not orch.is_draft_first
    before = orch.ir.latest_brief_version()
    result = _cli(
        "approve",
        "r1",
        "brief",
        "--accept-risk",
        "km9",
        "--by",
        "Ada",
        "--runs-root",
        str(tmp_path),
    )
    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
    reloaded = Orchestrator("r1", runs_root=tmp_path, create=False)
    assert reloaded.ir.latest_brief_version() == before  # no brief was built from a draft
    assert reloaded.ir.load_brief().open_risks == []
    assert "Ada" in reloaded.state.approvals["brief"]


def test_cli_render_refuses_when_the_outline_is_not_approved(tmp_path: Path) -> None:
    orch = draft_first_run(tmp_path)
    validated(orch)
    approve_brief(orch)
    orch.approve(Gate.CLAIMS, approver="Ada")
    assert state_of(orch, Gate.OUTLINE) is ApprovalState.PENDING

    result = _cli("render", "r1", "--runs-root", str(tmp_path))
    assert result.exit_code == 3, result.output  # type: ignore[attr-defined]
    assert not orch.paths.deck_pptx.exists()


# ---------------------------------------------------------------------------
# 7. The UI route
# ---------------------------------------------------------------------------


@pytest.fixture
def roots(tmp_path: Path) -> Roots:
    (tmp_path / "knowledge" / "projects" / "proj").mkdir(parents=True)
    return Roots(
        knowledge=tmp_path / "knowledge",
        corpus=tmp_path / "corpus",
        runs=tmp_path / "runs",
        env="dev",
        profile=tmp_path / "profile.json",
    )


def test_ui_refuses_the_brief_on_a_gate_first_run(roots: Roots) -> None:
    seed_artifact(Orchestrator("r1", runs_root=roots.runs, env="dev"), Gate.BRIEF)
    with pytest.raises(UIError) as caught:
        approve_gate(roots, "r1", "brief", approver="Ada")
    assert caught.value.status == 400


def test_ui_brief_on_a_draft_first_run_needs_the_risk_accepted(roots: Roots) -> None:
    orch = draft_first_run(roots.runs)
    with pytest.raises(UIError) as caught:
        approve_gate(roots, "r1", "brief", approver="Ada")
    assert caught.value.status == 409
    assert orch.ir.latest_brief_version() is None

    result = approve_gate(roots, "r1", "brief", approver="Ada", accepted_risks={"km2": ""})
    assert result["gate"] == "brief" and result["by"] == "Ada"
    reloaded = Orchestrator("r1", runs_root=roots.runs, create=False)
    assert state_of(reloaded, Gate.BRIEF) is ApprovalState.CURRENT


def test_ui_approval_on_a_draft_first_run_starts_no_follow_up_job(roots: Roots) -> None:
    draft_first_run(roots.runs)
    profile.save_profile(roots.profile, "Ada")
    ui = App(roots, fake_jobs({}))

    brief = ui.approve_run("r1", {"gate": "brief", "accepted_risks": {"km2": ""}})
    outline = ui.approve_run("r1", {"gate": "outline"})
    assert brief["job"] is None and outline["job"] is None
    assert not ui.jobs.running("r1")
    assert ui.jobs.wait("r1") is None  # nothing was ever started


def test_ui_approval_on_a_gate_first_run_still_starts_its_follow_up(roots: Roots) -> None:
    seed_artifact(Orchestrator("r1", runs_root=roots.runs, env="dev"), Gate.OUTLINE)
    profile.save_profile(roots.profile, "Ada")
    ui = App(roots, fake_jobs({}))
    result = ui.approve_run("r1", {"gate": "outline"})
    assert result["job"] is not None
    ui.jobs.wait("r1")


# ---------------------------------------------------------------------------
# 8. No draft path writes deck.pptx
# ---------------------------------------------------------------------------


def test_compose_and_preview_write_no_final_deck_and_leave_all_four_gates_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def build(deck: Deck, tokens: object, out_path: Path) -> dict[str, str]:
        presentation = Presentation()
        for _ in deck.slides:
            presentation.slides.add_slide(presentation.slide_layouts[6])
        presentation.save(str(out_path))
        return {}

    monkeypatch.setattr(render_draft_module, "_build_pptx", build)
    monkeypatch.setattr(
        render_draft_module,
        "render_pptx",
        lambda *a, **k: (_ for _ in ()).throw(RenderError("no libreoffice")),
    )
    tokens = tokens_for()
    monkeypatch.setattr("autodeck.cli.DesignTokens.load", lambda _p: tokens)

    orch = draft_first_run(tmp_path)
    result = _cli("preview", "r1", "--runs-root", str(tmp_path))
    assert result.exit_code == 0, result.output  # type: ignore[attr-defined]

    orch = Orchestrator("r1", runs_root=tmp_path, create=False)
    assert orch.is_draft_first and orch.state.is_complete("preview")
    assert not orch.paths.deck_pptx.exists()
    assert {p.name for p in orch.paths.root.rglob("*.pptx")} == {"draft.pptx"}
    assert orch.pending_gates() == list(Gate)
    assert len(list(Gate)) == 4
