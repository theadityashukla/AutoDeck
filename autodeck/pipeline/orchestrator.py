"""Pipeline orchestration: run directories, resumability, the human gates (A7), and the
one guard that decides whether a deck is safe to render (A3, A5).

Three responsibilities, and two of them are accuracy invariants.

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

**The render guard is the enforcement point for A3 and A5.** `require_safe_to_render` is
the single place that knows what "safe to render" means, and it exists because a deck that
validates clean is no longer evidence that the invariants hold — see its docstring for the
trap it closes. Three checks at three call sites is how one of them gets forgotten.

Owning phase: 0 (task 0.7); the four real gates are wired in Phases 2a, 2b and 4, and the
render guard in Phase 2b (task 2b.8).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from autodeck.audit.framing_linter import FramingReport
from autodeck.audit.numeric_linter import NumericReport
from autodeck.audit.verdicts import blocking_blocks, unverified_claims
from autodeck.ir.models import Deck
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
# The render guard — A3 and A5's enforcement point
# ---------------------------------------------------------------------------


class RenderBlocked(RuntimeError):
    """The deck is not safe to render, and every reason it is not.

    Raised rather than returned so that the render stage cannot proceed by ignoring a
    boolean, and carrying **all** the reasons rather than the first: a guard that reports
    one failure at a time turns a blocked build into a queue of surprises, and the writer
    fixes three things in three runs instead of three things in one.
    """

    def __init__(self, run_id: str | None, reasons: list[str]) -> None:
        where = f" for run {run_id!r}" if run_id else ""
        super().__init__(
            f"Final render is blocked{where} by {len(reasons)} finding(s):\n"
            + "\n".join(f"  - {reason}" for reason in reasons)
            + "\n\nA3 forbids rendering an unsupported or contradicted claim; A5's "
            "demotions are claims with no citation, which A1 forbids outright. Fix the "
            "content or re-validate — no flag skips this, for the same reason no flag "
            "skips a gate."
        )
        self.run_id = run_id
        self.reasons = reasons


def require_safe_to_render(
    deck: Deck,
    *,
    framing: FramingReport,
    numeric: NumericReport,
    run_id: str | None = None,
) -> None:
    """Refuse to enter the render stage unless A1, A2, A3 and A5 all hold over this deck.

    **A clean `Deck` is not sufficient evidence that the invariants hold, and that is the
    trap this function exists to close.** The framing linter (A5) demotes a `framing` block
    carrying a fabricated fact to `claim` — a real state change, whose `materialise()`
    raises pydantic's `ValidationError` from `Claim.citations` exactly as A1 requires. But
    the IR cannot *hold* that demoted block, so the block stays in the deck typed `framing`,
    validating perfectly, and `Deck.blocking_blocks()` comes back empty. Measured on a deck
    with one demotion:

        framing findings: 2 | blocks_build: True
        demoted kind: claim | verdict: unsupported | blocks_render: True
        Deck.blocking_blocks(): []          <- empty. The deck alone looks clean.

    A guard reading only the deck ships that block. So this function reads the deck **and**
    the two linter reports, and it is one function on purpose: the next check to be added
    goes inside it, not at a call site. Three checks at three call sites is how one of them
    gets forgotten, and the one that gets forgotten is the one that would have fired.

    `framing` and `numeric` have no defaults for the same reason. A caller who omits a
    report would get the trap straight back, silently, and a passing build is exactly what
    that failure looks like.

    Args:
        deck: the deck about to be rendered, verdicts already assigned.
        framing: `lint_framing(deck)` — A5. Its demotions are invisible in the deck.
        numeric: `lint_deck(deck)` — A2. Blocking findings are unmatched numerals and
            derivations that do not re-execute.
        run_id: named in the error when there is one; the guard works without a run.

    Raises:
        RenderBlocked: listing every reason, when any of the four conditions fails.
    """
    reasons: list[str] = []

    # A3, second clause: no final render while any block is unsupported or contradicted.
    reasons.extend(f"A3 {block}" for block in blocking_blocks(deck))

    # A3, first clause: *every* claim gets a verdict. `unverified` is not one of the four
    # and does not block under `Claim.blocks_render` — correctly, since that method answers
    # the second clause — so a validation pass that failed outright leaves a deck whose
    # `blocking_blocks()` is empty because nothing was ever judged. Same trap, different
    # linter: absence of a bad verdict is not the presence of a good one.
    reasons.extend(
        f"A3 {block} — no verdict; the validator never reached this claim"
        for block in unverified_claims(deck)
    )

    # A5, and through it A1: the blocks the deck could not be made to carry. The report's
    # own `blocks_build` is the condition; the demotions are the detail a writer needs.
    if framing.blocks_build:
        reasons.extend(f"A5 {demotion.summary()}" for demotion in framing.demotions)

    # A2: an unmatched numeral or a derivation that does not re-execute.
    if not numeric.passes:
        reasons.extend(f"A2 {finding}" for finding in numeric.blocking)

    if reasons:
        raise RenderBlocked(run_id, reasons)


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
