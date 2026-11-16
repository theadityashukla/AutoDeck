"""The notes workspace (B80): citations through the deck's resolver, field rules, atomic
edits, persistence, and the deterministic rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodeck.agents.notes_workspace import (
    CiteDraft,
    NoteItemDraft,
    NotesError,
    NotesWorkspace,
    notes_text,
    render_notes,
    write_notes,
)
from autodeck.ingest.document_store import DocumentStore
from autodeck.ingest.transcript_source import transcript_document
from tests.test_transcript_source import make_transcript

SEGMENTS = (
    (5.0, 10.0, "Welcome everyone to the pilot review.", None),
    (12.5, 20.0, "We decided to go with the vendor plan for the data bricks migration.", None),
    (31.0, 39.0, "Shikta will run the walkthrough on the sixteenth.", None),
    (50.0, 55.0, "We are not sure about the budget yet.", None),
    (3700.0, 3710.0, "Let us close here.", None),
)
TIMES = {1: 5.0, 2: 12.5, 3: 31.0, 4: 50.0, 5: 3700.0}
DECIDED = "go with the vendor plan"
WALK = "Shikta will run the walkthrough"


def build(tmp_path: Path, *, segments=SEGMENTS, run: str = "n1") -> NotesWorkspace:  # type: ignore[no-untyped-def]
    doc = transcript_document(make_transcript(*segments), run)
    store = DocumentStore(tmp_path / "source")
    store.add(doc)
    return NotesWorkspace(transcript=doc, store=store)


def item(text: str, page: int, quote: str, **fields) -> NoteItemDraft:  # type: ignore[no-untyped-def]
    return NoteItemDraft(text=text, cites=[CiteDraft(page=page, quote=quote)], **fields)


def shown(tmp_path: Path) -> NotesWorkspace:
    ws = build(tmp_path)
    ws.show_pages(range(1, 6))
    return ws


def test_a_quote_from_a_shown_turn_resolves(tmp_path: Path) -> None:
    ws = build(tmp_path)
    ws.show_pages([2])
    item_id = ws.add_item("decisions", item("Vendor plan chosen.", 2, DECIDED))
    found = ws.find(item_id)
    assert item_id == "n1" and found.section == "Decisions"
    assert found.citations[0].page == 2 and found.citations[0].quote == DECIDED


def test_a_turn_that_was_not_shown_is_refused(tmp_path: Path) -> None:
    ws = build(tmp_path)
    ws.show_pages([1])
    with pytest.raises(NotesError, match="turn 2 has not been shown"):
        ws.add_item("Decisions", item("x", 2, DECIDED))
    assert ws.ids() == []


def test_show_pages_refuses_a_turn_that_does_not_exist(tmp_path: Path) -> None:
    ws = build(tmp_path)
    with pytest.raises(NotesError, match="turns 1 to 5"):
        ws.show_pages([9])


def test_a_quote_on_another_turn_names_that_turn(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    with pytest.raises(NotesError, match="that quote is in turn 2"):
        ws.add_item("Decisions", item("x", 3, DECIDED))


def test_a_quote_spanning_two_turns_is_refused(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    spliced = "pilot review. We decided to go"
    with pytest.raises(NotesError, match="not verbatim"):
        ws.add_item("Decisions", item("x", 1, spliced))


def test_a_quote_that_is_not_in_the_transcript_is_refused(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    with pytest.raises(NotesError, match="not verbatim"):
        ws.add_item("Decisions", item("x", 2, "we chose the other vendor"))


def test_a_point_across_turns_carries_one_citation_per_turn(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    draft = NoteItemDraft(
        text="Vendor plan chosen; walkthrough follows.",
        cites=[CiteDraft(page=2, quote=DECIDED), CiteDraft(page=3, quote=WALK)],
    )
    found = ws.find(ws.add_item("Themes", draft))
    assert found.pages == (2, 3)


def test_unknown_section_lists_the_sections(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    with pytest.raises(NotesError, match="Action items"):
        ws.add_item("Gossip", item("x", 2, DECIDED))


def test_field_rules(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    with pytest.raises(NotesError, match="owner and due belong to Action items"):
        ws.add_item("Decisions", item("x", 2, DECIDED, owner="Shikha"))
    with pytest.raises(NotesError, match="date and precision belong to Key dates"):
        ws.add_item("Decisions", item("x", 2, DECIDED, date="the sixteenth", precision="day"))
    with pytest.raises(NotesError, match="needs date"):
        ws.add_item("Key dates", item("x", 3, "on the sixteenth"))
    with pytest.raises(NotesError, match="needs date"):
        ws.add_item("Key dates", item("x", 3, "on the sixteenth", date="the sixteenth"))
    with pytest.raises(NotesError, match="owner is empty"):
        ws.add_item("Action items", item("x", 3, WALK, owner="  "))
    ws.add_item(
        "Key dates",
        item("Walkthrough", 3, "on the sixteenth", date="the sixteenth", precision="day"),
    )
    ws.add_item("Action items", item("Run the walkthrough", 3, WALK, owner="Shikha"))
    assert len(ws.ids()) == 2


def test_set_section_is_atomic(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    ws.set_section("Decisions", [item("Vendor plan.", 2, DECIDED)])
    before = ws.state_json()
    with pytest.raises(NotesError):
        ws.set_section(
            "Decisions",
            [item("Good.", 2, DECIDED), item("Bad.", 2, "never said")],
        )
    assert ws.state_json() == before


def test_set_section_replaces_and_gives_new_ids(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    first = ws.set_section("Decisions", [item("A.", 2, DECIDED)])
    second = ws.set_section("Decisions", [item("B.", 2, DECIDED), item("C.", 2, DECIDED)])
    assert first == ["n1"] and second == ["n2", "n3"]
    assert [i.text for i in ws.sections["Decisions"]] == ["B.", "C."]


def test_edit_keeps_id_section_and_position(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    ids = ws.set_section("Themes", [item("A.", 2, DECIDED), item("B.", 3, WALK)])
    ws.edit_item(ids[0], item("A, reworded.", 2, DECIDED))
    assert [i.id for i in ws.sections["Themes"]] == ids
    assert ws.sections["Themes"][0].text == "A, reworded."
    with pytest.raises(NotesError, match="no note 'n99'"):
        ws.edit_item("n99", item("x", 2, DECIDED))


def test_remove_and_ids_are_never_reused(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    a = ws.add_item("Themes", item("A.", 2, DECIDED))
    ws.remove_item(a)
    b = ws.add_item("Themes", item("B.", 2, DECIDED))
    assert (a, b) == ("n1", "n2") and ws.ids() == ["n2"]
    with pytest.raises(NotesError):
        ws.remove_item(a)


def test_finish_problems(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    assert any("Summary is empty" in p for p in ws.finish_problems(require_cold_read=False))
    ws.add_item("Summary", item("A pilot review.", 1, "pilot review"))
    problems = ws.finish_problems(require_cold_read=False)
    assert problems == ["every section but the Summary is empty"]
    ws.add_item("Decisions", item("Vendor plan.", 2, DECIDED))
    assert ws.finish_problems(require_cold_read=False) == []
    assert "advisor has not read" in ws.finish_problems(require_cold_read=True)[0]
    ws.record_cold_read()
    assert ws.finish_problems(require_cold_read=True) == []


def _written(tmp_path: Path) -> NotesWorkspace:
    ws = shown(tmp_path)
    ws.meeting_date = "3 November"
    ws.attendees_hint = ["Shikha"]
    ws.add_item("Summary", item("A pilot review.", 1, "pilot review"))
    ws.add_item("Decisions", item("Vendor plan chosen.", 2, DECIDED))
    ws.add_item("Action items", item("Run the walkthrough", 3, WALK, due="the sixteenth"))
    ws.add_item(
        "Key dates",
        item("Walkthrough", 3, "on the sixteenth", date="the sixteenth", precision="day"),
    )
    ws.record_cold_read()
    ws.note_to_person = "Check Shikha's spelling."
    return ws


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    ws = _written(tmp_path)
    path = ws.save(tmp_path / "session" / "notes_workspace.json")
    again = NotesWorkspace.load(path, transcript=ws.transcript, store=ws.store)
    assert again.state_json() == ws.state_json()
    assert again.next_id == ws.next_id and again.cold_read_revision == ws.cold_read_revision


def test_load_refuses_a_changed_transcript(tmp_path: Path) -> None:
    ws = _written(tmp_path)
    path = ws.save(tmp_path / "notes_workspace.json")
    changed = list(SEGMENTS)
    changed[1] = (
        12.5,
        20.0,
        "We decided to take the other plan for the data bricks migration.",
        None,
    )
    other = build(tmp_path / "other", segments=tuple(changed))
    with pytest.raises(NotesError):
        NotesWorkspace.load(path, transcript=other.transcript, store=other.store)
    elsewhere = build(tmp_path / "third", run="other-run")
    with pytest.raises(NotesError, match="not on"):
        NotesWorkspace.load(path, transcript=elsewhere.transcript, store=elsewhere.store)


def test_render_is_deterministic_with_owner_tbd_and_times(tmp_path: Path) -> None:
    ws = _written(tmp_path)
    first = render_notes(ws, TIMES)
    assert render_notes(ws, TIMES) == first
    text = first.markdown
    assert "Date: 3 November" in text
    assert "- Vendor plan chosen. [00:12] <!-- n2 -->" in text
    assert "**Owner TBD**: Run the walkthrough (due: the sixteenth) [00:31] <!-- n3 -->" in text
    assert "**the sixteenth** (day): Walkthrough [00:31] <!-- n4 -->" in text
    assert "## Themes\n\n_None noted._" in text
    # no time for a turn: it reads "turn N"; an hour in reads h:mm:ss
    assert "[turn 2]" in notes_text(ws, {})
    late = shown(tmp_path / "late")
    late.add_item("Themes", item("Closing.", 5, "close here"))
    assert "[1:01:40]" in notes_text(late, TIMES)
    assert "Date: not given" in notes_text(late, TIMES)


def test_notes_json_has_pages_and_quotes_but_no_times(tmp_path: Path) -> None:
    ws = _written(tmp_path)
    data = render_notes(ws, TIMES).data
    flat = json.dumps(data)
    assert "00:12" not in flat and "12.5" not in flat
    cite = data["sections"]["Decisions"][0]["cites"][0]
    assert cite["page"] == 2 and cite["quote"] == DECIDED and len(cite["quote_sha256"]) == 64
    action = data["sections"]["Action items"][0]
    assert action["owner"] is None and action["due"] == "the sixteenth"


def test_write_notes_writes_the_rendered_copy_beside_notes(tmp_path: Path) -> None:
    ws = _written(tmp_path)
    md, js = write_notes(ws, tmp_path / "meeting", TIMES)
    meeting = tmp_path / "meeting"
    assert md.read_text() == (meeting / "notes.rendered.md").read_text()
    assert json.loads(js.read_text())["doc_id"] == ws.doc_id


def test_the_manifest_hashes_a_notes_session(tmp_path) -> None:
    """A6: a notes session's workspace is part of what a build records (B80)."""
    import json as _json

    from autodeck.audit.manifest import session_record

    session = tmp_path / "session"
    session.mkdir()
    (session / "transcript.jsonl").write_text(
        _json.dumps({"message": {"role": "assistant"}, "step": 1}) + "\n", encoding="utf-8"
    )
    (session / "notes_workspace.json").write_text("{}\n", encoding="utf-8")
    record = session_record(session)
    assert record is not None
    assert "notes_workspace.json" in record["sha256"]
