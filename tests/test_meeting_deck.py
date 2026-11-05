"""The deck written in the session that made the meeting's notes (B82): scripted turns, a tiny
real transcript, no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import autodeck.agents.meeting_deck as meeting_deck
import autodeck.agents.notes_agent as notes_agent
from autodeck.agents.compose import ComposedMessage, ComposeError
from autodeck.agents.content import ProposedBlock, ProposedCitation, ProposedClaim
from autodeck.agents.deck_agent import SessionFiles as DeckFiles
from autodeck.agents.deck_agent import build_settings, resume_deck_agent
from autodeck.agents.meeting_deck import compose_meeting_deck_agent
from autodeck.agents.notes_agent import (
    SessionFiles as NotesFiles,
)
from autodeck.agents.notes_agent import (
    compose_notes_agent,
    migrate_notes_session,
    resume_notes_agent,
)
from autodeck.agents.notes_workspace import NotesWorkspace
from autodeck.agents.session import SessionLimits
from autodeck.agents.workspace import DeckBriefDraft
from autodeck.providers.base import AssistantTurn, ToolCall, Usage
from autodeck.retrieval.hybrid import build_index
from tests.test_agent_tools import TOKENS, deck_fields
from tests.test_compose import slide
from tests.test_content import context
from tests.test_notes_workspace import DECIDED, TIMES, WALK, build
from tests.test_session import ScriptedConverse

DOC = "transcript--n1"


def turn(name: str, i: int, /, **args: Any) -> AssistantTurn:
    return AssistantTurn(
        tool_calls=[ToolCall(id=f"c{i}", name=name, arguments=args)], usage=Usage(10, 2)
    )


def cite(page: int, quote: str) -> dict[str, Any]:
    return {"page": page, "quote": quote}


def notes_script(*, read_first: bool = False) -> list[AssistantTurn]:
    script = [
        turn(
            "notes_set_section",
            2,
            section="Decisions",
            items=[{"text": "Vendor plan chosen.", "cites": [cite(2, DECIDED)]}],
        ),
        turn(
            "notes_set_section",
            3,
            section="Summary",
            items=[{"text": "A pilot review.", "cites": [cite(1, "pilot review")]}],
        ),
        turn("finish_notes", 4, note_to_person="Check the spelling of Shikha."),
    ]
    if read_first:
        script.insert(0, turn("read_transcript", 1, from_page=1, to_page=2))
    return script


def run_notes(tmp_path: Path, *, preload: bool = True, monkeypatch=None):  # type: ignore[no-untyped-def]
    if not preload:
        monkeypatch.setattr(notes_agent, "PRELOAD_TOKENS", 0)
    base = build(tmp_path)
    ran = compose_notes_agent(
        transcript=base.transcript,
        store=base.store,
        times=TIMES,
        context=context(),
        model=ScriptedConverse(*notes_script(read_first=not preload)),
        project="p",
        session_dir=tmp_path / "session",
    )
    assert ran.state.stop_reason == "finished"
    return base, ran


def quote_slide(page_quote: str, sid: str = "s1") -> dict[str, Any]:
    s = slide(
        sid,
        ["km1"],
        ProposedBlock(
            id="b1",
            kind="claim",
            slot="headline",
            claim=ProposedClaim(
                text="The vendor plan was chosen.",
                citations=[ProposedCitation(doc_id=DOC, quote=page_quote)],
            ),
        ),
        ProposedBlock(
            id="b2",
            kind="claim",
            slot="quote",
            claim=ProposedClaim(
                text="The vendor plan was chosen.",
                citations=[ProposedCitation(doc_id=DOC, quote=page_quote)],
            ),
        ),
        ProposedBlock(id="b3", kind="framing", slot="attribution", text="The meeting"),
    )
    return {"slide": s.model_dump(mode="json")}


def brief(quote: str = DECIDED) -> dict[str, Any]:
    return DeckBriefDraft(
        objective="Report the decision.",
        audience="The board",
        length_target=2,
        key_messages=[
            ComposedMessage(
                id="km1",
                text="The vendor plan was chosen.",
                origin="prompt",
                citations=[ProposedCitation(doc_id=DOC, quote=quote)],
            )
        ],
        must_include=[],
        must_avoid=[],
    ).model_dump(mode="json")


def deck_script(quote: str = DECIDED) -> list[AssistantTurn]:
    return [
        turn("set_brief", 1, **brief(quote)),
        turn("write_slide", 2, **quote_slide(quote)),
        turn("finish", 3, coverage=[], notes="Done."),
    ]


def compose(base: NotesWorkspace, tmp_path: Path, model: Any, notes, **kw: Any):  # type: ignore[no-untyped-def]
    index = build_index([base.transcript], project="p")
    kwargs: dict[str, Any] = {
        "answers": [],
        "transcript": base.transcript,
        "times": TIMES,
        "notes": notes,
        "index": index,
        "claims": [],
        "documents": [base.transcript],
        "context": context(),
        "store": base.store,
        "tokens": TOKENS,
        "model": model,
        "run_id": "r1",
        "client": "northwind",
        "project": "p",
        "theme_ref": "config/tokens/dev.json",
        "component_lib_version": deck_fields()["component_lib_version"],
        "session_dir": tmp_path / "session",
    }
    kwargs.update(kw)
    return compose_meeting_deck_agent("Report the meeting's decision.", **kwargs)


def tool_texts(run) -> list[str]:  # type: ignore[no-untyped-def]
    return [m.content for m in run.state.messages if m.role == "tool"]


def test_a_deck_from_the_meeting_session(tmp_path: Path) -> None:
    base, notes_run = run_notes(tmp_path)
    session = tmp_path / "session"
    notes_files = {p.name: p.read_bytes() for p in session.iterdir() if p.is_file()}
    assert set(notes_files) >= {"notes_transcript.jsonl", "notes_system.md",
                                "notes_workspace.json"}  # fmt: skip

    model = ScriptedConverse(*deck_script())
    seen_systems: list[str | None] = []
    original = model.converse

    def recording(messages, tools, *, system=None):  # type: ignore[no-untyped-def]
        seen_systems.append(system)
        return original(messages, tools, system=system)

    model.converse = recording  # type: ignore[method-assign]
    run = compose(base, tmp_path, model, notes_run.workspace)

    assert run.state.stop_reason == "finished" and len(run.result.deck.slides) == 1
    system = seen_systems[0] or ""
    assert "# This deck is built from a meeting" in system
    assert "# Skill: `meeting-readout`" in system
    assert "`meeting-readout` —" not in system  # loaded, so not offered again

    opening = model.seen[0][0].content
    assert f"# The meeting (citable: doc id `{DOC}`, one page per turn)" in opening
    assert "turn 2 [00:12]: We decided to go with the vendor plan" in opening
    assert "# Your notes from this meeting (context, not evidence: cite the turns)" in opening
    assert f"cites turn 2: {DECIDED!r}" in opening
    assert "What you told the person about the notes" in opening
    assert "Check the spelling of Shikha." in opening
    assert opening.index("# The meeting") < opening.index("# Passages you start with")

    # no read was needed: the whole transcript is citable at the start
    assert not any(t.startswith("ERROR") for t in tool_texts(run)), tool_texts(run)
    claim = run.result.deck.slides[0].blocks[0].claim
    assert claim.citations[0].doc_id == DOC
    assert claim.citations[0].source_class == "transcript"
    assert run.result.deck.provenance == "strict"

    # the notes files were not touched; the deck wrote its own
    for name, content in notes_files.items():
        assert (session / name).read_bytes() == content, name
    for name in ("system.md", "workspace.json", "transcript.jsonl", "corpus_map.md"):
        assert (session / name).is_file(), name
    steps = [
        json.loads(line) for line in (session / "transcript.jsonl").read_text().splitlines()
    ]
    assert any("opening message (from the meeting session)" in json.dumps(r) for r in steps)


def test_a_turn_the_notes_session_never_showed_must_be_read_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, notes_run = run_notes(tmp_path, preload=False, monkeypatch=monkeypatch)
    assert notes_run.workspace.shown_pages == {1, 2}
    monkeypatch.setattr(meeting_deck, "PRELOAD_TOKENS", 0)  # too long to show whole

    model = ScriptedConverse(
        turn("set_brief", 1, **brief()),
        turn("write_slide", 2, **quote_slide(WALK, "s1")),  # turn 3: not shown
        turn("read_passage", 3, doc_id=DOC, page=3),
        turn("write_slide", 4, **quote_slide(WALK, "s1")),
        turn("finish", 5, coverage=[], notes="Done."),
    )
    run = compose(base, tmp_path, model, notes_run.workspace)
    opening = model.seen[0][0].content
    assert "5 turns, about 1:01:40 long" in opening and "read_passage" in opening
    assert "turn 2 [00:12]" not in opening  # the transcript is not in the message
    texts = tool_texts(run)
    # some turns are shown, so the unshown one is a quote that is not among them
    assert "FAIL quote_not_found" in texts[1]
    assert "quote_not_found" not in texts[3]
    assert run.state.stop_reason == "finished" and len(run.result.deck.slides) == 1

    # the turn the notes session did show (2) was citable without a read
    model = ScriptedConverse(*deck_script())
    again = compose(base, tmp_path, model, notes_run.workspace)
    assert not any(t.startswith("ERROR") for t in tool_texts(again))


def test_above_the_cap_with_no_notes_nothing_of_the_meeting_is_citable_until_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(meeting_deck, "PRELOAD_TOKENS", 0)
    base = build(tmp_path)
    model = ScriptedConverse(
        turn("set_brief", 1, **brief()),
        turn("write_slide", 2, **quote_slide(DECIDED)),
        turn("read_passage", 3, doc_id=DOC, page=2),
        turn("write_slide", 4, **quote_slide(DECIDED)),
        turn("finish", 5, coverage=[], notes="Done."),
    )
    run = compose(base, tmp_path, model, None)
    texts = tool_texts(run)
    assert "FAIL doc_not_shown" in texts[1]
    assert "doc_not_shown" not in texts[3]
    assert len(run.result.deck.slides) == 1


def test_without_notes_the_deck_is_written_from_the_transcript(tmp_path: Path) -> None:
    base = build(tmp_path)
    model = ScriptedConverse(*deck_script())
    run = compose(base, tmp_path, model, None)
    assert run.state.stop_reason == "finished" and len(run.result.deck.slides) == 1
    opening = model.seen[0][0].content
    assert "# The meeting (citable" in opening and "turn 3 [00:31]" in opening
    assert "Your notes from this meeting" not in opening
    steps = (tmp_path / "session" / "transcript.jsonl").read_text()
    assert "from the meeting session" not in steps


def test_a_notes_session_with_no_items_adds_no_notes_section(tmp_path: Path) -> None:
    base = build(tmp_path)
    empty = NotesWorkspace(transcript=base.transcript, store=base.store)
    model = ScriptedConverse(*deck_script())
    compose(base, tmp_path, model, empty)
    assert "Your notes from this meeting" not in model.seen[0][0].content


def test_a_second_draft_archives_the_deck_transcript_and_leaves_the_notes(
    tmp_path: Path,
) -> None:
    base, notes_run = run_notes(tmp_path)
    session = tmp_path / "session"
    compose(base, tmp_path, ScriptedConverse(*deck_script()), notes_run.workspace)
    first = (session / "transcript.jsonl").read_text()
    notes_before = (session / "notes_transcript.jsonl").read_bytes()

    compose(base, tmp_path, ScriptedConverse(*deck_script()), notes_run.workspace)
    assert (session / "transcript.1.jsonl").read_text() == first
    assert (session / "transcript.jsonl").read_text() != ""
    assert (session / "notes_transcript.jsonl").read_bytes() == notes_before
    compose(base, tmp_path, ScriptedConverse(*deck_script()), notes_run.workspace)
    assert (session / "transcript.2.jsonl").is_file()


def test_revise_resumes_the_deck_session_after_the_meeting_deck(tmp_path: Path) -> None:
    base, notes_run = run_notes(tmp_path)
    compose(base, tmp_path, ScriptedConverse(*deck_script()), notes_run.workspace)
    settings = build_settings(
        prompt="Report.",
        answers=[],
        chat_brief=None,
        store=base.store,
        tokens=TOKENS,
        provenance="strict",
        deck_fields=deck_fields(),
    )
    model = ScriptedConverse(turn("finish", 9, coverage=[], notes="Changed."))
    again = resume_deck_agent(
        "Tighten it.",
        session_dir=tmp_path / "session",
        settings=settings,
        index=build_index([base.transcript], project="p"),
        claims=[],
        model=model,
    )
    assert again.result.notes == "Changed." and len(again.result.deck.slides) == 1
    # the notes session still resumes from its own files
    model = ScriptedConverse(turn("finish_notes", 1, note_to_person="Same."))
    notes_again = resume_notes_agent(
        "Nothing changes.",
        session_dir=tmp_path / "session",
        transcript=base.transcript,
        store=base.store,
        times=TIMES,
        model=model,
        project="p",
    )
    assert notes_again.workspace.note_to_person == "Same."
    deck_log = (tmp_path / "session" / "transcript.jsonl").read_text()
    assert "Nothing changes." not in deck_log


def step10_layout(session: Path) -> None:
    """What step 10 left: the notes session under the deck names."""
    session.mkdir(parents=True, exist_ok=True)
    (session / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
    (session / "system.md").write_text("old", encoding="utf-8")
    (session / "meta.json").write_text('{"kind": "notes"}', encoding="utf-8")
    (session / "transcript.1.jsonl").write_text("{}\n", encoding="utf-8")


def test_a_step_10_layout_is_renamed_when_the_deck_phase_begins(tmp_path: Path) -> None:
    base, notes_run = run_notes(tmp_path)
    session = tmp_path / "session"
    # what step 10 left: the notes session under the deck names
    (session / "notes_transcript.jsonl").rename(session / "transcript.jsonl")
    (session / "notes_system.md").rename(session / "system.md")
    (session / "meta.json").write_text('{"kind": "notes"}', encoding="utf-8")
    (session / "transcript.1.jsonl").write_text("{}\n", encoding="utf-8")
    notes_log = (session / "transcript.jsonl").read_text()

    compose(base, tmp_path, ScriptedConverse(*deck_script()), notes_run.workspace)
    names = {p.name for p in session.iterdir() if p.is_file()}
    assert {
        "notes_transcript.jsonl",
        "notes_system.md",
        "notes_meta.json",
        "notes_transcript.1.jsonl",
    } <= names
    assert (session / "notes_transcript.jsonl").read_text() == notes_log
    # the deck's own files are the deck's, not the renamed notes
    assert "# This deck is built from a meeting" in (session / "system.md").read_text()
    assert "# This deck is built" not in (session / "notes_system.md").read_text()
    assert (session / "transcript.jsonl").read_text() != notes_log
    assert not (session / "transcript.1.jsonl").exists()  # the notes archive moved away

    model = ScriptedConverse(turn("finish_notes", 1, note_to_person="Still works."))
    resumed = resume_notes_agent(
        "Anything.",
        session_dir=session,
        transcript=base.transcript,
        store=base.store,
        times=TIMES,
        model=model,
        project="p",
    )
    assert resumed.workspace.note_to_person == "Still works."


def test_resuming_notes_migrates_a_step_10_layout_on_its_own(tmp_path: Path) -> None:
    base, _ = run_notes(tmp_path)
    session = tmp_path / "session"
    (session / "notes_transcript.jsonl").rename(session / "transcript.jsonl")
    (session / "notes_system.md").rename(session / "system.md")
    model = ScriptedConverse(turn("finish_notes", 1, note_to_person="Migrated."))
    resumed = resume_notes_agent(
        "Anything.",
        session_dir=session,
        transcript=base.transcript,
        store=base.store,
        times=TIMES,
        model=model,
        project="p",
    )
    assert resumed.workspace.note_to_person == "Migrated."
    assert (session / "notes_transcript.jsonl").is_file()
    assert not (session / "transcript.jsonl").exists()


def test_migration_waits_for_a_deck_session_and_never_overwrites(tmp_path: Path) -> None:
    session = tmp_path / "session"
    step10_layout(session)
    assert migrate_notes_session(session) == []  # no notes_workspace.json: not a notes layout
    (session / "notes_workspace.json").write_text("{}", encoding="utf-8")
    (session / "workspace.json").write_text("{}", encoding="utf-8")
    assert migrate_notes_session(session) == []  # a deck session owns the old names
    (session / "workspace.json").unlink()
    (session / "notes_system.md").write_text("new", encoding="utf-8")
    moved = migrate_notes_session(session)
    assert "system.md -> notes_system.md" not in moved
    assert (session / "notes_system.md").read_text() == "new"
    assert (session / "system.md").read_text() == "old"
    assert "transcript.jsonl -> notes_transcript.jsonl" in moved
    assert migrate_notes_session(session) == []  # idempotent


def test_a_deck_meta_is_not_taken_for_the_notes_meta(tmp_path: Path) -> None:
    session = tmp_path / "session"
    session.mkdir()
    (session / "notes_workspace.json").write_text("{}", encoding="utf-8")
    (session / "meta.json").write_text('{"kind": "deck"}', encoding="utf-8")
    migrate_notes_session(session)
    assert (session / "meta.json").is_file() and not (session / "notes_meta.json").exists()


def test_notes_session_files_use_the_notes_names(tmp_path: Path) -> None:
    files = NotesFiles(tmp_path)
    names = [files.transcript.name, files.system.name, files.workspace.name, files.meta.name]
    assert names == [
        "notes_transcript.jsonl",
        "notes_system.md",
        "notes_workspace.json",
        "notes_meta.json",
    ]
    assert DeckFiles(tmp_path).transcript.name == "transcript.jsonl"


def test_a_session_with_nothing_to_build_still_raises(tmp_path: Path) -> None:
    base = build(tmp_path)
    model = ScriptedConverse(turn("show_corpus_map", 1))
    with pytest.raises(ComposeError):
        compose(base, tmp_path, model, None, limits=SessionLimits(max_steps=1))


def test_the_manifest_records_a_notes_only_session_and_its_archives(tmp_path) -> None:
    """A6 (B82): a meeting run with notes and no deck session still has a session record,
    and notes reseed archives are hashed with the deck's."""
    import json as _json

    from autodeck.audit.manifest import session_record

    session = tmp_path / "session"
    session.mkdir()
    line = _json.dumps({"message": {"role": "assistant"}, "step": 3}) + "\n"
    (session / "notes_transcript.jsonl").write_text(line, encoding="utf-8")
    (session / "notes_transcript.1.jsonl").write_text(line, encoding="utf-8")
    (session / "notes_system.md").write_text("s\n", encoding="utf-8")
    record = session_record(session)
    assert record is not None
    assert record["steps"] == 3
    assert {"notes_transcript.jsonl", "notes_system.md"} <= set(record["sha256"])
    assert "notes_transcript.1.jsonl" in record["archived_transcripts"]
