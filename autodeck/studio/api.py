"""The studio's JSON API, as plain request → response functions (Phase 1).

The HTTP plumbing (`server.py`) parses a request into `(method, path, body)` and calls
`StudioApp.handle`; this module decides what it means. That split keeps every route
testable without a socket (`tests/studio/test_api.py`) and leaves `server.py` only the
parts that need one (host checks, content types, SSE, static files).

The routes, request bodies, response shapes and error shapes are specified in
docs/phases/V3-PHASE-1.md, "Front-end contract"; that document is the authority, and the
route list below must match it.

**Client isolation (A4, V9).** Every route that names an engagement resolves it with
`Studio.engagement(client, project)`, i.e. `open_engagement`, before anything else. Every
thread, artifact and proposal is then looked up through that engagement's own stores, so
an id from another client's engagement is simply not found there, and a directory that
resolves into another client's tree raises `ClientIsolationError` (403). Path segments
are percent-decoded once and then validated (`InvalidSegmentError` → 400), never joined
into a path unchecked. There is no route that takes two clients.

Routes (`E` = `/api/engagements/<client>/<project>`):

| Method | Path | Success |
|---|---|---|
| GET | `/api/health` | 200 |
| GET | `/api/engagements` | 200 |
| POST | `/api/engagements` | 201 |
| GET | `E` | 200 |
| GET | `E/artifacts/<a>` | 200 |
| GET | `E/artifacts/<a>/changes` | 200 |
| POST | `E/artifacts/<a>/undo` | 200 |
| POST | `E/artifacts/<a>/redo` | 200 |
| POST | `E/artifacts/<a>/render` | 202 |
| GET | `E/artifacts/<a>/renders/<digest12>/<n>.png` | 200 image/png |
| GET | `E/threads` | 200 |
| POST | `E/threads` | 201 |
| GET | `E/threads/<t>` | 200 |
| POST | `E/threads/<t>/messages` | 202 |
| GET | `E/threads/<t>/events` | SSE (served by `server.py` via `subscribe`) |
| GET | `E/proposals/<p>` | 200 |
| GET | `E/proposals/<p>/options/<o>/previews/<n>.png` | 200 image/png |
| POST | `E/proposals/<p>/pick` | 202 |
| POST | `E/proposals/<p>/dismiss` | 200 |
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from pydantic import ValidationError

from autodeck.knowledge.loader import ClientIsolationError, KnowledgeError, KnowledgeLoader
from autodeck.studio import views
from autodeck.studio.engagement import Engagement, list_engagements
from autodeck.studio.errors import (
    ArtifactExistsError,
    ArtifactNotFoundError,
    EngagementExistsError,
    EngagementNotFoundError,
    InvalidSegmentError,
    NothingToRedoError,
    NothingToUndoError,
    ProposalNotFoundError,
    ProposalStateError,
    StudioError,
    ThreadNotFoundError,
    TurnInProgressError,
)
from autodeck.studio.events import Subscription, channel_key
from autodeck.studio.previews import read_manifest
from autodeck.studio.proposals import ProposalStore
from autodeck.studio.session import Studio
from autodeck.studio.sources import SourceLibrary
from autodeck.studio.threads import ThreadStore

API_PREFIX = "/api/"
MAX_MESSAGE_CHARS = 8000
"""A message longer than this is refused (400 `bad_request`)."""

ISOLATION_MESSAGE = "That belongs to another client's engagement."

_IMAGE_NAME = re.compile(r"^([0-9]+)\.png$")

ERROR_STATUS: dict[str, int] = {
    "bad_request": 400,
    "isolation": 403,
    "not_found": 404,
    "knowledge_not_found": 404,
    "method_not_allowed": 405,
    "conflict": 409,
    "turn_in_progress": 409,
    "nothing_to_undo": 409,
    "nothing_to_redo": 409,
    "proposal_resolved": 409,
    "unsupported_media_type": 415,
    "payload_too_large": 413,
    "forbidden_host": 403,
    "internal": 500,
}
"""Every error code the API returns, with its HTTP status. The body is always
`{"error": {"code": <code>, "message": <one human sentence>}}`."""


class ApiError(Exception):
    """An error with a code from `ERROR_STATUS` and a message for the owner."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        if code not in ERROR_STATUS:
            raise ValueError(f"unknown API error code {code!r}")
        self.code = code
        self.message = message

    @property
    def status(self) -> int:
        return ERROR_STATUS[self.code]


@dataclass(frozen=True)
class Response:
    """A JSON payload, or bytes with a content type (images)."""

    status: int
    payload: dict[str, Any] | None = None
    body: bytes | None = None
    content_type: str = "application/json"


def error_payload(code: str, message: str) -> dict[str, Any]:
    """`{"error": {"code": code, "message": message}}`."""
    return {"error": {"code": code, "message": message}}


def to_api_error(exc: BaseException) -> ApiError:
    """Map an exception to the API's error. In this order (subclasses before bases):

    * `ApiError` → itself;
    * `InvalidSegmentError` → `bad_request`; pydantic `ValidationError` → `bad_request`
      (message: the first error's location and message);
    * v2's `ClientIsolationError` → `isolation`, message exactly
      "That belongs to another client's engagement." (never the path);
    * v2's `KnowledgeError` → `knowledge_not_found` (its message);
    * `EngagementNotFoundError`, `ArtifactNotFoundError`, `ThreadNotFoundError`,
      `ProposalNotFoundError`, `FileNotFoundError` → `not_found`;
    * `EngagementExistsError`, `ArtifactExistsError` → `conflict`;
    * `TurnInProgressError` → `turn_in_progress`;
    * `NothingToUndoError` → `nothing_to_undo`; `NothingToRedoError` → `nothing_to_redo`;
    * `ProposalStateError` → `proposal_resolved`;
    * anything else → `internal`, message `"<ExceptionType>: <message>"`.

    Messages for the not-found and exists errors are fixed sentences: the exceptions' own
    text names workspace paths, which never reach the owner.
    """
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, InvalidSegmentError):
        return ApiError("bad_request", str(exc))
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        if errors:
            where = ".".join(str(part) for part in errors[0]["loc"])
            message = f"{where}: {errors[0]['msg']}" if where else str(errors[0]["msg"])
        else:
            message = "invalid request"
        return ApiError("bad_request", message)
    if isinstance(exc, ClientIsolationError):
        return ApiError("isolation", ISOLATION_MESSAGE)
    if isinstance(exc, KnowledgeError):
        return ApiError("knowledge_not_found", str(exc))
    if isinstance(exc, EngagementNotFoundError):
        return ApiError("not_found", "There is no such engagement.")
    if isinstance(exc, ArtifactNotFoundError):
        return ApiError("not_found", "There is no such artifact.")
    if isinstance(exc, ThreadNotFoundError):
        return ApiError("not_found", "There is no such thread.")
    if isinstance(exc, ProposalNotFoundError):
        return ApiError("not_found", "There is no such proposal.")
    if isinstance(exc, FileNotFoundError):
        return ApiError("not_found", "Not found.")
    if isinstance(exc, EngagementExistsError):
        return ApiError("conflict", "That engagement already exists.")
    if isinstance(exc, ArtifactExistsError):
        return ApiError("conflict", "That artifact already exists.")
    if isinstance(exc, TurnInProgressError):
        return ApiError("turn_in_progress", str(exc))
    if isinstance(exc, NothingToUndoError):
        return ApiError("nothing_to_undo", str(exc))
    if isinstance(exc, NothingToRedoError):
        return ApiError("nothing_to_redo", str(exc))
    if isinstance(exc, ProposalStateError):
        return ApiError("proposal_resolved", str(exc))
    return ApiError("internal", f"{type(exc).__name__}: {exc}")


def split_path(path: str) -> list[str]:
    """The segments after `/api/`, each percent-decoded once (`urllib.parse.unquote`),
    empty segments dropped. A path not starting with `/api/` raises
    `ApiError("not_found", ...)`."""
    if not path.startswith(API_PREFIX):
        raise ApiError("not_found", "There is nothing at that address.")
    return [unquote(part) for part in path[len(API_PREFIX) :].split("/") if part]


def _raise(exc: Exception) -> Response:
    raise exc


class StudioApp:
    """The API over one `Studio`. Holds no state of its own beyond what it is given."""

    def __init__(self, studio: Studio, *, env: str, scripted: bool) -> None:
        self.studio = studio
        self.env = env
        self.scripted = scripted

    def handle(self, method: str, path: str, body: dict[str, Any] | None) -> Response:
        """Route one request and return the response; never raises.

        `path` has no query string. `body` is the parsed JSON object for POST (the server
        guarantees an object or None) and None for GET. Unknown path → `not_found`; known
        path with the wrong method → `method_not_allowed`. Any exception is mapped with
        `to_api_error` and returned as its error response.

        Body rules: `POST /api/engagements` needs string `client` and `project`, optional
        string `title`. `POST E/threads` takes optional string `title`.
        `POST E/threads/<t>/messages` needs string `text`, non-blank after stripping and at
        most `MAX_MESSAGE_CHARS` characters. `POST .../undo|redo` take optional string
        `thread_id`; so does `POST .../render`. `POST .../pick` needs string `option_id` and
        `thread_id`;
        `.../dismiss` needs string `thread_id`. A missing or mistyped field, or an unknown
        field, is `bad_request` naming the field.
        """
        try:
            return self._dispatch(method, path, body)
        except Exception as exc:
            error = to_api_error(exc)
            return Response(error.status, error_payload(error.code, error.message))

    # -- routing ------------------------------------------------------------------------

    def _dispatch(self, method: str, path: str, body: dict[str, Any] | None) -> Response:
        segments = split_path(path)
        routes = self._routes(segments)
        if routes is None:
            raise ApiError("not_found", "There is nothing at that address.")
        handler = routes.get(method)
        if handler is None:
            raise ApiError("method_not_allowed", f"{method} is not allowed on that address.")
        return handler(body if body is not None else {})

    def _routes(self, s: list[str]) -> dict[str, Callable[[dict[str, Any]], Response]] | None:
        """The handlers (by method) of the route a path names, or None for no such route."""
        if s == ["health"]:
            return {"GET": lambda _b: self._health()}
        if not s or s[0] != "engagements":
            return None
        if len(s) == 1:
            return {
                "GET": lambda _b: self._list_engagements(),
                "POST": self._create_engagement,
            }
        if len(s) < 3:
            return None
        client, project = s[1], s[2]
        rest = s[3:]

        def eng(
            fn: Callable[..., Response], *args: str
        ) -> Callable[[dict[str, Any]], Response]:
            def run(body: dict[str, Any]) -> Response:
                engagement = self.studio.engagement(client, project)
                return fn(engagement, *args, body)

            return run

        if not rest:
            return {"GET": eng(self._home)}
        kind = rest[0]
        if kind == "artifacts" and len(rest) >= 2:
            a = rest[1]
            tail = rest[2:]
            if not tail:
                return {"GET": eng(self._artifact, a)}
            if tail == ["changes"]:
                return {"GET": eng(self._changes, a)}
            if tail == ["undo"]:
                return {"POST": eng(self._revert, a, "undo")}
            if tail == ["redo"]:
                return {"POST": eng(self._revert, a, "redo")}
            if tail == ["render"]:
                return {"POST": eng(self._render, a)}
            if len(tail) == 3 and tail[0] == "renders":
                return {"GET": eng(self._artifact_image, a, tail[1], tail[2])}
            return None
        if kind == "threads":
            if len(rest) == 1:
                return {"GET": eng(self._threads), "POST": eng(self._new_thread)}
            t = rest[1]
            if len(rest) == 2:
                return {"GET": eng(self._thread, t)}
            if rest[2:] == ["messages"]:
                return {"POST": eng(self._message, t)}
            if rest[2:] == ["events"]:
                return {
                    "GET": lambda _b: _raise(
                        ApiError("not_found", "Event streams are served by the server.")
                    )
                }
            return None
        if kind == "proposals" and len(rest) >= 2:
            p = rest[1]
            tail = rest[2:]
            if not tail:
                return {"GET": eng(self._proposal, p)}
            if tail == ["pick"]:
                return {"POST": eng(self._pick, p)}
            if tail == ["dismiss"]:
                return {"POST": eng(self._dismiss, p)}
            if len(tail) == 4 and tail[0] == "options" and tail[2] == "previews":
                return {"GET": eng(self._proposal_image, p, tail[1], tail[3])}
            return None
        return None

    # -- body validation ----------------------------------------------------------------

    @staticmethod
    def _fields(
        body: dict[str, Any], *, required: tuple[str, ...] = (), optional: tuple[str, ...] = ()
    ) -> dict[str, str]:
        """The string fields of a body; `bad_request` naming a missing, mistyped or
        unknown field."""
        for name in body:
            if name not in required and name not in optional:
                raise ApiError("bad_request", f"Unknown field {name!r}.")
        out: dict[str, str] = {}
        for name in (*required, *optional):
            if name not in body:
                if name in required:
                    raise ApiError("bad_request", f"Field {name!r} is required.")
                continue
            value = body[name]
            if not isinstance(value, str):
                raise ApiError("bad_request", f"Field {name!r} must be a string.")
            out[name] = value
        return out

    # -- routes -------------------------------------------------------------------------

    def _health(self) -> Response:
        return Response(
            200,
            {
                "ok": True,
                "model_id": self.studio.lead.model_id,
                "env": self.env,
                "scripted": self.scripted,
            },
        )

    def _list_engagements(self) -> Response:
        engagements: list[dict[str, Any]] = []
        for client, project in list_engagements(self.studio.settings.workspace_root):
            try:
                view = views.engagement_view(self.studio.engagement(client, project).record)
                engagements.append({**view, "error": None})
            except Exception as exc:
                engagements.append(
                    {
                        "client": client,
                        "project": project,
                        "title": "",
                        "created_at": "",
                        "error": to_api_error(exc).message,
                    }
                )
        loader = KnowledgeLoader(self.studio.settings.knowledge_root)
        knowledge = {
            "clients": sorted(loader.client_names()),
            "projects": sorted(loader.project_names()),
        }
        return Response(200, {"engagements": engagements, "knowledge": knowledge})

    def _create_engagement(self, body: dict[str, Any]) -> Response:
        fields = self._fields(body, required=("client", "project"), optional=("title",))
        engagement = self.studio.create_engagement(
            fields["client"], fields["project"], title=fields.get("title", "")
        )
        return Response(201, {"engagement": views.engagement_view(engagement.record)})

    def _home(self, engagement: Engagement, _body: dict[str, Any]) -> Response:
        artifacts: list[dict[str, Any]] = []
        for artifact_id in engagement.artifact_ids():
            try:
                store = engagement.artifact_store(artifact_id)
                artifacts.append(views.artifact_summary(store.load(), store.changelog()))
            except (ClientIsolationError, StudioError, ValueError, OSError):
                continue
        thread_store = ThreadStore(engagement)
        threads: list[dict[str, Any]] = []
        for record in thread_store.list():
            try:
                threads.append(views.thread_summary(record, thread_store.read_lines(record.id)))
            except (ClientIsolationError, StudioError, ValueError, OSError):
                continue
        library = SourceLibrary(engagement, corpus_root=self.studio.settings.corpus_root)
        sources = [
            {"id": i.id, "kind": i.kind, "title": i.title, "detail": i.detail}
            for i in library.list()
        ]
        proposals = [
            self._proposal_view(engagement, record)
            for record in ProposalStore(engagement).list()
        ]
        return Response(
            200,
            {
                "engagement": views.engagement_view(engagement.record),
                "artifacts": artifacts,
                "threads": threads,
                "sources": sources,
                "proposals": proposals,
                "running_turn": self.studio.running_turn(engagement),
            },
        )

    @staticmethod
    def _base(engagement: Engagement) -> str:
        return (
            f"/api/engagements/{quote(engagement.client, safe='')}"
            f"/{quote(engagement.project, safe='')}"
        )

    def _artifact(
        self, engagement: Engagement, artifact_id: str, _body: dict[str, Any]
    ) -> Response:
        store = engagement.artifact_store(artifact_id)
        deck = store.load()
        log = store.changelog()
        manifest = self.studio.previews.current(store)
        base = f"{self._base(engagement)}/artifacts/{quote(artifact_id, safe='')}/renders"
        return Response(200, views.artifact_view(deck, log, manifest, base=base))

    def _changes(
        self, engagement: Engagement, artifact_id: str, _body: dict[str, Any]
    ) -> Response:
        store = engagement.artifact_store(artifact_id)
        return Response(200, views.changes_view(store.changelog()))

    def _revert(
        self, engagement: Engagement, artifact_id: str, action: str, body: dict[str, Any]
    ) -> Response:
        thread_id = self._fields(body, optional=("thread_id",)).get("thread_id")
        if action == "undo":
            entry = self.studio.owner_undo(engagement, artifact_id, thread_id=thread_id)
        else:
            entry = self.studio.owner_redo(engagement, artifact_id, thread_id=thread_id)
        log = engagement.artifact_store(artifact_id).changelog()
        return Response(
            200,
            {"entry": views.change_view(entry, log), "changes": views.changes_view(log)},
        )

    def _render(
        self, engagement: Engagement, artifact_id: str, body: dict[str, Any]
    ) -> Response:
        thread_id = self._fields(body, required=("thread_id",))["thread_id"]
        self.studio.request_render(engagement, artifact_id, thread_id=thread_id)
        return Response(202, {"status": "queued"})

    def _artifact_image(
        self,
        engagement: Engagement,
        artifact_id: str,
        digest: str,
        name: str,
        _body: dict[str, Any],
    ) -> Response:
        n = self._image_number(name)
        render_dir = engagement.artifact_store(artifact_id).paths.render_dir(digest)
        engagement.guard(render_dir)
        manifest = read_manifest(render_dir)
        if manifest is None or not manifest.rendered:
            raise ApiError("not_found", "There is no such image.")
        return Response(
            200, body=self.image_file(render_dir, manifest.images, n), content_type="image/png"
        )

    @staticmethod
    def _image_number(name: str) -> int:
        match = _IMAGE_NAME.match(name)
        if match is None:
            raise ApiError("not_found", "There is no such image.")
        return int(match.group(1))

    def _threads(self, engagement: Engagement, _body: dict[str, Any]) -> Response:
        store = ThreadStore(engagement)
        rows: list[dict[str, Any]] = []
        for record in store.list():
            try:
                rows.append(views.thread_summary(record, store.read_lines(record.id)))
            except (ClientIsolationError, StudioError, ValueError, OSError):
                continue
        return Response(200, {"threads": rows})

    def _new_thread(self, engagement: Engagement, body: dict[str, Any]) -> Response:
        title = self._fields(body, optional=("title",)).get("title", "")
        record, recap_turn_id = self.studio.begin_open_thread(engagement, title=title)
        return Response(
            201,
            {"thread": views.thread_summary(record, []), "recap_turn_id": recap_turn_id},
        )

    def _thread(
        self, engagement: Engagement, thread_id: str, _body: dict[str, Any]
    ) -> Response:
        store = ThreadStore(engagement)
        record = store.load(thread_id)
        lines = store.read_lines(thread_id)
        return Response(
            200,
            {
                "thread": views.thread_summary(record, lines),
                "messages": views.messages_view(lines),
                "running_turn": self.studio.running_turn(engagement),
            },
        )

    def _message(
        self, engagement: Engagement, thread_id: str, body: dict[str, Any]
    ) -> Response:
        text = self._fields(body, required=("text",))["text"]
        if not text.strip():
            raise ApiError("bad_request", "Field 'text' must not be blank.")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ApiError(
                "bad_request", f"Field 'text' is longer than {MAX_MESSAGE_CHARS} characters."
            )
        turn_id = self.studio.begin_turn(engagement, thread_id, text=text)
        return Response(202, {"turn_id": turn_id})

    def _proposal_view(self, engagement: Engagement, record: Any) -> dict[str, Any]:
        base = f"{self._base(engagement)}/proposals/{quote(record.id, safe='')}/options"
        previews: dict[Any, list[str]] = {}
        for option in record.options:
            if not option.slides:
                continue
            manifest = self.studio.previews.proposal_manifest(engagement, record.id, option.id)
            if manifest is not None and manifest.rendered:
                previews[option.id] = [
                    f"{base}/{option.id}/previews/{n}.png"
                    for n in range(1, len(manifest.images) + 1)
                ]
        deck = None
        if record.artifact_id is not None and any(o.slides for o in record.options):
            try:
                deck = engagement.artifact_store(record.artifact_id).load()
            except (StudioError, OSError, ValueError):
                deck = None
        return views.proposal_view(record, previews=previews, deck=deck)

    def _proposal(
        self, engagement: Engagement, proposal_id: str, _body: dict[str, Any]
    ) -> Response:
        record = ProposalStore(engagement).load(proposal_id)
        return Response(200, self._proposal_view(engagement, record))

    def _proposal_image(
        self,
        engagement: Engagement,
        proposal_id: str,
        option_id: str,
        name: str,
        _body: dict[str, Any],
    ) -> Response:
        n = self._image_number(name)
        ProposalStore(engagement).load(proposal_id)
        render_dir = self.studio.previews.proposal_render_dir(
            engagement, proposal_id, option_id
        )
        engagement.guard(render_dir)
        manifest = read_manifest(render_dir)
        if manifest is None or not manifest.rendered:
            raise ApiError("not_found", "There is no such image.")
        return Response(
            200, body=self.image_file(render_dir, manifest.images, n), content_type="image/png"
        )

    def _pick(self, engagement: Engagement, proposal_id: str, body: dict[str, Any]) -> Response:
        fields = self._fields(body, required=("option_id", "thread_id"))
        turn_id = self.studio.begin_pick_option(
            engagement, fields["thread_id"], proposal_id, fields["option_id"]
        )
        record = ProposalStore(engagement).load(proposal_id)
        return Response(
            202, {"turn_id": turn_id, "proposal": self._proposal_view(engagement, record)}
        )

    def _dismiss(
        self, engagement: Engagement, proposal_id: str, body: dict[str, Any]
    ) -> Response:
        thread_id = self._fields(body, required=("thread_id",))["thread_id"]
        record = self.studio.dismiss_proposal(engagement, thread_id, proposal_id)
        return Response(200, {"proposal": self._proposal_view(engagement, record)})

    def subscribe(self, path: str, *, last_event_id: int) -> Subscription:
        """For `GET E/threads/<t>/events`: resolve the engagement (`Studio.engagement`) and
        the thread (`ThreadStore.load`, so it must exist) exactly as the JSON routes do,
        then `bus.subscribe(channel_key(client, project, t), after_id=last_event_id)`.

        Raises:
            ApiError: mapped as `to_api_error` (the server turns it into a JSON error
                response before any SSE header is sent).
        """
        try:
            segments = split_path(path)
            if not self._is_events_segments(segments):
                raise ApiError("not_found", "There is nothing at that address.")
            client, project, thread_id = segments[1], segments[2], segments[4]
            engagement = self.studio.engagement(client, project)
            ThreadStore(engagement).load(thread_id)
            return self.studio.bus.subscribe(
                channel_key(engagement.client, engagement.project, thread_id),
                after_id=last_event_id,
            )
        except Exception as exc:
            raise to_api_error(exc) from exc

    def is_events_path(self, path: str) -> bool:
        """True when `path` has the shape `/api/engagements/<c>/<p>/threads/<t>/events`
        (segments not yet validated)."""
        try:
            return self._is_events_segments(split_path(path))
        except ApiError:
            return False

    @staticmethod
    def _is_events_segments(segments: list[str]) -> bool:
        return (
            len(segments) == 6
            and segments[0] == "engagements"
            and segments[3] == "threads"
            and segments[5] == "events"
        )

    def image_file(self, render_dir: Path, manifest_images: list[str], n: int) -> bytes:
        """The bytes of the n-th (1-based) image listed in a manifest, read from
        `render_dir / manifest_images[n - 1]`; `not_found` when `n` is out of range or the
        file is missing. The path comes from the manifest, never from the request."""
        if n < 1 or n > len(manifest_images):
            raise ApiError("not_found", "There is no such image.")
        root = render_dir.resolve()
        target = (render_dir / manifest_images[n - 1]).resolve()
        if not target.is_relative_to(root):
            raise ApiError("not_found", "There is no such image.")
        try:
            return target.read_bytes()
        except OSError:
            raise ApiError("not_found", "There is no such image.") from None
