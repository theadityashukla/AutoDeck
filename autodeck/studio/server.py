"""The studio's local HTTP server: JSON API, Server-Sent Events, static front end.

Standard library only (`http.server.ThreadingHTTPServer`), bound to 127.0.0.1, as v2's UI
server (`autodeck/ui/server.py`): a single-user local tool with no login defends the two
ways a page elsewhere could reach it:

* every request must carry a localhost `Host` header (`LOCAL_HOSTS`, port ignored),
  against DNS rebinding; anything else gets 403 `forbidden_host` before routing;
* every POST must be `Content-Type: application/json` (415 otherwise), so a cross-site
  form or `text/plain` fetch cannot send one without a CORS preflight, which this server
  never grants (no CORS headers are ever sent). Bodies over `MAX_BODY` bytes are 413;
  a body that is not a JSON object is 400.

Every response carries `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer` and the Content-Security-Policy `CSP` (no external
resources: the front end uses no library and no remote font).

**Streaming.** `GET E/threads/<t>/events` is answered with `text/event-stream`. The
subscription is resolved first (`StudioApp.subscribe`, so a bad engagement or thread gets
a normal JSON error). Then, for each published event: `id: <n>`, `event: <type>`,
`data: <compact JSON of the event>`, blank line; a `: ping` comment line every
`PING_SECONDS` without events; the stream ends when the client disconnects or the server
shuts down. `Last-Event-ID` (header) or `?last_event_id=` (query, for `EventSource`
reconnects done by hand) selects the replay start.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from autodeck.studio.api import StudioApp

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
MAX_BODY = 64 * 1024
PING_SECONDS = 15.0
CSP = (
    "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)

STATIC_FILES: dict[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
"""Path → (file in `autodeck/studio/static/`, content type). Read with
`importlib.resources.files("autodeck.studio").joinpath("static", name)`. Anything else
outside `/api/` is 404."""


def host_ok(host_header: str | None) -> bool:
    """True when the `Host` header's host part (port stripped; `[::1]:8765` → `[::1]`) is
    in `LOCAL_HOSTS`. A missing header is False."""
    raise NotImplementedError


def sse_frame(event_id: int, event_type: str, data_json: str) -> bytes:
    """`f"id: {event_id}\\nevent: {event_type}\\ndata: {data_json}\\n\\n"` as UTF-8.
    `data_json` contains no newline (compact JSON)."""
    raise NotImplementedError


class Handler(BaseHTTPRequestHandler):
    """Dispatches to `app`. `app` is set on a subclass made by `make_server`."""

    app: StudioApp
    server_version = "AutoDeckStudio"

    def do_GET(self) -> None:
        """Host check; static file; events stream; else `app.handle("GET", path, None)`."""
        raise NotImplementedError

    def do_POST(self) -> None:
        """Host check; content type; length; JSON object; `app.handle("POST", ...)`."""
        raise NotImplementedError

    def log_message(self, format: str, *args: object) -> None:
        """Silent: the terminal belongs to the person."""
        return


def make_server(app: StudioApp, *, port: int = 0) -> ThreadingHTTPServer:
    """A server on 127.0.0.1 (never another interface); port 0 picks a free one (read it
    from `server.server_address`). `daemon_threads = True`."""
    raise NotImplementedError
