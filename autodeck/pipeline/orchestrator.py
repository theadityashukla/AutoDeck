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

**The render guard is the enforcement point for A3 and A5.** `assess_render_safety` is the
single place that knows what "safe to render" means, and it exists because a deck that
validates clean is no longer evidence that the invariants hold — see `require_safe_to_render`
for the two traps it closes. Three checks at three call sites is how one of them gets
forgotten, and GATE 2 was the second site until it was made to read this one.

It takes a deck and nothing else. The linter reports it consults are pure functions of that
deck, so they are computed here rather than accepted from a caller who can hand over the
wrong ones — an empty report, or another deck's.

Owning phase: 0 (task 0.7); the four real gates are wired in Phases 2a, 2b and 4, and the
render guard in Phase 2b (task 2b.8).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from autodeck.audit.framing_linter import FramingReport, lint_framing
from autodeck.audit.numeric_linter import NumericReport, lint_deck
from autodeck.audit.verdicts import ClaimBlock, blocking_blocks, unverified_claims
from autodeck.ir.actions import facts_digest
from autodeck.ir.models import Deck
from autodeck.ir.store import IRStore, IRStoreError, RunPaths, run_paths

DEFAULT_RUNS_ROOT = Path("runs")


class GateBlocked(RuntimeError):
    """A human gate has been reached and not approved.

    Raised, never logged. This is the mechanism behind A7, and a caught-and-ignored
    exception here would make the pipeline look compliant while approving its own work.

    `reason` is for the cases where an approval exists on disk but does not count: it was
    recorded before approvals were bound to an artifact, or the artifact changed after it
    was given. Either way the remedy is the same — look at what is there now and approve it.
    """

    def __init__(self, gate: Gate, run_id: str, *, reason: str | None = None) -> None:
        lead = (
            f"GATE '{gate.value}' is not approved for run {run_id!r}: {reason} "
            if reason
            else f"GATE '{gate.value}' requires human approval before run {run_id!r} "
            "continues. "
        )
        super().__init__(
            lead + f"Review the artifacts under runs/{run_id}/ and record approval with "
            f"`autodeck approve {run_id} {gate.value}`. The pipeline never self-approves "
            "(A7)."
        )
        self.gate = gate
        self.run_id = run_id
        self.reason = reason


class ArtifactMissing(RuntimeError):
    """A gate was asked to cover an artifact that does not exist yet.

    An approval is a statement about a specific thing. `approve` on a gate whose stage has
    not run would record a statement about nothing, which a later stage would then read as
    permission.
    """

    def __init__(self, gate: Gate, run_id: str, what: str) -> None:
        super().__init__(
            f"cannot approve GATE '{gate.value}' for run {run_id!r}: {what}. Nothing was "
            "recorded."
        )
        self.what = what
        self.gate = gate
        self.run_id = run_id


class ApprovalRefused(RuntimeError):
    """A gate's artifact exists, but approving it now would be approving the wrong thing.

    Distinct from `ArtifactMissing` (nothing to approve) and `GateBlocked` (a later stage
    needs an approval that is not there): here the owner asked to approve, and a
    precondition the gate depends on does not hold. Nothing is recorded.
    """

    def __init__(self, gate: Gate, run_id: str, reason: str) -> None:
        super().__init__(
            f"cannot approve GATE '{gate.value}' for run {run_id!r}: {reason} Nothing was "
            "recorded."
        )
        self.gate = gate
        self.run_id = run_id
        self.reason = reason


class UnknownRunError(RuntimeError):
    """A command that works on an existing run was given an id with no run directory."""

    def __init__(self, run_id: str, runs_root: Path) -> None:
        super().__init__(
            f"no such run {run_id!r} under {runs_root}. Runs are created by `autodeck "
            "plan`; check the id with `ls` on the runs directory."
        )
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
    ir_version: int | None = None
    """The IR version this stage wrote, when it wrote one. A gate's fingerprint is taken
    from this file, so it names the version the stage produced rather than whichever is
    newest by the time somebody approves."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "finished_at": self.finished_at,
            "ir_version": self.ir_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StageRecord:
        return cls(
            name=payload["name"],
            status=StageStatus(payload.get("status", "pending")),
            detail=payload.get("detail", ""),
            finished_at=payload.get("finished_at"),
            ir_version=payload.get("ir_version"),
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
    """Gate value -> "<ISO timestamp> by <approver>"."""
    fingerprints: dict[str, str] = field(default_factory=dict)
    """Gate value -> sha256 of the artifact that was approved. An approval with no entry
    here is from before approvals were bound to an artifact, and does not count."""
    final_assessment: dict[str, Any] = field(default_factory=dict)
    """What `autodeck gate3` last concluded:
    `{"digest": <canonical_pptx_digest>, "passes": bool, "at": <ISO>}`. Written only by
    `record_final_assessment`. Empty until `gate3` has run."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "env": self.env,
            "stages": {name: record.to_dict() for name, record in self.stages.items()},
            "approvals": dict(self.approvals),
            "fingerprints": dict(self.fingerprints),
            "final_assessment": dict(self.final_assessment),
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
            fingerprints=dict(payload.get("fingerprints") or {}),
            final_assessment=dict(payload.get("final_assessment") or {}),
        )

    def is_complete(self, stage: str) -> bool:
        record = self.stages.get(stage)
        return record is not None and record.status is StageStatus.COMPLETED

    def is_approved(self, gate: Gate) -> bool:
        """Whether an approval *bound to an artifact* is on record.

        Says nothing about whether that artifact is still the current one — only
        `Orchestrator.require_gate` compares against the disk. An approval without a
        fingerprint (an old `state.json`) is "approved, fingerprint unknown", and unknown
        is not approved.
        """
        return gate.value in self.approvals and gate.value in self.fingerprints


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ApprovalState(StrEnum):
    """Where one gate stands, as the disk says it does right now."""

    PENDING = "pending"
    """Nothing approved."""
    CURRENT = "current"
    """Approved, and the artifact is byte-for-byte what was approved."""
    CHANGED = "changed"
    """Approved, but the artifact is not what was approved any more."""
    UNBOUND = "unbound"
    """An approval from before approvals named an artifact. Counts as not approved."""
    NO_ARTIFACT = "no-artifact"
    """Approved, but the artifact it covered is not there to compare against."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Orchestrator:
    """Runs stages in order, persisting state and stopping at unapproved gates."""

    def __init__(
        self,
        run_id: str,
        *,
        runs_root: Path = DEFAULT_RUNS_ROOT,
        env: str = "dev",
        create: bool = True,
    ) -> None:
        """Open a run.

        Args:
            create: make the run directory if it is absent. Only the commands that *start*
                a run (`plan`, the Phase 0 stub) pass True; every other command passes
                False, so a mistyped run id is an error rather than a new empty run that
                `status` then reports as "not started" and `approve` then accepts.

        Raises:
            UnknownRunError: `create` is False and there is no such run.
        """
        self.run_id = run_id
        try:
            self.paths: RunPaths = run_paths(runs_root, run_id)
        except IRStoreError:
            raise UnknownRunError(run_id, Path(runs_root)) from None
        if create:
            self.paths.ensure()
        elif not self.paths.root.is_dir():
            raise UnknownRunError(run_id, Path(runs_root))
        self.ir = IRStore(runs_root, run_id)
        self.state = self._load_state(env)
        self._produced_ir: int | None = None

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

    def save_ir(self, deck: Deck, *, overwrite: bool = False) -> Path:
        """Save an IR version on behalf of the stage that is running.

        The stage's record remembers which version it wrote, and that is the file a gate's
        fingerprint is taken from. A stage that saves through `self.ir` directly still
        works, but the gate that covers it will report its artifact as missing.
        """
        path = self.ir.save(deck, overwrite=overwrite)
        self._produced_ir = deck.version
        return path

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
        self._produced_ir = None
        try:
            record.detail = work()
        except Exception as exc:
            record.status = StageStatus.FAILED
            record.detail = f"{type(exc).__name__}: {exc}"
            record.finished_at = _now()
            self.save_state()
            raise

        record.status = StageStatus.COMPLETED
        record.ir_version = self._produced_ir
        record.finished_at = _now()
        self.save_state()
        return True

    # -- gates -------------------------------------------------------------

    def current_fingerprint(self, gate: Gate) -> str:
        """sha256 of the artifact `gate` covers, as it is on disk now.

        - brief: the latest brief file.
        - outline: the IR version the outline stage wrote.
        - claims: the facts of the IR version the validate stage wrote (`facts_digest`),
          valid only while the newest IR has the same facts. A later IR that changes a
          claim, citation, verdict or block text makes the table the owner reviewed stale;
          one that only changes style, component, mode or icons (art direction, the
          aesthetic loop) does not.
        - final_render: `canonical_pptx_digest` of `runs/<run>/deck.pptx`.

        Raises:
            ArtifactMissing: there is nothing to fingerprint yet.
        """
        run = self.run_id
        if gate is Gate.BRIEF:
            version = self.ir.latest_brief_version()
            if version is None:
                raise ArtifactMissing(
                    gate, run, f"the run has no brief. Run `autodeck plan {run}` first"
                )
            return _sha256_file(self.ir.brief_version_path(version))

        if gate is Gate.FINAL_RENDER:
            pptx = self.paths.deck_pptx
            if not pptx.exists():
                raise ArtifactMissing(
                    gate, run, f"there is no rendered deck at {pptx}. Render it first"
                )
            from autodeck.audit.manifest import canonical_pptx_digest

            return canonical_pptx_digest(pptx)

        stage = "outline" if gate is Gate.OUTLINE else "validate"
        command = f"autodeck {stage} {run}"
        record = self.state.stages.get(stage)
        if record is None or record.status is not StageStatus.COMPLETED:
            raise ArtifactMissing(
                gate, run, f"the {stage} stage has not completed. Run `{command}` first"
            )
        if record.ir_version is None or not self.ir.version_path(record.ir_version).exists():
            raise ArtifactMissing(
                gate,
                run,
                f"the {stage} stage did not record the IR version it wrote (a run from "
                f"before approvals were bound to artifacts). Re-run `{command}`",
            )
        if gate is Gate.CLAIMS:
            # Bound to the deck's facts, not to an IR file: art direction and the aesthetic
            # loop write fact-identical IR versions that must not void the approval.
            latest = self.ir.latest_version()
            try:
                validated = facts_digest(self.ir.load(record.ir_version))
                latest_digest = facts_digest(self.ir.load(latest))
            except (IRStoreError, ValueError) as unreadable:
                raise ArtifactMissing(
                    gate,
                    run,
                    f"an IR version cannot be read ({unreadable}). Re-run `{command}`",
                ) from unreadable
            if latest_digest != validated:
                raise ArtifactMissing(
                    gate,
                    run,
                    f"the facts changed after validation (IR v{latest}); re-run `{command}`",
                )
            return validated
        return _sha256_file(self.ir.version_path(record.ir_version))

    def approval_state(self, gate: Gate) -> tuple[ApprovalState, str]:
        """Whether `gate`'s approval counts, and if not, why. Reads the disk; writes nothing."""
        if gate.value not in self.state.approvals:
            return ApprovalState.PENDING, "not approved"
        recorded = self.state.fingerprints.get(gate.value)
        if recorded is None:
            return (
                ApprovalState.UNBOUND,
                "this approval was recorded before approvals named the artifact they "
                "cover, so it cannot be checked against anything and does not count. "
                "Re-approve it",
            )
        try:
            current = self.current_fingerprint(gate)
        except ArtifactMissing as missing:
            return ApprovalState.NO_ARTIFACT, missing.what
        if current != recorded:
            return (
                ApprovalState.CHANGED,
                f"the {_ARTIFACT_NAMES[gate]} changed after it was approved; review what "
                "is there now and re-approve it",
            )
        return ApprovalState.CURRENT, "approved"

    def require_gate(self, gate: Gate) -> None:
        """Stop unless `gate` has been approved by a human **for the artifact as it is now**.

        Raises:
            GateBlocked: the gate is not approved, the approval predates fingerprints, or
                the artifact it covered has changed since. Re-running a stage therefore
                invalidates the approval by itself; no code has to remember to clear it.
        """
        state, detail = self.approval_state(gate)
        if state is ApprovalState.CURRENT:
            return
        if state is ApprovalState.PENDING:
            raise GateBlocked(gate, self.run_id)
        raise GateBlocked(gate, self.run_id, reason=f"{detail}.")

    def approve(self, gate: Gate, *, approver: str = "owner") -> None:
        """Record a human approval of the artifact `gate` covers, as it is right now.

        Deliberately a separate operation from running the pipeline. A build cannot call
        this on its own behalf mid-run without that being visible in the code as an
        explicit approval — which is the point.

        The fingerprint is taken here, at approval time, so the approval is a statement
        about these bytes and not about whatever a later stage leaves in their place.

        Raises:
            ArtifactMissing: the gate's artifact does not exist. Nothing is written.
            ApprovalRefused: `Gate.FINAL_RENDER` only, and nothing is written. The claims
                approval is not current (a finished deck cannot be approved on top of claims
                nobody has approved as they now stand); `gate3` has not been run on this
                exact deck (the owner approves what the final audit described, not a deck it
                never saw); or the final audit it recorded did not pass (GATE 3 is the
                visual result *and* a final audit pass).
        """
        fingerprint = self.current_fingerprint(gate)
        if gate is Gate.FINAL_RENDER:
            self._check_final_render_preconditions(fingerprint)
        self.state.approvals[gate.value] = f"{_now()} by {approver}"
        self.state.fingerprints[gate.value] = fingerprint
        self.save_state()

    def _check_final_render_preconditions(self, deck_digest: str) -> None:
        gate = Gate.FINAL_RENDER
        run = self.run_id
        claims_state, claims_detail = self.approval_state(Gate.CLAIMS)
        if claims_state is not ApprovalState.CURRENT:
            raise ApprovalRefused(
                gate,
                run,
                f"the claims approval does not count: {claims_detail}. "
                f"Run `autodeck gate2 {run}`, review the claims, and `autodeck approve {run} "
                "claims` first.",
            )
        assessment = self.state.final_assessment
        if not assessment or assessment.get("digest") != deck_digest:
            raise ApprovalRefused(
                gate,
                run,
                f"the final audit has not been run on this deck. Run `autodeck gate3 {run}` "
                "first.",
            )
        if not assessment.get("passes"):
            raise ApprovalRefused(
                gate,
                run,
                "the final audit did not pass on this deck. Fix what it reports, then "
                f"re-run `autodeck render {run}` and `autodeck gate3 {run}`.",
            )

    def record_final_assessment(self, digest: str, passes: bool) -> None:
        """Remember what `gate3` concluded about the deck with `digest`.

        Records a fact about a report; it is not an approval and grants nothing. The latest
        call replaces any earlier one.
        """
        self.state.final_assessment = {"digest": digest, "passes": passes, "at": _now()}
        self.save_state()

    def pending_gates(self) -> list[Gate]:
        """Gates without a *current* approval, in order."""
        return [
            gate for gate in Gate if self.approval_state(gate)[0] is not ApprovalState.CURRENT
        ]


_ARTIFACT_NAMES: dict[Gate, str] = {
    Gate.BRIEF: "brief",
    Gate.OUTLINE: "outline",
    Gate.CLAIMS: "validated claims table",
    Gate.FINAL_RENDER: "rendered deck",
}


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


@dataclass(frozen=True)
class RenderSafety:
    """What every render-safety check says about one deck, computed from that deck.

    Exists so that there is one answer rather than one per caller. `require_safe_to_render`
    raises on exactly `not self.safe`, and `cli._gate2_checks` prints the same four fields
    criterion by criterion — so a GATE 2 screen showing six green ticks and a render stage
    refusing the same deck cannot both be right, because they are the same computation.

    Only `assess_render_safety` builds one, from a `Deck`. There is deliberately no way to
    assemble a `RenderSafety` whose reports describe a different deck than its verdicts do.
    """

    run_id: str
    """The deck's own `run_id`. Every field below was computed from that deck, which is the
    property the guard could not previously state about its arguments."""

    blocking: tuple[ClaimBlock, ...]
    unverified: tuple[ClaimBlock, ...]
    framing: FramingReport
    numeric: NumericReport

    @property
    def reasons(self) -> list[str]:
        """Every reason this deck may not render, in invariant order. Empty when safe."""
        reasons = [f"A3 {block}" for block in self.blocking]
        reasons.extend(
            f"A3 {block} — no verdict; the validator never reached this claim"
            for block in self.unverified
        )
        if self.framing.blocks_build:
            reasons.extend(f"A5 {demotion.summary()}" for demotion in self.framing.demotions)
        if not self.numeric.passes:
            reasons.extend(f"A2 {finding}" for finding in self.numeric.blocking)
        return reasons

    @property
    def safe(self) -> bool:
        return not self.reasons


def assess_render_safety(deck: Deck) -> RenderSafety:
    """Run A1, A2, A3 and A5 over `deck` and return everything they found.

    **The linter reports are computed here, from the deck.** They used to be parameters of
    `require_safe_to_render`, and a parameter can be wrong: `NumericReport()` is a clean
    report of nothing and is one keystroke shorter than `lint_deck(deck)`. Both linters are
    pure, deterministic functions of the deck with no I/O, no model call and no retrieval —
    there was never a reason for a caller to supply them, and every reason for a caller not
    to be able to.

    A3's two clauses are asked separately on purpose. `blocking_blocks` answers the second
    — no final render while a claim is `unsupported` or `contradicted`. `unverified_claims`
    answers the first — *every* claim gets a verdict — and it is a different question:
    `unverified` does not block under `Claim.blocks_render`, correctly, so a validation
    pass that failed outright leaves a deck whose `blocking_blocks()` is empty because
    nothing was ever judged. Absence of a bad verdict is not the presence of a good one.

    Both walk `Deck.claim_sites()`, so a claim on a diagram node is seen by both.
    """
    return RenderSafety(
        run_id=deck.run_id,
        blocking=tuple(blocking_blocks(deck)),
        unverified=tuple(unverified_claims(deck)),
        framing=lint_framing(deck),
        numeric=lint_deck(deck),
    )


def require_safe_to_render(deck: Deck) -> None:
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

    A guard reading only the deck ships that block. So the deck **and** both linter reports
    are consulted, and that is `assess_render_safety`'s job: one function, into which the
    next check goes. Three checks at three call sites is how one of them gets forgotten,
    and the one that gets forgotten is the one that would have fired.

    **This function takes one argument, and that is the fix for a different trap than the
    one the paragraph above describes.** The reports were once parameters with no defaults,
    defended here on the grounds that a caller who omitted one would get the trap back
    silently. The omission was never the risk — nothing compiles without them. The risk was
    the value: on the deck whose only block reads *"The fastest inference stack available,
    proven to cut cost 40%."*, `lint_framing(deck), lint_deck(deck)` blocked with two
    reasons, while `FramingReport(), NumericReport()` passed, and so did another deck's
    clean reports. Neither report carries a run id, deck id or version, so the guard could
    not have noticed. Now there is nothing to pass and nothing to bind: the reports are
    computed from the deck, and the run named in the error is the deck's own.

    Args:
        deck: the deck about to be rendered, verdicts already assigned.

    Raises:
        RenderBlocked: listing every reason, when any of the four conditions fails.
    """
    safety = assess_render_safety(deck)
    if not safety.safe:
        raise RenderBlocked(safety.run_id, safety.reasons)


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
