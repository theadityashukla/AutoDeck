"""Pipeline orchestration: run directories, resumability, and the human gates (A7).

Two responsibilities, and the second is an accuracy invariant.

**Resumability.** Every stage records completion in `runs/<run_id>/state.json`, so a run
interrupted by a rate limit, a crash, or a gate resumes from where it stopped rather than
re-running work that has already produced artifacts. Combined with the provider cache
(task 0.3), a resumed run costs nothing for the stages that already succeeded.

**Gates block.** A7 requires four human approvals per deck — planning brief, outline,
post-validation claims table, final render — and says the pipeline never auto-approves. So
a gate raises `GateBlocked` and the run stops. It does not warn, it does not log and
continue, and there is **no flag that skips it**: `tests/test_orchestrator.py` asserts that
no such flag exists, because the obvious way this invariant dies is someone adding `--yes`
for a demo.

Owning phase: 0 (task 0.7); the four real gates are wired in Phases 2a, 2b and 4.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from autodeck.ir.store import IRStore, RunPaths, run_paths

DEFAULT_RUNS_ROOT = Path("runs")


class GateBlocked(RuntimeError):
    """A human gate has been reached and not approved.

    Raised, never logged. This is the mechanism behind A7, and a caught-and-ignored
    exception here would make the pipeline look compliant while approving its own work.
    """

    def __init__(self, gate: Gate, run_id: str) -> None:
        super().__init__(
            f"GATE '{gate.value}' requires human approval before run {run_id!r} continues. "
            f"Review the artifacts under runs/{run_id}/ and record approval with "
            f"`autodeck approve {run_id} {gate.value}`. The pipeline never self-approves "
            "(A7)."
        )
        self.gate = gate
        self.run_id = run_id


class Gate(StrEnum):
    """The four per-deck approvals of A7, in the order a build reaches them.

    Distinct from the six build-time GATEs in `docs/BRANCHING.md`, which gate the *project*
    rather than a deck. `docs/BRANCHING.md` warns against conflating them.
    """

    BRIEF = "brief"
    OUTLINE = "outline"
    CLAIMS = "claims"
    FINAL_RENDER = "final_render"


class StageStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StageRecord:
    """What happened to one stage."""

    name: str
    status: StageStatus = StageStatus.PENDING
    detail: str = ""
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StageRecord:
        return cls(
            name=payload["name"],
            status=StageStatus(payload.get("status", "pending")),
            detail=payload.get("detail", ""),
            finished_at=payload.get("finished_at"),
        )


@dataclass
class RunState:
    """Everything needed to resume a run, persisted as `state.json`.

    Approvals are recorded here rather than passed as arguments, so an approval is an
    auditable event on disk with a timestamp — not a boolean that existed only in the
    process that happened to be running.
    """

    run_id: str
    env: str = "dev"
    stages: dict[str, StageRecord] = field(default_factory=dict)
    approvals: dict[str, str] = field(default_factory=dict)
    """Gate value -> ISO timestamp of approval."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "env": self.env,
            "stages": {name: record.to_dict() for name, record in self.stages.items()},
            "approvals": dict(self.approvals),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunState:
        return cls(
            run_id=payload["run_id"],
            env=payload.get("env", "dev"),
            stages={
                name: StageRecord.from_dict(record)
                for name, record in (payload.get("stages") or {}).items()
            },
            approvals=dict(payload.get("approvals") or {}),
        )

    def is_complete(self, stage: str) -> bool:
        record = self.stages.get(stage)
        return record is not None and record.status is StageStatus.COMPLETED

    def is_approved(self, gate: Gate) -> bool:
        return gate.value in self.approvals


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Orchestrator:
    """Runs stages in order, persisting state and stopping at unapproved gates."""

    def __init__(
        self, run_id: str, *, runs_root: Path = DEFAULT_RUNS_ROOT, env: str = "dev"
    ) -> None:
        self.run_id = run_id
        self.paths: RunPaths = run_paths(runs_root, run_id).ensure()
        self.ir = IRStore(runs_root, run_id)
        self.state = self._load_state(env)

    # -- state -------------------------------------------------------------

    def _load_state(self, env: str) -> RunState:
        if self.paths.state_file.exists():
            payload = json.loads(self.paths.state_file.read_text(encoding="utf-8"))
            return RunState.from_dict(payload)
        return RunState(run_id=self.run_id, env=env)

    def save_state(self) -> Path:
        self.paths.state_file.write_text(
            json.dumps(self.state.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        return self.paths.state_file

    # -- stages ------------------------------------------------------------

    def run_stage(self, name: str, work: Callable[[], str], *, force: bool = False) -> bool:
        """Run one stage unless it has already completed.

        Args:
            name: stage identifier, stable across runs — it is the resumability key.
            work: the stage body; returns a short detail string for the state file.
            force: re-run even if already complete.

        Returns:
            True if the stage ran, False if it was skipped as already complete.
        """
        if not force and self.state.is_complete(name):
            return False

        record = StageRecord(name=name)
        self.state.stages[name] = record
        try:
            record.detail = work()
        except Exception as exc:
            record.status = StageStatus.FAILED
            record.detail = f"{type(exc).__name__}: {exc}"
            record.finished_at = _now()
            self.save_state()
            raise

        record.status = StageStatus.COMPLETED
        record.finished_at = _now()
        self.save_state()
        return True

    # -- gates -------------------------------------------------------------

    def require_gate(self, gate: Gate) -> None:
        """Stop unless `gate` has been approved by a human.

        Raises:
            GateBlocked: the gate is not approved.
        """
        if not self.state.is_approved(gate):
            raise GateBlocked(gate, self.run_id)

    def approve(self, gate: Gate, *, approver: str = "owner") -> None:
        """Record a human approval.

        Deliberately a separate operation from running the pipeline. A build cannot call
        this on its own behalf mid-run without that being visible in the code as an
        explicit approval — which is the point.
        """
        self.state.approvals[gate.value] = f"{_now()} by {approver}"
        self.save_state()

    def pending_gates(self) -> list[Gate]:
        """Gates still awaiting approval, in order."""
        return [gate for gate in Gate if not self.state.is_approved(gate)]


# ---------------------------------------------------------------------------
# The stub pipeline (Phase 0 milestone)
# ---------------------------------------------------------------------------

#: The stage sequence a real build will follow. Phase 0 implements the first two and
#: leaves the rest for the phases that own them; the names are fixed now so resumability
#: keys stay stable as the stages are filled in.
STAGE_SEQUENCE: tuple[str, ...] = (
    "ingest",
    "plan",
    "outline",
    "content",
    "validate",
    "art_direction",
    "render",
    "audit",
)
