"""B78/B79 wired through: audit labels, flags, validation terms, planning and the pack."""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.agents.evidence_pack import EvidencePack, with_transcript
from autodeck.agents.validation import validate_deck
from autodeck.audit.report import build_audit_report, meeting_stamp, render
from autodeck.audit.verdicts import VerdictJudgement
from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore
from autodeck.ingest.transcript_source import (
    ingest_transcript,
    save_meeting_settings,
    transcript_document,
)
from autodeck.ir.models import Claim, Deck, Slide
from autodeck.pipeline.planning import (
    MeetingPlanning,
    PlanningSetupError,
    RedesignPlanning,
    prepare_planning,
    run_source_store,
)
from autodeck.providers.registry import default_env_name
from autodeck.render.draft import slide_flags
from autodeck.retrieval.hybrid import build_index, search
from tests.test_cli_gate2 import CLIENT, PROJECT
from tests.test_knowledge import build_knowledge
from tests.test_transcript_source import TRANSCRIPT
from tests.test_validation import PROMPT, Scripted, claim_block, deck_with

QUOTE = "The pilot goes live in the first week of February."


def _meeting_deck(tmp_path: Path, *, page_quote: str = QUOTE) -> tuple[Deck, DocumentStore]:
    run = tmp_path / "runs" / "r1"
    TRANSCRIPT.save(run / "meeting")
    ingest_transcript(run, "r1")
    store = DocumentStore(run / "source")
    cite = store.resolve_quote("transcript--r1", page_quote)
    claim = Claim(
        text="The pilot goes live in February.", citations=[cite], verdict="supported"
    )
    slide = Slide(
        id="s1",
        narrative_role="evidence",
        component="big_number",
        blocks=[claim_block("b1", claim)],
    )
    return deck_with(slide), store


# -- audit labels ----------------------------------------------------------------------


def test_audit_report_labels_a_meeting_citation_with_its_time(tmp_path: Path) -> None:
    deck, _ = _meeting_deck(tmp_path)
    times = {"transcript--r1": {1: 12.5, 2: 31.0, 3: 777.7}}
    text = render(build_audit_report(deck, brief=None, meeting_times=times))
    assert "from the meeting, 00:31 (`transcript--r1` turn 2)" in text


def test_audit_report_without_times_says_the_turn(tmp_path: Path) -> None:
    deck, _ = _meeting_deck(tmp_path)
    text = render(build_audit_report(deck, brief=None))
    assert "from the meeting, turn 2 (`transcript--r1` turn 2)" in text


def test_audit_report_switches_to_hours_after_the_first(tmp_path: Path) -> None:
    deck, _ = _meeting_deck(tmp_path)
    times = {"transcript--r1": {2: 3725.0}}
    assert "from the meeting, 1:02:05" in render(
        build_audit_report(deck, brief=None, meeting_times=times)
    )


def test_meeting_stamp_units() -> None:
    assert meeting_stamp(0) == "00:00"
    assert meeting_stamp(12.9) == "00:12"
    assert meeting_stamp(754) == "12:34"
    assert meeting_stamp(3725) == "1:02:05"
    assert meeting_stamp(-4) == "00:00"


# -- flags -----------------------------------------------------------------------------


def test_slide_flags_marks_a_slide_that_cites_the_meeting(tmp_path: Path) -> None:
    deck, _ = _meeting_deck(tmp_path)
    assert slide_flags(deck) == {"s1": "from_meeting"}


# -- validation terms ------------------------------------------------------------------


def test_the_terms_block_reaches_the_prompt_only_when_given(tmp_path: Path) -> None:
    deck, store = _meeting_deck(tmp_path)
    index = build_index(list(store.documents()), project="p")
    verdict = VerdictJudgement(verdict="supported", verdict_notes="ok", supporting_quote=QUOTE)

    plain = Scripted({"s1:b1": verdict})
    validate_deck(deck, index=index, store=store, model=plain, prompt_path=PROMPT)
    assert "Engagement terms" not in plain.prompts[0]

    given = Scripted({"s1:b1": verdict})
    validate_deck(
        deck.model_copy(deep=True),
        index=index,
        store=store,
        model=given,
        prompt_path=PROMPT,
        terms=["APLD (heard as APID)"],
    )
    assert "Engagement terms" in given.prompts[0] and "APLD (heard as APID)" in given.prompts[0]


# -- the pack --------------------------------------------------------------------------


def _pack() -> EvidencePack:
    return EvidencePack(
        claims=(),
        spans=(),
        text="# Evidence\n\nnothing",
        queries=(),
        dropped=0,
        approx_tokens=5,
    )


def test_with_transcript_leads_the_pack_and_skips_a_long_one() -> None:
    doc = transcript_document(TRANSCRIPT, "r1")
    pack = with_transcript(_pack(), doc)
    assert pack.text.startswith("# What was said in the meeting (doc id transcript--r1")
    assert [s.element_id for s in pack.spans] == ["t1-e1", "t2-e1", "t3-e1"]
    assert QUOTE in pack.text and pack.text.endswith("nothing")

    assert (
        with_transcript(_pack(), doc, max_tokens=5) == _pack()
    )  # over the cap: retrieval only
    assert with_transcript(_pack(), None) == _pack()


def test_with_transcript_does_not_repeat_spans_the_pack_has() -> None:
    from autodeck.agents.evidence_pack import document_spans

    doc = transcript_document(TRANSCRIPT, "r1")
    spans = document_spans(doc)
    pack = EvidencePack(
        claims=(), spans=spans[:1], text="x", queries=(), dropped=0, approx_tokens=1
    )
    out = with_transcript(pack, doc)
    keys = [(s.doc_id, s.element_id) for s in out.spans]
    assert len(keys) == len(set(keys)) == 3


# -- planning --------------------------------------------------------------------------


def _meeting_run(tmp_path: Path, *, check_papers: bool = False, corpus: bool = False):  # type: ignore[no-untyped-def]
    knowledge = build_knowledge(tmp_path)
    runs, corpus_root = tmp_path / "runs", tmp_path / "corpus"
    run = runs / "r1"
    TRANSCRIPT.save(run / "meeting")
    doc_id = ingest_transcript(run, "r1")
    save_meeting_settings(
        run,
        {"client": CLIENT, "project": PROJECT, "doc_id": doc_id, "check_papers": check_papers},
    )
    if corpus:
        DocumentStore(corpus_root / PROJECT).add(
            Document(
                doc_id="paper-1",
                source_path="paper-1.pdf",
                page_count=1,
                elements=[
                    DocumentElement(
                        element_id="e1",
                        doc_id="paper-1",
                        kind="text",
                        page=1,
                        bbox=(0.0, 0.0, 1.0, 1.0),
                        reading_order=0,
                        text="Attention kernels cut latency.",
                    )
                ],
            )
        )
    return dict(
        client=CLIENT,
        project=PROJECT,
        env=default_env_name(),
        knowledge_root=knowledge,
        corpus_root=corpus_root,
        runs_root=runs,
    )


def test_a_meeting_run_plans_without_any_corpus(tmp_path: Path) -> None:
    kwargs = _meeting_run(tmp_path)
    planning = prepare_planning("r1", **kwargs)
    assert isinstance(planning, MeetingPlanning) and not isinstance(planning, RedesignPlanning)
    assert planning.claims == []
    assert planning.transcript_document.doc_id == "transcript--r1"
    assert planning.store.get("transcript--r1").page_count == 3
    hits = search(planning.index, "pilot goes live February", limit=3)  # type: ignore[arg-type]
    assert any(h.doc_id == "transcript--r1" for h in hits)
    assert not (tmp_path / "corpus").exists()  # the corpus folder is never touched


def test_the_conversation_is_never_indexed(tmp_path: Path) -> None:
    kwargs = _meeting_run(tmp_path)
    DocumentStore(tmp_path / "runs" / "r1" / "source").add(
        Document(
            doc_id="conversation--r1",
            source_path="conversation",
            page_count=1,
            elements=[
                DocumentElement(
                    element_id="m1-e1",
                    doc_id="conversation--r1",
                    kind="text",
                    page=1,
                    bbox=(0.0, 0.0, 960.0, 540.0),
                    reading_order=0,
                    text="zanzibar pilot goes live",
                )
            ],
        )
    )
    planning = prepare_planning("r1", **kwargs)
    hits = search(planning.index, "zanzibar pilot goes live", limit=10)  # type: ignore[arg-type]
    assert hits and all(h.doc_id != "conversation--r1" for h in hits)
    assert "conversation--r1" in planning.store.doc_ids()  # but it still resolves


def test_the_paper_check_needs_a_corpus(tmp_path: Path) -> None:
    kwargs = _meeting_run(tmp_path, check_papers=True)
    with pytest.raises(PlanningSetupError, match="paper check is on") as caught:
        prepare_planning("r1", **kwargs)
    assert caught.value.exit_code == 2


def test_the_paper_check_brings_papers_and_claims(tmp_path: Path) -> None:
    kwargs = _meeting_run(tmp_path, check_papers=True, corpus=True)
    planning = prepare_planning("r1", **kwargs)
    assert isinstance(planning, MeetingPlanning)
    assert {"paper-1", "transcript--r1"} <= set(planning.store.doc_ids())
    assert planning.claims  # the project's claims.md


def test_a_missing_transcript_document_is_re_ingested(tmp_path: Path) -> None:
    kwargs = _meeting_run(tmp_path)
    (tmp_path / "runs" / "r1" / "source" / "transcript--r1.json").unlink()
    planning = prepare_planning("r1", **kwargs)
    assert planning.store.get("transcript--r1").page_count == 3


def test_a_missing_transcript_is_exit_2(tmp_path: Path) -> None:
    kwargs = _meeting_run(tmp_path)
    (tmp_path / "runs" / "r1" / "source" / "transcript--r1.json").unlink()
    (tmp_path / "runs" / "r1" / "meeting" / "transcript.json").unlink()
    with pytest.raises(PlanningSetupError, match="meeting source") as caught:
        prepare_planning("r1", **kwargs)
    assert caught.value.exit_code == 2


def test_corrupt_settings_are_exit_1_and_unknown_runs_are_not_created(tmp_path: Path) -> None:
    kwargs = _meeting_run(tmp_path)
    (tmp_path / "runs" / "r1" / "meeting" / "settings.json").write_text("{", encoding="utf-8")
    with pytest.raises(PlanningSetupError) as caught:
        prepare_planning("r1", **kwargs)
    assert caught.value.exit_code == 1
    assert run_source_store_or_none(tmp_path, "ghost") is None
    assert not (tmp_path / "runs" / "ghost").exists()


def run_source_store_or_none(tmp_path: Path, run_id: str):  # type: ignore[no-untyped-def]
    return run_source_store(
        tmp_path / "runs", run_id, corpus_root=tmp_path / "corpus", project=PROJECT
    )


def test_run_source_store_for_a_meeting_run(tmp_path: Path) -> None:
    _meeting_run(tmp_path)
    store, documents = run_source_store_or_none(tmp_path, "r1")  # type: ignore[misc]
    assert [d.doc_id for d in documents] == ["transcript--r1"]
    assert store.get("transcript--r1").page_count == 3
