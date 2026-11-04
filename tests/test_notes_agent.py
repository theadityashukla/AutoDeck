"""The notes agent end to end (B80): scripted turns, a tiny real transcript, no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import autodeck.agents.notes_agent as notes_agent
import autodeck.agents.tools.notes as notes_tools_module
from autodeck.agents.compose import ComposeError
from autodeck.agents.deck_agent import agent_system
from autodeck.agents.notes_agent import (
    NotesRun,
    SessionFiles,
    compose_notes_agent,
    notes_system,
    resume_notes_agent,
    transcript_text,
)
from autodeck.agents.notes_workspace import NotesWorkspace
from autodeck.agents.session import SessionLimits
from autodeck.agents.tools.notes import notes_tools, transcript_index
from autodeck.agents.tools.registry import ToolBox
from autodeck.ingest.document_store import Document, DocumentElement
from autodeck.providers.base import AssistantTurn, ToolCall, Usage
from tests.test_content import context
from tests.test_notes_workspace import DECIDED, TIMES, WALK, build
from tests.test_session import ScriptedConverse

SECRETS = ("vendor", "Shikta", "walkthrough", "bricks", "budget")
"""Words of the transcript that must never reach a summary."""


def turn(name: str, i: int, /, **args: Any) -> AssistantTurn:
    return AssistantTurn(
        tool_calls=[ToolCall(id=f"c{i}", name=name, arguments=args)], usage=Usage(10, 2)
    )


def cite(page: int, quote: str) -> dict[str, Any]:
    return {"page": page, "quote": quote}


def decisions() -> dict[str, Any]:
    return {
        "section": "Decisions",
        "items": [{"text": "Vendor plan chosen.", "cites": [cite(2, DECIDED)]}],
    }


def actions() -> dict[str, Any]:
    return {
        "section": "Action items",
        "items": [{"text": "Run the walkthrough.", "cites": [cite(3, WALK)]}],
    }


def summary() -> dict[str, Any]:
    return {
        "section": "Summary",
        "items": [{"text": "A pilot review.", "cites": [cite(1, "pilot review")]}],
    }


def full_script() -> list[AssistantTurn]:
    return [
        turn("read_transcript", 1, from_page=1, to_page=5),
        turn("notes_set_section", 2, **decisions()),
        turn("notes_set_section", 3, **actions()),
        turn("notes_set_section", 4, **summary()),
        turn("finish_notes", 5, note_to_person="too early"),
        turn("ask_advisor", 6, question="Read cold.", whole_notes=True, pages=[]),
        turn("finish_notes", 7, note_to_person="Check the spelling of Shikha."),
    ]


class Advisor:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        return "Looks right."


def start(tmp_path: Path, model: Any, **overrides: Any) -> NotesRun:
    base = build(tmp_path)
    kwargs: dict[str, Any] = {
        "transcript": base.transcript,
        "store": base.store,
        "times": TIMES,
        "context": context(),
        "model": model,
        "project": "p",
        "session_dir": tmp_path / "session",
    }
    kwargs.update(overrides)
    return compose_notes_agent(**kwargs)


def tool_texts(run: NotesRun) -> list[str]:
    return [m.content for m in run.state.messages if m.role == "tool"]


def test_a_full_session_reads_writes_is_refused_then_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notes_agent, "PRELOAD_TOKENS", 0)  # nothing is preloaded
    model, advisor = ScriptedConverse(*full_script()), Advisor()
    steps: list[dict[str, Any]] = []
    run = start(tmp_path, model, advisor=advisor, on_step=steps.append)

    assert run.state.stop_reason == "finished" and run.state.provider_calls == 7
    ws = run.workspace
    assert ws.shown_pages == {1, 2, 3, 4, 5}
    assert [i.text for i in ws.sections["Decisions"]] == ["Vendor plan chosen."]
    assert ws.sections["Action items"][0].owner is None
    assert ws.note_to_person == "Check the spelling of Shikha."
    opening = model.seen[0][0].content
    assert "Read it with `read_transcript`" in opening and "vendor plan" not in opening

    refused = tool_texts(run)[4]  # the first finish_notes, before any cold read
    assert refused.startswith("ERROR:") and "advisor has not read" in refused

    [prompt] = advisor.prompts
    assert "cites turn 2" in prompt and "turn 3 [00:31]: Shikta will run" in prompt
    assert (
        "Advisor (who saw only: The notes, with the words each item cites"
        in (tool_texts(run)[5])
    )

    session = tmp_path / "session"
    for name in ("transcript.jsonl", "system.md", "notes_workspace.json"):
        assert (session / name).is_file(), name
    saved = json.loads((session / "notes_workspace.json").read_text())
    assert saved["cold_read_revision"] is not None

    # a summary never carries what was said (B78)
    summaries = " ".join(str(s["summary"]) for s in steps)
    assert not any(word in summaries for word in SECRETS)
    assert "finish_notes: refused" in summaries


def test_a_short_transcript_is_preloaded_and_citable_at_once(tmp_path: Path) -> None:
    model = ScriptedConverse(
        turn("notes_set_section", 1, **decisions()),
        turn("notes_set_section", 2, **summary()),
        turn("finish_notes", 3, note_to_person=""),
    )
    run = start(tmp_path, model)  # no advisor: no cold read required
    assert run.state.stop_reason == "finished"
    opening = model.seen[0][0].content
    assert "every turn; all citable now" in opening
    assert "turn 2 [00:12]: We decided to go with the vendor plan" in opening
    assert run.workspace.shown_pages == {1, 2, 3, 4, 5}
    assert (tmp_path / "session" / "system.md").is_file()


def test_the_opening_carries_the_date_and_the_people(tmp_path: Path) -> None:
    model = ScriptedConverse(turn("show_notes", 1))
    start(
        tmp_path,
        model,
        meeting_date="3 November",
        attendees=["Shikha", "Dev"],
        limits=SessionLimits(max_steps=1),
    )
    opening = model.seen[0][0].content
    assert "Date: 3 November" in opening
    assert "not evidence): Shikha, Dev" in opening and "# Client context" in opening
    ws = NotesWorkspace.load(
        tmp_path / "session" / "notes_workspace.json",
        transcript=build(tmp_path / "x").transcript,
        store=build(tmp_path / "x").store,
    )
    assert ws.meeting_date == "3 November" and ws.attendees_hint == ["Shikha", "Dev"]


def long_workspace(tmp_path: Path, turns: int = 45) -> NotesWorkspace:
    segments = tuple(
        (float(i * 10), float(i * 10 + 5), f"Turn number {i} talks about item {i}.", None)
        for i in range(1, turns + 1)
    )
    return build(tmp_path, segments=segments)


def test_read_transcript_refuses_more_than_forty_turns(tmp_path: Path) -> None:
    ws = long_workspace(tmp_path)
    box = ToolBox(
        notes_tools(
            ws, times={}, index=transcript_index(ws, project="p"), require_cold_read=False
        )
    )
    result = box.dispatch(ToolCall("c1", "read_transcript", {"from_page": 1, "to_page": 45}))
    assert result.error and "at most 40" in result.text and ws.shown_pages == set()
    ok = box.dispatch(ToolCall("c2", "read_transcript", {"from_page": 1, "to_page": 40}))
    assert not ok.error and ok.summary == "read_transcript: turns 1-40"
    assert ok.text.startswith("turn 1: Turn number 1")  # no time known: no bracket
    assert ws.shown_pages == set(range(1, 41))


def test_search_transcript_searches_only_the_transcript(tmp_path: Path) -> None:
    ws = build(tmp_path)
    ws.store.add(
        Document(
            doc_id="paper-1",
            source_path="paper.pdf",
            page_count=1,
            elements=[
                DocumentElement(
                    element_id="p1",
                    doc_id="paper-1",
                    kind="text",
                    page=1,
                    bbox=(0, 0, 10, 10),
                    reading_order=0,
                    text="Quantisation halves memory in the budget model.",
                )
            ],
        )
    )
    box = ToolBox(
        notes_tools(
            ws, times=TIMES, index=transcript_index(ws, project="p"), require_cold_read=False
        )
    )
    paper = box.dispatch(ToolCall("c1", "search_transcript", {"query": "quantisation memory"}))
    assert paper.summary == "search_transcript: 0 turns" and "Quantisation" not in paper.text
    hit = box.dispatch(ToolCall("c2", "search_transcript", {"query": "budget"}))
    assert hit.summary == "search_transcript: 1 turns"
    assert hit.text == "turn 4 [00:50]: We are not sure about the budget yet."
    assert ws.shown_pages == {4}  # only what the search returned became citable


def test_ask_advisor_on_a_long_transcript_attaches_cited_and_asked_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notes_tools_module, "WHOLE_TRANSCRIPT_TOKENS", 1)
    advisor = Advisor()
    model = ScriptedConverse(
        turn("notes_set_section", 1, **decisions()),
        turn("ask_advisor", 2, question="Cold.", whole_notes=True, pages=[5]),
    )
    run = start(tmp_path, model, advisor=advisor, limits=SessionLimits(max_steps=2))
    [prompt] = advisor.prompts
    assert "only the turns the notes cite" in prompt
    assert "turn 2 [00:12]" in prompt and "turn 5 [1:01:40]" in prompt
    assert "turn 4 [00:50]" not in prompt and "turn 1 [00:05]" not in prompt
    assert run.workspace.cold_read_revision is not None


def test_ask_advisor_with_pages_only_is_not_a_cold_read(tmp_path: Path) -> None:
    advisor = Advisor()
    model = ScriptedConverse(
        turn("ask_advisor", 1, question="What was said?", whole_notes=False, pages=[4]),
        turn("ask_advisor", 2, question="Too many.", whole_notes=False, pages=[1] * 7),
    )
    run = start(tmp_path, model, advisor=advisor, limits=SessionLimits(max_steps=2))
    [prompt] = advisor.prompts
    assert "# Transcript turns" in prompt and "budget" in prompt and "cites turn" not in prompt
    assert run.workspace.cold_read_revision is None
    assert "at most 6" in tool_texts(run)[1]


def finished_session(tmp_path: Path) -> NotesRun:
    script = [
        turn("notes_set_section", 1, **decisions()),
        turn("notes_set_section", 2, **summary()),
        turn("finish_notes", 3, note_to_person="First."),
    ]
    return start(tmp_path, ScriptedConverse(*script))


def resume(tmp_path: Path, model: Any, instruction: str = "Fix it.", **kw: Any) -> NotesRun:
    base = build(tmp_path / "again")
    return resume_notes_agent(
        instruction,
        session_dir=tmp_path / "session",
        transcript=base.transcript,
        store=base.store,
        times=TIMES,
        model=model,
        project="p",
        **kw,
    )


def test_resume_edits_an_item_under_the_saved_system_prompt(tmp_path: Path) -> None:
    finished_session(tmp_path)
    files = SessionFiles(tmp_path / "session")
    before = len(files.transcript.read_text().splitlines())
    files.system.write_text("SAVED SYSTEM PROMPT", encoding="utf-8")
    systems: list[str | None] = []

    class Recording(ScriptedConverse):
        def converse(self, messages, tools, *, system=None):  # type: ignore[no-untyped-def]
            systems.append(system)
            return super().converse(messages, tools, system=system)

    model = Recording(
        turn(
            "notes_edit_item",
            1,
            item_id="n1",
            item={"text": "The vendor plan was chosen.", "cites": [cite(2, DECIDED)]},
        ),
        turn("finish_notes", 2, note_to_person="Reworded n1."),
    )
    again = resume(tmp_path, model, "Reword the decision.")
    assert again.state.stop_reason == "finished"
    assert systems == ["SAVED SYSTEM PROMPT"] * 2
    assert again.workspace.find("n1").text == "The vendor plan was chosen."
    assert again.workspace.note_to_person == "Reworded n1."
    asked = [m for m in model.seen[0] if m.role == "user"][-1].content
    assert "Reword the decision." in asked
    assert "Fix every item a correction affects" in asked
    assert len(files.transcript.read_text().splitlines()) > before
    saved = json.loads(files.workspace.read_text())
    assert saved["sections"]["Decisions"][0]["text"] == "The vendor plan was chosen."


def test_resume_reseeds_a_session_that_has_grown_too_long(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    finished_session(tmp_path)
    monkeypatch.setattr(notes_agent, "RESEED_TOKENS", 0)
    model = ScriptedConverse(turn("finish_notes", 1, note_to_person="Same."))
    again = resume(tmp_path, model)
    files = SessionFiles(tmp_path / "session")
    assert (files.root / "transcript.1.jsonl").is_file()
    seed = again.state.messages[0].content
    assert seed.startswith("# You are continuing meeting notes")
    assert "Vendor plan chosen." in seed and "<!-- n1 -->" in seed
    assert "still citable" in seed and "Read it again" in seed


def test_resume_without_a_notes_session_raises(tmp_path: Path) -> None:
    with pytest.raises(ComposeError, match="no notes session"):
        resume(tmp_path, ScriptedConverse())


def test_resume_refuses_notes_on_a_changed_transcript(tmp_path: Path) -> None:
    finished_session(tmp_path)
    segments = (
        (5.0, 10.0, "Welcome.", None),
        (12.5, 20.0, "Something else entirely.", None),
    )
    other = build(tmp_path / "other", segments=segments)
    with pytest.raises(ComposeError):
        resume_notes_agent(
            "x",
            session_dir=tmp_path / "session",
            transcript=other.transcript,
            store=other.store,
            times={},
            model=ScriptedConverse(),
        )


def test_the_system_prompt_has_the_skill_and_an_index_of_the_rest() -> None:
    system = notes_system(project=None)
    assert "# Skill: `meeting-notes`" in system
    for name in ("writing-style", "fidelity", "meeting-readout"):
        assert f"- `{name}` " in system
    assert "- `meeting-notes` " not in system


def test_the_deck_agent_no_longer_indexes_meeting_notes() -> None:
    system = agent_system(provenance="strict", design_mode="structured", project=None)
    assert "- `meeting-notes` " not in system and "- `meeting-readout` " in system


def test_transcript_text_gives_turns_with_times_where_known(tmp_path: Path) -> None:
    doc = build(tmp_path).transcript
    assert transcript_text(doc, TIMES, [2]) == (
        "turn 2 [00:12]: We decided to go with the vendor plan for the data bricks migration."
    )
    assert transcript_text(doc, {}, [1]).startswith("turn 1: Welcome")
