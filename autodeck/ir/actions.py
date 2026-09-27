"""The closed action set through which presentation may change a deck (Phase 3b, task 3b.5).

SCAFFOLD (Opus). The types below are the invariant and are final; `apply_action` and
`fact_fingerprint` raise `NotImplementedError` and are Sonnet's to implement to their
docstrings. Tests: `tests/test_actions.py`.

**The defining constraint of Phase 3b: the aesthetic loop may never edit claim text or
citations, and that must be structural, not a prompt instruction** (PHASE-3B.md). A vision
model that can rewrite a verified claim is a silent accuracy-corruption channel (plan §9),
and a prompt telling it not to is advice a model is free to ignore.

So the guarantee is carried three ways, each independent of the others:

1. **Unrepresentable.** Every field of every action is either an *address* (a slide id, a
   block id, a slot name, a catalog component name, an icon concept) or a *closed
   vocabulary* (`TypeScale`, `AccentToken`, `ColumnBalance`, `CommunicationMode`). There
   is no field that can hold a sentence, a number or a citation. `IRModel`'s
   `extra="forbid"` means a model that adds `"text": "..."` to an action is rejected at
   parse time, not ignored. `tests/test_actions.py` walks every action type's fields and
   fails if a string-typed field appears that is not on `ADDRESS_FIELDS` — so a future
   action cannot quietly widen the channel.
2. **Addresses are only ever looked up, never written as content.** A `block_id` selects a
   block; nothing copies it into text. An unknown address is a rejection.
3. **Detected if it happens anyway.** `apply_action` fingerprints every fact in the deck
   before and after (`fact_fingerprint`) and raises `FactMutationError` if they differ.
   The types are prevention; this is detection, and it catches a bug in `apply_action`
   itself, which the types cannot.

What an action may change, exhaustively: `Slide.style`, `Slide.component`,
`Slide.communication_mode`, a `Block.slot` (only through `SwapComponent`'s slot map), and
an `IconRef`'s `glyph_id`/`concept`/`color_token`. Nothing else.

**Layout pins are honoured structurally.** An action that would change a slide's pinned
`component`, `communication_mode` or diagram kind is rejected (`PinnedTargetError`), not
merely discouraged — a pin the aesthetic loop can override teaches the consultant that
pinning does nothing.

**Layering.** `autodeck/ir/` must not import the design layer, so the two checks that need
it — which slots a component has, and which icon concepts exist — are injected as callables
(`SlotLookup`, `ConceptLookup`). The caller in `autodeck/render/qa/aesthetic.py` passes the
catalog and icon library.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Annotated, Literal

from pydantic import Field

from autodeck.ir.models import (
    AccentToken,
    ColumnBalance,
    CommunicationMode,
    Deck,
    IRModel,
    LayoutPin,
    TypeScale,
)

# ---------------------------------------------------------------------------
# The action set — final. Adding one is a reviewed change to an accuracy boundary.
# ---------------------------------------------------------------------------


class SetTypeScale(IRModel):
    """Step the slide along the client's type scale. Never a point size."""

    kind: Literal["set_type_scale"] = "set_type_scale"
    slide_id: str = Field(min_length=1)
    scale: TypeScale


class SetAccent(IRModel):
    """Change which theme accent the slide's component draws with."""

    kind: Literal["set_accent"] = "set_accent"
    slide_id: str = Field(min_length=1)
    accent: AccentToken


class SetColumnBalance(IRModel):
    """Rebalance a two-column component among the layouts it was built for."""

    kind: Literal["set_column_balance"] = "set_column_balance"
    slide_id: str = Field(min_length=1)
    balance: ColumnBalance


class SetEmphasis(IRModel):
    """Give one existing block visual emphasis, or clear it with `None`."""

    kind: Literal["set_emphasis"] = "set_emphasis"
    slide_id: str = Field(min_length=1)
    block_id: str | None = None


class SetCommunicationMode(IRModel):
    """Assign the slide's D13 mode. Used by art direction; subject to layout pins."""

    kind: Literal["set_communication_mode"] = "set_communication_mode"
    slide_id: str = Field(min_length=1)
    mode: CommunicationMode


class SwapComponent(IRModel):
    """Re-seat a slide's existing blocks in a different catalog component.

    `slot_map` sends every current slot name to a slot of `component`. It must cover every
    slot the slide's blocks use and may only name slots the target component has; a block
    left without a home is a *deleted fact*, which is a mutation even though no text
    changed, so an incomplete map is a rejection. Speaker notes keep their slots.
    """

    kind: Literal["swap_component"] = "swap_component"
    slide_id: str = Field(min_length=1)
    component: str = Field(min_length=1)
    slot_map: dict[str, str]


class SwapGlyph(IRModel):
    """Replace an icon block's glyph by naming a concept from the icon library."""

    kind: Literal["swap_glyph"] = "swap_glyph"
    slide_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    concept: str = Field(min_length=1)


class SetIconColour(IRModel):
    """Recolour an icon block from the theme palette."""

    kind: Literal["set_icon_colour"] = "set_icon_colour"
    slide_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    color_token: AccentToken


Action = Annotated[
    SetTypeScale
    | SetAccent
    | SetColumnBalance
    | SetEmphasis
    | SetCommunicationMode
    | SwapComponent
    | SwapGlyph
    | SetIconColour,
    Field(discriminator="kind"),
]
"""The whole vocabulary. There is deliberately no `EditText`, `SetClaim`, `MoveNode` or
free-geometry action — the brief names free-form geometry and text edits as exactly what
this set must not be able to express."""

ACTION_TYPES: tuple[type[IRModel], ...] = (
    SetTypeScale,
    SetAccent,
    SetColumnBalance,
    SetEmphasis,
    SetCommunicationMode,
    SwapComponent,
    SwapGlyph,
    SetIconColour,
)

ADDRESS_FIELDS: frozenset[str] = frozenset(
    {"kind", "slide_id", "block_id", "component", "concept", "slot_map"}
)
"""The only string-carrying fields any action may have. Each is looked up, never written as
content: ids and slot names address existing IR; `component` and `concept` are checked
against the catalog and icon library. Extending this set is a reviewed change."""


class ActionList(IRModel):
    """What a critique model returns: a score and a bounded list of actions."""

    score: float = Field(ge=0.0, le=10.0)
    rationale: str = Field(description="Why. Reporting only — never applied to the deck.")
    actions: list[Action] = Field(default_factory=list, max_length=8)


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


class ActionRejected(ValueError):
    """An action that cannot be applied. Carries the action so the loop can report it."""


class UnknownAddressError(ActionRejected):
    """A slide id, block id, slot, component or concept that does not exist."""


class PinnedTargetError(ActionRejected):
    """The action would change something a layout pin fixes."""


class FactMutationError(RuntimeError):
    """`apply_action` changed a fact. A defect in `apply_action`, never in the model's
    output — the types make that unrepresentable — so it is not an `ActionRejected`."""


SlotLookup = Callable[[str], frozenset[str] | None]
"""Component name → its slot names, or `None` if the catalog has no such component."""

ConceptLookup = Callable[[str], str | None]
"""Icon concept → resolved glyph id, or `None` if the library has no such concept."""


# ---------------------------------------------------------------------------
# Application — Sonnet implements to these contracts
# ---------------------------------------------------------------------------


def fact_fingerprint(deck: Deck) -> tuple[object, ...]:
    """Everything in `deck` that is a fact or verbatim content, in a stable, comparable form.

    Contract:
      - Covers every claim site (`deck.claim_sites()`): its path-independent identity
        (slide id, block id, node id, notes flag), `claim.text`, every citation's
        `doc_id`/`page`/`bbox`/`quote`/`quote_sha256`/`retrieved_by`, the derivation, the
        verdict, `verdict_notes`, and `contradicting_spans`.
      - Covers every block's `text` (framing, section headers, anything), every `ChartSpec`
        in full, every `DiagramSpec` in full, every `FigureRef`, on the face and in notes.
      - Excludes exactly what actions may change: `Slide.style`, `Slide.component`,
        `Slide.communication_mode`, `Block.slot`, and `IconRef` fields.
      - Keyed by block id, not by position, so a `SwapComponent` that reorders nothing but
        re-slots blocks leaves it unchanged, while a block that disappears changes it.
      - Pure; never mutates `deck`.
    """
    raise NotImplementedError("scaffold: Sonnet fills this in")


def apply_action(
    deck: Deck,
    action: SetTypeScale
    | SetAccent
    | SetColumnBalance
    | SetEmphasis
    | SetCommunicationMode
    | SwapComponent
    | SwapGlyph
    | SetIconColour,
    *,
    pins: Sequence[LayoutPin] = (),
    slots_of: SlotLookup,
    glyph_for: ConceptLookup,
) -> Deck:
    """Return a new deck with `action` applied. Never mutates `deck`.

    Contract:
      - Unknown `slide_id` / `block_id` → `UnknownAddressError`. `SetEmphasis` with a
        `block_id` not on that slide's face → `UnknownAddressError`.
      - `SwapComponent`: `slots_of(component)` is `None` → `UnknownAddressError`; the map
        must cover every face block's slot and map only onto slots the target has →
        otherwise `ActionRejected` naming the unmapped or unknown slot.
      - `SwapGlyph`: `glyph_for(concept)` is `None` → `UnknownAddressError`; else set both
        `concept` and `glyph_id`. The target block must be `kind == "icon"`.
      - `SetIconColour`: target block must be an icon.
      - Pins: a `SwapComponent` on a slide whose served message has a `component` pin, a
        `SetCommunicationMode` against a `communication_mode` pin, or any action altering a
        pinned `diagram_kind` → `PinnedTargetError`. A slide is pinned by a `LayoutPin`
        whose `message_id` is in `slide.message_ids`.
      - After applying: `fact_fingerprint(new) == fact_fingerprint(deck)`, else
        `FactMutationError`. Always checked, never behind a flag.
      - Structure: implement the mutation in a private `_apply_unchecked(deck, action, ...)`
        and have `apply_action` call it and then check the fingerprint. The test that proves
        detection works sabotages `_apply_unchecked` to edit a claim and asserts
        `FactMutationError` — a check that has never been seen to fire is not a check.
    """
    raise NotImplementedError("scaffold: Sonnet fills this in")
