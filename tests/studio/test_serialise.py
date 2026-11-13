"""Canonical serialisation: one state, one text. Exact undo depends on it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from autodeck.studio.changelog import new_changelog
from autodeck.studio.models import DeckArtifact, EngagementRecord
from autodeck.studio.serialise import (
    artifact_digest,
    atomic_write_text,
    dump_artifact,
    dump_model,
    load_artifact,
    load_changelog,
    load_engagement_record,
    read_text,
    text_digest,
)
from tests.studio.helpers import CLIENT, PROJECT, T0


def test_dump_format_matches_v2_convention(base_deck: DeckArtifact) -> None:
    text = dump_artifact(base_deck)
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert (
        text
        == json.dumps(base_deck.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    )
    assert dump_model(base_deck) == text


def test_round_trip_is_byte_identical(base_deck: DeckArtifact) -> None:
    text = dump_artifact(base_deck)
    again = dump_artifact(load_artifact(text))
    assert again == text
    assert load_artifact(text) == base_deck


def test_non_ascii_is_kept_verbatim(base_deck: DeckArtifact) -> None:
    deck = base_deck.model_copy(update={"title": "Coûts — résumé"})
    assert "Coûts — résumé" in dump_artifact(deck)


def test_digest_is_sha256_of_the_canonical_text(base_deck: DeckArtifact) -> None:
    text = dump_artifact(base_deck)
    assert text_digest(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert artifact_digest(base_deck) == text_digest(text)
    changed = base_deck.model_copy(update={"title": "Other"})
    assert artifact_digest(changed) != artifact_digest(base_deck)


def test_load_rejects_invalid_text() -> None:
    with pytest.raises(ValidationError):
        load_artifact("{}")
    with pytest.raises(ValidationError):
        load_artifact("not json")


def test_other_models_round_trip(base_deck: DeckArtifact) -> None:
    record = EngagementRecord(client=CLIENT, project=PROJECT, created_at=T0)
    assert load_engagement_record(dump_model(record)) == record
    log = new_changelog("deck", artifact_digest(base_deck))
    assert load_changelog(dump_model(log)) == log


def test_atomic_write_then_read_is_exact(tmp_path: Path) -> None:
    path = tmp_path / "f.json"
    text = 'line one\r\nline two\n"é"\n'
    assert atomic_write_text(path, text) == path
    assert path.read_bytes() == text.encode("utf-8")
    assert read_text(path) == text
    atomic_write_text(path, "second\n")
    assert read_text(path) == "second\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f.json"]


def test_atomic_write_needs_an_existing_parent(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        atomic_write_text(tmp_path / "missing" / "f.json", "x")


def test_read_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_text(tmp_path / "nope.json")
