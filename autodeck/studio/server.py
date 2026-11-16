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

import importlib.resources
import json
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from autodeck.studio.api import ApiError, Response, StudioApp, error_payload, to_api_error

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
MAX_BODY = 64 * 1024
PING_SECONDS = 15.0
STREAM_POLL_SECONDS = 0.5
"""How often an open event stream wakes to check for shutdown and a vanished client."""
DRAIN_LIMIT = 1024 * 1024
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
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        if end == -1:
            return False
        host = host[: end + 1]
    else:
        host = host.partition(":")[0]
    return host in LOCAL_HOSTS


def sse_frame(event_id: int, event_type: str, data_json: str) -> bytes:
    """`f"id: {event_id}\\nevent: {event_type}\\ndata: {data_json}\\n\\n"` as UTF-8.
    `data_json` contains no newline (compact JSON)."""
    return f"id: {event_id}\nevent: {event_type}\ndata: {data_json}\n\n".encode()


class Handler(BaseHTTPRequestHandler):
    """Dispatches to `app`. `app` is set on a subclass made by `make_server`."""

    app: StudioApp
    server_version = "AutoDeckStudio"

    # -- plumbing ---------------------------------------------------------------------

    def _send_headers(self, status: int, content_type: str, length: int | None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self._send_headers(status, content_type, len(body))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_error(self, code: str, message: str) -> None:
        self._send_response(
            Response(ApiError(code, message).status, error_payload(code, message))
        )

    def _send_response(self, response: Response) -> None:
        if response.body is not None:
            self._send_bytes(response.status, response.content_type, response.body)
            return
        body = json.dumps(response.payload if response.payload is not None else {}).encode()
        self._send_bytes(response.status, "application/json", body)

    def _check_host(self) -> bool:
        if host_ok(self.headers.get("Host")):
            return True
        self._send_error("forbidden_host", "Only localhost may use the studio.")
        return False

    def _static(self, path: str) -> bool:
        entry = STATIC_FILES.get(path)
        if entry is None:
            return False
        name, content_type = entry
        resource = importlib.resources.files("autodeck.studio").joinpath("static", name)
        try:
            body = resource.read_bytes()
        except OSError:
            self._send_error("not_found", "That file is missing.")
            return True
        self._send_bytes(200, content_type, body)
        return True

    def _last_event_id(self, query: str) -> int:
        raw = self.headers.get("Last-Event-ID")
        if raw is None:
            values = parse_qs(query).get("last_event_id")
            raw = values[0] if values else None
        try:
            return max(int(raw), 0) if raw is not None else 0
        except ValueError:
            return 0

    def _client_gone(self) -> bool:
        """True when the peer closed its end (the socket is readable and yields EOF)."""
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return False
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _stream(self, path: str, query: str) -> None:
        try:
            subscription = self.app.subscribe(path, last_event_id=self._last_event_id(query))
        except Exception as exc:
            error = to_api_error(exc)
            self._send_error(error.code, error.message)
            return
        stop: threading.Event | None = getattr(self.server, "stopping", None)
        try:
            self._send_headers(200, "text/event-stream", None)
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.flush()
            self.close_connection = True
            idle = 0.0
            while not (stop is not None and stop.is_set()):
                item = subscription.get(STREAM_POLL_SECONDS)
                if item is not None:
                    data = json.dumps(item.event.model_dump(mode="json"), separators=(",", ":"))
                    self.wfile.write(sse_frame(item.id, item.event.type, data))
                    self.wfile.flush()
                    idle = 0.0
                    continue
                if subscription.closed:
                    break
                idle += STREAM_POLL_SECONDS
                if idle >= PING_SECONDS:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    idle = 0.0
                if self._client_gone():
                    break
        except (OSError, ValueError):
            pass
        finally:
            subscription.close()

    # -- verbs ------------------------------------------------------------------------

    def do_GET(self) -> None:
        """Host check; static file; events stream; else `app.handle("GET", path, None)`."""
        try:
            if not self._check_host():
                return
            split = urlsplit(self.path)
            path = split.path
            if self._static(path):
                return
            if not path.startswith("/api/"):
                self._send_error("not_found", "There is nothing at that address.")
                return
            if self.app.is_events_path(path):
                self._stream(path, split.query)
                return
            self._send_response(self.app.handle("GET", path, None))
        except (OSError, ValueError):
            self.close_connection = True

    def _read_body(self) -> dict[str, Any] | bool | None:
        """The JSON object (or None for an empty body); False when an error was sent."""
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._send_error("unsupported_media_type", "Send the request as application/json.")
            return False
        raw_length = self.headers.get("Content-Length", "0").strip()
        if not raw_length.isdigit():
            self._send_error("bad_request", "Content-Length must be a number.")
            return False
        length = int(raw_length)
        if length > MAX_BODY:
            remaining = min(length, DRAIN_LIMIT)
            while remaining > 0:  # let the client finish sending so it can read the answer
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
            self.close_connection = True
            self._send_error("payload_too_large", "That request body is too large.")
            return False
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return None
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send_error("bad_request", "The request body is not valid JSON.")
            return False
        if not isinstance(body, dict):
            self._send_error("bad_request", "The request body must be a JSON object.")
            return False
        return body

    def do_POST(self) -> None:
        """Host check; content type; length; JSON object; `app.handle("POST", ...)`."""
        try:
            if not self._check_host():
                return
            path = urlsplit(self.path).path
            body = self._read_body()
            if body is False:
                return
            self._send_response(self.app.handle("POST", path, body))  # type: ignore[arg-type]
        except (OSError, ValueError):
            self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        """Silent: the terminal belongs to the person."""
        return


class _StudioServer(ThreadingHTTPServer):
    """Tells open event streams to end when `shutdown()` is called."""

    daemon_threads = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.stopping = threading.Event()

    def shutdown(self) -> None:
        self.stopping.set()
        super().shutdown()


def make_server(app: StudioApp, *, port: int = 0) -> ThreadingHTTPServer:
    """A server on 127.0.0.1 (never another interface); port 0 picks a free one (read it
    from `server.server_address`). `daemon_threads = True`."""
    handler = type("BoundHandler", (Handler,), {"app": app})
    return _StudioServer(("127.0.0.1", port), handler)
