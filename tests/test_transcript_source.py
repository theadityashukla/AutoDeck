"""B78: a meeting transcript as a run-local source document (plan step 9)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from autodeck.ingest.document_store import DocumentStore, IngestError
from autodeck.ingest.multi_store import MultiStore
from autodeck.ingest.transcript_source import (
    PAGE_BOX,
    TITLE,
    MeetingSettingsError,
    ingest_transcript,
    load_meeting_settings,
    meeting_times,
    normalise,
    save_meeting_settings,
    segments_sidecar,
    transcript_doc_id,
    transcript_document,
)
from autodeck.ir.models import TRANSCRIPT_DOC_PREFIX, Block, Citation, Claim, Deck
from autodeck.meeting.schema import AudioInfo, Segment, Transcript, TranscriptModels

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ir.json"


def make_transcript(
    *segments: tuple[float, float, str, str | None], audio_name: str = "board.m4a"
) -> Transcript:
    return Transcript(
        audio=AudioInfo(name=audio_name, sha256="ab" * 32, duration_s=900.0),
        models=TranscriptModels(asr="a", vad="v", diarization=None, sherpa_onnx="1"),
        segments=[Segment(start=s, end=e, text=t, speaker=who) for s, e, t, who in segments],
        speakers_labelled=any(who for *_, who in segments),
        timings={},
    )


TRANSCRIPT = make_transcript(
    (12.5, 20.0, "Good morning everyone.", "S1"),
    (31.0, 39.0, "The pilot goes live  in the first\nweek of February.", "S2"),
    (50.0, 52.0, "   ", None),
    (777.7, 790.0, "Shikha will run the walkthrough.", "S1"),
)


def test_doc_id_uses_the_prefix_and_a_slug() -> None:
    assert transcript_doc_id("Board Call #3") == f"{TRANSCRIPT_DOC_PREFIX}board-call-3"
    with pytest.raises(IngestError):
        transcript_doc_id("###")


def test_one_page_and_one_text_element_per_kept_segment() -> None:
    doc = transcript_document(TRANSCRIPT, "r1")
    assert doc.doc_id == "transcript--r1" and doc.title == TITLE
    assert doc.source_path == "meeting" and doc.page_count == 3
    assert [e.element_id for e in doc.elements] == ["t1-e1", "t2-e1", "t3-e1"]
    assert [e.page for e in doc.elements] == [1, 2, 3]
    assert [e.reading_order for e in doc.elements] == [0, 1, 2]
    assert all(e.kind == "text" and e.bbox == PAGE_BOX and e.is_citable for e in doc.elements)
    assert doc.elements[1].text == "The pilot goes live in the first week of February."


def test_sidecar_page_numbers_match_the_document_after_empty_segments() -> None:
    sidecar = segments_sidecar(TRANSCRIPT, "r1")
    assert sidecar["doc_id"] == "transcript--r1"
    assert sorted(sidecar["pages"]) == ["1", "2", "3"]
    assert sidecar["pages"]["3"] == {"start": 777.7, "end": 790.0, "speaker": "S1"}
    doc = transcript_document(TRANSCRIPT, "r1")
    assert doc.elements[2].text == "Shikha will run the walkthrough."


def test_the_document_carries_no_times_speakers_or_audio_details() -> None:
    text = transcript_document(TRANSCRIPT, "r1").model_dump_json()
    for leaked in ("12.5", "31.0", "777.7", "S1", "S2", "board.m4a", "abab"):
        assert leaked not in text


def test_same_words_give_a_byte_identical_document() -> None:
    first = transcript_document(TRANSCRIPT, "r1").model_dump_json()
    assert transcript_document(TRANSCRIPT, "r1").model_dump_json() == first
    shifted = make_transcript(
        (99.0, 120.0, "Good morning everyone.", None),
        (131.0, 139.0, "The pilot goes live in the first week of February.", "S9"),
        (777.7, 790.0, "Shikha will run the walkthrough.", None),
        audio_name="other.wav",
    )
    assert transcript_document(shifted, "r1").model_dump_json() == first


def test_ingest_writes_the_source_document_and_the_times_sidecar(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"
    TRANSCRIPT.save(run / "meeting")
    assert ingest_transcript(run, "r1") == "transcript--r1"

    stored = DocumentStore(run / "source").get("transcript--r1")
    assert stored.page_count == 3
    raw = (run / "meeting" / "segments.json").read_text(encoding="utf-8")
    assert raw.endswith("\n") and json.loads(raw)["pages"]["2"]["start"] == 31.0
    assert not list((run / "meeting").glob("*.tmp"))
    assert meeting_times(run) == {"transcript--r1": {1: 12.5, 2: 31.0, 3: 777.7}}
    # re-ingesting is deterministic
    before = (run / "source" / "transcript--r1.json").read_bytes()
    ingest_transcript(run, "r1")
    assert (run / "source" / "transcript--r1.json").read_bytes() == before


def test_ingest_returns_none_when_nothing_is_citable(tmp_path: Path) -> None:
    run = tmp_path / "r1"
    make_transcript((0.0, 1.0, "  ", None)).save(run / "meeting")
    assert ingest_transcript(run, "r1") is None
    assert not (run / "source").exists()


def test_ingest_errors_never_carry_transcript_text(tmp_path: Path) -> None:
    run = tmp_path / "r1"
    with pytest.raises(IngestError, match="no transcript"):
        ingest_transcript(run, "r1")
    (run / "meeting").mkdir(parents=True)
    (run / "meeting" / "transcript.json").write_text('{"secret": "quokka"}', encoding="utf-8")
    with pytest.raises(IngestError) as caught:
        ingest_transcript(run, "r1")
    assert "quokka" not in str(caught.value)


def test_meeting_times_is_empty_when_absent_or_unreadable(tmp_path: Path) -> None:
    assert meeting_times(tmp_path) == {}
    (tmp_path / "meeting").mkdir()
    (tmp_path / "meeting" / "segments.json").write_text("{nope", encoding="utf-8")
    assert meeting_times(tmp_path) == {}


def test_settings_round_trip_and_defaults(tmp_path: Path) -> None:
    raw = {
        "audio_name": "board.m4a",
        "audio_sha256": "ab" * 32,
        "speakers": True,
        "num_speakers": 2,
        "client": "acme",
        "project": "proj",
        "doc_id": "transcript--r1",
        "surprise": "dropped",
    }
    save_meeting_settings(tmp_path, raw)
    loaded = load_meeting_settings(tmp_path)
    assert loaded is not None and "surprise" not in loaded
    assert loaded["check_papers"] is False  # B49: the paper check is off unless asked for
    assert loaded["doc_id"] == "transcript--r1" and loaded["num_speakers"] == 2
    assert load_meeting_settings(tmp_path / "elsewhere") is None


@pytest.mark.parametrize(
    "bad",
    [{}, {"doc_id": "paper-1"}, {"doc_id": "transcript--r1", "num_speakers": "two"}],
)
def test_settings_refuse_bad_values(bad: dict) -> None:
    with pytest.raises(MeetingSettingsError):
        normalise(bad)


def test_unreadable_settings_raise_a_clear_error(tmp_path: Path) -> None:
    (tmp_path / "meeting").mkdir()
    (tmp_path / "meeting" / "settings.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(MeetingSettingsError, match="cannot be read"):
        load_meeting_settings(tmp_path)
    # the pre-step-9 file (no doc_id) points at the fix
    (tmp_path / "meeting" / "settings.json").write_text('{"client": "acme"}', encoding="utf-8")
    with pytest.raises(MeetingSettingsError, match="meeting source"):
        load_meeting_settings(tmp_path)


def test_a_citation_into_the_transcript_resolves_through_a_multistore(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"
    TRANSCRIPT.save(run / "meeting")
    ingest_transcript(run, "r1")
    store = MultiStore(run / "source", None)
    cite = store.resolve_quote("transcript--r1", "pilot goes live in the first week")
    assert cite.source_class == "transcript"
    assert cite.page == 2 and cite.bbox == PAGE_BOX


def _deck_with_citation(doc_id: str, provenance: str) -> Deck:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["provenance"] = provenance
    cite = Citation.for_quote(
        doc_id=doc_id, page=1, bbox=(0, 0, 1, 1), quote="a real sentence", retrieved_by="writer"
    )
    block = Block(
        id="bx", kind="claim", slot="points", claim=Claim(text="said", citations=[cite])
    )
    raw["slides"][0]["blocks"].append(block.model_dump(mode="json"))
    return Deck.model_validate(raw)


def test_a_strict_deck_may_cite_the_transcript_but_not_the_conversation() -> None:
    _deck_with_citation("transcript--r1", "strict")
    with pytest.raises(ValidationError):
        _deck_with_citation("conversation--r1", "strict")
