"""The meeting UI (step 12, B83): the recording upload, the transcribe → notes chain, the notes
editor's routes, "make a deck from this meeting", and the agent session for a notes-only run.

Offline: jobs go through a stub manager (or a real one running `python -c` commands), the
clarify call through a stub runner, and no model is touched. Nothing here prints or logs a
word of a transcript or notes.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from autodeck.ui import api, jobs
from autodeck.ui.api import Roots, UIError
from autodeck.ui.server import App
from tests.test_renderer import _citation, _claim_block, _deck, _slide
from tests.test_ui import Client, make_client, make_run
from tests.test_ui import roots as roots
from tests.test_ui_agent import _record
from tests.test_ui_draft import StubJobs, stub_clarify
from tests.test_ui_draft import http as http

__all__ = ["http", "roots"]

RUN = "m1"
HEADER = {"X-AutoDeck-Upload": "1"}

SAID = [
    (0.0, 4.0, "Welcome, everyone, to the board call."),
    (4.0, 9.5, "The rollout starts in the first week of February."),
    (65.0, 70.0, "Shikha will own the data bricks migration."),
]

NOTES = """# Meeting notes

Date: not given

## Summary

- The rollout is planned for February. [00:04] <!-- n1 -->

## Attendees

_None noted._

## Decisions

- Start the rollout in February. [00:04] <!-- n2 -->
- Migrate to Databricks. [01:05] <!-- n3 -->

## Action items

- **Shikha**: Own the migration. [01:05] <!-- n4 -->
"""


@pytest.fixture(autouse=True)
def uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "uploads"
    monkeypatch.setenv("AUTODECK_UPLOADS_DIR", str(folder))
    return folder


def seed_meeting(
    roots: Roots,
    run_id: str = RUN,
    *,
    notes: str | None = NOTES,
    note_to_person: str | None = None,
    notes_session: bool = False,
    client: str = "acme",
    project: str = "proj",
    said: list[tuple[float, float, str]] | None = None,
) -> Path:
    """A meeting run as `meeting transcribe` and `meeting notes` leave it (no model needed)."""
    from autodeck.ingest.transcript_source import ingest_transcript, save_meeting_settings
    from autodeck.meeting.schema import AudioInfo, Segment, Transcript, TranscriptModels

    make_run(roots, run_id)
    api.write_run_meta(roots, run_id, client=client, project=project, meeting=True)
    root = roots.runs / run_id
    transcript = Transcript(
        audio=AudioInfo(
            name="board.m4a", sha256="ab" * 32, duration_s=max(e for _, e, _ in (said or SAID))
        ),
        models=TranscriptModels(asr="a", vad="v", diarization=None, sherpa_onnx="1"),
        segments=[Segment(start=s, end=e, text=t) for s, e, t in (said or SAID)],
        speakers_labelled=False,
        timings={"total": 1.0},
    )
    transcript.save(root / "meeting")
    doc_id = ingest_transcript(root, run_id)
    save_meeting_settings(
        root,
        {
            "audio_name": "board.m4a",
            "audio_sha256": "ab" * 32,
            "client": client,
            "project": project,
            "doc_id": doc_id,
            "check_papers": False,
        },
    )
    if notes is not None:
        (root / "meeting" / "notes.md").write_text(notes, encoding="utf-8")
        (root / "meeting" / "notes.rendered.md").write_text(notes, encoding="utf-8")
    if note_to_person:
        (root / "meeting" / "agent-note.md").write_text(note_to_person + "\n", encoding="utf-8")
    if notes_session:
        write_session(root, "notes_transcript.jsonl", "notes_meta.json", {"kind": "notes"})
    return root


def write_session(root: Path, transcript: str, meta: str, meta_data: dict[str, Any]) -> None:
    folder = root / "session"
    folder.mkdir(parents=True, exist_ok=True)
    call = {"id": "c1", "name": "show_notes", "arguments": {}}
    records = [
        _record({"role": "user", "content": "Take the notes."}, None, 0),
        _record({"role": "assistant", "tool_calls": [call]}, None, 1),
        _record({"role": "tool", "content": "ok", "tool_call_id": "c1"}, "4 items", 1),
    ]
    (folder / transcript).write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    (folder / meta).write_text(json.dumps(meta_data), encoding="utf-8")


def raw(
    port: int,
    path: str,
    headers: dict[str, str],
    body: bytes = b"",
    *,
    length: int | None = None,
    half_close: bool = False,
) -> tuple[int, dict[str, Any]]:
    """One raw POST: `length` is what Content-Length claims (None: the header is omitted)."""
    lines = [f"POST {path} HTTP/1.1", f"Host: 127.0.0.1:{port}", "Connection: close"]
    lines += [f"{k}: {v}" for k, v in headers.items()]
    if length is not None:
        lines.append(f"Content-Length: {length}")
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
        if half_close:
            sock.shutdown(socket.SHUT_WR)
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    finally:
        sock.close()
    head, _, payload = data.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    try:
        return status, json.loads(payload or b"{}")
    except ValueError:
        return status, {}


QUERY = "run_id=m1&client=acme&project=proj&name=board.m4a"
URL = f"/api/meeting/upload?{QUERY}"


def files_under(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file()) if folder.exists() else []


def wait_until(check: Any, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return check()


# -- the upload route ------------------------------------------------------------------------


def test_upload_refusals_come_before_the_body_is_read(
    roots: Roots, http: tuple[Client, App, StubJobs], uploads: Path
) -> None:
    make_client(roots)
    client, _, stub = http
    port = client.port
    ok = {**HEADER, "Content-Type": "application/octet-stream"}
    big = 1024**3 + 1

    # No body is ever sent: a refusal that read the body would hang until the timeout.
    assert raw(port, URL, {"Content-Type": "application/octet-stream"}, length=10)[0] == 403
    assert raw(port, URL.replace("board.m4a", "board.txt"), ok, length=10)[0] == 415
    assert raw(port, URL.replace("board.m4a", "board"), ok, length=10)[0] == 415
    assert raw(port, URL, ok)[0] == 411
    status, body = raw(port, URL, ok, length=big)
    assert status == 413 and body["error"] == "That recording is over the 1 GB limit."
    assert raw(port, URL, ok, length=0)[0] == 400
    assert stub.started == [] and files_under(uploads) == []
    assert not (roots.runs / RUN).exists()


def test_upload_is_streamed_to_the_uploads_folder_and_starts_the_chain(
    roots: Roots, http: tuple[Client, App, StubJobs], uploads: Path
) -> None:
    make_client(roots)
    client, _, stub = http
    audio = (b"RIFF" + bytes(range(256))) * 12_000  # about 3 MB: several 1 MiB chunks
    query = f"{QUERY}&with_papers=true&date=Tuesday+the+4th&attendees=Shikha,+Dev"
    status, payload = client.request(
        "POST",
        f"/api/meeting/upload?{query}",
        raw=audio,
        headers={**HEADER, "Content-Type": "audio/mp4"},
    )
    assert status == 200
    out = json.loads(payload)
    assert out["run_id"] == RUN and out["job"]["steps"] == ["transcribe", "notes"]

    target = uploads / RUN / "board.m4a"
    assert target.read_bytes() == audio
    assert not list(roots.runs.rglob("*.m4a"))  # never in the repo's runs folder
    assert api.read_run_meta(roots, RUN) == {"client": "acme", "project": "proj"}
    assert api.run_is_meeting(roots, RUN)
    [(run_id, chain, extra)] = stub.started
    assert (run_id, chain) == (RUN, "meeting")
    assert extra["audio"] == str(target)
    assert extra["delete_after"] == {"step": "transcribe", "path": str(target)}
    assert extra["with_papers"] is True and extra["date"] == "Tuesday the 4th"
    assert extra["attendees"] == "Shikha, Dev"

    transcribe = jobs.cli_command("transcribe", RUN, roots=roots, extra=extra)
    assert transcribe[3:6] == ["meeting", "transcribe", RUN]
    assert transcribe[transcribe.index("--audio") + 1] == str(target)
    assert transcribe[transcribe.index("--client") + 1] == "acme"
    assert transcribe[transcribe.index("--project") + 1] == "proj"
    assert "--with-papers" in transcribe
    notes = jobs.cli_command("notes", RUN, roots=roots, extra=extra)
    assert notes[3:6] == ["meeting", "notes", RUN]
    assert notes[notes.index("--date") + 1] == "Tuesday the 4th"
    assert notes[notes.index("--attendees") + 1] == "Shikha, Dev"
    plain = jobs.cli_command("transcribe", RUN, roots=roots, extra={"audio": "a.m4a"})
    assert "--with-papers" not in plain
    assert plain[plain.index("--client") + 1] == "acme"  # falls back to the run's meta
    assert "--date" not in jobs.cli_command("notes", RUN, roots=roots)


def test_upload_name_is_made_safe(
    roots: Roots, http: tuple[Client, App, StubJobs], uploads: Path
) -> None:
    make_client(roots)
    client, _, stub = http
    name = "..%2F..%2Fevil%20call%3F.M4A"
    status, _ = client.request(
        "POST",
        f"/api/meeting/upload?run_id=m1&client=acme&project=proj&name={name}",
        raw=b"abc",
        headers=HEADER,
    )
    assert status == 200
    assert [p.relative_to(uploads).as_posix() for p in files_under(uploads)] == [
        "m1/evil call_.m4a"
    ]
    assert Path(stub.started[0][2]["audio"]).parent == uploads / "m1"


def test_upload_of_an_existing_run_or_unknown_client_is_refused(
    roots: Roots, http: tuple[Client, App, StubJobs], uploads: Path
) -> None:
    make_client(roots)
    client, _, stub = http
    seed_meeting(roots)
    for url, expected in (
        (URL, 409),
        (URL.replace("run_id=m1", "run_id=fresh").replace("acme", "ghost"), 400),
        (URL.replace("run_id=m1", "run_id=fresh").replace("proj", "ghost"), 400),
        (URL.replace("run_id=m1", "run_id=..%2Fx"), 400),
    ):
        status, _ = client.request("POST", url, raw=b"abc", headers=HEADER)
        assert status == expected, url
    assert stub.started == [] and files_under(uploads) == []


def test_a_cut_off_upload_leaves_nothing_behind(
    roots: Roots, http: tuple[Client, App, StubJobs], uploads: Path
) -> None:
    make_client(roots)
    client, _, stub = http
    status, body = raw(
        client.port,
        URL,
        HEADER,
        b"x" * (1024 * 1024 + 5),
        length=3 * 1024 * 1024,
        half_close=True,
    )
    assert status == 400 and "stopped" in body["error"]
    assert wait_until(lambda: files_under(uploads) == [])
    assert stub.started == [] and not (roots.runs / RUN).exists()
    assert not (uploads / RUN).exists()  # the empty run folder went too


# -- delete_after ----------------------------------------------------------------------------


def command_for(transcribe_code: int, *, notes_needs_gone: Path | None = None) -> Any:
    def build(step: str, run_id: str, extra: dict[str, Any] | None = None) -> list[str]:
        if step == "transcribe":
            return [sys.executable, "-c", f"import sys; sys.exit({transcribe_code})"]
        check = (
            f"import os, sys; sys.exit(7 if os.path.exists({str(notes_needs_gone)!r}) else 0)"
            if notes_needs_gone
            else "pass"
        )
        return [sys.executable, "-c", check]

    return build


def upload_file(uploads: Path, name: str = "board.m4a") -> Path:
    folder = uploads / RUN
    folder.mkdir(parents=True)
    path = folder / name
    path.write_bytes(b"audio")
    return path


@pytest.mark.parametrize("code", [0, 1])
def test_the_recording_is_gone_when_transcribe_ends_whatever_its_result(
    uploads: Path, code: int
) -> None:
    path = upload_file(uploads)
    manager = jobs.JobManager(command_for(code, notes_needs_gone=path))
    manager.start(RUN, "meeting", {"delete_after": {"step": "transcribe", "path": str(path)}})
    job = manager.wait(RUN)
    assert job is not None
    # On success the notes step ran and saw the file already gone (it exits 7 otherwise).
    assert job.status == ("done" if code == 0 else "failed")
    assert not path.exists() and not path.parent.exists()


def test_a_stopped_job_deletes_the_recording_too(uploads: Path) -> None:
    path = upload_file(uploads)
    manager = jobs.JobManager(
        lambda step, run_id, extra=None: [sys.executable, "-c", "import time; time.sleep(60)"]
    )
    manager.start(RUN, "meeting", {"delete_after": {"step": "transcribe", "path": str(path)}})
    assert wait_until(lambda: (job := manager.get(RUN)) is not None and job.process is not None)
    manager.stop(RUN)
    job = manager.wait(RUN)
    assert job is not None and job.status == "stopped"
    assert not path.exists()


def test_a_path_outside_the_uploads_folder_is_never_deleted(
    uploads: Path, tmp_path: Path
) -> None:
    uploads.mkdir()
    outside = tmp_path / "precious.m4a"
    outside.write_bytes(b"keep me")
    sneaky = uploads / ".." / "precious.m4a"
    link = uploads / "link.m4a"
    link.symlink_to(outside)
    for target in (outside, sneaky, link, uploads, uploads / "missing.m4a", Path("")):
        manager = jobs.JobManager(command_for(0))
        manager.start(
            RUN, "meeting", {"delete_after": {"step": "transcribe", "path": str(target)}}
        )
        manager.wait(RUN)
        assert outside.read_bytes() == b"keep me", target
        assert uploads.is_dir()
    assert not jobs.remove_upload(str(outside))


def test_labels_and_chains_for_the_meeting_steps() -> None:
    assert jobs.CHAINS["meeting"] == ["transcribe", "notes"]
    assert jobs.CHAINS["revise-notes"] == ["revise-notes"]
    assert jobs.STEP_LABELS["transcribe"] == "Transcribing on this computer"
    assert jobs.STEP_LABELS["notes"] == "Writing the notes"
    assert jobs.STEP_LABELS["revise-notes"] == "Revising the notes"
    job = jobs.Job(run_id=RUN, steps=["transcribe", "notes"], step="transcribe")
    assert job.to_dict()["step_label"] == "Transcribing on this computer"
    assert "delete_after" not in json.dumps(job.to_dict())


def test_the_generic_run_route_does_not_start_meeting_chains(roots: Roots) -> None:
    seed_meeting(roots)
    app = App(roots, StubJobs())  # type: ignore[arg-type]
    for chain in ("meeting", "revise-notes"):
        with pytest.raises(UIError):
            app.start_job(RUN, chain)


# -- the meeting, transcript and notes routes ------------------------------------------------


def test_meeting_view_reads_the_files(roots: Roots, http: tuple[Client, App, StubJobs]) -> None:
    client, _, _ = http
    seed_meeting(roots, note_to_person="I could not tell who owns the migration.")
    status, out = client.json("GET", f"/api/runs/{RUN}/meeting")
    assert status == 200
    assert out["has_meeting"] is True and out["audio_name"] == "board.m4a"
    assert out["duration_s"] == 70.0 and out["turns"] == 3
    assert out["speakers_labelled"] is False and out["check_papers"] is False
    assert out["has_deck"] is False
    notes = out["notes"]
    assert notes["markdown"] == NOTES and notes["edited"] is False
    assert notes["counts"] == {
        "Summary": 1,
        "Attendees": 0,
        "Decisions": 2,
        "Action items": 1,
    }
    assert notes["agent_note"] == "I could not tell who owns the migration."
    assert notes["has_session"] is False


def test_meeting_view_before_notes_and_for_a_run_with_no_meeting(
    roots: Roots, http: tuple[Client, App, StubJobs]
) -> None:
    client, _, _ = http
    seed_meeting(roots, notes=None)
    status, out = client.json("GET", f"/api/runs/{RUN}/meeting")
    assert status == 200 and out["notes"]["markdown"] is None
    assert out["notes"]["edited"] is False and out["notes"]["agent_note"] is None
    make_run(roots, "plain")
    status, out = client.json("GET", "/api/runs/plain/meeting")
    assert status == 404 and "no meeting" in out["error"]
    assert client.json("GET", "/api/runs/ghost/meeting")[0] == 404


def test_transcript_view_has_turns_and_times(
    roots: Roots, http: tuple[Client, App, StubJobs]
) -> None:
    client, _, _ = http
    seed_meeting(roots)
    status, out = client.json("GET", f"/api/runs/{RUN}/transcript")
    assert status == 200
    assert out["turns"] == [
        {"page": 1, "time": "00:00", "text": "Welcome, everyone, to the board call."},
        {
            "page": 2,
            "time": "00:04",
            "text": "The rollout starts in the first week of February.",
        },
        {"page": 3, "time": "01:05", "text": "Shikha will own the data bricks migration."},
    ]


def test_put_notes_saves_text_and_flags_the_edit(
    roots: Roots, http: tuple[Client, App, StubJobs]
) -> None:
    client, _, _ = http
    root = seed_meeting(roots)
    edited = NOTES.replace("Migrate to Databricks.", "Migrate to Databricks by March.")
    status, out = client.json("PUT", f"/api/runs/{RUN}/notes", {"markdown": edited})
    assert status == 200 and out["edited"] is True and out["counts"]["Decisions"] == 2
    meeting = root / "meeting"
    assert (meeting / "notes.md").read_text(encoding="utf-8") == edited
    assert (meeting / "notes.rendered.md").read_text(encoding="utf-8") == NOTES
    assert not (meeting / "notes.tmp").exists() and not (meeting / "notes.json").exists()
    assert client.json("GET", f"/api/runs/{RUN}/meeting")[1]["notes"]["edited"] is True
    # Putting the rendered text back is "no edits".
    status, out = client.json("PUT", f"/api/runs/{RUN}/notes", {"markdown": NOTES})
    assert status == 200 and out["edited"] is False


def test_put_notes_refusals(roots: Roots, http: tuple[Client, App, StubJobs]) -> None:
    client, _, _ = http
    root = seed_meeting(roots, notes=None)
    path = f"/api/runs/{RUN}/notes"
    assert client.json("PUT", path, {"markdown": "x"})[0] == 409  # no notes yet
    assert not (root / "meeting" / "notes.md").exists()
    (root / "meeting" / "notes.md").write_text(NOTES, encoding="utf-8")
    assert client.json("PUT", path, {"markdown": 5})[0] == 400
    assert client.json("PUT", path, {"markdown": "a\x00b"})[0] == 400
    assert client.json("PUT", path, {})[0] == 400
    status, out = client.json("PUT", path, {"markdown": "x" * 200_001})
    assert status == 413 and "200 KB" in out["error"]
    assert (root / "meeting" / "notes.md").read_text(encoding="utf-8") == NOTES


def test_apply_edits_starts_the_job_only_when_there_are_edits(
    roots: Roots, http: tuple[Client, App, StubJobs]
) -> None:
    client, _, stub = http
    root = seed_meeting(roots)
    path = f"/api/runs/{RUN}/notes/apply"
    status, out = client.json("POST", path, {})
    assert status == 200 and out == {"job": None, "message": "No edits to apply."}
    assert stub.started == []

    (root / "meeting" / "notes.md").write_text(NOTES + "\n- Another line.\n", encoding="utf-8")
    status, out = client.json("POST", path, {})
    assert status == 200 and out["job"]["steps"] == ["revise-notes"]
    assert stub.started == [(RUN, "revise-notes", {"apply_edits": True})]
    argv = jobs.cli_command("revise-notes", RUN, roots=roots, extra={"apply_edits": True})
    assert argv[3:6] == ["meeting", "revise-notes", RUN]
    assert "--apply-edits" in argv and "--say" not in argv


def test_say_starts_the_job_with_the_text(
    roots: Roots, http: tuple[Client, App, StubJobs]
) -> None:
    client, _, stub = http
    seed_meeting(roots)
    path = f"/api/runs/{RUN}/notes/say"
    assert client.json("POST", path, {"text": "  "})[0] == 400
    status, out = client.json("POST", path, {"text": " it's APLD, not APID "})
    assert status == 200 and out["job"]["steps"] == ["revise-notes"]
    assert stub.started == [(RUN, "revise-notes", {"say": "it's APLD, not APID"})]
    argv = jobs.cli_command("revise-notes", RUN, roots=roots, extra=stub.started[0][2])
    assert argv[argv.index("--say") + 1] == "it's APLD, not APID"
    assert "--apply-edits" not in argv


def test_notes_actions_are_refused_while_a_job_runs_or_before_notes(
    roots: Roots, http: tuple[Client, App, StubJobs]
) -> None:
    client, app, stub = http
    root = seed_meeting(roots)
    (root / "meeting" / "notes.md").write_text(NOTES + "\n- Edit.\n", encoding="utf-8")
    app.jobs.running = lambda run_id: True  # type: ignore[method-assign]
    assert client.json("POST", f"/api/runs/{RUN}/notes/apply", {})[0] == 409
    assert client.json("POST", f"/api/runs/{RUN}/notes/say", {"text": "x"})[0] == 409
    assert client.json("PUT", f"/api/runs/{RUN}/notes", {"markdown": "x"})[0] == 409
    assert client.json("POST", f"/api/runs/{RUN}/meeting-deck", {})[0] == 409
    app.jobs.running = lambda run_id: False  # type: ignore[method-assign]
    seed_meeting(roots, "early", notes=None)
    assert client.json("POST", "/api/runs/early/notes/say", {"text": "x"})[0] == 409
    assert client.json("POST", "/api/runs/early/notes/apply", {})[0] == 409
    assert stub.started == []


# -- a deck from the meeting -----------------------------------------------------------------


def test_meeting_deck_runs_clarify_then_the_ordinary_answers_to_draft_chain(
    roots: Roots,
) -> None:
    make_client(roots)
    seed_meeting(roots)
    calls: list[list[str]] = []
    stub = StubJobs()
    app = App(roots, stub, cli_runner=stub_clarify(roots, calls))  # type: ignore[arg-type]

    out = app.start_meeting_deck(RUN, {"prompt": " A readout for the board. "})
    assert out["questions"][0]["id"] == "q1" and out["mode"] == "draft"
    [argv] = calls
    assert argv[3:5] == ["clarify", RUN]
    assert argv[argv.index("--prompt") + 1] == "A readout for the board."
    assert argv[argv.index("--client") + 1] == "acme"
    assert argv[argv.index("--project") + 1] == "proj"
    assert api.run_is_meeting(roots, RUN)  # the meeting flag survives

    job = app.submit_answers(RUN, {"accept_all": True})["job"]
    assert job["steps"] == ["draft", "validate", "preview"]
    assert stub.started == [(RUN, "draft", {})]


def test_meeting_deck_default_prompt_agent_and_refusals(roots: Roots) -> None:
    make_client(roots)
    seed_meeting(roots)
    calls: list[list[str]] = []
    stub = StubJobs()
    app = App(roots, stub, cli_runner=stub_clarify(roots, calls))  # type: ignore[arg-type]
    app.start_meeting_deck(RUN, {"agent": True, "design_mode": "creative"})
    argv = calls[0]
    assert argv[argv.index("--prompt") + 1] == (
        "A short readout of this meeting for people who were not there"
    )
    assert argv[argv.index("--design-mode") + 1] == "creative"
    assert api.run_uses_agent(roots, RUN)
    app.submit_answers(RUN, {"accept_all": True})
    assert stub.started == [(RUN, "draft", {"agent": True})]

    make_run(roots, "plain")
    with pytest.raises(UIError) as caught:
        app.start_meeting_deck("plain", {})
    assert caught.value.status == 404

    failing = App(roots, stub, cli_runner=lambda argv: (5, "STOPPED: no key"))  # type: ignore[arg-type]
    with pytest.raises(UIError, match="no key"):
        failing.start_meeting_deck(RUN, {})


def test_meeting_deck_needs_a_transcript_and_no_draft(roots: Roots) -> None:
    make_client(roots)
    app = App(roots, StubJobs(), cli_runner=stub_clarify(roots, []))  # type: ignore[arg-type]
    api.write_run_meta(roots, "young", client="acme", project="proj", meeting=True)
    with pytest.raises(UIError) as caught:
        app.start_meeting_deck("young", {})
    assert caught.value.status in (404, 409)

    root = seed_meeting(roots, "done")
    orch = make_run(roots, "done")
    deck = _deck(_slide("s1", "quote", [_claim_block("figure", "A.")]))  # type: ignore[arg-type]
    orch.run_stage(
        "compose", lambda: f"wrote {orch.save_ir(deck.model_copy(update={'run_id': 'done'}))}"
    )
    assert root.is_dir()
    with pytest.raises(UIError) as caught:
        app.start_meeting_deck("done", {})
    assert caught.value.status == 409 and "already has a draft" in str(caught.value)


# -- run summaries ---------------------------------------------------------------------------


def test_a_meeting_run_is_recognisable_and_reads_its_stage(roots: Roots) -> None:
    make_client(roots)
    app = App(roots, StubJobs())  # type: ignore[arg-type]
    api.write_run_meta(roots, "m2", client="acme", project="proj", meeting=True)
    out = app.summary("m2")
    assert out["meeting"] is True and out["meeting_stage"] == "Transcribing"
    assert out["next"] == "Transcribing" and out["resume"] == "#/meeting/m2"
    running = api.run_summary(roots, "m2", running_step="transcribe")
    assert running["meeting_stage"] == "Transcribing"
    assert api.run_summary(roots, "m2", running_step="notes")["meeting_stage"] == (
        "Writing the notes"
    )

    seed_meeting(roots, notes=None)
    assert app.summary(RUN)["meeting_stage"] == "Transcribed"
    (roots.runs / RUN / "meeting" / "notes.md").write_text(NOTES, encoding="utf-8")
    ready = app.summary(RUN)
    assert ready["meeting_stage"] == "Notes ready" and ready["next"] == "Notes ready"
    assert "clarify" in ready["command_hint"]

    (roots.runs / RUN / "clarify.json").write_text("{}", encoding="utf-8")
    assert app.summary(RUN)["meeting_stage"] == "Drafting"
    assert app.summary(RUN)["resume"] != "#/meeting/m1"  # a draft run goes to its own screens

    orch = make_run(roots, RUN)
    deck = _deck(_slide("s1", "quote", [_claim_block("figure", "A.")]))  # type: ignore[arg-type]
    orch.run_stage(
        "compose", lambda: f"wrote {orch.save_ir(deck.model_copy(update={'run_id': RUN}))}"
    )
    assert app.summary(RUN)["meeting_stage"] == "Draft"

    make_run(roots, "plain")
    assert "meeting" not in app.summary("plain")
    listed = {r["id"]: r for r in app.runs()}
    assert listed[RUN]["meeting"] is True and "meeting" not in listed["plain"]


def test_a_failed_transcription_reads_failed_in_the_run_list(roots: Roots) -> None:
    make_client(roots)
    manager = jobs.JobManager(command_for(1))
    app = App(roots, manager)
    api.write_run_meta(roots, "m2", client="acme", project="proj", meeting=True)
    manager.start("m2", "meeting", {})
    manager.wait("m2")
    assert app.summary("m2")["meeting_stage"] == "Transcription failed"
    assert {r["id"]: r for r in app.runs()}["m2"]["meeting_stage"] == "Transcription failed"


def test_the_cli_writing_run_meta_keeps_the_meeting_flag(roots: Roots) -> None:
    api.write_run_meta(roots, "m2", client="acme", project="proj", meeting=True)
    api.write_run_meta(
        roots, "m2", client="acme", project="proj"
    )  # as `meeting transcribe` does
    assert json.loads((roots.runs / "m2" / "ui.json").read_text())["meeting"] is True
    api.write_run_meta(roots, "p", client="acme", project="proj")
    assert "meeting" not in json.loads((roots.runs / "p" / "ui.json").read_text())


# -- the agent session -----------------------------------------------------------------------


def test_session_view_kinds(roots: Roots, http: tuple[Client, App, StubJobs]) -> None:
    client, _, _ = http
    make_run(roots, "bare")
    assert client.json("GET", "/api/runs/bare/session")[1] == {
        "timeline": [],
        "meta": None,
        "active": False,
    }

    root = seed_meeting(roots, notes_session=True)
    status, out = client.json("GET", f"/api/runs/{RUN}/session")
    assert status == 200 and out["kind"] == "notes" and "notes_session" not in out
    assert out["meta"] == {"kind": "notes"}
    assert [r["role"] for r in out["timeline"]] == ["user", "assistant", "tool"]

    seed_meeting(roots, "deckonly")
    write_session(roots.runs / "deckonly", "transcript.jsonl", "meta.json", {"steps": 3})
    out = client.json("GET", "/api/runs/deckonly/session")[1]
    assert out["kind"] == "deck" and out["meta"] == {"steps": 3} and "notes_session" not in out

    write_session(root, "transcript.jsonl", "meta.json", {"steps": 9})
    out = client.json("GET", f"/api/runs/{RUN}/session")[1]
    assert out["kind"] == "deck" and out["meta"] == {"steps": 9}
    assert out["notes_session"] is True


def test_meeting_view_reports_a_notes_session(roots: Roots) -> None:
    from autodeck.ui import meeting_view

    seed_meeting(roots, notes_session=True)
    assert meeting_view.meeting_view(roots, RUN)["notes"]["has_session"] is True


# -- citation times in the draft view --------------------------------------------------------


def test_draft_view_gives_transcript_citations_their_meeting_time(roots: Roots) -> None:
    seed_meeting(roots)
    orch = make_run(roots, RUN)
    meeting_cite = _citation(
        "The rollout starts in the first week of February.", doc_id="transcript--m1", page=2
    )
    paper_cite = _citation("Cost fell.", doc_id="vendor-report", page=4)
    deck = _deck(
        _slide(
            "s1",
            "quote",
            [
                _claim_block("figure", "Rollout.", citations=[meeting_cite]),  # type: ignore[arg-type]
                _claim_block("quote", "Cost.", citations=[paper_cite]),  # type: ignore[arg-type]
            ],
        )
    ).model_copy(update={"run_id": RUN})
    orch.run_stage("compose", lambda: f"wrote {orch.save_ir(deck)}")
    out = api.draft_view(roots, RUN)
    assert out["meeting"] is True
    first, second = (b["citations"][0] for b in out["slides"][0]["blocks"])
    assert first["source_class"] == "transcript" and first["time"] == "00:04"
    assert "time" not in second


def test_a_draft_run_that_is_not_a_meeting_is_unchanged(roots: Roots) -> None:
    from tests.test_ui_draft import seed_draft

    seed_draft(roots)
    out = api.draft_view(roots, "r1")
    assert out["meeting"] is False
    assert all(
        "time" not in c for s in out["slides"] for b in s["blocks"] for c in b["citations"]
    )
