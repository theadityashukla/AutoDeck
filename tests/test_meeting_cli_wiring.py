"""A meeting run through the CLI, offline: transcript -> source -> clarify -> draft -> validate.

Fake providers only (the `World` of `test_cli_draft.py`). No corpus exists for the meeting-only
runs: a transcript is a complete source on its own (B78).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import autodeck.providers.registry as registry_module
from autodeck.agents.compose import ComposeDraft
from autodeck.agents.validation import ClaimJudgement, ValidationDraft
from autodeck.audit.verdicts import VerdictJudgement
from autodeck.cli import run_source_hashes
from autodeck.ingest.document_store import DocumentStore
from autodeck.pipeline.orchestrator import Orchestrator
from tests.test_cli_draft import CLARIFIED, COMPOSED, World, claim_slide
from tests.test_cli_gate2 import CLIENT, PROJECT
from tests.test_transcript_source import TRANSCRIPT

QUOTE = "The pilot goes live in the first week of February."
RUN = "m1"
DOC = "transcript--m1"


class MeetingJudge:
    """Supports every claim named in the prompt, quoting the meeting."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        ids = [c for c in ("s1:b1", "s2:b1") if c in prompt]
        verdict = VerdictJudgement(
            verdict="supported", verdict_notes="said", supporting_quote=QUOTE
        )
        return ValidationDraft(
            judgements=[ClaimJudgement(claim_id=i, judgement=verdict) for i in ids]
        )


def _meeting_slide(sid: str):  # type: ignore[no-untyped-def]
    slide = claim_slide(sid, "The pilot goes live in February.", ["km1"])
    slide.blocks[0].claim.citations[0].doc_id = DOC
    slide.blocks[0].claim.citations[0].quote = QUOTE
    return slide


def _composed() -> ComposeDraft:
    message = COMPOSED.key_messages[0].model_copy(deep=True)
    message.citations[0].doc_id = DOC
    message.citations[0].quote = QUOTE
    return COMPOSED.model_copy(
        update={
            "key_messages": [message],
            "slides": [_meeting_slide("s1"), _meeting_slide("s2")],
        }
    )


def _world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *answers: Any) -> World:
    w = World(tmp_path, monkeypatch, *answers)
    shutil.rmtree(w.corpus)  # a meeting-only project: no ingested papers at all
    w.judge = MeetingJudge()  # type: ignore[assignment]
    roles = {"composer": w.composer, "validation": w.judge}
    monkeypatch.setattr(
        registry_module.ModelRegistry, "provider_for", lambda self, role, **kw: roles[role]
    )
    memory = w.knowledge / "clients" / CLIENT / "memory"
    memory.mkdir(parents=True)
    (memory / f"{PROJECT}.md").write_text(
        "# Memory\n\n## Terms\n- APLD — the product; transcripts hear it as APID (run old)\n",
        encoding="utf-8",
    )
    TRANSCRIPT.save(w.runs / RUN / "meeting")
    return w


def _source(w: World, *extra: str):  # type: ignore[no-untyped-def]
    return w.run("meeting", "source", RUN, *extra, *w.roots)


def _through_clarify(w: World, *extra: str) -> None:
    result = _source(w)
    assert result.exit_code == 0, result.output
    result = w.run(
        "clarify", RUN, "--client", CLIENT, "--project", PROJECT,
        "--prompt", "Turn the meeting into a deck.", *extra, *w.data_roots,
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    result = w.run("answer", RUN, "--accept-all", *w.roots)
    assert result.exit_code == 0, result.output


def test_meeting_source_writes_the_document_and_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(tmp_path, monkeypatch)
    result = _source(w)
    assert result.exit_code == 0, result.output
    assert "Citable turns: 3" in result.output and "Paper check: off" in result.output
    assert "pilot" not in result.output  # transcript text is never printed
    run = w.runs / RUN
    assert DocumentStore(run / "source").get(DOC).page_count == 3
    settings = json.loads((run / "meeting" / "settings.json").read_text())
    assert settings["doc_id"] == DOC and settings["check_papers"] is False

    assert _source(w, "--with-papers").exit_code == 0
    assert json.loads((run / "meeting" / "settings.json").read_text())["check_papers"] is True


def test_meeting_source_keeps_the_audio_details_of_an_older_settings_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(tmp_path, monkeypatch)
    old = {"audio_name": "board.m4a", "audio_sha256": "ab" * 32, "speakers": True,
           "num_speakers": 2, "client": CLIENT, "project": PROJECT}  # fmt: skip
    path = w.runs / RUN / "meeting" / "settings.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    assert _source(w).exit_code == 0
    settings = json.loads(path.read_text())
    assert settings["audio_name"] == "board.m4a" and settings["speakers"] is True
    assert settings["doc_id"] == DOC


def test_meeting_source_needs_a_run_with_a_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(tmp_path, monkeypatch)
    assert w.run("meeting", "source", "ghost", *w.roots).exit_code == 1
    (w.runs / RUN / "meeting" / "transcript.json").unlink()
    result = _source(w)
    assert result.exit_code == 1 and "no transcript" in result.output


def test_clarify_draft_validate_a_meeting_without_any_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(tmp_path, monkeypatch, CLARIFIED, _composed())
    _through_clarify(w, "--provenance", "strict")
    assert "pilot goes live" in w.composer.prompts[0]  # clarify saw the whole transcript

    result = w.run("draft", RUN, *w.data_roots)
    assert result.exit_code == 0, result.output
    prompt = w.composer.prompts[1]
    assert "What was said in the meeting" in prompt and QUOTE in prompt
    deck = Orchestrator(RUN, runs_root=w.runs).ir.load()
    cited = [c for site in deck.claim_sites() for c in site.claim.citations]
    assert cited and all(c.source_class == "transcript" for c in cited)
    assert not w.corpus.exists()

    result = w.run("validate", RUN, *w.data_roots)
    assert result.exit_code == 0, result.output
    assert "0 blocking" in result.output and "supported:" in result.output

    # the engagement's Terms reached the validator, as context, without their run tag
    assert "Engagement terms" in w.judge.prompts[0]  # type: ignore[attr-defined]
    assert "APLD" in w.judge.prompts[0] and "(run old)" not in w.judge.prompts[0]  # type: ignore[attr-defined]
    snapshot = json.loads((w.runs / RUN / "validation-terms.json").read_text())
    assert snapshot == {"terms": ["APLD — the product; transcripts hear it as APID"]}

    hashes = run_source_hashes(w.runs / RUN)
    assert {"meeting/transcript.json", "meeting/settings.json", "meeting/segments.json"} <= set(
        hashes
    )
    assert DOC in hashes and "validation-terms" in hashes

    result = w.run("gate2", RUN, *w.roots)
    assert (
        "from the meeting, 00:12" in result.output or "from the meeting, 00:31" in result.output
    )


def test_a_stale_terms_snapshot_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(tmp_path, monkeypatch, CLARIFIED, _composed())
    _through_clarify(w, "--provenance", "strict")
    assert w.run("draft", RUN, *w.data_roots).exit_code == 0
    (w.knowledge / "clients" / CLIENT / "memory" / f"{PROJECT}.md").write_text("", "utf-8")
    stale = w.runs / RUN / "validation-terms.json"
    stale.write_text('{"terms": ["old"]}', encoding="utf-8")
    assert w.run("validate", RUN, *w.data_roots).exit_code == 0
    assert not stale.exists()
    assert "Engagement terms" not in w.judge.prompts[0]  # type: ignore[attr-defined]


def test_normal_mode_adds_the_conversation_but_never_indexes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(tmp_path, monkeypatch, CLARIFIED, _composed())
    _through_clarify(w)  # the project default is normal
    result = w.run("draft", RUN, *w.data_roots)
    assert result.exit_code == 0, result.output
    assert not w.corpus.exists()  # the paper check is off: the corpus is never opened
    assert (w.runs / RUN / "source" / f"conversation--{RUN}.json").exists()
    assert w.run("validate", RUN, *w.data_roots).exit_code == 0


def test_validate_exits_2_when_the_transcript_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _world(tmp_path, monkeypatch, CLARIFIED, _composed())
    _through_clarify(w, "--provenance", "strict")
    assert w.run("draft", RUN, *w.data_roots).exit_code == 0
    (w.runs / RUN / "source" / f"{DOC}.json").unlink()
    (w.runs / RUN / "meeting" / "transcript.json").unlink()
    result = w.run("validate", RUN, *w.data_roots)
    assert result.exit_code == 2 and "meeting transcript is missing" in result.output
