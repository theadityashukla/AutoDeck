"""The UI side of the deck agent (Phase 4c): toggle, job command, session route."""

from __future__ import annotations

import json
from typing import Any

import pytest

from autodeck.ui import api, jobs
from autodeck.ui.api import Roots
from autodeck.ui.server import App
from tests.test_ui import Client, make_client, make_run
from tests.test_ui import roots as roots
from tests.test_ui_draft import StubJobs, stub_clarify
from tests.test_ui_draft import http as http

__all__ = ["http", "roots"]


def _record(message: dict[str, Any], summary: str | None, step: int, error: bool = False):  # type: ignore[no-untyped-def]
    message = {"content": "", "tool_calls": [], "tool_call_id": None, **message}
    return {
        "message": message,
        "summary": summary,
        "step": step,
        "meta": {
            "at": "2026-01-01T00:00:00",
            "input_tokens": 0,
            "output_tokens": 0,
            "error": error,
        },
    }


def write_transcript(roots: Roots, run_id: str = "r1") -> None:
    call = {"id": "c1", "name": "read_paper", "arguments": {}}
    records = [
        _record({"role": "user", "content": "Build it."}, None, 0),
        _record({"role": "assistant", "tool_calls": [call]}, None, 1),
        _record(
            {"role": "tool", "content": "ERROR: no", "tool_call_id": "c1"}, "no page", 1, True
        ),
    ]
    folder = roots.runs / run_id / "session"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "transcript.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def test_cli_command_adds_agent_only_for_an_agent_draft(roots: Roots) -> None:
    assert "--agent" in jobs.cli_command("draft", "r1", roots=roots, extra={"agent": True})
    assert "--agent" not in jobs.cli_command("draft", "r1", roots=roots)
    assert "--agent" not in jobs.cli_command("draft", "r1", roots=roots, extra={"agent": False})
    assert "--agent" not in jobs.cli_command("revise", "r1", roots=roots, extra={"agent": True})


def test_agent_labels_follow_the_job() -> None:
    draft = jobs.Job(run_id="r1", steps=["draft"], step="draft", extra={"agent": True})
    assert draft.to_dict()["step_label"] == "Agent drafting"
    revise = jobs.Job(run_id="r1", steps=["revise"], step="revise", extra={"agent": True})
    assert revise.to_dict()["step_label"] == "Agent revising"
    plain = jobs.Job(run_id="r1", steps=["draft"], step="draft")
    assert plain.to_dict()["step_label"] == jobs.STEP_LABELS["draft"]


def test_agent_choice_is_stored_and_carried_into_the_draft_chain(roots: Roots) -> None:
    make_client(roots)
    stub = StubJobs()
    app = App(roots, stub, cli_runner=stub_clarify(roots, []))  # type: ignore[arg-type]
    app.start_draft(
        {"run_id": "r1", "client": "acme", "project": "proj", "prompt": "x", "agent": True}
    )
    assert api.run_uses_agent(roots, "r1")
    assert json.loads((roots.runs / "r1" / "ui.json").read_text())["agent"] is True

    app.submit_answers("r1", {"accept_all": True})
    assert stub.started == [("r1", "draft", {"agent": True})]


def test_without_the_agent_nothing_changes(roots: Roots) -> None:
    make_client(roots)
    app = App(roots, StubJobs(), cli_runner=stub_clarify(roots, []))  # type: ignore[arg-type]
    app.start_draft({"run_id": "r1", "client": "acme", "project": "proj", "prompt": "x"})
    assert not api.run_uses_agent(roots, "r1")
    assert json.loads((roots.runs / "r1" / "ui.json").read_text()) == {
        "client": "acme",
        "project": "proj",
    }


def test_session_route_is_empty_without_a_transcript(
    roots: Roots, http: tuple[Client, App, StubJobs]
) -> None:
    client, _, _ = http
    make_run(roots)
    status, body = client.request("GET", "/api/runs/r1/session")
    assert status == 200
    assert json.loads(body) == {"timeline": [], "meta": None, "active": False}


def test_session_route_returns_rows_and_meta(
    roots: Roots, http: tuple[Client, App, StubJobs]
) -> None:
    client, _, _ = http
    make_run(roots)
    write_transcript(roots)
    (roots.runs / "r1" / "session" / "meta.json").write_text('{"steps": 1}', encoding="utf-8")
    status, body = client.request("GET", "/api/runs/r1/session")
    out = json.loads(body)
    assert status == 200 and out["meta"] == {"steps": 1} and out["active"] is False
    assert [r["role"] for r in out["timeline"]] == ["user", "assistant", "tool"]
    assert out["timeline"][2]["tool"] == "read_paper" and out["timeline"][2]["error"] is True


def test_session_route_rejects_a_bad_run_id(http: tuple[Client, App, StubJobs]) -> None:
    client, _, _ = http
    status, _ = client.request("GET", "/api/runs/..%2Fx/session")
    assert status in (400, 404)


def test_revise_of_an_agent_run_is_marked_agent(roots: Roots) -> None:
    from tests.test_ui_draft import seed_draft

    seed_draft(roots)
    stub = StubJobs()
    app = App(roots, stub)  # type: ignore[arg-type]
    app.start_revise("r1", {"instruction": "Shorter."})
    assert stub.started[-1][2] == {"instruction": "Shorter."}
    write_transcript(roots)
    app.start_revise("r1", {"instruction": "Shorter."})
    assert stub.started[-1][2] == {"instruction": "Shorter.", "agent": True}


@pytest.mark.parametrize("flag", [True, False])
def test_write_run_meta_keeps_the_agent_choice(roots: Roots, flag: bool) -> None:
    api.write_run_meta(roots, "r1", client="a", project="p", agent=flag)
    api.write_run_meta(roots, "r1", client="a", project="p")
    assert api.run_uses_agent(roots, "r1") is flag
