"""B86: grounded, not copied. In a `normal` deck (and in meeting notes) the writer may point
at a passage instead of copying it exactly, and may round a cited figure for readability.
The citation always stores the source's exact words (A1); a `strict` deck keeps the exact
rules for both.
"""

from __future__ import annotations

from pathlib import Path

from autodeck.audit.numeric_linter import LintScope, lint_scopes
from autodeck.ingest.provenance import (
    NORMAL_SNAP_MIN_COVERAGE,
    SNAP_MIN_COVERAGE,
    snap_span,
)
from autodeck.ir.models import Citation
from tests.test_notes_workspace import CiteDraft, NoteItemDraft, shown

PASSAGE = (
    "In the twelve-store pilot, the new replenishment model reduced out-of-stock events "
    "by 33.4% over eight weeks compared with the control stores."
)
LOOSE = "the replenishment model cut stockouts 33.4% over eight weeks against control"


def cite(quote: str) -> Citation:
    return Citation.for_quote(
        doc_id="pilot2026", page=3, bbox=(0.0, 0.0, 1.0, 1.0), quote=quote,
        retrieved_by="writer",
    )  # fmt: skip


# -- pointing, not copying --------------------------------------------------------------


def test_a_loose_quote_points_at_its_passage_only_at_the_normal_bar() -> None:
    assert snap_span(PASSAGE, LOOSE, min_coverage=SNAP_MIN_COVERAGE) is None
    found = snap_span(PASSAGE, LOOSE, min_coverage=NORMAL_SNAP_MIN_COVERAGE)
    assert found is not None
    (start, end), coverage = found
    assert NORMAL_SNAP_MIN_COVERAGE <= coverage < SNAP_MIN_COVERAGE
    # The stored words are the source's, never the writer's version.
    assert PASSAGE[start:end] in PASSAGE and "cut" not in PASSAGE[start:end]


def test_an_unrelated_sentence_still_points_nowhere() -> None:
    assert snap_span(PASSAGE, "customer satisfaction rose in every region last year",
                     min_coverage=NORMAL_SNAP_MIN_COVERAGE) is None  # fmt: skip


def test_notes_resolve_a_close_quote_to_the_turns_exact_words(tmp_path: Path) -> None:
    ws = shown(tmp_path)
    turn = ws.page_text(2)
    close = turn.replace("the", "a", 1) if "the" in turn else turn[:-1]
    item_id = ws.add_item(
        "Decisions", NoteItemDraft(text="x", cites=[CiteDraft(page=2, quote=close)])
    )
    [citation] = ws.find(item_id).citations
    assert citation.quote in turn


# -- rounding a cited figure --------------------------------------------------------------


def _lint(text: str, quote: str, *, rounding: bool):  # type: ignore[no-untyped-def]
    scope = LintScope(location="slide s1 block b1", text=text, citations=(cite(quote),))
    return lint_scopes([scope], rounding=rounding)


def _blocking(report) -> list:  # type: ignore[no-untyped-def]
    return [f for f in report.findings if f.severity == "blocking"]


def test_normal_mode_accepts_a_readable_rounding_and_reports_it() -> None:
    report = _lint("Out-of-stocks fell by about 33%.", PASSAGE, rounding=True)
    assert not _blocking(report)
    assert any(m.via_rounding for m in report.matches)


def test_strict_mode_keeps_the_exact_figure() -> None:
    assert _blocking(_lint("Out-of-stocks fell by about 33%.", PASSAGE, rounding=False))


def test_rounding_too_far_or_into_another_unit_still_fails() -> None:
    assert _blocking(_lint("Out-of-stocks fell by 30%.", PASSAGE, rounding=True))  # 10.2% off
    assert _blocking(_lint("Out-of-stocks fell by 33 ms.", PASSAGE, rounding=True))
    assert _blocking(
        _lint("Out-of-stocks fell by 34%.", PASSAGE, rounding=True)
    )  # not a rounding


def test_counts_round_to_significant_figures() -> None:
    quote = "The pilot covered 1,212 stores across four regions."
    assert not _blocking(_lint("About 1,200 stores took part.", quote, rounding=True))
    assert _blocking(_lint("About 1,200 stores took part.", quote, rounding=False))


def test_the_validator_is_told_the_decks_mode() -> None:
    from autodeck.agents.validation import _render_batch_prompt

    assert "NORMAL mode" in _render_batch_prompt([], {}, (), "normal")
    assert "STRICT mode" in _render_batch_prompt([], {}, (), "strict")
    assert "mode" not in _render_batch_prompt([], {}, ()).split("Judge")[0]
