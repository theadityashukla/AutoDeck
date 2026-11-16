"""A meeting run to a deck through the CLI, offline: notes, clarify, answer, `draft --agent`,
validate and `revise --agent`, all in scripted sessions (B82).

Nothing said in the meeting may reach any command's output (B78).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import autodeck.providers.registry as registry_module
from autodeck.agents.compose import ComposedSlide
from autodeck.agents.content import ProposedBlock, ProposedCitation, ProposedClaim
from autodeck.agents.workspace import DeckBriefDraft
from autodeck.ir.store import IRStore
from tests.test_cli_draft import CLARIFIED, AgentComposer, World, agent_turn
from tests.test_cli_gate2 import CLIENT, PROJECT
from tests.test_meeting_cli_wiring import DOC, QUOTE, RUN, _composed, _source, _world
from tests.test_meeting_notes_cli import SAID, Advisor, notes_script

READ_COLD = {
    "question": "Read cold.",
    "slide_ids": ["all"],
    "headlines_only": True,
    "include_notes": False,
    "skills": [],
    "pages": [],
}


def meeting_slide(sid: str, text: str) -> dict[str, Any]:
    cite = [ProposedCitation(doc_id=DOC, quote=QUOTE)]
    slide = ComposedSlide(
        id=sid,
        narrative_role="evidence",
        component="quote",
        intent=f"Land {sid}.",
        message_ids=["km1"],
        blocks=[
            ProposedBlock(
                id=bid, kind="claim", slot=slot, claim=ProposedClaim(text=text, citations=cite)
            )
            for bid, slot in (("b1", "headline"), ("b2", "quote"))
        ]
        + [ProposedBlock(id="b3", kind="framing", slot="attribution", text="The meeting")],
        speaker_notes=[],
    )
    return {"slide": slide.model_dump(mode="json")}


def deck_script(text: str = "The rollout has a first date.") -> list[Any]:
    brief = DeckBriefDraft(
        objective="Report the meeting.",
        audience="The board",
        length_target=2,
        key_messages=_composed().key_messages,
        must_include=[],
        must_avoid=[],
    )
    return [
        agent_turn("set_brief", 1, **brief.model_dump(mode="json")),
        agent_turn("write_slide", 2, **meeting_slide("s1", text)),
        agent_turn("ask_advisor", 3, **READ_COLD),
        agent_turn("finish", 4, coverage=[], notes="Drafted from the meeting."),
    ]


class MeetingWorld:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.w: World = _world(tmp_path, monkeypatch, CLARIFIED)
        self.composer = AgentComposer(CLARIFIED)
        roles = {"composer": self.composer, "validation": self.w.judge, "advisor": Advisor()}
        monkeypatch.setattr(
            registry_module.ModelRegistry, "provider_for", lambda self, role, **kw: roles[role]
        )
        settings = {"audio_name": "board.m4a", "audio_sha256": "ab" * 32, "speakers": False,
                    "num_speakers": None, "client": CLIENT, "project": PROJECT}  # fmt: skip
        (self.w.runs / RUN / "meeting" / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )
        assert _source(self.w).exit_code == 0

    @property
    def run(self) -> Path:
        return self.w.runs / RUN

    @property
    def session(self) -> Path:
        return self.run / "session"

    def go(self, *args: str) -> Any:
        return self.w.run(*args, *self.w.data_roots)

    def notes(self) -> Any:
        self.composer.turns = notes_script()
        return self.go("meeting", "notes", RUN)

    def clarify(self) -> None:
        result = self.go(
            "clarify", RUN, "--client", CLIENT, "--project", PROJECT,
            "--prompt", "Turn the meeting into a deck.", "--provenance", "strict",
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        assert self.w.run("answer", RUN, "--accept-all", *self.w.roots).exit_code == 0

    def draft(self) -> Any:
        self.composer.turns = deck_script()
        return self.go("draft", RUN, "--agent")


def clean(result: Any) -> None:
    assert not any(word in result.output for word in SAID), result.output


def test_notes_then_a_deck_from_the_same_session_then_revise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = MeetingWorld(tmp_path, monkeypatch)
    result = m.notes()
    assert result.exit_code == 0, result.output
    clean(result)
    m.clarify()
    assert (m.session / "notes_meta.json").is_file() and not (m.session / "meta.json").exists()
    notes_files = {p.name: p.read_bytes() for p in m.session.iterdir() if p.is_file()}

    result = m.draft()
    assert result.exit_code == 0, result.output
    clean(result)
    assert "fell back" not in result.output and "step 2 write_slide" in result.output
    meta = json.loads((m.session / "meta.json").read_text())
    assert meta["kind"] == "deck" and meta["from_meeting_session"] is True
    assert meta["stop_reason"] == "finished" and meta["fell_back"] is False
    assert [s.id for s in IRStore(m.w.runs, RUN).load().slides] == ["s1"]
    for name, content in notes_files.items():  # the deck phase leaves the notes alone
        assert (m.session / name).read_bytes() == content, name
    for name in ("system.md", "workspace.json", "transcript.jsonl", "corpus_map.md"):
        assert (m.session / name).is_file(), name
    assert "# This deck is built from a meeting" in (m.session / "system.md").read_text()

    result = m.go("validate", RUN)
    assert result.exit_code == 0, result.output
    clean(result)

    m.composer.turns = [
        agent_turn("write_slide", 6, **meeting_slide("s1", "The rollout date is named.")),
        agent_turn("ask_advisor", 7, **READ_COLD),
        agent_turn("finish", 8, coverage=[], notes="Reworded slide one."),
    ]
    result = m.go("revise", RUN, "--instruction", "Reword it.", "--agent")
    assert result.exit_code == 0, result.output
    clean(result)
    assert "Reworded slide one." in result.output and "changed: s1" in result.output
    assert "Reword it." in (m.session / "transcript.jsonl").read_text()
    assert "Reword it." not in (m.session / "notes_transcript.jsonl").read_text()

    # revise-notes still resumes the notes session, and leaves the deck files alone
    deck_log = (m.session / "transcript.jsonl").read_bytes()
    m.composer.turns = [agent_turn("finish_notes", 9, note_to_person="Spelling noted.")]
    result = m.go("meeting", "revise-notes", RUN, "--say", "Spell it Shikha.")
    assert result.exit_code == 0, result.output
    clean(result)
    assert "Spell it Shikha." in (m.session / "notes_transcript.jsonl").read_text()
    assert (m.session / "transcript.jsonl").read_bytes() == deck_log

    # fresh notes after a deck phase do not touch the deck either
    result = m.notes()
    assert result.exit_code == 0, result.output
    assert (m.session / "transcript.jsonl").read_bytes() == deck_log
    assert (m.session / "workspace.json").is_file()


def test_revise_agent_with_only_a_notes_session_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = MeetingWorld(tmp_path, monkeypatch)
    assert m.notes().exit_code == 0
    m.clarify()
    m.w.composer.answers.append(_composed())  # the one-shot draft
    m.composer.answers.append(_composed())
    assert m.go("draft", RUN).exit_code == 0
    result = m.go("revise", RUN, "--instruction", "Reword it.", "--agent")
    assert result.exit_code == 1
    assert "notes session but no deck session" in result.output
    assert "draft with --agent first" in result.output


def test_a_meeting_deck_without_notes_is_drafted_from_the_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = MeetingWorld(tmp_path, monkeypatch)
    m.clarify()
    result = m.draft()
    assert result.exit_code == 0, result.output
    clean(result)
    meta = json.loads((m.session / "meta.json").read_text())
    assert meta["kind"] == "deck" and meta["from_meeting_session"] is False
    assert not (m.session / "notes_workspace.json").exists()
    steps = (m.session / "transcript.jsonl").read_text()
    assert "from the meeting session" not in steps
    # a second draft archives the first deck transcript
    assert m.draft().exit_code == 0
    assert (m.session / "transcript.1.jsonl").is_file()


def test_the_agent_falls_back_to_one_call_when_it_writes_too_few_slides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = MeetingWorld(tmp_path, monkeypatch)
    m.clarify()
    m.composer.answers.append(_composed())
    script = deck_script()
    brief = json.loads(json.dumps(script[0].tool_calls[0].arguments))
    brief["length_target"] = 6  # one slide of six is under half
    script[0] = agent_turn("set_brief", 1, **brief)
    m.composer.turns = script
    result = m.go("draft", RUN, "--agent")
    assert result.exit_code == 0, result.output
    assert "agent fell back to one-shot compose" in result.output
    meta = json.loads((m.session / "meta.json").read_text())
    assert meta["fell_back"] is True and meta["kind"] == "deck"
    assert [s.id for s in IRStore(m.w.runs, RUN).load().slides] == ["s1", "s2"]
