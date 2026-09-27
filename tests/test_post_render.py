"""The post-render audit (task 3b.8) and rendered-text extraction. SCAFFOLD (Opus): Sonnet
fills bodies, deletes every `@_SCAFFOLD` and `_SCAFFOLD`. Strict xfail.

Most tests render a clean deck, then tamper with the saved PPTX's XML directly — simulating a
pipeline stage that rewrote content — and assert the audit catches it. Tampering after render
is the honest test: it does not depend on a renderer bug existing.
"""

from __future__ import annotations

import pytest

_SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


@_SCAFFOLD
def test_a_clean_render_passes() -> None:
    """`post_render_audit(deck, rendered)` passes with no findings and a passing A2 report."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_number_changed_after_render_is_caught_by_a2() -> None:
    """Edit the slide XML so "40%" reads "45%". The numeric report blocks."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_word_changed_after_render_is_caught_with_no_number_involved() -> None:
    """Edit "reduces" to "eliminates" in a claim. A2 passes (no numeral changed); the report
    has a "claim altered in render" finding naming both sentences — the check A2 cannot do."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_chart_value_changed_in_the_chart_xml_is_caught() -> None:
    """Edit one `c:v` in the chart part's numCache. Extraction reads it and A2 blocks."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_notes_claim_changed_after_render_is_caught() -> None:
    """Edit a notes-page claim; a "claim altered in render" finding for that slide."""
    raise NotImplementedError


@_SCAFFOLD
@pytest.mark.parametrize("tamper", ["delete a slide", "duplicate a slide"])
def test_slide_set_changes_are_caught(tamper: str) -> None:
    """A deleted slide gives "slide missing from render"; a duplicated slide's repeated tag
    raises `ExtractionError` — text that cannot be attributed cannot be audited."""
    raise NotImplementedError


@_SCAFFOLD
def test_an_untagged_slide_cannot_be_audited() -> None:
    """Clear one slide's `cSld/@name`: `post_render_audit` raises `ExtractionError`."""
    raise NotImplementedError


@_SCAFFOLD
def test_an_image_part_in_a_deck_without_figures_is_flagged() -> None:
    """Add a `ppt/media/image1.png` part: an "image part without a figure" finding."""
    raise NotImplementedError


@_SCAFFOLD
def test_disabling_claim_survival_lets_the_word_change_through() -> None:
    """Monkeypatch the survival comparison to always match; the "reduces" → "eliminates"
    tamper then passes. Proves the green above comes from the check."""
    raise NotImplementedError
