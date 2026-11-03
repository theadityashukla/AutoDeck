"""The deck agent end to end (B71, B74): scripted turns, a tiny real store, no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import autodeck.agents.deck_agent as deck_agent
from autodeck.agents.compose import ComposeError
from autodeck.agents.content import ProposedBlock
from autodeck.agents.deck_agent import (
    SessionFiles,
    build_settings,
    compose_deck_agent,
    resume_deck_agent,
)
from autodeck.agents.session import SessionLimits, TranscriptLog
from autodeck.agents.tools.advisor import advisor_tools
from autodeck.audit.manifest import session_record
from autodeck.providers.base import AssistantTurn, ToolCall, Usage
from tests.test_agent_tools import CLAIMS, TOKENS, brief_args, deck_fields, make_env
from tests.test_compose import QUOTE, claim_block, slide
from tests.test_content import context
from tests.test_session import ScriptedConverse


def turn(name: str, i: int, /, **args: Any) -> AssistantTurn:
    return AssistantTurn(
        tool_calls=[ToolCall(id=f"c{i}", name=name, arguments=args)], usage=Usage(10, 2)
    )


def slide_args() -> dict[str, Any]:
    """A `quote` slide that passes every draft check: headline, quote and attribution."""
    s = slide(
        "s1",
        ["km1"],
        claim_block("b1", "Quantisation halves memory.", QUOTE),
        claim_block("b2", "Quantisation halves memory.", QUOTE, slot="quote"),
        ProposedBlock(id="b3", kind="framing", slot="attribution", text="Paper One"),
    )
    return {"slide": s.model_dump(mode="json")}


def good_script() -> list[AssistantTurn]:
    return [
        turn("load_skill", 1, name="deck-thinking"),
        turn("set_brief", 2, **brief_args()),
        turn("read_passage", 3, doc_id="paper-1", page=4),
        turn("write_slide", 4, **slide_args()),
        turn("finish", 5, coverage=[], notes="Done."),
    ]


def start(tmp_path: Path, model: Any, **overrides: Any):  # type: ignore[no-untyped-def]
    ws, index, docs = make_env(tmp_path / "corpus")
    kwargs: dict[str, Any] = {
        "answers": [],
        "index": index,
        "claims": CLAIMS,
        "documents": docs,
        "context": context(),
        "store": ws.settings.store,
        "tokens": TOKENS,
        "model": model,
        "run_id": "r1",
        "client": "northwind",
        "project": "p",
        "theme_ref": "config/tokens/dev.json",
        "component_lib_version": deck_fields()["component_lib_version"],
        "session_dir": tmp_path / "session",
    }
    kwargs.update(overrides)
    return compose_deck_agent("Show that quantisation halves memory.", **kwargs), index, ws


def test_a_scripted_session_writes_a_draft_and_its_files(tmp_path: Path) -> None:
    model = ScriptedConverse(*good_script())
    run, _index, _ws = start(tmp_path, model)

    assert run.state.stop_reason == "finished"
    assert len(run.result.deck.slides) == 1
    assert run.result.provider_calls == 5 == len(model.seen)
    assert run.result.notes == "Done."
    assert run.result.coverage  # recomputed by code, not taken from the model
    session = tmp_path / "session"
    for name in ("transcript.jsonl", "workspace.json", "system.md", "corpus_map.md"):
        assert (session / name).is_file(), name
    record = session_record(session)
    assert record and record["provider_calls"] == 5 and record["steps"] == 5


def test_a_session_that_never_sets_a_brief_raises(tmp_path: Path) -> None:
    model = ScriptedConverse(turn("load_skill", 1, name="deck-thinking"))
    with pytest.raises(ComposeError):
        start(tmp_path, model, limits=SessionLimits(max_steps=1))


def test_step_cap_still_returns_the_draft_with_a_correction(tmp_path: Path) -> None:
    script = good_script()[:4]  # everything but finish
    run, _i, _w = start(tmp_path, ScriptedConverse(*script), limits=SessionLimits(max_steps=4))
    assert run.state.stop_reason == "step_cap"
    assert len(run.result.deck.slides) == 1
    assert any("step_cap" in line for line in run.result.corrections)


def _settings(index_ws):  # type: ignore[no-untyped-def]
    return build_settings(
        prompt="Show that quantisation halves memory.",
        answers=[],
        chat_brief=None,
        store=index_ws.settings.store,
        tokens=TOKENS,
        provenance="strict",
        deck_fields=deck_fields(),
    )


def test_resume_continues_the_transcript_under_the_saved_system_prompt(
    tmp_path: Path,
) -> None:
    _run, index, ws = start(tmp_path, ScriptedConverse(*good_script()))
    files = SessionFiles(tmp_path / "session")
    before = len(files.transcript.read_text().splitlines())
    files.system.write_text("SAVED SYSTEM PROMPT", encoding="utf-8")

    seen_systems: list[str | None] = []

    class Recording(ScriptedConverse):
        def converse(self, messages, tools, *, system=None):  # type: ignore[no-untyped-def]
            seen_systems.append(system)
            return super().converse(messages, tools, system=system)

    model = Recording(turn("finish", 9, coverage=[], notes="Changed."))
    again = resume_deck_agent(
        "Tighten slide one.",
        session_dir=files.root,
        settings=_settings(ws),
        index=index,
        claims=CLAIMS,
        model=model,
    )
    assert seen_systems == ["SAVED SYSTEM PROMPT"]
    assert len(files.transcript.read_text().splitlines()) > before
    assert "Tighten slide one." in model.seen[0][-1].content
    assert len(again.result.deck.slides) == 1 and again.result.notes == "Changed."
    assert again.workspace.slide_ids() == ["s1"]  # the workspace was reloaded


def test_resume_without_a_session_is_an_error(tmp_path: Path) -> None:
    ws, index, _docs = make_env(tmp_path / "corpus")
    with pytest.raises(ComposeError, match="no agent session"):
        resume_deck_agent(
            "x",
            session_dir=tmp_path / "none",
            settings=_settings(ws),
            index=index,
            claims=CLAIMS,
            model=ScriptedConverse(),
        )


def test_a_huge_transcript_is_archived_and_reseeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run, index, ws = start(tmp_path, ScriptedConverse(*good_script()))
    files = SessionFiles(tmp_path / "session")
    monkeypatch.setattr(deck_agent, "RESEED_TOKENS", 10)
    model = ScriptedConverse(turn("finish", 9, coverage=[], notes="n"))
    resume_deck_agent(
        "Change it.",
        session_dir=files.root,
        settings=_settings(ws),
        index=index,
        claims=CLAIMS,
        model=model,
    )
    assert (files.root / "transcript.1.jsonl").is_file()
    first = model.seen[0]
    assert "continuing a deck you built earlier" in first[0].content
    assert "Change it." in first[-1].content and len(first) == 2
    assert TranscriptLog.load(files.transcript).messages[0].content == first[0].content
    record = session_record(files.root)
    assert record and "transcript.1.jsonl" in record["archived_transcripts"]


# -- the advisor tool ---------------------------------------------------------------


class Advisor:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        return "Looks fine."


def _ask(tool, **overrides: Any):  # type: ignore[no-untyped-def]
    args = {
        "question": "Read cold.",
        "slide_ids": [],
        "headlines_only": False,
        "include_notes": False,
        "skills": [],
        "pages": [],
    }
    args.update(overrides)
    return tool.run(tool.args_model(**args))


def test_advisor_tool_attaches_only_what_is_asked(tmp_path: Path) -> None:
    run, index, _ws = start(tmp_path, ScriptedConverse(*good_script()))
    model = Advisor()
    (tool,) = advisor_tools(run.workspace, model=model, index=index, project=None)

    result = _ask(tool, slide_ids=["all"], headlines_only=True)
    assert not result.error and "Looks fine." in result.text
    assert "The headlines, in deck order" in model.prompts[-1]
    assert "cites" not in model.prompts[-1]  # no claim text or quotes, headlines only

    _ask(tool, slide_ids=["s1"])
    assert "slide s1" in model.prompts[-1]

    nothing = _ask(tool)
    assert "(none)" in model.prompts[-1] and not nothing.error


def test_advisor_tool_refuses_unknown_slides_and_too_many_pages(tmp_path: Path) -> None:
    run, index, _ws = start(tmp_path, ScriptedConverse(*good_script()))
    model = Advisor()
    (tool,) = advisor_tools(run.workspace, model=model, index=index, project=None)
    from autodeck.agents.tools.registry import ToolError

    with pytest.raises(ToolError, match="no slide"):
        _ask(tool, slide_ids=["s99"])
    pages = [{"doc_id": "paper-1", "page": 4}] * 5
    with pytest.raises(ToolError, match="at most 4"):
        _ask(tool, pages=pages)
    assert model.prompts == []


def test_session_record_is_none_without_a_transcript(tmp_path: Path) -> None:
    assert session_record(tmp_path / "nothing") is None
    assert json.dumps(session_record(tmp_path / "x")) == "null"


def test_with_an_advisor_finish_is_held_back_until_the_cold_read(tmp_path: Path) -> None:
    script = good_script()[:4] + [
        turn("finish", 5, coverage=[], notes="Early."),
        turn(
            "ask_advisor",
            6,
            question="Read cold.",
            slide_ids=["all"],
            headlines_only=True,
            include_notes=False,
            skills=[],
            pages=[],
        ),
        turn("finish", 7, coverage=[], notes="Done."),
    ]
    model = ScriptedConverse(*script)
    run, _index, ws = start(tmp_path, model, advisor=Advisor())

    assert run.state.stop_reason == "finished"
    assert run.result.notes == "Done."
    assert run.result.provider_calls == 7
    assert ws is not None and run.workspace.cold_read == ["s1"]
