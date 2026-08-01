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

from autodeck.audit.manifest import Manifest, build_manifest, hash_prompts
from autodeck.pipeline.orchestrator import (
    Gate,
    GateBlocked,
    Orchestrator,
    StageStatus,
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
