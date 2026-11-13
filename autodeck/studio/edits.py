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

from autodeck.studio.models import DeckArtifact, Marker


def set_block_text(deck: DeckArtifact, *, slide_id: str, block_id: str, text: str) -> DeckArtifact:
    """The deck with the text of one text block replaced by `text` (verbatim, not stripped).

    Raises:
        EditError: no slide `slide_id`, no block `block_id` on it, or the block's kind is
            not `text` (the message names the kind).
        pydantic.ValidationError: `text` is empty or whitespace (a text block's own rule).
    """
    raise NotImplementedError


def set_slide_marker(deck: DeckArtifact, *, slide_id: str, marker: Marker) -> DeckArtifact:
    """The deck with one slide's `marker` set. Setting the marker it already has returns an
    equal deck (the store will then refuse it as `NoChangeError`; that is the caller's
    concern).

    Raises:
        EditError: no slide `slide_id`.
    """
    raise NotImplementedError


def move_slide(deck: DeckArtifact, *, slide_id: str, to_index: int) -> DeckArtifact:
    """The deck with slide `slide_id` moved to position `to_index` of the result (0-based;
    `list.insert` semantics after removal, so `to_index` may be 0 .. len(slides) - 1).

    Raises:
        EditError: no slide `slide_id`, or `to_index` outside 0 .. len(slides) - 1
            (negative indices are not accepted).
    """
    raise NotImplementedError
