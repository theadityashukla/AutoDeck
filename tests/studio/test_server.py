"""The HTTP layer over a real socket: localhost only, JSON only, SSE in order, static files."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from autodeck.studio.api import StudioApp
from autodeck.studio.scripted import ScriptedModel
from autodeck.studio.server import CSP, host_ok, make_server, sse_frame
from tests.studio.helpers import CLIENT, PROJECT, make_studio

E = f"/api/engagements/{CLIENT}/{PROJECT}"

STEPS: list[dict[str, Any]] = [
    {"tool_calls": [{"name": "create_deck", "arguments": {"artifact_id": "deck"}}]},
    {"tool_calls": [{"name": "set_brief", "arguments": {"goal": "Approve"}}]},
    {"text": "Started."},
]


def test_host_ok() -> None:
    assert host_ok("127.0.0.1:8765") and host_ok("localhost") and host_ok("[::1]:9")
    assert not host_ok("evil.example:8765") and not host_ok(None) and not host_ok("")
    assert not host_ok("127.0.0.1.evil.example")


def test_sse_frame() -> None:
    assert sse_frame(7, "turn_started", '{"a":1}') == (
        b'id: 7\nevent: turn_started\ndata: {"a":1}\n\n'
    )


@contextmanager
def _serve(tmp_path: Path, knowledge_root: Path) -> Iterator[tuple[int, Any]]:
    """Serve on a free port for the length of a `with` block (called inside each test: it
    runs studio code, so it is not a fixture)."""
    studio, _, _ = make_studio(
        tmp_path, ScriptedModel.from_steps(STEPS), knowledge_root=knowledge_root
    )
    httpd = make_server(StudioApp(studio, env="scripted", scripted=True), port=0)
    assert httpd.server_address[0] == "127.0.0.1"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], studio
    finally:
        httpd.shutdown()
        httpd.server_close()
        studio.shutdown()


def _request(
    port: int,
    method: str,
    path: str,
    body: Any = None,
    *,
    headers: dict[str, str] | None = None,
    raw: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    sent = {"Host": f"127.0.0.1:{port}"}
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        sent["Content-Type"] = "application/json"
    sent.update(headers or {})
    conn.request(method, path, body=data, headers=sent)
    response = conn.getresponse()
    payload = response.read()
    conn.close()
    return response.status, {k.lower(): v for k, v in response.getheaders()}, payload


def test_static_files_and_security_headers(tmp_path: Path, knowledge_root: Path) -> None:
    with _serve(tmp_path, knowledge_root) as (port, _):
        status, headers, body = _request(port, "GET", "/")
        assert status == 200 and headers["content-type"].startswith("text/html")
        assert b"/app.js" in body
        assert headers["content-security-policy"] == CSP
        assert headers["cache-control"] == "no-store"
        assert headers["x-content-type-options"] == "nosniff"
        assert "access-control-allow-origin" not in headers
        assert _request(port, "GET", "/app.css")[0] == 200
        assert _request(port, "GET", "/app.js")[1]["content-type"].startswith("text/javascript")
        assert _request(port, "GET", "/secret.txt")[0] == 404


def test_only_localhost_hosts(tmp_path: Path, knowledge_root: Path) -> None:
    with _serve(tmp_path, knowledge_root) as (port, _):
        status, _, body = _request(port, "GET", "/api/health", headers={"Host": "evil.example"})
        assert status == 403 and json.loads(body)["error"]["code"] == "forbidden_host"
        status, _, _ = _request(port, "GET", "/", headers={"Host": "evil.example"})
        assert status == 403


def test_post_must_be_a_small_json_object(tmp_path: Path, knowledge_root: Path) -> None:
    with _serve(tmp_path, knowledge_root) as (port, _):
        status, _, body = _request(
            port,
            "POST",
            "/api/engagements",
            raw=b"client=x",
            headers={"Content-Type": "text/plain"},
        )
        assert status == 415 and json.loads(body)["error"]["code"] == "unsupported_media_type"
        status, _, body = _request(
            port,
            "POST",
            "/api/engagements",
            raw=b"[1, 2]",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400 and json.loads(body)["error"]["code"] == "bad_request"
        status, _, body = _request(
            port,
            "POST",
            "/api/engagements",
            raw=b"{" + b" " * (70 * 1024) + b"}",
            headers={"Content-Type": "application/json"},
        )
        assert status == 413 and json.loads(body)["error"]["code"] == "payload_too_large"
        status, _, body = _request(port, "GET", "/api/health")
        assert status == 200 and json.loads(body)["ok"] is True


def _read_events(
    response: http.client.HTTPResponse, until: str
) -> list[tuple[int, str, dict[str, Any]]]:
    events: list[tuple[int, str, dict[str, Any]]] = []
    current: dict[str, str] = {}
    while True:
        line = response.readline().decode("utf-8")
        if line == "":
            raise AssertionError(f"stream ended before {until}: {events}")
        line = line.rstrip("\n")
        if line.startswith(":"):
            continue
        if line == "":
            if current:
                events.append(
                    (int(current["id"]), current["event"], json.loads(current["data"]))
                )
                if current["event"] == until:
                    return events
            current = {}
            continue
        key, _, value = line.partition(": ")
        current[key] = value


def _open_stream(
    port: int, path: str, last_event_id: int | None = None
) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": f"localhost:{port}", "Accept": "text/event-stream"}
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    conn.request("GET", path, headers=headers)
    return conn, conn.getresponse()


def test_a_turn_streams_its_events_in_order(tmp_path: Path, knowledge_root: Path) -> None:
    with _serve(tmp_path, knowledge_root) as (port, _):
        assert (
            _request(port, "POST", "/api/engagements", {"client": CLIENT, "project": PROJECT})[
                0
            ]
            == 201
        )
        assert _request(port, "POST", f"{E}/threads", {})[0] == 201
        conn, response = _open_stream(port, f"{E}/threads/t0001/events")
        assert response.status == 200
        assert response.getheader("Content-Type", "").startswith("text/event-stream")
        status, _, body = _request(
            port, "POST", f"{E}/threads/t0001/messages", {"text": "Start a deck"}
        )
        assert status == 202 and json.loads(body) == {"turn_id": "u0001"}
        events = _read_events(response, "previews_ready")
        conn.close()
        names = [name for _, name, _ in events]
        assert names == [
            "turn_started",
            "tool_called",
            "tool_finished",
            "artifact_created",
            "tool_called",
            "tool_finished",
            "change_recorded",
            "assistant_text",
            "turn_finished",
            "previews_ready",
        ]
        ids = [i for i, _, _ in events]
        assert ids == sorted(ids) and len(set(ids)) == len(ids)
        assert all(data["type"] == name for _, name, data in events)
        finished = events[8][2]
        assert finished["turn_kind"] == "change" and finished["change_ids"] == ["c0001"]
        # A reconnect with Last-Event-ID replays only what came after.
        conn, response = _open_stream(port, f"{E}/threads/t0001/events", last_event_id=ids[7])
        replayed = _read_events(response, "previews_ready")
        conn.close()
        assert [name for _, name, _ in replayed] == ["turn_finished", "previews_ready"]


def test_a_stream_for_an_unknown_thread_is_a_json_error(
    tmp_path: Path, knowledge_root: Path
) -> None:
    with _serve(tmp_path, knowledge_root) as (port, _):
        _request(port, "POST", "/api/engagements", {"client": CLIENT, "project": PROJECT})
        conn, response = _open_stream(port, f"{E}/threads/t0003/events")
        body = response.read()
        conn.close()
        assert response.status == 404 and json.loads(body)["error"]["code"] == "not_found"
