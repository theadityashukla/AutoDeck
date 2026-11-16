"""The review UI's local server: a JSON API plus the static front end (B40).

Standard library only (`http.server`), bound to 127.0.0.1. It is a single-user local tool
with no login, so it defends the two ways a web page elsewhere could reach it: requests
must carry a localhost `Host` header (DNS rebinding), and every POST and PUT must be
`application/json` (a cross-site form or `text/plain` fetch cannot send that without a
CORS preflight, which this server never grants).

Two routes, and only two, reach an approval (A7, B39, B42): signing the brief goes
through `PlannerSession.sign_off`, exactly as `/sign` does in `autodeck plan`, and
`POST /api/runs/<id>/approve` goes through `approvals.approve_gate`, which calls the method
`autodeck approve` calls. Both record the name from Settings > Profile. Pipeline steps run
as the CLI commands themselves (`jobs.py`), and a job never approves anything.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, unquote, urlsplit

from autodeck.ui import api, jobs, meeting_view, profile, review, workspace
from autodeck.ui.api import Roots, UIError
from autodeck.ui.approvals import approve_gate

if TYPE_CHECKING:
    from autodeck.agents.planner import Draft, PlannerSession
    from autodeck.providers.guard import ProviderGuard

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
MAX_BODY = 1_000_000
MAX_UPLOAD = 50 * 1024 * 1024
"""A client's deck, as a raw request body (B41). Larger is refused before it is read."""
MAX_AUDIO_UPLOAD = 1024 * 1024 * 1024
"""A meeting recording (B83). Larger is refused before it is read; the body is streamed to
disk in `AUDIO_CHUNK` pieces and never held in memory."""
AUDIO_CHUNK = 1024 * 1024
MAX_NOTE_FIELD = 500
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
UPLOAD_HEADER = "X-AutoDeck-Upload"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


@dataclass
class LiveSession:
    """A planning conversation held open between requests."""

    session: PlannerSession
    guard: ProviderGuard
    client: str
    project: str
    lock: threading.Lock = field(default_factory=threading.Lock)
    #: When the reply in progress started (`time.monotonic()`), or None. Lets a screen that
    #: was left and reopened mid-reply show that the planner is still working.
    busy_since: float | None = None
    #: The last turn's failure, shown once the person comes back to the screen.
    last_error: str = ""


DEFAULT_MEETING_PROMPT = "A short readout of this meeting for people who were not there"
"""The deck prompt of "Make a deck from this meeting" when the person leaves it empty."""

CLARIFY_TIMEOUT = 600
"""Seconds the person may wait for the one short clarify call before it is given up on."""


def run_cli(argv: list[str]) -> tuple[int, str]:
    """Run one CLI command to completion and return (exit code, its output).

    Used for the one step that is not a job: `clarify` is a single short call the person
    waits for, so it is run in the request, through the same command the terminal runs.
    """
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"}
    try:
        done = subprocess.run(
            argv,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLARIFY_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return done.returncode, done.stdout


class App:
    """State shared by every request: the roots and the open planning sessions."""

    def __init__(
        self,
        roots: Roots,
        job_manager: jobs.JobManager | None = None,
        cli_runner: Any = run_cli,
    ) -> None:
        self.roots = roots
        self.sessions: dict[str, LiveSession] = {}
        self._sessions_lock = threading.Lock()
        self.cli_runner = cli_runner
        self.jobs = job_manager or jobs.JobManager(
            lambda step, run_id, extra=None: jobs.cli_command(
                step, run_id, roots=roots, extra=extra
            )
        )

    # -- runs and jobs ------------------------------------------------------

    def summary(self, run_id: str) -> dict[str, Any]:
        job = self.jobs.get(run_id)
        running = job.step if job is not None and job.status == "running" else ""
        out = api.run_summary(self.roots, run_id, running_step=running)
        out["job"] = job.to_dict() if job is not None else None
        self._meeting_job_stage(out, job)
        return out

    @staticmethod
    def _meeting_job_stage(out: dict[str, Any], job: jobs.Job | None) -> None:
        """A meeting run's stage word, corrected by a failed job (the files cannot tell)."""
        if not out.get("meeting") or job is None or job.status != "failed":
            return
        failed = {"transcribe": "Transcription failed", "notes": "Notes failed"}.get(job.step)
        if failed and out["meeting_stage"] in ("Transcribing", "Transcribed"):
            out["meeting_stage"] = failed
            out["next"] = failed

    def runs(self) -> list[dict[str, Any]]:
        out = []
        for run in api.list_runs(self.roots):
            job = self.jobs.get(run["id"])
            run["job"] = job.to_dict() if job is not None else None
            self._meeting_job_stage(run, job)
            out.append(run)
        return out

    def start_job(self, run_id: str, chain: str) -> dict[str, Any]:
        api._open(self.roots, run_id)  # 404 for an unknown run, before anything starts
        # A person starts a draft or a revision through its own route, which checks what
        # that step needs; the generic route is for the gate-first steps.
        if chain in jobs.OWN_ROUTE_CHAINS:
            raise UIError(f"Start {chain!r} from its own screen.")
        return self.jobs.start(run_id, chain).to_dict()

    def approve_run(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        run_id = api.check_run_id(run_id)
        if self.jobs.running(run_id):
            raise UIError(
                "A step is still running for this run. Approve once it has finished, so the "
                "approval covers what you saw.",
                status=409,
            )
        gate = str(body.get("gate", ""))
        risks = body.get("accepted_risks") or {}
        if not isinstance(risks, dict):
            raise UIError("accepted_risks must map key message ids to a description.")
        result = approve_gate(
            self.roots,
            run_id,
            gate,
            approver=profile.approver_name(self.roots.profile),
            accepted_risks={str(k): str(v) for k, v in risks.items()},
        )
        # A gate-first run continues the pipeline after an approval. A draft-first run is
        # already built, so an approval starts nothing; its final deck is built by its own
        # action ("Build the final deck") once the brief, outline and claims are approved.
        draft_first = api._open(self.roots, run_id).is_draft_first
        follow = None if draft_first else {"outline": "content", "claims": "render"}.get(gate)
        result["job"] = self.jobs.start(run_id, follow).to_dict() if follow else None
        return result

    # -- planning -----------------------------------------------------------

    def _checked_new_run(self, body: dict[str, Any]) -> tuple[str, str, str]:
        """The run id, client and project of a request that starts or resumes a run.

        Shared by planning and drafting: the client and project must exist, and a run that
        was not started from this window is never taken over.
        """
        run_id = api.check_run_id(str(body.get("run_id", "")))
        client = str(body.get("client", "")).strip()
        project = str(body.get("project", "")).strip()
        if client not in api.list_clients(self.roots):
            raise UIError(f"Unknown client {client!r}.")
        if project not in api.list_projects(self.roots):
            raise UIError(f"Unknown project {project!r}.")
        meta = api.read_run_meta(self.roots, run_id)
        if meta and (meta.get("client"), meta.get("project")) != (client, project):
            raise UIError(
                f"Run {run_id!r} belongs to {meta.get('client')} / {meta.get('project')}. "
                "Pick another name.",
                status=409,
            )
        if not meta and (self.roots.runs / run_id).exists():
            raise UIError(
                f"Run {run_id!r} already exists and was not started here. Open it from "
                "the terminal, or pick another name.",
                status=409,
            )
        return run_id, client, project

    def start_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        run_id, client, project = self._checked_new_run(body)
        # Written first, so a session that fails to open (a missing key) leaves a run the
        # UI still recognises as its own and can resume once the cause is fixed.
        api.write_run_meta(self.roots, run_id, client=client, project=project)
        # A chat-started run is planned before any CLI step, so fix its design mode now (B69).
        api.snapshot_run_design_mode(
            self.roots, run_id, _design_mode_field(body.get("design_mode"))
        )
        self._open_session(run_id, client, project)
        return {"run_id": run_id}

    # -- drafting (B43, B47, B48) -------------------------------------------

    def start_draft(self, body: dict[str, Any]) -> dict[str, Any]:
        """One prompt in; the clarify checkpoint out (assumptions and any questions).

        Runs `autodeck clarify` while the person waits (it is one short call), so the
        terminal command and this route are the same code. Nothing is drafted yet.
        """
        run_id, client, project = self._checked_new_run(body)
        prompt = str(body.get("prompt", "")).strip()
        if not prompt:
            raise UIError("Say what the deck is for first.")
        if self.jobs.running(run_id):
            raise UIError("A step is already running for this run.", status=409)
        if api.is_draft_mode(api._open_or_none(self.roots, run_id)):
            raise UIError(
                "This run already has a draft. Revise it, or start a new run.", status=409
            )
        api.write_run_meta(
            self.roots, run_id, client=client, project=project, agent=bool(body.get("agent"))
        )
        argv = jobs.cli_command(
            "clarify",
            run_id,
            roots=self.roots,
            extra={
                "client": client,
                "project": project,
                "prompt": prompt,
                "provenance": _provenance_field(body.get("provenance")),
                "design_mode": _design_mode_field(body.get("design_mode")),
            },
        )
        code, output = self.cli_runner(argv)
        if code != 0:
            raise UIError(_cli_failure("clarify", code, output))
        return api.clarify_view(self.roots, run_id)

    def submit_answers(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Record the person's answers and start writing the draft.

        The draft starts only once every question has an answer (accepting the suggestions
        counts); nothing is approved by answering.
        """
        from autodeck.pipeline.clarify_state import (
            ClarifyStateError,
            load_clarify,
            record_answers,
            save_clarify,
        )

        run_id = api.check_run_id(run_id)
        orch = api._open(self.roots, run_id)
        if self.jobs.running(run_id):
            raise UIError("A step is already running for this run.", status=409)
        answers = body.get("answers") or {}
        corrections = body.get("corrections") or []
        if not isinstance(answers, dict) or not isinstance(corrections, list):
            raise UIError("answers must be an object and corrections a list.")
        try:
            data = load_clarify(orch.paths.root)
            record_answers(
                data,
                answers={str(k): str(v) for k, v in answers.items()},
                corrections=[str(c) for c in corrections],
                accept_all=bool(body.get("accept_all")),
                accepted={str(q) for q in body.get("accepted") or []},
            )
        except ClarifyStateError as exc:
            raise UIError(str(exc)) from None
        save_clarify(orch.paths.root, data)
        job = self.jobs.start(run_id, "draft", self._agent_extra(run_id, body))
        return {"job": job.to_dict(), "answers": data["answers"]}

    def _agent_extra(self, run_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """`{"agent": True}` when the draft should be built by the deck agent, else nothing."""
        if (body or {}).get("agent") or api.run_uses_agent(self.roots, run_id):
            return {"agent": True}
        return {}

    def draft_from_chat(self, run_id: str) -> dict[str, Any]:
        """ "Draft the deck" at the end of a planning chat: compose keeps its brief verbatim."""
        run_id = api.check_run_id(run_id)
        orch = api._open(self.roots, run_id)
        if not orch.paths.draft_brief.exists():
            raise UIError("The conversation has not produced a draft brief yet.", status=409)
        job = self.jobs.start(run_id, "draft", {"from_chat": True, **self._agent_extra(run_id)})
        return {"job": job.to_dict()}

    def start_revise(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        run_id = api.check_run_id(run_id)
        instruction = str(body.get("instruction", "")).strip()
        if not instruction:
            raise UIError("Say what to change first.")
        if not api._open(self.roots, run_id).is_draft_first:
            raise UIError("There is no draft to revise yet.", status=409)
        extra: dict[str, Any] = {"instruction": instruction}
        # `autodeck revise` picks the agent by itself when a deck session exists (a meeting
        # run's notes session does not count).
        if (self.roots.runs / run_id / "session" / "workspace.json").is_file():
            extra["agent"] = True
        job = self.jobs.start(run_id, "revise", extra)
        return {"job": job.to_dict()}

    def start_redesign(self, params: dict[str, str], data: bytes) -> dict[str, Any]:
        """A client's deck in; the clarify checkpoint out (B41, Phase 3d).

        Saves the upload under `runs/<run>/upload/` and runs `autodeck redesign` on it through
        the same runner `start_draft` uses, so the terminal command and this route are the
        same code. Nothing is drafted or approved here.
        """
        run_id, client, project = self._checked_new_run(
            {k: params.get(k, "") for k in ("run_id", "client", "project")}
        )
        wording = params.get("wording", "keep") or "keep"
        if wording not in ("keep", "light"):
            raise UIError("wording must be 'keep' or 'light'.")
        if not data[:2] == b"PK":
            raise UIError("That file is not a .pptx (it is not a zip package).", status=415)
        if self.jobs.running(run_id):
            raise UIError("A step is already running for this run.", status=409)
        if api.is_draft_mode(api._open_or_none(self.roots, run_id)):
            raise UIError(
                "This run already has a draft. Revise it, or start a new run.", status=409
            )
        name = _upload_name(params.get("name", ""))
        folder = self.roots.runs / run_id / "upload"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        target.write_bytes(data)
        api.write_run_meta(self.roots, run_id, client=client, project=project)
        argv = jobs.cli_command(
            "redesign",
            run_id,
            roots=self.roots,
            extra={
                "client": client,
                "project": project,
                "deck": str(target),
                "wording": wording,
                "layouts": _flag(params.get("layouts"), default=True),
                "check_papers": _flag(params.get("check_papers"), default=False),
                "provenance": _provenance_field(params.get("provenance")),
                "design_mode": _design_mode_field(params.get("design_mode")),
            },
        )
        code, output = self.cli_runner(argv)
        if code != 0:
            raise UIError(_cli_failure("redesign", code, output))
        return api.clarify_view(self.roots, run_id)

    # -- the meeting (step 12, B83) -------------------------------------------

    def start_meeting(self, params: dict[str, str], stream: Any, length: int) -> dict[str, Any]:
        """A recording in; the transcribe → notes chain out.

        The body is copied to `<uploads>/<run>/<name>` in 1 MiB pieces (never held in memory,
        never in the repository folder); a short read, such as the browser closing, deletes the
        partial file. The run, its meta and the job exist only once the whole file has arrived.
        The job deletes the file when its transcribe step ends, however it ends.
        """
        run_id, client, project = self._checked_new_run(
            {k: params.get(k, "") for k in ("run_id", "client", "project")}
        )
        if (self.roots.runs / run_id).exists():
            raise UIError(
                f"Run {run_id!r} already exists. Pick another name for this meeting.",
                status=409,
            )
        name = _audio_name(params.get("name", ""))
        folder = profile.uploads_dir() / run_id
        target = folder / name
        folder.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("wb") as out:
                remaining = length
                while remaining > 0:
                    chunk = stream.read(min(AUDIO_CHUNK, remaining))
                    if not chunk:
                        raise UIError("The upload stopped before the whole recording arrived.")
                    out.write(chunk)
                    remaining -= len(chunk)
            extra: dict[str, Any] = {
                "client": client,
                "project": project,
                "audio": str(target),
                "with_papers": _flag(params.get("with_papers"), default=False),
                "delete_after": {"step": "transcribe", "path": str(target)},
            }
            for key in ("date", "attendees"):
                value = " ".join(params.get(key, "").split())[:MAX_NOTE_FIELD]
                if value:
                    extra[key] = value
            api.write_run_meta(self.roots, run_id, client=client, project=project, meeting=True)
            job = self.jobs.start(run_id, "meeting", extra)
        except BaseException:
            jobs.remove_upload(str(target))
            raise
        return {"run_id": run_id, "job": job.to_dict()}

    def _notes_job(self, run_id: str, extra: dict[str, Any]) -> dict[str, Any]:
        job = self.jobs.start(run_id, "revise-notes", extra)
        return {"job": job.to_dict()}

    def _checked_notes_run(self, run_id: str) -> str:
        """A meeting run with notes and no job in progress, else a refusal in words."""
        run_id = api.check_run_id(run_id)
        directory = meeting_view.meeting_dir(self.roots, run_id)
        if not (directory / meeting_view.NOTES_FILE).is_file():
            raise UIError("There are no notes for this run yet.", status=409)
        if self.jobs.running(run_id):
            raise UIError("A step is already running for this run.", status=409)
        return run_id

    def save_notes(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        run_id = api.check_run_id(run_id)
        if self.jobs.running(run_id):
            raise UIError(
                "A step is running for this run; save once it has finished.", status=409
            )
        return meeting_view.save_notes(self.roots, run_id, body.get("markdown"))

    def apply_notes_edits(self, run_id: str) -> dict[str, Any]:
        """Apply my edits: `meeting revise-notes --apply-edits`, if there are edits."""
        run_id = self._checked_notes_run(run_id)
        directory = meeting_view.meeting_dir(self.roots, run_id)
        if not meeting_view.notes_edited(directory):
            return {"job": None, "message": "No edits to apply."}
        return self._notes_job(run_id, {"apply_edits": True})

    def say_to_notes(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """The chat box: `meeting revise-notes --say TEXT`."""
        text = str(body.get("text", "")).strip()
        if not text:
            raise UIError("Say what to fix first.")
        run_id = self._checked_notes_run(run_id)
        return self._notes_job(run_id, {"say": text})

    def start_meeting_deck(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Make a deck from this meeting: `clarify` on the run, while the person waits.

        The clarify screen and the answers → `draft` chain are the ordinary ones: the run
        already exists, and `submit_answers` never assumed otherwise.
        """
        run_id = api.check_run_id(run_id)
        orch = api._open(self.roots, run_id)
        meeting_view.meeting_dir(self.roots, run_id)
        if not api.run_is_meeting(self.roots, run_id):
            raise UIError(f"Run {run_id!r} has no meeting.", status=404)
        if self.jobs.running(run_id):
            raise UIError("A step is already running for this run.", status=409)
        if orch.state.is_complete("compose"):
            raise UIError(
                "This run already has a draft. Revise it, or start a new run.", status=409
            )
        if not (orch.paths.root / "meeting" / "transcript.json").is_file():
            raise UIError("The recording has not been transcribed yet.", status=409)
        meta = api.read_run_meta(self.roots, run_id)
        prompt = str(body.get("prompt", "")).strip() or DEFAULT_MEETING_PROMPT
        if body.get("agent"):
            api.write_run_meta(
                self.roots,
                run_id,
                client=meta.get("client", ""),
                project=meta.get("project", ""),
                agent=True,
            )
        argv = jobs.cli_command(
            "clarify",
            run_id,
            roots=self.roots,
            extra={
                "prompt": prompt,
                "provenance": _provenance_field(body.get("provenance")),
                "design_mode": _design_mode_field(body.get("design_mode")),
            },
        )
        code, output = self.cli_runner(argv)
        if code != 0:
            raise UIError(_cli_failure("clarify", code, output))
        return api.clarify_view(self.roots, run_id)

    def chat(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """One conversation per run (B48): the planner first, revisions once a draft exists."""
        run_id = api.check_run_id(run_id)
        text = str(body.get("text", "")).strip()
        if not text:
            raise UIError("Say something first.")
        if api._open(self.roots, run_id).is_draft_first:
            return {"mode": "revise", **self.start_revise(run_id, {"instruction": text})}
        return {"mode": "plan", **self.plan_say(run_id, body)}

    def _open_session(self, run_id: str, client: str, project: str) -> LiveSession:
        from autodeck.pipeline.planning import PlanningSetupError, prepare_planning

        with self._sessions_lock:
            live = self.sessions.get(run_id)
            if live is not None:
                return live
            try:
                planning = prepare_planning(
                    run_id,
                    client=client,
                    project=project,
                    env=self.roots.env,
                    knowledge_root=self.roots.knowledge,
                    corpus_root=self.roots.corpus,
                    runs_root=self.roots.runs,
                )
            except PlanningSetupError as exc:
                raise UIError(str(exc)) from None
            try:
                session = planning.open_session()
            except Exception as exc:
                raise UIError(_provider_message(planning.guard, exc)) from exc
            live = LiveSession(session, planning.guard, client, project)
            self.sessions[run_id] = live
            return live

    def _live(self, run_id: str) -> LiveSession:
        run_id = api.check_run_id(run_id)
        live = self.sessions.get(run_id)
        if live is not None:
            return live
        meta = api.read_run_meta(self.roots, run_id)
        if not meta.get("client") or not meta.get("project"):
            raise UIError(
                f"Run {run_id!r} was not started from this window, so its client is not "
                "known here. Resume it with `autodeck plan` in a terminal.",
                status=404,
            )
        return self._open_session(run_id, meta["client"], meta["project"])

    def plan_state(self, run_id: str) -> dict[str, Any]:
        from autodeck.agents.planner import render_draft

        live = self._live(run_id)
        session = live.session
        return {
            "run_id": run_id,
            "client": live.client,
            "project": live.project,
            "signed": session.signed,
            "draft": render_draft(session.draft),
            "brief": _brief_fields(session.draft),
            "blockers": [] if session.signed else _sign_blockers(session.draft, run_id),
            "transcript": [{"role": t.role, "text": t.text} for t in session.transcript.turns],
            "thinking": live.busy_since is not None,
            "thinking_for": (
                round(time.monotonic() - live.busy_since) if live.busy_since is not None else 0
            ),
            "error": live.last_error,
        }

    def plan_say(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from autodeck.agents.planner import PlannerError

        text = str(body.get("text", "")).strip()
        if not text:
            raise UIError("Say something first.")
        if text.startswith("/"):
            raise UIError(
                "There are no slash commands here: the draft brief is always shown, and "
                "Approve & proceed approves it."
            )
        live = self._live(run_id)
        if live.busy_since is not None:
            raise UIError("The planner is still answering your last message.", status=409)
        with live.lock:
            live.busy_since = time.monotonic()
            live.last_error = ""
            try:
                live.session.turn(text)
            except PlannerError as exc:
                live.last_error = str(exc)
                raise UIError(str(exc)) from None
            except Exception as exc:
                live.session.save_draft()
                live.last_error = _provider_message(live.guard, exc)
                raise UIError(live.last_error) from exc
            finally:
                live.busy_since = None
        return self.plan_state(run_id)

    def plan_sign(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from autodeck.agents.planner import PlannerError

        approver = profile.approver_name(self.roots.profile)
        live = self._live(run_id)
        with live.lock:
            try:
                brief = live.session.sign_off(approver=approver)
            except PlannerError as exc:
                raise UIError(str(exc)) from None
        job = self.jobs.start(api.check_run_id(run_id), "outline").to_dict()
        return {"version": brief.version, "approved_by": brief.approved_by, "job": job}


def _brief_fields(draft: Draft) -> dict[str, Any]:
    """The draft brief as fields, for the planning screen (the CLI shows `render_draft`)."""
    return {
        "objective": draft.objective,
        "audience": draft.audience,
        "length_target": draft.length_target,
        "header_style": draft.header_style,
        "key_messages": [
            {
                "id": m.id,
                "text": m.text,
                "evidence": m.evidence_status,
                "notes": m.probe_notes or "",
                "leads": list(m.supporting_claims),
            }
            for m in draft.key_messages
        ],
        "must_include": list(draft.must_include),
        "must_avoid": list(draft.must_avoid),
        "layout_pins": [
            {"message_id": p.message_id, "target": p.target, "value": p.value}
            for p in draft.layout_pins
        ],
        "open_risks": [
            {
                "message_id": r.message_id,
                "description": r.description,
                "accepted_by": r.accepted_by,
            }
            for r in draft.open_risks
        ],
    }


def _sign_blockers(draft: Draft, run_id: str) -> list[str]:
    """Why the brief cannot be approved yet, in words; empty when it can.

    Informational only: `sign_off` makes the same checks and is what actually refuses.
    """
    blockers = []
    if not draft.objective.strip():
        blockers.append("No objective yet: say what decision the deck is for.")
    if not draft.audience.strip():
        blockers.append("No audience yet: say who will be in the room.")
    if not draft.key_messages:
        blockers.append("No key messages yet.")
    for message in draft.unaccounted_gaps():
        blockers.append(
            f"{message.id} is {message.evidence_status}: reword it, drop it, or accept the "
            "risk in the chat."
        )
    if not blockers:
        try:
            draft.to_brief(run_id)
        except Exception as exc:
            blockers.append(f"The brief is not complete yet: {str(exc).splitlines()[0]}")
    return blockers


def _provenance_field(value: Any) -> str | None:
    """An optional `provenance` from a start request: 'strict', 'normal' or none."""
    if value in (None, ""):
        return None
    if value not in ("strict", "normal"):
        raise UIError("provenance must be 'strict' or 'normal'.")
    return str(value)


def _design_mode_field(value: Any) -> str | None:
    """An optional `design_mode` from a start request: 'structured', 'creative' or none."""
    if value in (None, ""):
        return None
    if value not in ("structured", "creative"):
        raise UIError("design_mode must be 'structured' or 'creative'.")
    return str(value)


def _flag(value: str | None, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _upload_name(raw: str) -> str:
    """A safe file name for an upload: no directories, a conservative alphabet, `.pptx`."""
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", PurePosixPath(raw.replace("\\", "/")).name)
    stem = stem.strip(" .")
    if stem.lower().endswith(".pptx"):
        stem = stem[:-5].strip(" .")
    return f"{stem or 'deck'}.pptx"


def _audio_name(raw: str) -> str:
    """A safe file name for an uploaded recording: no directories, a conservative alphabet,
    and the (already validated) suffix kept."""
    path = PurePosixPath(raw.replace("\\", "/"))
    suffix = path.suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", path.name[: len(path.name) - len(path.suffix)])
    return f"{stem.strip(' .') or 'recording'}{suffix}"


def _cli_failure(step: str, code: int, output: str) -> str:
    """The tail of a failed command's output, in a sentence a person can act on."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    tail = " ".join(lines[-4:]) if lines else "no output"
    return f"`{step}` stopped with exit code {code}. {tail}"


def _provider_message(guard: ProviderGuard, exc: Exception) -> str:
    """The CLI's wording for a provider failure, minus the 'run this command' line."""
    failure = guard.failure_behind(exc)
    if failure is None:
        raise exc
    from autodeck.cli import _provider_failure_message

    message = _provider_failure_message(
        failure, command="plan", saved="your draft brief is kept; nothing is approved."
    )
    return message.split("\n  Then run")[0]


class Handler(BaseHTTPRequestHandler):
    server_version = "AutoDeck"
    app: App  # set on the subclass made by `make_server`

    # -- plumbing ----------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:
        return  # quiet: the terminal belongs to the person, not to access logs

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in LOCAL_HOSTS

    def _body(self) -> dict[str, Any]:
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            raise UIError("Expected application/json.", status=415)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise UIError("Request too large.", status=413)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise UIError("Malformed JSON.") from None
        if not isinstance(data, dict):
            raise UIError("Expected a JSON object.")
        return data

    def _upload(self) -> dict[str, Any]:
        """`POST /api/redesign/upload?run_id=&client=&project=&name=...`, body = the .pptx.

        Refused, in this order and before the body is read: no `X-AutoDeck-Upload: 1`
        header (403), a content type other than `.pptx` (415), no length or a length over
        `MAX_UPLOAD` (411, 413). The two request headers are what a cross-site page cannot
        send without a CORS preflight, which this server never grants.
        """
        if self.headers.get(UPLOAD_HEADER) != "1":
            raise UIError(f"Uploads need the {UPLOAD_HEADER}: 1 header.", status=403)
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != PPTX_TYPE:
            raise UIError(f"Expected {PPTX_TYPE}.", status=415)
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            raise UIError("Content-Length is required.", status=411) from None
        if length > MAX_UPLOAD:
            raise UIError("That deck is over the 50 MB limit.", status=413)
        if length <= 0:
            raise UIError("The upload is empty.")
        params = dict(parse_qsl(urlsplit(self.path).query))
        data = self.rfile.read(length)
        return self.app.start_redesign(params, data)

    def _meeting_upload(self) -> dict[str, Any]:
        """`POST /api/meeting/upload?run_id=&client=&project=&name=&...`, body = the recording.

        The other query fields are `with_papers`, `date` and `attendees`. Refused, in this
        order and before the body is read: no `X-AutoDeck-Upload: 1` header (403), a file name
        whose suffix is not an audio type we transcribe (415), no length (411), a length over
        `MAX_AUDIO_UPLOAD` (413), an empty body (400). The body is then streamed to disk by
        `App.start_meeting`.
        """
        from autodeck.meeting.audio import ALLOWED_SUFFIXES

        if self.headers.get(UPLOAD_HEADER) != "1":
            raise UIError(f"Uploads need the {UPLOAD_HEADER}: 1 header.", status=403)
        params = dict(parse_qsl(urlsplit(self.path).query))
        suffix = PurePosixPath(params.get("name", "").replace("\\", "/")).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise UIError(
                f"AutoDeck cannot transcribe {suffix or 'that kind of file'}. Use one of "
                f"{', '.join(sorted(ALLOWED_SUFFIXES))}.",
                status=415,
            )
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            raise UIError("Content-Length is required.", status=411) from None
        if length > MAX_AUDIO_UPLOAD:
            raise UIError("That recording is over the 1 GB limit.", status=413)
        if length <= 0:
            raise UIError("The upload is empty.")
        return self.app.start_meeting(params, self.rfile, length)

    # -- routing -----------------------------------------------------------

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            self._json(HTTPStatus.FORBIDDEN, {"error": "AutoDeck only answers on localhost."})
            return
        path = urlsplit(self.path).path
        try:
            if method == "GET" and path in STATIC_FILES:
                name, content_type = STATIC_FILES[path]
                body = resources.files("autodeck.ui").joinpath("static", name).read_bytes()
                self._send(HTTPStatus.OK, body, content_type)
                return
            if not path.startswith("/api/"):
                raise UIError("Not found.", status=404)
            parts = [unquote(p) for p in path[len("/api/") :].split("/") if p]
            match method, parts:
                case "GET", ["runs", run_id, "draft-preview", number] if number.isdigit():
                    data, content_type = api.draft_preview_file(
                        self.app.roots, run_id, int(number)
                    )
                    self._send(HTTPStatus.OK, data, content_type)
                    return
                case "GET", ["runs", run_id, "preview", number] if number.isdigit():
                    data, content_type = review.preview_file(
                        self.app.roots, run_id, int(number)
                    )
                    self._send(HTTPStatus.OK, data, content_type)
                    return
            if method == "POST" and parts == ["meeting", "upload"]:
                self._json(HTTPStatus.OK, self._meeting_upload())
                return
            if method == "POST" and parts == ["redesign", "upload"]:
                self._json(HTTPStatus.OK, self._upload())
                return
            payload = self._route(method, parts)
            self._json(HTTPStatus.OK, payload)
        except UIError as exc:
            self._json(exc.status, {"error": str(exc)})
        except Exception as exc:  # the page shows it; the server keeps running
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(exc).__name__}: {exc}"}
            )

    def _route(self, method: str, parts: list[str]) -> Any:
        app = self.app
        roots = app.roots
        match method, parts:
            case "GET", ["home"]:
                return api.home(roots)
            case "GET", ["runs"]:
                return {"runs": app.runs()}
            case "GET", ["runs", run_id]:
                return app.summary(run_id)
            case "GET", ["runs", run_id, "job"]:
                job = app.jobs.get(api.check_run_id(run_id))
                return {"job": job.to_dict() if job is not None else None}
            case "GET", ["runs", run_id, "session"]:
                run_id = api.check_run_id(run_id)
                return api.session_view(roots, run_id, active=app.jobs.running(run_id))
            case "POST", ["runs", run_id, "run"]:
                return {"job": app.start_job(run_id, str(self._body().get("stage", "")))}
            case "POST", ["runs", run_id, "stop"]:
                job = app.jobs.stop(api.check_run_id(run_id))
                return {"job": job.to_dict() if job is not None else None}
            case "POST", ["runs", run_id, "approve"]:
                return app.approve_run(run_id, self._body())
            case "POST", ["draft", "start"]:
                return app.start_draft(self._body())
            case "GET", ["runs", run_id, "clarify"]:
                return api.clarify_view(roots, api.check_run_id(run_id))
            case "POST", ["runs", run_id, "answers"]:
                return app.submit_answers(run_id, self._body())
            case "GET", ["runs", run_id, "draft"]:
                return api.draft_view(roots, api.check_run_id(run_id))
            case "POST", ["runs", run_id, "draft-from-chat"]:
                self._body()
                return app.draft_from_chat(run_id)
            case "POST", ["runs", run_id, "revise"]:
                return app.start_revise(run_id, self._body())
            case "GET", ["runs", run_id, "meeting"]:
                return meeting_view.meeting_view(roots, api.check_run_id(run_id))
            case "GET", ["runs", run_id, "transcript"]:
                return meeting_view.transcript_view(roots, api.check_run_id(run_id))
            case "PUT", ["runs", run_id, "notes"]:
                return app.save_notes(run_id, self._body())
            case "POST", ["runs", run_id, "notes", "apply"]:
                self._body()
                return app.apply_notes_edits(run_id)
            case "POST", ["runs", run_id, "notes", "say"]:
                return app.say_to_notes(run_id, self._body())
            case "POST", ["runs", run_id, "meeting-deck"]:
                return app.start_meeting_deck(run_id, self._body())
            case "POST", ["runs", run_id, "chat"]:
                return app.chat(run_id, self._body())
            case "GET", ["runs", run_id, "outline"]:
                return review.outline_view(roots, run_id)
            case "GET", ["runs", run_id, "claims"]:
                return review.claims_view(roots, run_id)
            case "POST", ["runs", run_id, "send-back"]:
                items = self._body().get("items")
                if not isinstance(items, list):
                    raise UIError("Expected a list of {claim_id, reason} items.")
                return review.send_back(
                    roots, run_id, items, by=profile.approver_name(roots.profile)
                )
            case "GET", ["runs", run_id, "final"]:
                return review.final_view(roots, run_id)
            case "POST", ["runs", run_id, "open-copy"]:
                self._body()
                return review.open_deck_copy(roots, run_id)
            case "GET", ["knowledge"]:
                return workspace.knowledge_view(roots)
            case "GET", ["profile"]:
                return profile.read_profile(roots.profile)
            case "POST", ["profile"]:
                return profile.save_profile(roots.profile, str(self._body().get("name", "")))
            case "GET", ["memory"]:
                query = dict(parse_qsl(urlsplit(self.path).query))
                return api.memory_view(roots, query.get("client", ""), query.get("project", ""))
            case "PUT", ["memory"]:
                body = self._body()
                return api.save_memory(
                    roots,
                    str(body.get("client", "")),
                    str(body.get("project", "")),
                    str(body.get("scope", "")),
                    str(body.get("content", "")),
                )
            case "GET", ["clients"]:
                return {"clients": api.list_clients(roots)}
            case "POST", ["clients"]:
                body = self._body()
                folder = api.create_client(
                    roots,
                    name=str(body.get("name", "")),
                    client_md=str(body.get("client_md", "")),
                    value_prop_md=str(body.get("value_prop_md", "")),
                )
                return {"name": folder.name, "path": str(folder)}
            case "POST", ["lint", "framing"]:
                return {"findings": api.lint_framing(str(self._body().get("text", "")))}
            case "GET", ["settings"]:
                return api.settings(roots)
            case "POST", ["settings"]:
                api.set_env(roots, str(self._body().get("env", "")))
                return api.settings(roots)
            case "GET", ["projects"]:
                return {"projects": api.list_projects(roots)}
            case "GET", ["projects", project, "settings"]:
                return api.project_settings_view(roots, project)
            case "POST", ["projects", project, "settings"]:
                body = self._body()
                return api.save_project_settings_view(
                    roots,
                    project,
                    provenance=body.get("provenance"),
                    named_terms=body.get("named_terms"),
                )
            case "POST", ["plan", "start"]:
                return app.start_plan(self._body())
            case "GET", ["plan", run_id]:
                return app.plan_state(run_id)
            case "POST", ["plan", run_id, "say"]:
                return app.plan_say(run_id, self._body())
            case "POST", ["plan", run_id, "sign"]:
                return app.plan_sign(run_id, self._body())
        raise UIError("Not found.", status=404)


def make_server(roots: Roots, *, port: int = 0) -> ThreadingHTTPServer:
    """A server on 127.0.0.1; port 0 picks a free one (read it from `server_address`)."""
    app = App(roots)
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server
