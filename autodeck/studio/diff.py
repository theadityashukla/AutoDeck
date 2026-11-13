"""The id-keyed diff between two deck states, reusing v2's (plan §4: `ir/store.diff_decks`).

v2's diff matches list elements by `id` where every element has one, so inserting a slide
reads as one addition and not as a change to every later slide; a reordering of an id-keyed
list is reported once as `<path>[order]`. Slides, blocks and storyline points all carry
ids, so a base deck gets the same readable diffs. Layout elements carry no id and are
compared by position, exactly as in v2.

The walk itself is v2's `autodeck.ir.store._diff`, imported rather than copied: two
implementations of one diff would drift, and v2 is not modified (its public `diff_decks`
is typed to v2's `Deck`, so the module-private walker is what fits; importing a private
helper across packages has precedent in `render/draft.py`).

A diff here is for display and thread context. Undo never replays it.
"""

from __future__ import annotations

from autodeck.studio.models import DeckArtifact, DiffItem


def diff_artifacts(before: DeckArtifact, after: DeckArtifact) -> list[DiffItem]:
    """Every difference from `before` to `after`, as `DiffItem`s.

    Compute `autodeck.ir.store._diff(before.model_dump(mode="json"),
    after.model_dump(mode="json"), "")` and convert each v2 `Change` to a `DiffItem` with
    the same `path`, `kind`, `before` and `after`, preserving order. Identical states give
    `[]`. Pure; neither argument is modified.
    """
    raise NotImplementedError


def describe(diff: list[DiffItem]) -> list[str]:
    """One human-readable line per item, in order, in v2's `Change.__str__` format:

    * added:   `+ <path> = <after>`
    * removed: `- <path> = <before>`
    * changed: `~ <path>: <before> -> <after>`

    where a string value is shown with `repr` and any other value as compact JSON
    (`ensure_ascii=False`), truncated to 70 characters with a trailing `…`. Build a v2
    `autodeck.ir.store.Change` from each item and call `str()` on it, so the format has one
    definition.
    """
    raise NotImplementedError
