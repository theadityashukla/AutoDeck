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

import pytest

_SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")

# -- A7 integrity ---------------------------------------------------------------------------


@_SCAFFOLD
@pytest.mark.parametrize("gate", ["brief", "outline", "claims"])
def test_an_approval_records_the_fingerprint_of_what_was_approved(gate: str) -> None:
    """After approving, `state.json` holds a sha256 for that gate's artifact alongside the
    approver and time."""
    raise NotImplementedError


@_SCAFFOLD
def test_rerunning_the_outline_after_approval_invalidates_the_approval() -> None:
    """Approve outline; re-run the outline stage (new IR bytes); `content` refuses with
    `GateBlocked` whose message says the outline changed after approval. Re-approving
    lets it proceed. The guide found this silently passing."""
    raise NotImplementedError


@_SCAFFOLD
def test_an_approval_without_a_fingerprint_does_not_count() -> None:
    """A `state.json` in the old format (timestamp and name only) is treated as not
    approved, with a message telling the owner to re-approve."""
    raise NotImplementedError


@_SCAFFOLD
@pytest.mark.parametrize("gate", ["outline", "claims"])
def test_approving_a_gate_whose_artifact_does_not_exist_is_refused(gate: str) -> None:
    """`autodeck approve <run> <gate>` on a run where that stage never ran exits non-zero,
    names what is missing, and writes nothing to `state.json`. The guide found
    `approve quit-demo claims` succeeding on an empty run."""
    raise NotImplementedError


@_SCAFFOLD
@pytest.mark.parametrize("command", ["approve", "status", "content", "validate", "gate2"])
def test_an_unknown_run_id_is_an_error_not_a_new_run(command: str) -> None:
    """Non-zero exit, message says no such run, and no `runs/<id>/` directory is created."""
    raise NotImplementedError


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
