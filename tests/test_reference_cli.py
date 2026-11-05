"""`autodeck reference ingest | show | gaps` (Phase 4, tasks 4.2 and 4.8).

The commands print counts, never deck text, unless `--exemplars` asks for the exemplar
headers (A1). They refuse an unknown client and any deck outside the client's `decks/` (A4).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from autodeck.cli import app
from tests.test_reference_decks import TITLES, build_deck, make_knowledge

runner = CliRunner()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    knowledge = make_knowledge(tmp_path / "knowledge", "acme", "other")
    build_deck(knowledge / "clients" / "acme" / "decks" / "Margin Review.pptx")
    return knowledge


def run(root: Path, *args: str):  # type: ignore[no-untyped-def]
    return runner.invoke(app, ["reference", *args, "--knowledge-root", str(root)])


def assert_no_deck_text(output: str) -> None:
    for title in (*TITLES.values(), "Retail margin review", "Where we are today", "Agenda"):
        assert title not in output


def test_ingest_prints_counts_only(root: Path) -> None:
    result = run(root, "ingest", "--client", "acme")
    assert result.exit_code == 0, result.output
    assert "decks: 1  slides: 10" in result.output
    assert "content=6" in result.output and "closing=1" in result.output
    assert "style=assertion" in result.output
    assert "catalog gaps: 1" in result.output
    assert_no_deck_text(result.output)
    assert (root / "clients" / "acme" / "decks" / "profile.json").is_file()


def test_ingest_a_named_deck(root: Path) -> None:
    result = run(root, "ingest", "Margin Review.pptx", "--client", "acme")
    assert result.exit_code == 0, result.output
    assert "slides: 10" in result.output


def test_show_hides_exemplars_unless_asked(root: Path) -> None:
    run(root, "ingest", "--client", "acme")
    plain = run(root, "show", "--client", "acme")
    assert plain.exit_code == 0, plain.output
    assert "decks: 1" in plain.output and "max_words=9" in plain.output
    assert_no_deck_text(plain.output)
    asked = run(root, "show", "--client", "acme", "--exemplars")
    assert asked.exit_code == 0
    assert f"exemplar: {TITLES['content1']}" in asked.output


def test_show_without_ingest_says_so(root: Path) -> None:
    result = run(root, "show", "--client", "acme")
    assert result.exit_code == 1
    assert "reference ingest" in result.output


def test_gaps_lists_the_ranked_layouts_without_text(root: Path) -> None:
    run(root, "ingest", "--client", "acme")
    result = run(root, "gaps", "--client", "acme")
    assert result.exit_code == 0, result.output
    assert " 1. text5-" in result.output and "slides=1" in result.output
    assert "best=data_card_grid" in result.output and "margin-review#9" in result.output
    assert_no_deck_text(result.output)


def test_gaps_before_ingest_is_an_error(root: Path) -> None:
    assert run(root, "gaps", "--client", "acme").exit_code == 1


def test_an_unknown_client_is_refused(root: Path) -> None:
    for command in ("ingest", "show", "gaps"):
        result = run(root, command, "--client", "nobody")
        assert result.exit_code == 1, command
        assert "not found" in result.output
    assert run(root, "ingest", "--client", "..").exit_code == 1


def test_a_deck_outside_the_clients_decks_folder_is_refused(root: Path, tmp_path: Path) -> None:
    foreign = build_deck(root / "clients" / "other" / "decks" / "theirs.pptx")
    stray = build_deck(root / "clients" / "acme" / "stray.pptx")
    elsewhere = build_deck(tmp_path / "elsewhere.pptx")
    for deck in (foreign, stray, elsewhere):
        result = run(root, "ingest", str(deck), "--client", "acme")
        assert result.exit_code == 1, deck
    result = run(
        root,
        "ingest",
        str(root / "clients" / "acme" / "decks" / ".." / "stray.pptx"),
        "--client",
        "acme",
    )
    assert result.exit_code == 1
    assert not list((root / "clients" / "acme" / "decks").glob("*theirs*"))
