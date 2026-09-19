"""Orchestrator: run directories, resumability, and the A7 gate mechanism.

`test_no_command_can_bypass_a_gate` is an invariant test. A7 says the pipeline never
auto-approves, and the way that dies in practice is someone adding `--yes` to unblock a
demo — so the absence of such a flag is asserted rather than assumed.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from autodeck.audit.framing_linter import FramingReport, lint_framing
from autodeck.audit.manifest import Manifest, build_manifest, hash_prompts
from autodeck.audit.numeric_linter import NumericReport, lint_deck
from autodeck.ir.models import Block, Citation, Claim, Deck, Slide, Verdict
from autodeck.pipeline.orchestrator import (
    Gate,
    GateBlocked,
    Orchestrator,
    RenderBlocked,
    StageStatus,
    assess_render_safety,
    require_safe_to_render,
)


def make(tmp_path: Path, run_id: str = "r1", env: str = "dev") -> Orchestrator:
    return Orchestrator(run_id, runs_root=tmp_path, env=env)


# ---------------------------------------------------------------------------
# A7 — gates block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gate", list(Gate))
def test_an_unapproved_gate_raises(tmp_path: Path, gate: Gate) -> None:
    with pytest.raises(GateBlocked):
        make(tmp_path).require_gate(gate)


def test_an_approved_gate_passes(tmp_path: Path) -> None:
    orchestrator = make(tmp_path)
    orchestrator.approve(Gate.BRIEF)
    orchestrator.require_gate(Gate.BRIEF)  # must not raise


def test_approving_one_gate_does_not_approve_the_others(tmp_path: Path) -> None:
    orchestrator = make(tmp_path)
    orchestrator.approve(Gate.BRIEF)
    assert orchestrator.pending_gates() == [Gate.OUTLINE, Gate.CLAIMS, Gate.FINAL_RENDER]
    with pytest.raises(GateBlocked):
        orchestrator.require_gate(Gate.FINAL_RENDER)


def test_there_are_exactly_four_gates(tmp_path: Path) -> None:
    """A7: planning brief, outline, claims table, final render."""
    assert [g.value for g in Gate] == ["brief", "outline", "claims", "final_render"]
    assert len(make(tmp_path).pending_gates()) == 4


def test_an_approval_records_who_and_when(tmp_path: Path) -> None:
    """An approval is an auditable event on disk, not a boolean in a process."""
    orchestrator = make(tmp_path)
    orchestrator.approve(Gate.CLAIMS, approver="aditya")
    stored = json.loads(orchestrator.paths.state_file.read_text(encoding="utf-8"))
    assert "aditya" in stored["approvals"]["claims"]


def test_approvals_survive_a_restart(tmp_path: Path) -> None:
    make(tmp_path).approve(Gate.OUTLINE)
    assert make(tmp_path).state.is_approved(Gate.OUTLINE)


def test_the_gate_error_says_how_to_approve(tmp_path: Path) -> None:
    with pytest.raises(GateBlocked, match="autodeck approve"):
        make(tmp_path).require_gate(Gate.BRIEF)


def test_no_command_can_bypass_a_gate() -> None:
    """The invariant. No CLI option may approve a gate as a side effect of running.

    `approve` is the only command allowed to record an approval, and it does nothing else.
    """
    from autodeck import cli

    banned = {"yes", "force", "skip_gates", "no_gates", "auto_approve", "approve"}
    for name in ("run", "status"):
        parameters = set(inspect.signature(getattr(cli, name)).parameters)
        assert not (parameters & banned), f"cli.{name} exposes a gate bypass"


# ---------------------------------------------------------------------------
# Stages and resumability
# ---------------------------------------------------------------------------


def test_a_stage_runs_once_and_is_then_skipped(tmp_path: Path) -> None:
    calls: list[int] = []

    def work() -> str:
        calls.append(1)
        return "done"

    orchestrator = make(tmp_path)
    assert orchestrator.run_stage("outline", work) is True
    assert orchestrator.run_stage("outline", work) is False
    assert len(calls) == 1


def test_completion_survives_a_restart(tmp_path: Path) -> None:
    """The point of resumability: a new process skips what already succeeded."""
    make(tmp_path).run_stage("outline", lambda: "done")

    calls: list[int] = []
    resumed = make(tmp_path)
    assert resumed.run_stage("outline", lambda: calls.append(1) or "again") is False
    assert calls == []
    assert resumed.state.is_complete("outline")


def test_force_reruns_a_completed_stage(tmp_path: Path) -> None:
    orchestrator = make(tmp_path)
    orchestrator.run_stage("outline", lambda: "one")
    assert orchestrator.run_stage("outline", lambda: "two", force=True) is True
    assert orchestrator.state.stages["outline"].detail == "two"


def test_a_failing_stage_is_recorded_and_re_raised(tmp_path: Path) -> None:
    orchestrator = make(tmp_path)

    def boom() -> str:
        raise RuntimeError("provider exploded")

    with pytest.raises(RuntimeError, match="provider exploded"):
        orchestrator.run_stage("content", boom)

    record = orchestrator.state.stages["content"]
    assert record.status is StageStatus.FAILED
    assert "provider exploded" in record.detail


def test_a_failed_stage_is_retried_on_resume(tmp_path: Path) -> None:
    """A failure must not be mistaken for completion."""
    orchestrator = make(tmp_path)
    with pytest.raises(RuntimeError):
        orchestrator.run_stage("content", lambda: (_ for _ in ()).throw(RuntimeError("x")))

    assert make(tmp_path).run_stage("content", lambda: "recovered") is True


def test_run_directories_are_created(tmp_path: Path) -> None:
    paths = make(tmp_path).paths
    for directory in (paths.ir, paths.brief, paths.artifacts, paths.logs, paths.llm_cache):
        assert directory.is_dir()


def test_the_environment_is_recorded(tmp_path: Path) -> None:
    """B8: a result is only interpretable alongside the bindings that produced it."""
    make(tmp_path, env="sit").save_state()
    assert make(tmp_path).state.env == "sit"


# ---------------------------------------------------------------------------
# A6 — manifest
# ---------------------------------------------------------------------------


def test_manifest_round_trips(tmp_path: Path) -> None:
    manifest = build_manifest(run_id="r1", env="dev", models={"env": "dev", "roles": {}})
    path = manifest.save(tmp_path / "build_manifest.json")
    assert Manifest.load(path) == manifest


def test_manifest_records_the_environment() -> None:
    assert build_manifest(run_id="r1", env="sit").env == "sit"


def test_two_builds_match_despite_different_timestamps() -> None:
    """A6 compares builds excluding timestamps; otherwise nothing ever matches itself."""
    first = build_manifest(run_id="r1", env="dev")
    second = build_manifest(run_id="r1", env="dev").model_copy(
        update={"created_at": "2030-01-01T00:00:00+00:00"}
    )
    assert first.matches(second)


def test_a_changed_model_binding_breaks_the_match() -> None:
    first = build_manifest(run_id="r1", env="dev", models={"roles": {"content": "a"}})
    second = build_manifest(run_id="r1", env="dev", models={"roles": {"content": "b"}})
    assert not first.matches(second)


def test_prompt_hashes_are_sorted_and_stable(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("second", encoding="utf-8")
    (tmp_path / "a.md").write_text("first", encoding="utf-8")
    hashes = hash_prompts(tmp_path)
    assert list(hashes) == ["a.md", "b.md"]
    assert hashes == hash_prompts(tmp_path)


def test_the_prompts_readme_is_not_hashed(tmp_path: Path) -> None:
    """Documentation under prompts/ is not a prompt; hashing it would make a README edit
    look like a changed build."""
    (tmp_path / "README.md").write_text("how prompts work", encoding="utf-8")
    (tmp_path / "content.md").write_text("the actual prompt", encoding="utf-8")
    assert list(hash_prompts(tmp_path)) == ["content.md"]


def test_editing_a_prompt_changes_its_hash(tmp_path: Path) -> None:
    """Plan §0.5 versions prompts; A6 is what pins which version actually ran."""
    prompt = tmp_path / "content.md"
    prompt.write_text("original", encoding="utf-8")
    before = hash_prompts(tmp_path)
    prompt.write_text("revised", encoding="utf-8")
    assert hash_prompts(tmp_path) != before


def test_manifest_forbids_unknown_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Manifest.model_validate(
            {"run_id": "r", "env": "dev", "created_at": "now", "surprise": True}
        )


# ---------------------------------------------------------------------------
# The render guard — A3 and A5
# ---------------------------------------------------------------------------
#
# The regression these exist for is `test_a_demotion_blocks_while_the_deck_validates_clean`.
# A demoted framing block is one the IR cannot hold, so it stays in the deck typed
# `framing` and `Deck.blocking_blocks()` comes back empty — a guard reading only the deck
# ships it. A test written against a deck that already fails would prove nothing here, so
# every fixture below starts from a deck that validates.


def citation(quote: str) -> Citation:
    return Citation.for_quote(
        doc_id="llm-int8",
        page=4,
        bbox=(72.0, 100.0, 523.0, 200.0),
        quote=quote,
        retrieved_by="writer",
    )


def claim_block(
    block_id: str,
    *,
    text: str = "Quantisation halves inference memory.",
    verdict: Verdict = "supported",
    quote: str = "cut the memory needed for inference by half",
) -> Block:
    return Block(
        id=block_id,
        kind="claim",
        slot="body",
        claim=Claim(text=text, citations=[citation(quote)], verdict=verdict),
    )


def framing_block(text: str, *, block_id: str = "f1") -> Block:
    return Block(id=block_id, kind="framing", slot="kicker", text=text)


def deck_with(*blocks: Block) -> Deck:
    return Deck(
        run_id="r1",
        project="llm-inference-efficiency",
        client="northwind-retail",
        audience="CTO",
        version=1,
        theme_ref="t",
        component_lib_version="1",
        slides=[
            Slide(
                id="s1", narrative_role="evidence", component="text_block", blocks=list(blocks)
            )
        ],
    )


def guard(deck: Deck) -> None:
    """The guard as a caller must use it — and the only way a caller can. One argument."""
    require_safe_to_render(deck)


def test_a_clean_deck_renders(tmp_path: Path) -> None:
    """The guard must let a correct deck through, or it teaches people to route around it."""
    deck = deck_with(claim_block("b1"), framing_block("Serve better before you buy more."))

    guard(deck)  # must not raise


def test_a_demotion_blocks_while_the_deck_validates_clean() -> None:
    """The trap the guard closes, asserted as the deck's own cleanliness.

    A5 demotes this framing block to `claim`, which A1 then refuses — but the IR cannot
    hold the demoted block, so the deck still validates and `blocking_blocks()` is empty. A
    guard consulting only the deck renders a fabricated fact.
    """
    deck = deck_with(
        claim_block("b1"), framing_block("Our approach is clinically shown to cut costs.")
    )

    assert deck.blocking_blocks() == [], "the deck alone looks clean — that is the trap"
    assert lint_framing(deck).blocks_build, "A5 is the only thing that knows"

    with pytest.raises(RenderBlocked) as blocked:
        guard(deck)

    assert {reason.split()[0] for reason in blocked.value.reasons} == {"A5"}, (
        "the demotion is the only thing blocking — nothing else in this deck fails"
    )


def test_a_contradicted_block_blocks() -> None:
    """A3's second clause, through `Deck.blocking_blocks()`."""
    deck = deck_with(claim_block("b1", verdict="contradicted"))

    with pytest.raises(RenderBlocked, match="A3"):
        guard(deck)


def test_an_unjudged_claim_blocks() -> None:
    """A3's first clause: every claim gets a verdict.

    `unverified` blocks nothing under `Claim.blocks_render`, so a validation pass that
    failed outright leaves a deck that looks exactly like a validated one.
    """
    deck = deck_with(claim_block("b1", verdict="unverified"))

    assert deck.blocking_blocks() == []

    with pytest.raises(RenderBlocked) as blocked:
        guard(deck)

    assert "never reached this claim" in str(blocked.value)


def test_an_untraceable_numeral_blocks() -> None:
    """A2, via the numeric report — the third thing the deck cannot tell you."""
    deck = deck_with(claim_block("b1", text="Serving costs fell 40% in the pilot."))

    assert deck.blocking_blocks() == []

    with pytest.raises(RenderBlocked, match="A2"):
        guard(deck)


def test_every_reason_is_reported_at_once() -> None:
    """One blocked build, not a queue of surprises: a guard that reports the first failure
    only makes the writer fix three things in three runs."""
    deck = deck_with(
        claim_block("b1", verdict="contradicted"),
        claim_block("b2", text="Serving costs fell 40% in the pilot."),
        framing_block("Our approach is clinically shown to cut costs."),
    )

    with pytest.raises(RenderBlocked) as blocked:
        guard(deck)

    prefixes = {reason.split()[0] for reason in blocked.value.reasons}
    assert prefixes == {"A2", "A3", "A5"}


# ---------------------------------------------------------------------------
# The guard cannot be handed the wrong reports, because it cannot be handed any
# ---------------------------------------------------------------------------
#
# The deck below is the attack's: its one block is `framing` and reads "The fastest
# inference stack available, proven to cut cost 40%." — a superlative, a named-proof
# phrase and a numeral, none of them citable. `lint_framing(deck), lint_deck(deck)`
# blocked it with two reasons. `FramingReport(), NumericReport()` passed it, and so did a
# clean deck's reports, because neither report carries a run id, deck id or version for
# the guard to check.

FABRICATED = "The fastest inference stack available, proven to cut cost 40%."


def test_the_fabricated_framing_block_is_blocked() -> None:
    """The honest call, which was always fine. Here so the tests below mean something."""
    with pytest.raises(RenderBlocked) as blocked:
        guard(deck_with(framing_block(FABRICATED)))

    # A5 for the superlative and the named proof, A2 for the 40% no citation can reach.
    assert {reason.split()[0] for reason in blocked.value.reasons} == {"A2", "A5"}


def test_the_guard_takes_the_deck_and_nothing_else() -> None:
    """The invariant, in the shape `test_no_command_can_bypass_a_gate` uses it.

    Not "the reports have no defaults" — the omission was never the risk, since nothing
    compiles without them. The risk was the value, so there is no value to supply.
    """
    parameters = inspect.signature(require_safe_to_render).parameters

    assert list(parameters) == ["deck"]
    assert parameters["deck"].annotation in (Deck, "Deck")


@pytest.mark.parametrize(
    "reports",
    [
        pytest.param({"framing": FramingReport(), "numeric": NumericReport()}, id="empty"),
        pytest.param(
            {
                "framing": lint_framing(deck_with(framing_block("The question is cost."))),
                "numeric": lint_deck(deck_with(framing_block("The question is cost."))),
            },
            id="another-deck",
        ),
    ],
)
def test_reports_cannot_be_passed_to_the_guard_at_all(reports: dict[str, object]) -> None:
    """Both attack calls, verbatim, now fail to call rather than passing the deck."""
    bad = deck_with(framing_block(FABRICATED))

    with pytest.raises(TypeError):
        require_safe_to_render(bad, **reports)  # type: ignore[arg-type]

    with pytest.raises(RenderBlocked):
        require_safe_to_render(bad)


def test_the_default_path_recomputes_the_reports_from_the_deck() -> None:
    """The seam is not merely hard to misuse; there is nothing to inject.

    `assess_render_safety` is handed only a deck, and the reports it returns are that
    deck's: the demotion names the fabricated block, and the run id is the deck's own.
    """
    bad = deck_with(claim_block("b1"), framing_block(FABRICATED))

    safety = assess_render_safety(bad)

    assert safety.run_id == bad.run_id
    assert [d.block_id for d in safety.framing.demotions] == ["f1"]
    assert not safety.numeric.passes or safety.framing.blocks_build
    assert not safety.safe
    assert list(inspect.signature(assess_render_safety).parameters) == ["deck"]


def test_a_clean_deck_assesses_safe() -> None:
    safety = assess_render_safety(deck_with(claim_block("b1")))

    assert safety.safe
    assert safety.reasons == []


def test_there_is_one_guard_and_not_three() -> None:
    """One function knows what 'safe to render' means, and one function computes it.

    `cli._gate2_checks` re-implemented three of these four conditions until it was made to
    read `assess_render_safety` too — which is the failure the guard's own docstring warns
    about, having already happened.
    """
    source = inspect.getsource(assess_render_safety)
    for consulted in ("blocking_blocks", "unverified_claims", "lint_framing", "lint_deck"):
        assert consulted in source

    assert "assess_render_safety" in inspect.getsource(require_safe_to_render)

    from autodeck.cli import _gate2_checks

    # Its body, not its docstring, which discusses the functions it must not call.
    gate2_body = inspect.getsource(_gate2_checks).split('"""')[2]
    assert "safety." in gate2_body
    for recomputed in ("blocking_blocks(", "unverified_claims(", "lint_deck(", "lint_framing("):
        assert recomputed not in gate2_body, (
            "GATE 2 is deriving render safety for itself again — it and the render stage "
            "will disagree, and the screen that disagrees is the one a human approves"
        )
