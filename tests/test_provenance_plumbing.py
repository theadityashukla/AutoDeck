"""B55 plumbing: project settings, run snapshot, conversation source, evidence section, blot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodeck.agents.evidence_pack import (
    EvidencePack,
    conversation_section,
    deck_spans,
    document_spans,
    with_conversation,
)
from autodeck.design.headers.profile import HeaderStyleProfile, guidance_for
from autodeck.ingest.conversation_source import (
    conversation_doc_id,
    conversation_document,
    ingest_conversation,
    person_messages,
)
from autodeck.ingest.document_store import DocumentStore
from autodeck.ingest.multi_store import MultiStore
from autodeck.knowledge.loader import (
    KnowledgeError,
    KnowledgeLoader,
    ProjectSettings,
    load_project_settings,
    save_project_settings,
)
from autodeck.pipeline.clarify_state import new_clarify, record_answers, save_clarify
from autodeck.pipeline.provenance import (
    ProvenanceModeError,
    load_mode,
    resolve_mode,
    snapshot_mode,
)

# -- project settings ---------------------------------------------------------


def _project(root: Path) -> Path:
    p = root / "projects" / "demo"
    p.mkdir(parents=True)
    (p / "project.md").write_text("# Demo\n")
    (p / "claims.md").write_text("")
    return p


def test_settings_default_when_missing(tmp_path: Path) -> None:
    _project(tmp_path)
    assert load_project_settings(tmp_path, "demo").provenance == "normal"
    assert KnowledgeLoader(tmp_path).load_project("demo").settings.provenance == "normal"


def test_settings_roundtrip_and_empty_key(tmp_path: Path) -> None:
    p = _project(tmp_path)
    save_project_settings(tmp_path, "demo", ProjectSettings(provenance="strict"))
    assert KnowledgeLoader(tmp_path).load_project("demo").settings.provenance == "strict"
    (p / "settings.yaml").write_text("{}\n")
    assert load_project_settings(tmp_path, "demo").provenance == "normal"


@pytest.mark.parametrize("text", ["provenance: loose", "nope: 1", "- a", "a: [b"])
def test_settings_malformed_is_loud(tmp_path: Path, text: str) -> None:
    p = _project(tmp_path)
    (p / "settings.yaml").write_text(text)
    with pytest.raises(KnowledgeError, match=r"settings\.yaml"):
        KnowledgeLoader(tmp_path).load_project("demo")


# -- run snapshot ---------------------------------------------------------------


def test_snapshot_is_fixed_once_set(tmp_path: Path) -> None:
    run = tmp_path / "run1"
    assert load_mode(run) == "strict"  # pre-B55 runs fail safe
    assert snapshot_mode(run, "normal") == "normal"
    assert snapshot_mode(run, "strict") == "normal"
    assert json.loads((run / "provenance.json").read_text()) == {"provenance": "normal"}
    assert load_mode(run) == "normal"


def test_resolve_mode_override_only_before_snapshot(tmp_path: Path) -> None:
    run = tmp_path / "run1"
    assert resolve_mode(run, ProjectSettings(provenance="normal"), "strict") == "strict"
    assert resolve_mode(run, ProjectSettings(provenance="normal"), None) == "strict"
    assert resolve_mode(run, ProjectSettings(), "strict") == "strict"
    with pytest.raises(ProvenanceModeError, match="cannot be changed"):
        resolve_mode(run, ProjectSettings(), "normal")


def test_resolve_mode_uses_project_setting(tmp_path: Path) -> None:
    assert resolve_mode(tmp_path / "r", ProjectSettings(provenance="strict")) == "strict"


# -- clarify sources --------------------------------------------------------------


def _clarify(run: Path) -> dict:
    data = new_clarify(
        prompt="Build a deck on our new platform.\n\nKeep it short.",
        client="c",
        project="p",
        assumptions=[],
        questions=[
            {"id": "q1", "question": "Audience?", "suggested_answer": "Executives"},
            {"id": "q2", "question": "Length?", "suggested_answer": "10 slides"},
            {"id": "q3", "question": "Tone?", "suggested_answer": "Formal"},
        ],
    )
    save_clarify(run, data)
    return data


def test_record_answers_tracks_sources(tmp_path: Path) -> None:
    data = _clarify(tmp_path)
    record_answers(
        data, answers={"q1": "Our board", "q2": "10 slides"}, accepted={"q3"}, accept_all=True
    )
    assert data["answer_sources"] == {"q1": "typed", "q2": "accepted", "q3": "accepted"}
    assert data["typed_order"] == ["q1"]


def test_accept_all_marks_fills_accepted(tmp_path: Path) -> None:
    data = _clarify(tmp_path)
    record_answers(data, accept_all=True)
    assert set(data["answer_sources"].values()) == {"accepted"}


# -- conversation source ----------------------------------------------------------


def _run_with_conversation(run: Path) -> None:
    data = _clarify(run)
    record_answers(
        data,
        answers={"q1": "The board of Acme", "q2": "10 slides"},
        accept_all=True,
        corrections=["Tone: casual"],
    )
    save_clarify(run, data)
    logs = run / "logs"
    logs.mkdir()
    (logs / "planner.jsonl").write_text(
        json.dumps({"role": "human", "text": "Add an architecture slide", "at": "2026-01-02"})
        + "\n"
        + json.dumps({"role": "planner", "text": "Sure thing", "at": "2026-01-02"})
        + "\n"
    )
    (run / "revisions.jsonl").write_text(
        json.dumps({"instruction": "Shorten slide 2", "reply": "Done", "at": "2026-01-03"})
        + "\n"
    )


def test_person_messages_order_and_exclusions(tmp_path: Path) -> None:
    _run_with_conversation(tmp_path)
    assert person_messages(tmp_path) == [
        "Build a deck on our new platform.\n\nKeep it short.",
        "The board of Acme",
        "Tone: casual",
        "Add an architecture slide",
        "Shorten slide 2",
    ]
    text = "\n".join(person_messages(tmp_path))
    assert "Executives" not in text and "Formal" not in text and "Sure thing" not in text


def test_no_messages_means_no_document(tmp_path: Path) -> None:
    assert person_messages(tmp_path) == []
    assert ingest_conversation(tmp_path, "run-1") is None


def test_document_shape_and_page_stability(tmp_path: Path) -> None:
    _run_with_conversation(tmp_path)
    before = conversation_document(tmp_path, "Run 1")
    assert before.doc_id == conversation_doc_id("Run 1") == "conversation--run-1"
    assert before.page_count == 5
    assert [e.element_id for e in before.elements if e.page == 1] == ["m1-e1", "m1-e2"]
    assert all(e.is_citable for e in before.elements)
    assert conversation_document(tmp_path, "Run 1") == before  # deterministic
    with (tmp_path / "revisions.jsonl").open("a") as fh:
        fh.write(json.dumps({"instruction": "One more", "at": "2026-02-01"}) + "\n")
    after = conversation_document(tmp_path, "Run 1")
    assert after.page_count == 6
    assert [e for e in after.elements if e.page <= 5] == before.elements


def test_quote_resolves_as_conversation_citation(tmp_path: Path) -> None:
    _run_with_conversation(tmp_path)
    doc_id = ingest_conversation(tmp_path, "run-1")
    assert doc_id == "conversation--run-1"
    store = MultiStore(tmp_path / "source")
    citation = store.resolve_quote(doc_id, "architecture slide")
    assert citation.source_class == "conversation"
    assert citation.page == 4
    assert citation.quote == "architecture slide"
    assert DocumentStore(tmp_path / "source").get(doc_id).page_count == 5


# -- evidence pack ----------------------------------------------------------------


def _pack() -> EvidencePack:
    return EvidencePack(
        claims=(), spans=(), text="CORPUS TEXT", queries=(), dropped=0, approx_tokens=2
    )


def test_with_conversation_modes(tmp_path: Path) -> None:
    _run_with_conversation(tmp_path)
    doc = conversation_document(tmp_path, "run-1")
    pack = _pack()
    assert with_conversation(pack, doc, "strict") is pack
    assert with_conversation(pack, None, "normal") is pack
    out = with_conversation(pack, doc, "normal")
    assert out.text.startswith(
        '# What you told us (citable as "from you"; doc id conversation--run-1)'
    )
    assert out.text.endswith("CORPUS TEXT")
    assert "[corpus · conversation--run-1 p.4 · citable] Add an architecture slide" in out.text
    assert len(out.spans) == len(doc.elements)
    assert out.approx_tokens == len(out.text) // 4
    assert deck_spans is document_spans
    assert conversation_section(()) == ""


# -- blot header --------------------------------------------------------------------


def test_blot_is_default_header_style() -> None:
    profile = HeaderStyleProfile()
    assert (profile.style, profile.max_words) == ("blot", 18)
    assert profile.sentence_case and not profile.terminal_punctuation
    assert "bottom line first" in guidance_for("blot")
