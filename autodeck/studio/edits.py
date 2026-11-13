"""A few pure edits on a deck state, enough for Phase 0's "an edit can be made".

Phase 1's edit tools grow from here. Every function takes a deck and returns a **new**,
fully validated `DeckArtifact`: build the updated data from `deck.model_dump()` (or nested
`model_copy` calls) and finish with `DeckArtifact.model_validate(...)` so every model
validator runs on the result. The input deck is never mutated (tests compare its
serialisation before and after). Ids are never changed: the strict overlay will key on
`slide_id:block_id` (plan §8.2), so an edit changes content, never identity.

These functions do not record anything; pass the result to `ArtifactStore.apply`.
"""

from __future__ import annotations

from autodeck.studio.errors import EditError
from autodeck.studio.models import DeckArtifact, Marker


def _slide_index(deck: DeckArtifact, slide_id: str) -> int:
    for index, slide in enumerate(deck.slides):
        if slide.id == slide_id:
            return index
    raise EditError(f"deck {deck.id!r} has no slide {slide_id!r}")


def set_block_text(
    deck: DeckArtifact, *, slide_id: str, block_id: str, text: str
) -> DeckArtifact:
    """The deck with the text of one text block replaced by `text` (verbatim, not stripped).

    Raises:
        EditError: no slide `slide_id`, no block `block_id` on it, or the block's kind is
            not `text` (the message names the kind).
        pydantic.ValidationError: `text` is empty or whitespace (a text block's own rule).
    """
    slide_index = _slide_index(deck, slide_id)
    slide = deck.slides[slide_index]
    block_index = next(
        (i for i, block in enumerate(slide.blocks) if block.id == block_id), None
    )
    if block_index is None:
        raise EditError(f"slide {slide_id!r} has no block {block_id!r}")
    block = slide.blocks[block_index]
    if block.kind != "text":
        raise EditError(
            f"block {block_id!r} on slide {slide_id!r} is a {block.kind}, not a text block; "
            "only a text block holds text"
        )
    data = deck.model_dump()
    data["slides"][slide_index]["blocks"][block_index]["text"] = text
    return DeckArtifact.model_validate(data)


def set_slide_marker(deck: DeckArtifact, *, slide_id: str, marker: Marker) -> DeckArtifact:
    """The deck with one slide's `marker` set. Setting the marker it already has returns an
    equal deck (the store will then refuse it as `NoChangeError`; that is the caller's
    concern).

    Raises:
        EditError: no slide `slide_id`.
    """
    slide_index = _slide_index(deck, slide_id)
    data = deck.model_dump()
    data["slides"][slide_index]["marker"] = marker
    return DeckArtifact.model_validate(data)


def move_slide(deck: DeckArtifact, *, slide_id: str, to_index: int) -> DeckArtifact:
    """The deck with slide `slide_id` moved to position `to_index` of the result (0-based;
    `list.insert` semantics after removal, so `to_index` may be 0 .. len(slides) - 1).

    Raises:
        EditError: no slide `slide_id`, or `to_index` outside 0 .. len(slides) - 1
            (negative indices are not accepted).
    """
    slide_index = _slide_index(deck, slide_id)
    if not 0 <= to_index <= len(deck.slides) - 1:
        raise EditError(
            f"to_index {to_index} is outside 0 .. {len(deck.slides) - 1} for deck {deck.id!r}"
        )
    data = deck.model_dump()
    slides = data["slides"]
    moved = slides.pop(slide_index)
    slides.insert(to_index, moved)
    return DeckArtifact.model_validate(data)
