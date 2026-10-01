"""Header horizontal flow, 3b.9 additions: repeated syntax and storyline order.

Both are advisory (`FlowFinding`), like everything in `flow.py` — they never block a build.
Build decks in the style of `tests/test_headers.py`.
"""

from __future__ import annotations

import pytest

SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


@SCAFFOLD
def test_three_headers_sharing_an_opening_are_flagged_once_two_are_not() -> None:
    """ "Costs fall…", "Costs rise…" → nothing; add "Costs stabilise…" → exactly one
    finding, on the third slide, naming all three slide ids and the opening "costs …"
    (first two words). Punctuation and case differences do not split a group."""
    raise NotImplementedError


@SCAFFOLD
def test_one_word_and_empty_headers_are_not_counted_as_syntax() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_slides_visiting_key_messages_out_of_order_are_flagged() -> None:
    """Brief messages m1, m2, m3; slides serve m1, m3, m2 → one finding on the m2 slide,
    phrased as a question, naming m2 (position 2) and m3 (position 3). Order m1, m2, m3 →
    none. m1, m3, m1, m3 → one finding (the second m1)."""
    raise NotImplementedError


@SCAFFOLD
def test_slides_without_messages_neither_advance_nor_break_the_order() -> None:
    """A title, agenda and divider with no `message_ids` interleaved anywhere → no
    storyline finding attributable to them."""
    raise NotImplementedError


@SCAFFOLD
def test_a_message_id_missing_from_the_brief_is_flagged() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_without_a_brief_no_storyline_findings_and_existing_behaviour_is_unchanged() -> None:
    """`flow_report(deck, tokens, profile)` with no brief → same lines and findings as before
    3b.9 apart from repeated-opening findings (compare against a deck with distinct
    openings, where the output must be identical to the pre-3b.9 report)."""
    raise NotImplementedError


@SCAFFOLD
def test_the_content_command_passes_the_brief() -> None:
    """`autodeck content`'s printed flow report includes a storyline finding for an
    out-of-order deck — i.e. cli.py passes `brief=brief_doc`. Drive it the way
    `tests/test_owner_run.py` drives the CLI."""
    raise NotImplementedError
