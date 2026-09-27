"""Deterministic render QA (task 3b.2). SCAFFOLD (Opus): Sonnet fills bodies and deletes every
`@_SCAFFOLD` and `_SCAFFOLD`. Strict xfail. Build fixture PPTXs directly with python-pptx
(tagging slides `autodeck:<id>`) so these tests do not depend on the renderer.
"""

from __future__ import annotations

import pytest

_SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


@_SCAFFOLD
@pytest.mark.parametrize(
    ("fg", "bg", "ratio"),
    [("000000", "FFFFFF", 21.0), ("FFFFFF", "FFFFFF", 1.0), ("777777", "FFFFFF", 4.48)],
)
def test_contrast_ratio_matches_wcag(fg: str, bg: str, ratio: float) -> None:
    """To two decimal places, and symmetric: `contrast_ratio(bg, fg)` is the same."""
    raise NotImplementedError


@_SCAFFOLD
def test_every_registered_component_preview_passes_clean() -> None:
    """Render each component's `preview.EXAMPLES` content onto a tagged slide; zero findings.
    The golden previews were judged by eye; this pins that they are arithmetically clean too."""
    raise NotImplementedError


@_SCAFFOLD
def test_two_overlapping_text_boxes_are_found() -> None:
    """Two text boxes overlapping by 20pt: one "overlap" finding naming both shapes."""
    raise NotImplementedError


@_SCAFFOLD
def test_text_over_its_own_panel_is_not_an_overlap() -> None:
    """A text box inside a filled rectangle with no text: no "overlap" finding."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_shape_outside_the_safe_area_is_found() -> None:
    """A text box 10pt past the right margin: "outside safe area", remedy `slot`."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_run_below_the_minimum_size_is_found() -> None:
    """An 8pt run with the dev tokens' 10pt minimum: "below minimum size", measured 8,
    threshold 10, remedy `token`."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_run_with_no_explicit_size_is_resolved_not_skipped() -> None:
    """A run inheriting its size from the theme is checked at the inherited size."""
    raise NotImplementedError


@_SCAFFOLD
def test_low_contrast_text_on_a_filled_panel_is_found() -> None:
    """Light grey text on a light accent panel: "insufficient contrast" with the measured
    ratio, remedy `token`."""
    raise NotImplementedError


@_SCAFFOLD
def test_large_bold_text_uses_the_large_threshold() -> None:
    """A colour pair at ratio ~3.5: flagged for 12pt text, not flagged for 14pt bold text."""
    raise NotImplementedError


@_SCAFFOLD
def test_an_untagged_slide_raises() -> None:
    """`ValueError` — findings must be attributable to an IR slide."""
    raise NotImplementedError


@_SCAFFOLD
def test_qa_is_pure() -> None:
    """The file's bytes are identical before and after; two runs return equal lists."""
    raise NotImplementedError
