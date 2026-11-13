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

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autodeck.studio.events import Subscription
from autodeck.studio.session import Studio

API_PREFIX = "/api/"
MAX_MESSAGE_CHARS = 8000
"""A message longer than this is refused (400 `bad_request`)."""

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
    raise NotImplementedError


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
    """
    raise NotImplementedError


def split_path(path: str) -> list[str]:
    """The segments after `/api/`, each percent-decoded once (`urllib.parse.unquote`),
    empty segments dropped. A path not starting with `/api/` raises
    `ApiError("not_found", ...)`."""
    raise NotImplementedError


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
        raise NotImplementedError

    def subscribe(self, path: str, *, last_event_id: int) -> Subscription:
        """For `GET E/threads/<t>/events`: resolve the engagement (`Studio.engagement`) and
        the thread (`ThreadStore.load`, so it must exist) exactly as the JSON routes do,
        then `bus.subscribe(channel_key(client, project, t), after_id=last_event_id)`.

        Raises:
            ApiError: mapped as `to_api_error` (the server turns it into a JSON error
                response before any SSE header is sent).
        """
        raise NotImplementedError

    def is_events_path(self, path: str) -> bool:
        """True when `path` has the shape `/api/engagements/<c>/<p>/threads/<t>/events`
        (segments not yet validated)."""
        raise NotImplementedError

    def image_file(self, render_dir: Path, manifest_images: list[str], n: int) -> bytes:
        """The bytes of the n-th (1-based) image listed in a manifest, read from
        `render_dir / manifest_images[n - 1]`; `not_found` when `n` is out of range or the
        file is missing. The path comes from the manifest, never from the request."""
        raise NotImplementedError
