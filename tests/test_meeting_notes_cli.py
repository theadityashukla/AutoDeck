"""`autodeck meeting notes` and `revise-notes` through the CLI, offline (B80).

A meeting run is built from a hand-written transcript; the composer is a scripted converse
model and the advisor a canned reader. Nothing is printed that was said in the meeting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import autodeck.providers.registry as registry_module
from autodeck.agents.notes_agent import SessionFiles
from autodeck.providers.base import AssistantTurn, ToolCall, Usage
from autodeck.providers.registry import ModelRegistry, RegistryError
from tests.test_cli_draft import CLARIFIED, World
from tests.test_cli_gate2 import CLIENT, PROJECT
from tests.test_meeting_cli_wiring import (
    RUN,
    _composed,
    _source,
    _through_clarify,
    _world,
)
from tests.test_session import ScriptedConverse

SAID = ("pilot", "walkthrough", "Shikha", "February")
"""Words of the meeting; none may reach the command's output."""


def turn(name: str, i: int, /, **args: Any) -> AssistantTurn:
    return AssistantTurn(
        tool_calls=[ToolCall(id=f"c{i}", name=name, arguments=args)], usage=Usage(10, 2)
    )


def cite(page: int, quote: str) -> dict[str, Any]:
    return {"page": page, "quote": quote}


def section(name: str, text: str, page: int, quote: str) -> dict[str, Any]:
    return {"section": name, "items": [{"text": text, "cites": [cite(page, quote)]}]}


def notes_script() -> list[AssistantTurn]:
    return [
        turn(
            "notes_set_section",
            1,
            **section("Decisions", "Pilot starts.", 2, "pilot goes live"),
        ),
        turn(
            "notes_set_section",
            2,
            **section("Action items", "Run the walkthrough.", 3, "will run the walkthrough"),
        ),
        turn("notes_set_section", 3, **section("Summary", "A short call.", 1, "Good morning")),
        turn("ask_advisor", 4, question="Read cold.", whole_notes=True, pages=[]),
        turn("finish_notes", 5, note_to_person="Check the spelling of Shikha."),
    ]


class Advisor:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        return "Looks right."


class NotesWorld:
    """A meeting run with its client and project known, and scripted model roles."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *turns: AssistantTurn):
        self.w: World = _world(tmp_path, monkeypatch)
        self.model = ScriptedConverse(*turns)
        self.advisor = Advisor()
        roles = {"composer": self.model, "advisor": self.advisor}
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

    def invoke(self, *args: str):  # type: ignore[no-untyped-def]
        return self.w.run("meeting", *args, RUN, *self.w.data_roots)

    def notes(self, *extra: str):  # type: ignore[no-untyped-def]
        return self.w.run("meeting", "notes", RUN, *extra, *self.w.data_roots)

    def revise(self, *extra: str):  # type: ignore[no-untyped-def]
        return self.w.run("meeting", "revise-notes", RUN, *extra, *self.w.data_roots)

    def revisions(self) -> list[dict]:
        path = self.run / "revisions.jsonl"
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )


def test_meeting_notes_writes_the_files_and_prints_counts_not_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = NotesWorld(tmp_path, monkeypatch, *notes_script())
    result = n.notes("--date", "3 November", "--attendees", "Shikha, Dev")
    assert result.exit_code == 0, result.output
    assert "Stop reason: finished" in result.output
    assert "Decisions: 1" in result.output and "Themes: 0" in result.output
    assert "Wrote meeting/notes.md" in result.output
    assert not any(word in result.output for word in SAID)  # B78: nothing said is printed

    meeting = n.run / "meeting"
    notes = (meeting / "notes.md").read_text()
    assert "Date: 3 November" in notes and "**Owner TBD**: Run the walkthrough." in notes
    assert "[00:31]" in notes  # times come from the sidecar
    assert (meeting / "notes.rendered.md").read_text() == notes
    data = json.loads((meeting / "notes.json").read_text())
    assert data["sections"]["Decisions"][0]["cites"][0]["page"] == 2
    assert (meeting / "agent-note.md").read_text() == "Check the spelling of Shikha.\n"
    session = n.run / "session"
    meta = json.loads((session / "meta.json").read_text())
    assert meta["kind"] == "notes" and meta["stop_reason"] == "finished"
    assert meta["provider_calls"] == 5 and meta["steps"] == 5
    assert (session / "notes_workspace.json").is_file()
    opening = n.model.seen[0][0].content
    assert "People the person says were there" in opening and "Shikha, Dev" in opening
    assert "APLD" in opening  # the engagement's memory reached the agent
    assert len(n.advisor.prompts) == 1 and "cites turn 2" in n.advisor.prompts[0]


def test_an_unfinished_session_still_writes_what_it_had(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = NotesWorld(tmp_path, monkeypatch, *notes_script()[:1])
    result = n.notes("--steps", "1")
    assert result.exit_code == 0, result.output
    assert "Stop reason: step_cap" in result.output and "before finishing" in result.output
    assert "Decisions: 1" in result.output
    assert (n.run / "meeting" / "notes.md").is_file()
    assert not (n.run / "meeting" / "agent-note.md").exists()


def test_notes_need_a_meeting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    n = NotesWorld(tmp_path, monkeypatch)
    (n.run / "meeting" / "settings.json").unlink()
    result = n.notes()
    assert result.exit_code == 1 and "has no meeting" in result.output
    assert "autodeck meeting transcribe" in result.output
    assert n.w.run("meeting", "notes", "ghost", *n.w.data_roots).exit_code == 1


def test_revise_notes_say_continues_the_session_and_logs_the_instruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = NotesWorld(tmp_path, monkeypatch, *notes_script())
    assert n.notes().exit_code == 0
    n.model.turns.extend(
        [
            turn(
                "notes_edit_item",
                11,
                item_id="n1",
                item={
                    "text": "The pilot goes live in February.",
                    "cites": [cite(2, "pilot goes live")],
                },
            ),
            turn("finish_notes", 12, note_to_person="Reworded the decision."),
        ]
    )
    calls = len(n.model.seen)
    result = n.revise("--say", "Say February, not just the pilot.")
    assert result.exit_code == 0, result.output
    assert "Stop reason: finished" in result.output
    assert not any(word in result.output for word in SAID)
    assert "pilot goes live in February" in (n.run / "meeting" / "notes.md").read_text()
    assert (n.run / "meeting" / "agent-note.md").read_text() == "Reworded the decision.\n"
    [record] = n.revisions()
    assert record["target"] == "notes" and record["instruction"] == (
        "Say February, not just the pilot."
    )
    assert record["reply"] == "Reworded the decision." and "edits" not in record
    asked = n.model.seen[calls][-1].content
    assert "Say February, not just the pilot." in asked


def test_revise_notes_needs_exactly_one_of_say_and_apply_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = NotesWorld(tmp_path, monkeypatch, *notes_script())
    assert n.notes().exit_code == 0
    assert n.revise().exit_code == 1
    both = n.revise("--say", "x", "--apply-edits")
    assert both.exit_code == 1 and "exactly one" in both.output


def test_revise_notes_needs_a_notes_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = NotesWorld(tmp_path, monkeypatch)
    result = n.revise("--say", "x")
    assert result.exit_code == 1 and "no notes session" in result.output
    assert n.model.seen == []


def test_apply_edits_with_no_difference_makes_no_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = NotesWorld(tmp_path, monkeypatch, *notes_script())
    assert n.notes().exit_code == 0
    calls = len(n.model.seen)
    result = n.revise("--apply-edits")
    assert result.exit_code == 0 and "No edits to apply." in result.output
    assert len(n.model.seen) == calls and n.revisions() == []


def test_apply_edits_sends_the_diff_and_logs_edits_not_an_instruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    n = NotesWorld(tmp_path, monkeypatch, *notes_script())
    assert n.notes().exit_code == 0
    path = n.run / "meeting" / "notes.md"
    path.write_text(
        path.read_text().replace("Pilot starts.", "Pilot starts in February."), encoding="utf-8"
    )
    n.model.turns.extend(
        [
            turn(
                "notes_edit_item",
                11,
                item_id="n1",
                item={
                    "text": "Pilot starts in February.",
                    "cites": [cite(2, "pilot goes live")],
                },
            ),
            turn("finish_notes", 12, note_to_person=""),
        ]
    )
    calls = len(n.model.seen)
    result = n.revise("--apply-edits")
    assert result.exit_code == 0, result.output
    asked = n.model.seen[calls][-1].content
    assert asked.count("The person edited the notes file.") == 1
    assert "-- Pilot starts. [00:31] <!-- n1 -->" in asked
    assert "+- Pilot starts in February. [00:31] <!-- n1 -->" in asked
    [record] = n.revisions()
    assert record["target"] == "notes" and "Pilot starts in February." in record["edits"]
    assert "instruction" not in record
    rendered = (n.run / "meeting" / "notes.rendered.md").read_text()
    assert (
        rendered == path.read_text()
    )  # rewritten from the workspace: the edit is now the notes
    assert not (n.run / "meeting" / "agent-note.md").exists()  # empty note: file removed


# -- confidential_ok (B81) -----------------------------------------------------------

REFUSAL = "not marked confidential_ok in config/models.yaml"


def flagless_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, flag: Any = None
) -> None:
    """A copy of the real config with `confidential_ok` absent (or set to `flag`)."""
    config = yaml.safe_load(Path("config/models.yaml").read_text(encoding="utf-8"))
    for env in config["environments"].values():
        env.pop("confidential_ok", None)
        if flag is not None:
            env["confidential_ok"] = flag
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(registry_module, "DEFAULT_CONFIG_PATH", path)


@pytest.mark.parametrize("flag", [None, False])
def test_a_meeting_run_is_refused_on_an_unflagged_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: Any
) -> None:
    n = NotesWorld(tmp_path, monkeypatch, *notes_script())
    assert n.notes().exit_code == 0
    flagless_config(tmp_path, monkeypatch, flag=flag)
    calls = len(n.model.seen)
    for result in (n.notes(), n.revise("--say", "x")):
        assert result.exit_code == 1 and REFUSAL in result.output
        assert "client-confidential" in result.output
    assert len(n.model.seen) == calls


def test_clarify_and_validate_refuse_a_meeting_run_on_an_unflagged_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(tmp_path, monkeypatch, CLARIFIED, _composed())
    assert _source(w).exit_code == 0
    flagless_config(tmp_path, monkeypatch)
    clarify = w.run(
        "clarify", RUN, "--client", CLIENT, "--project", PROJECT,
        "--prompt", "Turn the meeting into a deck.", *w.data_roots,
    )  # fmt: skip
    assert clarify.exit_code == 1 and REFUSAL in clarify.output
    assert w.composer.prompts == []


def test_validate_refuses_a_meeting_run_on_an_unflagged_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(tmp_path, monkeypatch, CLARIFIED, _composed())
    _through_clarify(w, "--provenance", "strict")
    assert w.run("draft", RUN, *w.data_roots).exit_code == 0
    flagless_config(tmp_path, monkeypatch)
    result = w.run("validate", RUN, *w.data_roots)
    assert result.exit_code == 1 and REFUSAL in result.output
    assert w.judge.prompts == []  # type: ignore[attr-defined]


def test_a_corpus_run_is_unaffected_by_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = World(tmp_path, monkeypatch, CLARIFIED)
    flagless_config(tmp_path, monkeypatch)
    result = w.clarify()
    assert result.exit_code == 0, result.output


def test_the_shipped_config_flags_every_environment() -> None:
    raw = yaml.safe_load(Path("config/models.yaml").read_text(encoding="utf-8"))
    assert set(raw["environments"]) == {"dev-mistral", "sit", "prod"}
    for env in raw["environments"]:
        assert ModelRegistry.load(env).confidential_ok is True


def test_the_flag_defaults_to_false_and_must_be_a_bool(tmp_path: Path) -> None:
    raw = yaml.safe_load(Path("config/models.yaml").read_text(encoding="utf-8"))
    del raw["environments"]["sit"]["confidential_ok"]
    raw["environments"]["prod"]["confidential_ok"] = "yes"
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert ModelRegistry.load("sit", path).confidential_ok is False
    with pytest.raises(RegistryError, match="confidential_ok must be true or false"):
        ModelRegistry.load("prod", path)
    assert "confidential_ok" not in ModelRegistry.load("sit", path).bindings()


def test_session_files_helper_points_at_the_run_session(tmp_path: Path) -> None:
    assert SessionFiles(tmp_path).workspace.name == "notes_workspace.json"
