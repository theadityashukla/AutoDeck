"""Pipeline steps started from the UI, run as the CLI commands themselves (B42).

A job is a short chain of `autodeck` commands (`outline`; `content` → `validate` → `gate2`;
`render` → `gate3`) run one after another in a subprocess, `python -m autodeck.cli ...`.
The UI therefore runs exactly what the terminal runs, with the same gate checks: a step
whose gate is not approved exits 3 and the chain stops there, as it would by hand.

Nothing here approves anything, and nothing here imports the module that does
(`autodeck/ui/approvals.py`) — a job is the pipeline working, never a person deciding (A7).
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOG_LINES = 200

#: Where each chain starts and what follows it. A chain is what one person action
#: implies: approving the outline means "write the slides", which is content, then
#: validation, then the GATE 2 report the claims screen reads.
CHAINS: dict[str, list[str]] = {
    "outline": ["outline"],
    "content": ["content", "validate", "gate2"],
    "render": ["render", "gate3"],
    # Draft-first (B43): one prompt becomes a draft that can be read. `clarify` is not a
    # chain here: it is one short call, run by the server while the person waits (see
    # `App.start_draft`), through the same CLI command.
    "draft": ["draft", "validate", "preview"],
    "revise": ["revise", "validate", "preview"],
    # The meeting (step 12): a recording becomes a transcript and then notes, as one chain;
    # a correction to the notes is its own one-step chain (B83).
    "meeting": ["transcribe", "notes"],
    "revise-notes": ["revise-notes"],
}

#: Chains the generic "run this stage" route never starts: each has its own screen and checks.
OWN_ROUTE_CHAINS = {"draft", "revise", "meeting", "revise-notes"}

#: Exit codes a step can end with and still let the chain continue. 4 is "a report with
#: findings" (`outline`, `gate2`, `gate3`): the report is the point, and the person reads it.
CONTINUE_CODES = {0, 4}

STEP_LABELS = {
    "transcribe": "Transcribing on this computer",
    "notes": "Writing the notes",
    "revise-notes": "Revising the notes",
    "redesign": "Reading your deck",
    "clarify": "Working out what the draft needs",
    "draft": "Writing the brief, outline and slides",
    "revise": "Revising the draft",
    "preview": "Drawing the draft previews",
    "outline": "Building the outline",
    "content": "Writing the slides",
    "validate": "Checking every claim against the papers",
    "gate2": "Writing the claims report",
    "render": "Art direction, rendering and critique",
    "gate3": "Final audit",
}

#: The same steps when the deck agent does the work (Phase 4c).
AGENT_LABELS = {"draft": "Agent drafting", "revise": "Agent revising"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Job:
    run_id: str
    steps: list[str]
    step: str = ""
    status: str = "running"  # running | done | failed | stopped
    exit_code: int | None = None
    started_at: str = field(default_factory=_now)
    finished_at: str = ""
    message: str = ""
    log: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_LINES))
    process: subprocess.Popen[str] | None = None
    stop_requested: bool = False
    #: Per-job inputs a step needs beyond the run (the revise instruction, chat mode).
    extra: dict[str, Any] = field(default_factory=dict)

    def _label(self) -> str:
        if self.extra.get("agent") and self.step in AGENT_LABELS:
            return AGENT_LABELS[self.step]
        return STEP_LABELS.get(self.step, self.step)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent": bool(self.extra.get("agent")),
            "steps": list(self.steps),
            "step": self.step,
            "step_label": self._label(),
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "message": self.message,
            "log": list(self.log),
        }


CommandFor = Callable[..., Sequence[str]]
"""(step, run_id) → the argv to run for that step; (step, run_id, extra) when the job has
extra inputs, so a two-argument callable keeps working for every job without any."""


class JobManager:
    """At most one job per run; jobs for different runs may run side by side."""

    def __init__(self, command_for: CommandFor, *, cwd: str | None = None) -> None:
        self._command_for = command_for
        self._cwd = cwd
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, run_id: str) -> Job | None:
        return self._jobs.get(run_id)

    def running(self, run_id: str) -> bool:
        job = self._jobs.get(run_id)
        return job is not None and job.status == "running"

    def start(self, run_id: str, chain: str, extra: dict[str, Any] | None = None) -> Job:
        from autodeck.ui.api import UIError

        if chain not in CHAINS:
            raise UIError(f"Unknown step {chain!r}.")
        with self._lock:
            if self.running(run_id):
                raise UIError("A step is already running for this run.", status=409)
            job = Job(run_id=run_id, steps=list(CHAINS[chain]), extra=dict(extra or {}))
            self._jobs[run_id] = job
        thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        thread.start()
        return job

    def stop(self, run_id: str) -> Job | None:
        job = self._jobs.get(run_id)
        if job is None or job.status != "running":
            return job
        job.stop_requested = True
        process = job.process
        if process is not None and process.poll() is None:
            process.terminate()
        return job

    def wait(self, run_id: str, timeout: float = 30.0) -> Job | None:
        """Block until the run's job finishes (tests and shutdown only)."""
        deadline = datetime.now(UTC).timestamp() + timeout
        while (job := self._jobs.get(run_id)) and job.status == "running":
            if datetime.now(UTC).timestamp() > deadline:
                break
            threading.Event().wait(0.05)
        return self._jobs.get(run_id)

    # -- the worker --------------------------------------------------------

    def _run(self, job: Job) -> None:
        try:
            self._run_steps(job)
        finally:
            # Whatever ended the job, an uploaded recording does not outlive it (B83).
            self._delete_after(job, None)

    @staticmethod
    def _delete_after(job: Job, step: str | None) -> None:
        """Delete the file named by `extra["delete_after"] = {"step", "path"}`.

        Called right after that step's process exits, and again when the job ends however it
        ends (`step=None`), so a stopped or failed job leaves nothing behind. Only a file
        inside the uploads folder is ever deleted.
        """
        spec = job.extra.get("delete_after")
        if not isinstance(spec, dict) or (step is not None and spec.get("step") != step):
            return
        remove_upload(str(spec.get("path", "")))

    def _run_steps(self, job: Job) -> None:
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"}
        for step in job.steps:
            if job.stop_requested:
                break
            job.step = step
            job.log.append(f"$ autodeck {step} {job.run_id}")
            try:
                argv = (
                    self._command_for(step, job.run_id, job.extra)
                    if job.extra
                    else self._command_for(step, job.run_id)
                )
                process = subprocess.Popen(
                    list(argv),
                    cwd=self._cwd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                self._finish(job, "failed", None, f"Could not start `{step}`: {exc}")
                return
            job.process = process
            assert process.stdout is not None
            for line in process.stdout:
                job.log.append(line.rstrip("\n"))
            code = process.wait()
            job.exit_code = code
            self._delete_after(job, step)
            if job.stop_requested:
                break
            if code not in CONTINUE_CODES:
                self._finish(job, "failed", code, _failure_message(step, code))
                return
        if job.stop_requested:
            self._finish(job, "stopped", job.exit_code, "Stopped. Finished work is kept.")
        else:
            self._finish(job, "done", job.exit_code, "")

    @staticmethod
    def _finish(job: Job, status: str, code: int | None, message: str) -> None:
        job.process = None
        job.exit_code = code
        job.message = message
        job.finished_at = _now()
        job.status = status


def remove_upload(path: str) -> bool:
    """Delete one uploaded recording, and its run folder when that is left empty.

    Refuses (returns False) anything that does not resolve to a file strictly inside the
    uploads folder, so a crafted path can never delete something else.
    """
    from autodeck.ui.profile import uploads_dir

    if not path:
        return False
    try:
        root = uploads_dir().resolve()
        target = Path(path).resolve()
        if target == root or not target.is_relative_to(root) or not target.is_file():
            return False
        target.unlink()
        folder = target.parent
        if folder != root and folder.is_relative_to(root):
            with contextlib.suppress(OSError):
                folder.rmdir()  # only when empty
    except OSError:
        return False
    return True


def _failure_message(step: str, code: int) -> str:
    if code == 3:
        return (
            f"`{step}` is waiting on an approval or an earlier step. The log says which; "
            "nothing was approved for you."
        )
    return f"`{step}` stopped with exit code {code}. The log above says why."


def cli_command(
    step: str, run_id: str, *, roots: Any, extra: dict[str, Any] | None = None
) -> list[str]:
    """The `autodeck` command line for one step, with the UI's roots and environment.

    `extra` carries what a step needs beyond the run: `prompt`, `client` and `project` for
    `clarify`; `deck`, `wording`, `layouts` and `check_papers` for `redesign`; `instruction`
    for `revise`; `from_chat` for `draft`.
    """
    from autodeck.ui.api import read_run_meta

    extra = extra or {}
    base = [sys.executable, "-m", "autodeck.cli", step, run_id]
    runs = ["--runs-root", str(roots.runs)]
    env = ["--env", roots.env]
    if step in ("transcribe", "notes", "revise-notes"):
        return _meeting_command(step, run_id, roots, extra)
    if step == "outline":
        meta = read_run_meta(roots, run_id)
        return [
            *base,
            "--client",
            meta.get("client", ""),
            "--project",
            meta.get("project", ""),
            *env,
            "--knowledge-root",
            str(roots.knowledge),
            *runs,
            *_tokens_args(roots),
        ]
    if step == "content":
        return [
            *base,
            *env,
            "--knowledge-root",
            str(roots.knowledge),
            "--corpus-root",
            str(roots.corpus),
            *runs,
        ]
    if step == "clarify":
        meta = read_run_meta(roots, run_id)
        argv = [
            *base,
            "--client",
            str(extra.get("client") or meta.get("client", "")),
            "--project",
            str(extra.get("project") or meta.get("project", "")),
            "--prompt",
            str(extra.get("prompt", "")),
            *env,
            "--knowledge-root",
            str(roots.knowledge),
            "--corpus-root",
            str(roots.corpus),
            *runs,
        ]
        if extra.get("provenance"):
            argv += ["--provenance", str(extra["provenance"])]
        if extra.get("design_mode"):
            argv += ["--design-mode", str(extra["design_mode"])]
        return argv
    if step == "redesign":
        meta = read_run_meta(roots, run_id)
        argv = [
            *base,
            "--client",
            str(extra.get("client") or meta.get("client", "")),
            "--project",
            str(extra.get("project") or meta.get("project", "")),
            "--deck",
            str(extra.get("deck", "")),
            "--wording",
            str(extra.get("wording", "keep")),
            *env,
            "--knowledge-root",
            str(roots.knowledge),
            "--corpus-root",
            str(roots.corpus),
            *runs,
        ]
        if extra.get("provenance"):
            argv += ["--provenance", str(extra["provenance"])]
        if extra.get("design_mode"):
            argv += ["--design-mode", str(extra["design_mode"])]
        if extra.get("layouts") is False:
            argv.append("--no-layouts")
        if extra.get("check_papers"):
            argv.append("--check-papers")
        return argv
    if step in ("draft", "revise"):
        argv = [
            *base,
            *env,
            "--knowledge-root",
            str(roots.knowledge),
            "--corpus-root",
            str(roots.corpus),
            *runs,
        ]
        if step == "draft":
            argv += _tokens_args(roots)
            if extra.get("from_chat"):
                argv.append("--from-chat")
            if extra.get("agent"):
                argv.append("--agent")
        else:
            argv += ["--instruction", str(extra.get("instruction", ""))]
        return argv
    if step == "preview":
        return [*base, *runs, *env]
    if step == "validate":
        return [*base, *env, "--corpus-root", str(roots.corpus), *runs]
    if step == "gate2":
        return [*base, *runs]
    if step == "render":
        return [*base, *runs, *env]
    if step == "gate3":
        return [*base, *runs, *env, "--knowledge-root", str(roots.knowledge)]
    raise ValueError(f"unknown step {step!r}")


def _tokens_args(roots: Any) -> list[str]:
    """`--tokens` only when the UI was configured with a non-default tokens file, so a build
    otherwise resolves the client's own `theme/tokens.json` exactly as the CLI does (4.1)."""
    from autodeck.design.theme.resolve import DEFAULT_TOKENS

    return [] if Path(roots.tokens) == DEFAULT_TOKENS else ["--tokens", str(roots.tokens)]


def _meeting_command(step: str, run_id: str, roots: Any, extra: dict[str, Any]) -> list[str]:
    """`autodeck meeting transcribe | notes | revise-notes RUN ...` (step 12, B83)."""
    from autodeck.ui.api import read_run_meta

    base = [sys.executable, "-m", "autodeck.cli", "meeting", step, run_id]
    runs = ["--runs-root", str(roots.runs)]
    env = ["--env", roots.env]
    knowledge = ["--knowledge-root", str(roots.knowledge)]
    if step == "transcribe":
        meta = read_run_meta(roots, run_id)
        argv = [
            *base,
            "--audio",
            str(extra.get("audio", "")),
            "--client",
            str(extra.get("client") or meta.get("client", "")),
            "--project",
            str(extra.get("project") or meta.get("project", "")),
            *env,
            *knowledge,
            *runs,
        ]
        if extra.get("with_papers"):
            argv.append("--with-papers")
        return argv
    argv = [*base]
    if step == "notes":
        if extra.get("date"):
            argv += ["--date", str(extra["date"])]
        if extra.get("attendees"):
            argv += ["--attendees", str(extra["attendees"])]
    elif extra.get("apply_edits"):
        argv.append("--apply-edits")
    else:
        argv += ["--say", str(extra.get("say", ""))]
    return [*argv, *env, *knowledge, "--corpus-root", str(roots.corpus), *runs]
