"""The render stage (task 3b.1). SCAFFOLD (Opus): Sonnet fills bodies, deletes every
`@_SCAFFOLD` and `_SCAFFOLD`. Strict xfail — a passing stub still marked fails the suite.

Decks rendered here must pass `require_safe_to_render`: claims `supported`, validated
citations. A fixture with `unverified` claims is blocked before any file is written, which
is correct behaviour and is itself one of the tests.
"""

from __future__ import annotations

import pytest

_SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


@_SCAFFOLD
def test_a_safe_deck_renders_one_tagged_slide_per_ir_slide_in_order() -> None:
    """A validated multi-slide deck renders; PPTX slide *i* carries tag
    `autodeck:<deck.slides[i].id>`; `RenderedDeck.slide_ids` matches."""
    raise NotImplementedError


@_SCAFFOLD
def test_an_unsafe_deck_is_refused_before_any_file_exists() -> None:
    """A deck with one `contradicted` claim raises `RenderBlocked`, and `out_path` does not
    exist afterwards."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_block_with_no_home_is_an_error_not_a_skip() -> None:
    """A face block whose `slot` matches no field of the component's content dataclass
    raises `UnplacedBlockError` naming the block. A dropped block is a deleted fact."""
    raise NotImplementedError


@_SCAFFOLD
def test_claim_text_reaches_the_slide_character_for_character() -> None:
    """A claim containing an en dash, a non-breaking space, `%` and a trailing period appears
    byte-identical in the rendered slide's text frames."""
    raise NotImplementedError


@_SCAFFOLD
def test_every_registered_component_can_be_adapted() -> None:
    """For each name in `known_components()`, build a slide from its `preview.EXAMPLES`
    content (one block per populated field), adapt it, and assert it equals the example —
    no component is silently unrenderable by the generic rule plus `ADAPTERS`."""
    raise NotImplementedError


@_SCAFFOLD
def test_style_accent_and_type_scale_are_applied() -> None:
    """`accent="accent3"` puts `accent3` into the content; `type_scale="spacious"` produces a
    larger rendered headline font size than `"standard"` for the same slide."""
    raise NotImplementedError


@_SCAFFOLD
def test_style_a_component_cannot_express_is_reported() -> None:
    """`column_balance="lead_left"` on a component with no such field yields one
    `StyleNotHonoured` in `RenderedDeck.warnings`; the default value yields none."""
    raise NotImplementedError


@_SCAFFOLD
def test_speaker_notes_are_written_with_their_sources() -> None:
    """A notes claim's text and its `doc p.N` source both appear on that slide's notes page."""
    raise NotImplementedError


@_SCAFFOLD
def test_two_renders_are_normalised_comparable() -> None:
    """A6 as corrected by B29: rendering the same deck twice gives equal
    `canonical_pptx_digest` values, while the raw bytes are allowed to differ."""
    raise NotImplementedError


@_SCAFFOLD
def test_no_image_part_is_written_for_a_deck_without_figures() -> None:
    """A deck with a chart, a diagram and an icon renders with zero `ppt/media/` parts."""
    raise NotImplementedError
