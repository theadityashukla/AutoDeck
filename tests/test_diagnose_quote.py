"""`diagnose_quote`: a quote found nowhere is a splice when two passages each supply a part."""

from __future__ import annotations

from autodeck.ingest.provenance import diagnose_quote

FIRST = (
    "Oral semaglutide 14 mg reduced HbA1c by 1.3 percentage points compared with "
    "placebo at week 26 in the pooled analysis."
)
SECOND = (
    "Gastrointestinal adverse events were the most common reason for treatment "
    "discontinuation across all of the trials."
)
UNRELATED = "The manufacturing process uses a proprietary absorption enhancer in the tablet."


def test_two_passages_joined_are_a_splice() -> None:
    quote = (
        "Oral semaglutide 14 mg reduced HbA1c by 1.3 percentage points compared with "
        "placebo at week 26 in the pooled analysis. Gastrointestinal adverse events were "
        "the most common reason for treatment discontinuation"
    )
    result = diagnose_quote(quote, [UNRELATED, FIRST, SECOND])
    assert result["splice"] is True
    assert {part["passage"] for part in result["parts"]} == {1, 2}


def test_a_quote_one_passage_accounts_for_is_not_a_splice() -> None:
    result = diagnose_quote(FIRST[:-1] + " overall.", [FIRST, SECOND])
    assert result["splice"] is False


def test_a_quote_from_nowhere_is_not_a_splice() -> None:
    result = diagnose_quote(
        "Patients overwhelmingly preferred the tablet to weekly injections in every trial.",
        [FIRST, SECOND, UNRELATED],
    )
    assert result["splice"] is False
    assert result["best_coverage"] < 0.85
