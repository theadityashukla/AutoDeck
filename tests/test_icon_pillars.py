"""`icon_pillars` (B35): the first component that can place an icon on a slide face.

Covers the renderer, its catalog registration, the IR adapter, and the end-to-end paths B35
exists to unblock: an icon on a rendered deck that the aesthetic loop's icon actions can
reach, and GATE 3 check 2 (an icon selectable and recolourable from the theme palette).
"""

from __future__ import annotations

import pytest

SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


@SCAFFOLD
def test_three_and_four_pillars_render_with_icon_label_and_optional_point() -> None:
    """Both counts render without overflow at standard scale with the preview example's
    content; each pillar's icon shapes carry the `icon:` name prefix
    (`icons.consistency.ICON_NAME_PREFIX`) and the label's text frame is in the same column."""
    raise NotImplementedError


@SCAFFOLD
def test_two_or_five_pillars_are_refused() -> None:
    """`render` raises `ValueError`; the adapter raises `RenderStageError`."""
    raise NotImplementedError


@SCAFFOLD
def test_the_drawn_glyph_is_the_irs_glyph_id_not_its_concept() -> None:
    """An icon block whose `concept` resolves to glyph A but whose `glyph_id` is B renders
    glyph B (compare the placed shape name to B)."""
    raise NotImplementedError


@SCAFFOLD
def test_icons_are_theme_recolourable() -> None:
    """GATE 3 check 2, as far as code can check it: every icon shape's fill/line uses a
    scheme colour (`a:schemeClr`) equal to the pillar's `color`, never `a:srgbClr`."""
    raise NotImplementedError


@SCAFFOLD
def test_adapter_pairs_by_position_and_refuses_ambiguous_points() -> None:
    """3 icons + 3 labels + 0 points → ok; + 3 points → ok; + 2 points → RenderStageError;
    3 icons + 2 labels → RenderStageError; a non-icon block in `pillar_icon` →
    RenderStageError naming it."""
    raise NotImplementedError


@SCAFFOLD
def test_placeable_slots_and_catalog_registration() -> None:
    """`placeable_slots("icon_pillars") == {"headline", "pillar_icon", "pillar_label",
    "pillar_point"}`; `catalog.registration("icon_pillars")` exists with a preview path;
    `COMPONENT_LIB_VERSION` was bumped with a changelog line."""
    raise NotImplementedError


@SCAFFOLD
def test_grammar_icon_adjacency_passes_on_a_rendered_pillar_slide() -> None:
    """`grammar.check_icon_adjacency` returns no findings for a rendered icon_pillars slide."""
    raise NotImplementedError


@SCAFFOLD
def test_aesthetic_icon_actions_reach_a_rendered_face_icon() -> None:
    """A deck with an icon_pillars slide: `SwapGlyph` and `SetIconColour` via `apply_action`
    then `render_deck` → the new glyph/colour is what the PPTX holds; fact fingerprint
    unchanged. This is the end-to-end path B35 says was missing."""
    raise NotImplementedError
