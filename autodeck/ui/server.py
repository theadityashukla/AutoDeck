"""The review UI's local server: a JSON API plus the static front end (B40).

Standard library only (`http.server`), bound to 127.0.0.1. It is a single-user local tool
with no login, so it defends the two ways a web page elsewhere could reach it: requests
must carry a localhost `Host` header (DNS rebinding), and every POST must be
`application/json` (a cross-site form or `text/plain` fetch cannot send that without a
CORS preflight, which this server never grants).

The one approval reachable from here is signing the brief, and it goes through
`PlannerSession.sign_off`, exactly as `/sign` does in `autodeck plan` (A7, B39).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

from autodeck.ui import api
from autodeck.ui.api import Roots, UIError

if TYPE_CHECKING:
    from autodeck.agents.planner import PlannerSession
    from autodeck.providers.guard import ProviderGuard

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.css": ("app.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
MAX_BODY = 1_000_000
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


@dataclass
class LiveSession:
    """A planning conversation held open between requests."""

    session: PlannerSession
    guard: ProviderGuard
    client: str
    project: str
    lock: threading.Lock = field(default_factory=threading.Lock)


class App:
    """State shared by every request: the roots and the open planning sessions."""

    def __init__(self, roots: Roots) -> None:
        self.roots = roots
        self.sessions: dict[str, LiveSession] = {}
        self._sessions_lock = threading.Lock()

    # -- planning -----------------------------------------------------------

    def start_plan(self, body: dict[str, Any]) -> dict[str, Any]:
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
        # Written first, so a session that fails to open (a missing key) leaves a run the
        # UI still recognises as its own and can resume once the cause is fixed.
        api.write_run_meta(self.roots, run_id, client=client, project=project)
        self._open_session(run_id, client, project)
        return {"run_id": run_id}

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
            "transcript": [{"role": t.role, "text": t.text} for t in session.transcript.turns],
        }

    def plan_say(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from autodeck.agents.planner import PlannerError

        text = str(body.get("text", "")).strip()
        if not text:
            raise UIError("Say something first.")
        if text.startswith("/"):
            raise UIError("Use the Sign button to sign; there are no slash commands here.")
        live = self._live(run_id)
        with live.lock:
            try:
                live.session.turn(text)
            except PlannerError as exc:
                raise UIError(str(exc)) from None
            except Exception as exc:
                live.session.save_draft()
                raise UIError(_provider_message(live.guard, exc)) from exc
        return self.plan_state(run_id)

    def plan_sign(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from autodeck.agents.planner import PlannerError

        approver = str(body.get("name", "")).strip()
        if not approver:
            raise UIError("Type your name to sign.")
        live = self._live(run_id)
        with live.lock:
            try:
                brief = live.session.sign_off(approver=approver)
            except PlannerError as exc:
                raise UIError(str(exc)) from None
        return {"version": brief.version, "approved_by": brief.approved_by}


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

    # -- routing -----------------------------------------------------------

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

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
                return {"runs": api.list_runs(roots)}
            case "GET", ["runs", run_id]:
                return api.run_summary(roots, run_id)
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
