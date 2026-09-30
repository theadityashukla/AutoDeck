"""The owner's run: A7 integrity and the failures the owner guide exposed.

SCAFFOLD (Opus). Sonnet: implement to these contracts, fill each body, delete every
`@_SCAFFOLD` and `_SCAFFOLD`. Strict xfail — a passing stub still marked fails the suite.

Found by writing `docs/OWNER-GUIDE.md` honestly: every command was run against the real CLI,
and several steps could not be described truthfully because the behaviour was wrong. Two
groups:

**A7 integrity.** An approval is a human's statement about a specific artifact. Today it is
a timestamp and a name with nothing tying it to what was approved, so re-running a stage
after approval silently changes what the approval covers, and `approve` records approval of
artifacts that do not exist. The fix, one design:

- `Orchestrator.approve(gate, approver=…)` records, beside the timestamp and name, the
  **fingerprint of the artifact the gate covers**: brief → sha256 of the current brief file;
  outline → sha256 of the IR version the outline stage produced; claims → sha256 of the IR
  version the validate stage produced; final_render → sha256 of the rendered PPTX's
  `canonical_pptx_digest`. Store it in `state.json`; older `state.json` files without a
  fingerprint are read as "approved, fingerprint unknown" and treated as NOT approved by
  `require_gate` (fail safe, with a message saying re-approve).
- `require_gate(gate)` passes only if the approval's fingerprint equals the current
  artifact's. A mismatch raises `GateBlocked` naming the gate and saying the artifact changed
  after approval. Re-running a stage therefore invalidates the approval automatically; no
  code has to remember to clear it.
- `approve` refuses (clear error, non-zero exit, nothing written) when the gate's artifact
  does not exist yet.
- Every command except `plan` refuses an unknown run id instead of creating an empty run.

**The owner's session on a free tier.**

- Provider failures (`RateLimitError`, `ProviderAuthError`) end a CLI command with a short
  message and exit code 5, never a traceback: which role and model, what it means (daily
  quota resets; or which environment variable is missing), and what has been saved.
- `plan`, `outline`, `content` and `validate` pass the existing
  `autodeck.providers.cache.ResponseCache` rooted at `runs/<run>/cache/`, so re-running a
  command after a quota failure replays completed calls for free and resumes. Do not build a
  second resume mechanism — use the cache that exists.
- `gate2` writes the rendered audit report to `runs/<run>/audit_report.md` every time it runs
  (A6: every deck ships an audit report) and says so.
- `content` reports every dropped block individually — slide, slot, and the first 60
  characters of the sentence — for budget overflows and for `incomplete_slots`, instead of a
  per-slot count that under-reports.
- `status` marks `plan` and `outline` complete when they are.
- `plan` persists the draft brief on `/quit`, `/exit`, Ctrl-C and Ctrl-D, and re-running
  `plan` on the same run id resumes from it, saying so. Signing still happens only by
  `/sign <name>`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from autodeck.cli import app
from autodeck.pipeline.orchestrator import ArtifactMissing, Gate, GateBlocked, Orchestrator
from tests.gate_artifacts import seed_artifact

runner = CliRunner()

_SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")

# -- A7 integrity ---------------------------------------------------------------------------

RUNS = "runs"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_path(orchestrator: Orchestrator, gate: Gate) -> Path:
    """The file whose bytes a gate's fingerprint must equal, found independently of the
    orchestrator's own lookup so the test is not the implementation agreeing with itself."""
    if gate is Gate.BRIEF:
        return orchestrator.paths.brief / "v1.yaml"
    stage = "outline" if gate is Gate.OUTLINE else "validate"
    version = json.loads(orchestrator.paths.state_file.read_text())["stages"][stage][
        "ir_version"
    ]
    return orchestrator.paths.ir / f"v{version}.json"


def _invoke(runs_root: Path, *args: str) -> Result:
    return runner.invoke(app, [*args, "--runs-root", str(runs_root)])


@pytest.mark.parametrize("gate", ["brief", "outline", "claims"])
def test_an_approval_records_the_fingerprint_of_what_was_approved(
    tmp_path: Path, gate: str
) -> None:
    """After approving, `state.json` holds a sha256 for that gate's artifact alongside the
    approver and time."""
    orchestrator = Orchestrator("r1", runs_root=tmp_path)
    seed_artifact(orchestrator, Gate(gate))
    orchestrator.approve(Gate(gate), approver="aditya")

    stored = json.loads(orchestrator.paths.state_file.read_text(encoding="utf-8"))
    assert "aditya" in stored["approvals"][gate]
    assert stored["fingerprints"][gate] == _sha256(_artifact_path(orchestrator, Gate(gate)))
    assert len(stored["fingerprints"][gate]) == 64


def test_rerunning_the_outline_after_approval_invalidates_the_approval(
    tmp_path: Path,
) -> None:
    """Approve outline; re-run the outline stage (new IR bytes); `content` refuses with
    `GateBlocked` whose message says the outline changed after approval. Re-approving
    lets it proceed. The guide found this silently passing."""
    orchestrator = Orchestrator("r1", runs_root=tmp_path)
    seed_artifact(orchestrator, Gate.OUTLINE)
    orchestrator.approve(Gate.OUTLINE)
    orchestrator.require_gate(Gate.OUTLINE)

    # What `autodeck outline` does on a second run: the same IR version, different bytes.
    deck = orchestrator.ir.load(1).model_copy(update={"audience": "a different audience"})
    orchestrator.run_stage(
        "outline", lambda: f"wrote {orchestrator.save_ir(deck, overwrite=True)}", force=True
    )

    with pytest.raises(GateBlocked, match="outline changed after it was approved"):
        Orchestrator("r1", runs_root=tmp_path).require_gate(Gate.OUTLINE)

    # Through the CLI: `content` stops at the gate, exit 3, before it touches anything.
    refused = _invoke(tmp_path, "content", "r1")
    assert refused.exit_code == 3
    assert "outline changed after it was approved" in refused.output
    assert "autodeck approve r1 outline" in refused.output

    # Re-approving is an explicit human act, and it is what lets the run continue.
    approved = _invoke(tmp_path, "approve", "r1", "outline")
    assert approved.exit_code == 0, approved.output
    Orchestrator("r1", runs_root=tmp_path).require_gate(Gate.OUTLINE)


def test_an_approval_without_a_fingerprint_does_not_count(tmp_path: Path) -> None:
    """A `state.json` in the old format (timestamp and name only) is treated as not
    approved, with a message telling the owner to re-approve."""
    orchestrator = Orchestrator("r1", runs_root=tmp_path)
    seed_artifact(orchestrator, Gate.OUTLINE)
    old_format = json.loads(orchestrator.paths.state_file.read_text(encoding="utf-8"))
    old_format.pop("fingerprints")
    old_format["approvals"] = {"outline": "2026-09-01T10:00:00+00:00 by owner"}
    orchestrator.paths.state_file.write_text(json.dumps(old_format), encoding="utf-8")

    reopened = Orchestrator("r1", runs_root=tmp_path)
    assert not reopened.state.is_approved(Gate.OUTLINE)
    assert Gate.OUTLINE in reopened.pending_gates()
    with pytest.raises(GateBlocked, match=r"(?i)re-approve"):
        reopened.require_gate(Gate.OUTLINE)

    status = _invoke(tmp_path, "status", "r1")
    assert status.exit_code == 0, status.output
    assert "NOT CURRENT" in status.output
    assert "Re-approve" in status.output


@pytest.mark.parametrize("gate", ["outline", "claims"])
def test_approving_a_gate_whose_artifact_does_not_exist_is_refused(
    tmp_path: Path, gate: str
) -> None:
    """`autodeck approve <run> <gate>` on a run where that stage never ran exits non-zero,
    names what is missing, and writes nothing to `state.json`. The guide found
    `approve quit-demo claims` succeeding on an empty run."""
    Orchestrator("r1", runs_root=tmp_path)
    state_file = tmp_path / "r1" / "state.json"
    before = state_file.read_bytes() if state_file.exists() else None

    refused = _invoke(tmp_path, "approve", "r1", gate)

    assert refused.exit_code != 0
    stage = "outline" if gate == "outline" else "validate"
    assert f"the {stage} stage has not completed" in refused.output
    assert f"autodeck {stage} r1" in refused.output
    assert (state_file.read_bytes() if state_file.exists() else None) == before

    # The other two gates refuse the same way when their artifacts are absent, directly.
    fresh = Orchestrator("r1", runs_root=tmp_path)
    for other in (Gate.BRIEF, Gate.FINAL_RENDER):
        with pytest.raises(ArtifactMissing):
            fresh.approve(other)
    assert (state_file.read_bytes() if state_file.exists() else None) == before


#: Commands beyond the five the spec names that also work on an existing run. They ride on
#: the `approve` case below rather than adding cases of their own.
_ALSO_NEEDS_A_RUN = (
    ("outline", "--client", "c", "--project", "p"),
    ("send-back", "--claim", "s1:b1", "--reason", "x"),
    ("ir", "versions"),
    ("ir", "diff", "1", "2"),
)


@pytest.mark.parametrize("command", ["approve", "status", "content", "validate", "gate2"])
def test_an_unknown_run_id_is_an_error_not_a_new_run(tmp_path: Path, command: str) -> None:
    """Non-zero exit, message says no such run, and no `runs/<id>/` directory is created."""
    invocations: list[tuple[str, ...]] = [(command,)]
    if command == "approve":
        invocations += list(_ALSO_NEEDS_A_RUN)

    for invocation in invocations:
        head, rest = invocation[0], invocation[1:]
        if head == "ir":
            args = [head, rest[0], "ghost", *rest[1:]]
        elif command == "approve" and head == "approve":
            args = ["approve", "ghost", "brief"]
        else:
            args = [head, "ghost", *rest]
        result = _invoke(tmp_path, *args)

        assert result.exit_code != 0, args
        assert "no such run 'ghost'" in result.output, args
        assert not (tmp_path / "ghost").exists(), args
    assert list(tmp_path.iterdir()) == []


# -- the owner's session ----------------------------------------------------------------------


@_SCAFFOLD
@pytest.mark.parametrize("failure", ["rate limit", "missing key"])
def test_provider_failures_end_with_a_message_not_a_traceback(failure: str) -> None:
    """A fake provider raising `RateLimitError` / `ProviderAuthError` inside `content`: exit
    code 5, output names the role and model and says what to do, and contains no
    "Traceback"."""
    raise NotImplementedError


@_SCAFFOLD
def test_content_resumes_from_the_cache_after_a_quota_failure() -> None:
    """A fake provider that fails on the third slide. First run exits 5. Second run with a
    working provider makes calls only for slides three onward — the first two are replayed
    from `runs/<run>/cache/`. Count provider calls to prove it."""
    raise NotImplementedError


@_SCAFFOLD
def test_gate2_writes_the_audit_report_to_the_run() -> None:
    """After `gate2`, `runs/<run>/audit_report.md` exists and equals the report printed."""
    raise NotImplementedError


@_SCAFFOLD
def test_content_names_every_dropped_block() -> None:
    """Two over-budget claims on one slot: output names both, with slide, slot and the start
    of each sentence — not "1 block(s) dropped"."""
    raise NotImplementedError


@_SCAFFOLD
def test_status_marks_plan_and_outline_complete() -> None:
    """After a signed plan and an outline, `status` shows both as complete."""
    raise NotImplementedError


@_SCAFFOLD
@pytest.mark.parametrize("how", ["/quit", "/exit", "EOF"])
def test_leaving_the_planner_keeps_the_draft_and_resuming_restores_it(how: str) -> None:
    """Draft a brief, leave by `how`; nothing is signed. Re-run `plan` on the same run id:
    `/brief` shows the same draft, and the output says it resumed. `/sign` still required."""
    raise NotImplementedError
