"""The JSON API without a socket: every route, its errors, and client isolation."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from autodeck.studio.api import ApiError, Response, StudioApp, to_api_error
from autodeck.studio.errors import ThreadNotFoundError, TurnInProgressError
from autodeck.studio.scripted import ScriptedModel
from autodeck.studio.session import Studio
from tests.studio.helpers import CLIENT, OTHER_CLIENT, PNG_SIGNATURE, PROJECT, make_studio

E = f"/api/engagements/{CLIENT}/{PROJECT}"
OTHER = f"/api/engagements/{OTHER_CLIENT}/{PROJECT}"

PROPOSE_STEPS: list[dict[str, Any]] = [
    {
        "tool_calls": [
            {"name": "create_deck", "arguments": {"artifact_id": "deck", "title": "Readout"}}
        ]
    },
    {"tool_calls": [{"name": "set_brief", "arguments": {"goal": "Approve"}}]},
    {
        "tool_calls": [
            {
                "name": "propose",
                "arguments": {
                    "summary": "Two tones",
                    "options": [
                        {"label": "Plain", "text": "Plain words."},
                        {"label": "Bold", "text": "Bold words."},
                    ],
                },
            }
        ]
    },
    {"text": "Started, and two tones to choose from."},
    {"text": "Plain it is."},
]


def _app(
    tmp_path: Path, knowledge_root: Path, steps: list[dict[str, Any]] | None = None
) -> tuple[StudioApp, Studio]:
    model = ScriptedModel.from_steps(steps or [{"text": "Hello."}])
    studio, _, _ = make_studio(tmp_path, model, knowledge_root=knowledge_root)
    return StudioApp(studio, env="scripted", scripted=True), studio


def _ok(response: Response, status: int = 200) -> dict[str, Any]:
    assert response.status == status, response.payload
    assert response.payload is not None
    return response.payload


def _error(response: Response, status: int, code: str) -> str:
    assert response.status == status, response.payload
    assert response.payload is not None
    assert set(response.payload) == {"error"} and response.payload["error"]["code"] == code
    return response.payload["error"]["message"]


def _wait(studio: Studio, client: str = CLIENT) -> None:
    engagement = studio.engagement(client, PROJECT)
    for _ in range(200):
        if studio.running_turn(engagement) is None:
            return
        time.sleep(0.02)
    raise AssertionError("turn did not finish")


def _engagement(app: StudioApp, client: str = CLIENT) -> None:
    _ok(app.handle("POST", "/api/engagements", {"client": client, "project": PROJECT}), 201)


def test_health(tmp_path: Path, knowledge_root: Path) -> None:
    app, _ = _app(tmp_path, knowledge_root)
    payload = _ok(app.handle("GET", "/api/health", None))
    assert payload["ok"] is True and payload["model_id"] == "scripted"
    assert payload["env"] == "scripted" and payload["scripted"] is True


def test_engagements_list_and_create(tmp_path: Path, knowledge_root: Path) -> None:
    app, _ = _app(tmp_path, knowledge_root)
    empty = _ok(app.handle("GET", "/api/engagements", None))
    assert empty["engagements"] == []
    assert empty["knowledge"] == {"clients": [OTHER_CLIENT, CLIENT], "projects": [PROJECT]}
    created = _ok(
        app.handle(
            "POST", "/api/engagements", {"client": CLIENT, "project": PROJECT, "title": "Pilot"}
        ),
        201,
    )
    assert (
        created["engagement"]["client"] == CLIENT and created["engagement"]["title"] == "Pilot"
    )
    listed = _ok(app.handle("GET", "/api/engagements", None))["engagements"]
    assert [(e["client"], e["project"]) for e in listed] == [(CLIENT, PROJECT)]
    _error(
        app.handle("POST", "/api/engagements", {"client": CLIENT, "project": PROJECT}),
        409,
        "conflict",
    )
    _error(
        app.handle("POST", "/api/engagements", {"client": "nobody", "project": PROJECT}),
        404,
        "knowledge_not_found",
    )
    _error(
        app.handle("POST", "/api/engagements", {"client": "../x", "project": PROJECT}),
        400,
        "bad_request",
    )
    _error(app.handle("POST", "/api/engagements", {"client": CLIENT}), 400, "bad_request")
    _error(
        app.handle("POST", "/api/engagements", {"client": CLIENT, "project": PROJECT, "x": 1}),
        400,
        "bad_request",
    )


def test_engagement_home(tmp_path: Path, knowledge_root: Path) -> None:
    app, studio = _app(tmp_path, knowledge_root, PROPOSE_STEPS)
    _engagement(app)
    home = _ok(app.handle("GET", E, None))
    assert home["engagement"]["project"] == PROJECT
    assert home["artifacts"] == [] and home["threads"] == [] and home["proposals"] == []
    assert home["sources"][0]["id"] == "knowledge:client/client.md"
    assert home["running_turn"] is None
    thread = _ok(app.handle("POST", f"{E}/threads", {"title": "First"}), 201)
    assert thread["thread"]["id"] == "t0001" and thread["recap_turn_id"] is None
    turn = _ok(app.handle("POST", f"{E}/threads/t0001/messages", {"text": "Start"}), 202)
    assert turn == {"turn_id": "u0001"}
    _wait(studio)
    home = _ok(app.handle("GET", E, None))
    assert [a["id"] for a in home["artifacts"]] == ["deck"]
    assert home["threads"][0]["turns"] == 1 and home["threads"][0]["preview"] == "Start"
    assert [p["id"] for p in home["proposals"]] == ["p0001"]
    _error(
        app.handle("GET", f"/api/engagements/{CLIENT}/other-project", None),
        404,
        "knowledge_not_found",
    )
    _error(app.handle("GET", OTHER, None), 404, "not_found")


def test_thread_routes_and_message_validation(tmp_path: Path, knowledge_root: Path) -> None:
    app, studio = _app(tmp_path, knowledge_root)
    _engagement(app)
    _ok(app.handle("POST", f"{E}/threads", {}), 201)
    for body in (
        {"text": "   "},
        {"text": "x" * 8001},
        {},
        {"text": 3},
        {"text": "hi", "extra": 1},
    ):
        _error(app.handle("POST", f"{E}/threads/t0001/messages", body), 400, "bad_request")
    _ok(app.handle("POST", f"{E}/threads/t0001/messages", {"text": "Hello"}), 202)
    _wait(studio)
    view = _ok(app.handle("GET", f"{E}/threads/t0001", None))
    assert view["thread"]["id"] == "t0001" and view["running_turn"] is None
    assert [m["type"] for m in view["messages"]] == ["user", "assistant"]
    assert view["messages"][1]["texts"] == ["Hello."] and view["messages"][1]["kind"] == "talk"
    listing = _ok(app.handle("GET", f"{E}/threads", None))
    assert [t["id"] for t in listing["threads"]] == ["t0001"]
    _error(app.handle("GET", f"{E}/threads/t0009", None), 404, "not_found")
    _error(app.handle("POST", f"{E}/threads/t0009/messages", {"text": "x"}), 404, "not_found")
    _error(app.handle("GET", f"{E}/threads/t0001/messages", None), 405, "method_not_allowed")
    _error(app.handle("GET", "/api/nowhere", None), 404, "not_found")


def test_artifact_changes_undo_redo_and_images(tmp_path: Path, knowledge_root: Path) -> None:
    app, studio = _app(tmp_path, knowledge_root, PROPOSE_STEPS)
    _engagement(app)
    _ok(app.handle("POST", f"{E}/threads", {}), 201)
    _ok(app.handle("POST", f"{E}/threads/t0001/messages", {"text": "Start"}), 202)
    _wait(studio)
    artifact = _ok(app.handle("GET", f"{E}/artifacts/deck", None))
    assert artifact["id"] == "deck" and artifact["deck"]["title"] == "Readout"
    assert artifact["head"] == "c0001" and artifact["can_undo"] and not artifact["can_redo"]
    render = artifact["render"]
    assert render is not None and render["rendered"]
    assert render["images"] == [] or render["images"][0].startswith(
        f"{E}/artifacts/deck/renders/"
    )
    changes = _ok(app.handle("GET", f"{E}/artifacts/deck/changes", None))
    assert [e["id"] for e in changes["entries"]] == ["c0001"]
    undone = _ok(app.handle("POST", f"{E}/artifacts/deck/undo", {"thread_id": "t0001"}))
    assert undone["entry"]["id"] == "c0001" and not undone["entry"]["live"]
    assert undone["changes"]["can_redo"] is True
    _error(app.handle("POST", f"{E}/artifacts/deck/undo", {}), 409, "nothing_to_undo")
    redone = _ok(app.handle("POST", f"{E}/artifacts/deck/redo", {}))
    assert redone["entry"]["live"]
    _error(app.handle("POST", f"{E}/artifacts/deck/redo", {}), 409, "nothing_to_redo")
    _error(app.handle("GET", f"{E}/artifacts/nope", None), 404, "not_found")
    _error(
        app.handle("POST", f"{E}/artifacts/deck/undo", {"thread_id": "t0042"}), 404, "not_found"
    )
    _error(app.handle("GET", f"{E}/artifacts/deck/renders/XYZ/1.png", None), 400, "bad_request")
    queued = _ok(app.handle("POST", f"{E}/artifacts/deck/render", {"thread_id": "t0001"}), 202)
    assert queued == {"status": "queued"}
    _error(app.handle("POST", f"{E}/artifacts/deck/render", {}), 400, "bad_request")
    _error(
        app.handle("POST", f"{E}/artifacts/nope/render", {"thread_id": "t0001"}),
        404,
        "not_found",
    )


def test_images_are_served_from_the_manifest(
    tmp_path: Path, knowledge_root: Path, base_deck: Any
) -> None:
    app, studio = _app(tmp_path, knowledge_root)
    _engagement(app)
    engagement = studio.engagement(CLIENT, PROJECT)
    store = engagement.create_artifact(base_deck)
    manifest = studio.previews.render_now(store)
    base = f"{E}/artifacts/{base_deck.id}/renders/{manifest.digest}"
    image = app.handle("GET", f"{base}/2.png", None)
    assert image.status == 200 and image.content_type == "image/png"
    assert image.body == PNG_SIGNATURE + b"s2"
    _error(app.handle("GET", f"{base}/5.png", None), 404, "not_found")
    _error(app.handle("GET", f"{base}/0.png", None), 404, "not_found")
    _error(
        app.handle("GET", f"{E}/artifacts/{base_deck.id}/renders/0123456789ab/1.png", None),
        404,
        "not_found",
    )


def test_proposal_pick_and_dismiss(tmp_path: Path, knowledge_root: Path) -> None:
    app, studio = _app(tmp_path, knowledge_root, PROPOSE_STEPS)
    _engagement(app)
    _ok(app.handle("POST", f"{E}/threads", {}), 201)
    _ok(app.handle("POST", f"{E}/threads/t0001/messages", {"text": "Start"}), 202)
    _wait(studio)
    proposal = _ok(app.handle("GET", f"{E}/proposals/p0001", None))
    assert proposal["status"] == "open" and [o["id"] for o in proposal["options"]] == ["A", "B"]
    _error(
        app.handle(
            "POST", f"{E}/proposals/p0001/pick", {"option_id": "C", "thread_id": "t0001"}
        ),
        409,
        "proposal_resolved",
    )
    _error(
        app.handle("POST", f"{E}/proposals/p0001/pick", {"option_id": "A"}), 400, "bad_request"
    )
    picked = _ok(
        app.handle(
            "POST", f"{E}/proposals/p0001/pick", {"option_id": "A", "thread_id": "t0001"}
        ),
        202,
    )
    assert picked["turn_id"] == "u0002" and picked["proposal"]["status"] == "accepted"
    _wait(studio)
    _error(
        app.handle("POST", f"{E}/proposals/p0001/dismiss", {"thread_id": "t0001"}),
        409,
        "proposal_resolved",
    )
    _error(app.handle("GET", f"{E}/proposals/p0009", None), 404, "not_found")


def test_dismiss_route(tmp_path: Path, knowledge_root: Path) -> None:
    app, studio = _app(tmp_path, knowledge_root, PROPOSE_STEPS)
    _engagement(app)
    _ok(app.handle("POST", f"{E}/threads", {}), 201)
    _ok(app.handle("POST", f"{E}/threads/t0001/messages", {"text": "Start"}), 202)
    _wait(studio)
    dismissed = _ok(app.handle("POST", f"{E}/proposals/p0001/dismiss", {"thread_id": "t0001"}))
    assert dismissed["proposal"]["status"] == "dismissed"
    view = _ok(app.handle("GET", f"{E}/threads/t0001", None))
    assert view["messages"][-1]["type"] == "note"


def test_routes_never_cross_clients(tmp_path: Path, knowledge_root: Path) -> None:
    app, studio = _app(tmp_path, knowledge_root, PROPOSE_STEPS)
    _engagement(app)
    _engagement(app, OTHER_CLIENT)
    _ok(app.handle("POST", f"{OTHER}/threads", {}), 201)
    _ok(app.handle("POST", f"{OTHER}/threads/t0001/messages", {"text": "Start"}), 202)
    _wait(studio, OTHER_CLIENT)
    # Another client's ids are simply not there.
    _error(app.handle("GET", f"{E}/threads/t0001", None), 404, "not_found")
    _error(app.handle("GET", f"{E}/proposals/p0001", None), 404, "not_found")
    _error(app.handle("GET", f"{E}/artifacts/deck", None), 404, "not_found")
    with pytest.raises(ApiError):
        app.subscribe(f"{E}/threads/t0001/events", last_event_id=0)
    # Encoded traversal never becomes a path.
    for path in (
        f"/api/engagements/{CLIENT}/..%2F..%2F{OTHER_CLIENT}/threads",
        f"{E}/threads/..%2F..%2F..%2F{OTHER_CLIENT}%2F{PROJECT}%2Fthreads%2Ft0001",
        f"{E}/artifacts/%2E%2E",
    ):
        _error(app.handle("GET", path, None), 400, "bad_request")
    # A symlink planted in this client's workspace is refused, and says nothing.
    engagement = studio.engagement(CLIENT, PROJECT)
    other = studio.engagement(OTHER_CLIENT, PROJECT)
    engagement.paths.threads.mkdir(parents=True, exist_ok=True)
    os.symlink(other.paths.thread("t0001").root, engagement.paths.threads / "t0002")
    message = _error(app.handle("GET", f"{E}/threads/t0002", None), 403, "isolation")
    assert message == "That belongs to another client's engagement."
    _error(app.handle("POST", f"{E}/threads/t0002/messages", {"text": "x"}), 403, "isolation")
    os.symlink(other.paths.artifact("deck").root, engagement.paths.artifacts / "deck")
    _error(app.handle("GET", f"{E}/artifacts/deck", None), 403, "isolation")
    home = _ok(app.handle("GET", E, None))
    assert [t["id"] for t in home["threads"]] == []


def test_subscribe_resolves_like_the_json_routes(tmp_path: Path, knowledge_root: Path) -> None:
    app, _ = _app(tmp_path, knowledge_root)
    _engagement(app)
    _ok(app.handle("POST", f"{E}/threads", {}), 201)
    assert app.is_events_path(f"{E}/threads/t0001/events")
    assert not app.is_events_path(f"{E}/threads/t0001")
    sub = app.subscribe(f"{E}/threads/t0001/events", last_event_id=0)
    assert sub.get(timeout=0.01) is None
    sub.close()
    with pytest.raises(ApiError) as missing:
        app.subscribe(f"{E}/threads/t0005/events", last_event_id=0)
    assert missing.value.code == "not_found"


def test_error_mapping() -> None:
    assert to_api_error(ThreadNotFoundError("x")).code == "not_found"
    assert to_api_error(TurnInProgressError("x")).status == 409
    internal = to_api_error(ZeroDivisionError("boom"))
    assert internal.code == "internal" and internal.message == "ZeroDivisionError: boom"


def test_an_old_proposal_record_does_not_break_the_engagement_home(
    tmp_path: Path, knowledge_root: Path
) -> None:
    """A proposal written before replace-or-insert (`slides` and `insert_at` on the option)
    still loads: the home lists it and says what applying it does was not recorded."""
    import json

    from autodeck.studio.proposals import ProposalStore

    app, studio = _app(tmp_path, knowledge_root, PROPOSE_STEPS)
    _engagement(app)
    _ok(app.handle("POST", f"{E}/threads", {}), 201)
    _ok(app.handle("POST", f"{E}/threads/t0001/messages", {"text": "Start"}), 202)
    _wait(studio)
    engagement = studio.engagement(CLIENT, PROJECT)
    record_path = ProposalStore(engagement).paths("p0001").record
    data = json.loads(record_path.read_text(encoding="utf-8"))
    slide = {"id": "s9", "intent": "Old candidate"}
    for option in data["options"]:
        option.pop("candidates", None)
        option.pop("legacy", None)
        option["slides"] = [slide]
        option["insert_at"] = 2
    data["artifact_id"] = "deck"
    record_path.write_text(json.dumps(data), encoding="utf-8")
    home = _ok(app.handle("GET", E, None))
    options = home["proposals"][0]["options"]
    assert [o["slide_ids"] for o in options] == [["s9"], ["s9"]]
    assert "was not recorded" in options[0]["applies"]
