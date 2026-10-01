"""The closed action set through which presentation may change a deck (Phase 3b, task 3b.5).

The types below are the invariant and are final. Tests: `tests/test_actions.py`.

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
`component` or `communication_mode` is rejected (`PinnedTargetError`), not merely
discouraged — a pin the aesthetic loop can override teaches the consultant that pinning
does nothing. `diagram_kind` pins need no check here because **no action can reach a
diagram's kind at all** — the geometry is part of the verified content, fingerprinted with
the rest of the `DiagramSpec`. If an action that re-chooses geometry is ever added, it must
check `diagram_kind` pins, and its tests must say so.

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
    Block,
    ColumnBalance,
    CommunicationMode,
    Deck,
    IconRef,
    IRModel,
    LayoutPin,
    Slide,
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


class AssignIcons(IRModel):
    """Set the ordered icons in one face slot — art direction only (3b.7, B36).

    Replaces every icon block in `slot` on the slide's face with one new icon block per
    concept, in order; ids are `f"{slot}.icon{i}"` (1-based). Not in `Action`: the aesthetic
    critic restyles icons that exist (`SwapGlyph`, `SetIconColour`) but does not decide that
    a slide has icons — that is a communication-mode decision (D13), and it is art
    direction's. See `ArtAction`.
    """

    kind: Literal["assign_icons"] = "assign_icons"
    slide_id: str = Field(min_length=1)
    slot: str = Field(min_length=1)
    concepts: list[str] = Field(min_length=1, max_length=6)
    color_token: AccentToken = "accent1"


ACTION_TYPES: tuple[type[IRModel], ...] = (
    SetTypeScale,
    SetAccent,
    SetColumnBalance,
    SetEmphasis,
    SetCommunicationMode,
    SwapComponent,
    SwapGlyph,
    SetIconColour,
    AssignIcons,
)

ArtAction = Annotated[
    SetTypeScale | SetAccent | SetEmphasis | SwapComponent | AssignIcons,
    Field(discriminator="kind"),
]
"""What the art-direction model may propose (3b.7, B36). Narrower than `Action` in one way
and wider in another: no `SetCommunicationMode` — modes are derived by rule from content
shape, not proposed (`agents/art_direction.derive_mode`) — and no glyph/colour restyling,
which is the aesthetic critic's; plus `AssignIcons`, which only art direction may use."""

ADDRESS_FIELDS: frozenset[str] = frozenset(
    {"kind", "slide_id", "block_id", "component", "concept", "slot_map", "slot", "concepts"}
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
      - **Icon blocks are excluded entirely** (B36). An icon
        block's only content is its `IconRef`, already excluded, and since B36 the IR
        refuses `text` on it — so it holds no fact, and `AssignIcons` may add or replace
        icon blocks without tripping the detector. Every other block kind stays keyed in,
        so a deleted claim, framing line, chart, diagram or figure still changes it.
      - Pure; never mutates `deck`.
    """
    claim_entries: list[tuple[tuple[str, str, str | None, bool], object]] = []
    for site in deck.claim_sites():
        identity = (site.slide_id, site.block_id, site.node_id, site.in_speaker_notes)
        claim_entries.append((identity, site.claim.model_dump(mode="python")))
    claim_entries.sort(
        key=lambda entry: (entry[0][0], entry[0][1], entry[0][2] or "", entry[0][3])
    )

    block_entries: list[tuple[tuple[str, str, bool], object]] = []
    for slide in deck.slides:
        for in_notes, blocks in ((False, slide.blocks), (True, slide.speaker_notes)):
            for block in blocks:
                if block.kind == "icon":
                    continue
                content = (
                    block.text,
                    block.chart.model_dump(mode="python") if block.chart is not None else None,
                    block.diagram.model_dump(mode="python")
                    if block.diagram is not None
                    else None,
                    block.figure.model_dump(mode="python")
                    if block.figure is not None
                    else None,
                )
                block_entries.append(((slide.id, block.id, in_notes), content))
    block_entries.sort(key=lambda entry: (entry[0][0], entry[0][1], entry[0][2]))

    return (tuple(claim_entries), tuple(block_entries))


# ---------------------------------------------------------------------------
# Address lookups — private, shared by `_apply_unchecked`
# ---------------------------------------------------------------------------


def _find_slide(deck: Deck, slide_id: str) -> Slide:
    for slide in deck.slides:
        if slide.id == slide_id:
            return slide
    raise UnknownAddressError(f"unknown slide_id {slide_id!r}")


def _find_icon_block(slide: Slide, block_id: str) -> Block:
    """The icon block `block_id` on `slide`'s face; a notes-resident id is rejected as such."""
    for block in slide.blocks:
        if block.id == block_id:
            if block.kind != "icon":
                raise ActionRejected(
                    f"block {block_id!r} on slide {slide.id!r} is of kind {block.kind!r}, "
                    "not 'icon'"
                )
            return block
    if any(block.id == block_id for block in slide.speaker_notes):
        raise UnknownAddressError(
            f"block_id {block_id!r} on slide {slide.id!r} is in the speaker notes, not on the "
            "face; notes are not drawn, so icon actions cannot address it"
        )
    raise UnknownAddressError(f"unknown block_id {block_id!r} on slide {slide.id!r}")


def _assign_icons(
    slide: Slide, action: AssignIcons, *, slots_of: SlotLookup, glyph_for: ConceptLookup
) -> None:
    """Replace the face's icon blocks in `action.slot` with one per concept, in place."""
    slots = slots_of(slide.component)
    if slots is None or action.slot not in slots:
        raise UnknownAddressError(
            f"slot {action.slot!r} is not a slot of component {slide.component!r}"
        )
    glyphs: list[str] = []
    for concept in action.concepts:
        glyph_id = glyph_for(concept)
        if glyph_id is None:
            raise UnknownAddressError(f"unknown icon concept {concept!r}")
        glyphs.append(glyph_id)

    occupant = next(
        (b for b in slide.blocks if b.slot == action.slot and b.kind != "icon"), None
    )
    if occupant is not None:
        raise ActionRejected(
            f"slot {action.slot!r} on slide {slide.id!r} already holds a {occupant.kind!r} "
            f"block ({occupant.id!r}); icons never displace content"
        )

    new_ids = [f"{action.slot}.icon{i}" for i in range(1, len(action.concepts) + 1)]
    taken = {b.id for b in slide.blocks if not (b.kind == "icon" and b.slot == action.slot)}
    taken |= {b.id for b in slide.speaker_notes}
    collisions = [block_id for block_id in new_ids if block_id in taken]
    if collisions:
        raise ActionRejected(
            f"new icon id(s) {', '.join(collisions)} collide with existing block(s) on "
            f"slide {slide.id!r}"
        )

    slide.blocks = [b for b in slide.blocks if not (b.kind == "icon" and b.slot == action.slot)]
    for block_id, concept, glyph_id in zip(new_ids, action.concepts, glyphs, strict=True):
        slide.blocks.append(
            Block(
                id=block_id,
                kind="icon",
                slot=action.slot,
                icon=IconRef(
                    concept=concept, glyph_id=glyph_id, color_token=action.color_token
                ),
            )
        )


def _is_pinned(slide: Slide, pins: Sequence[LayoutPin], target: str) -> bool:
    """Whether a `LayoutPin` on `target` applies to `slide` (its `message_id` is served)."""
    return any(pin.target == target for pin in pins if pin.message_id in slide.message_ids)


def apply_action(
    deck: Deck,
    action: SetTypeScale
    | SetAccent
    | SetColumnBalance
    | SetEmphasis
    | SetCommunicationMode
    | SwapComponent
    | SwapGlyph
    | SetIconColour
    | AssignIcons,
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
      - Both icon actions address **face** blocks only (`slide.blocks`). An icon block in
        `speaker_notes` is not drawn, so the vision model cannot have seen it and has no
        grounds to restyle it → `UnknownAddressError` saying the block is in the notes, not
        on the face. `_find_icon_block` enforces this for both actions.
      - `AssignIcons` (B36, implemented in `_apply_unchecked`): `slot` not
        in `slots_of(slide.component)` → `UnknownAddressError`; any concept with
        `glyph_for(concept) is None` → `UnknownAddressError` naming it; a non-icon face block
        already in `slot` → `ActionRejected` (icons never displace content). Otherwise remove
        the face's icon blocks in `slot` and append one `Block(kind="icon", slot=slot,
        id=f"{slot}.icon{i}", icon=IconRef(concept, glyph_for(concept), color_token))` per
        concept in order; an id collision with a non-icon block → `ActionRejected`.
      - Pins: a `SwapComponent` on a slide whose served message has a `component` pin, or a
        `SetCommunicationMode` against a `communication_mode` pin → `PinnedTargetError`.
        (No action can alter a diagram's kind; see the module docstring.) A slide is pinned
        by a `LayoutPin`
        whose `message_id` is in `slide.message_ids`.
      - After applying: `fact_fingerprint(new) == fact_fingerprint(deck)`, else
        `FactMutationError`. Always checked, never behind a flag.
      - Structure: implement the mutation in a private `_apply_unchecked(deck, action, ...)`
        and have `apply_action` call it and then check the fingerprint. The test that proves
        detection works sabotages `_apply_unchecked` to edit a claim and asserts
        `FactMutationError` — a check that has never been seen to fire is not a check.
    """
    new_deck = _apply_unchecked(deck, action, pins=pins, slots_of=slots_of, glyph_for=glyph_for)
    before = fact_fingerprint(deck)
    after = fact_fingerprint(new_deck)
    if before != after:
        raise FactMutationError(
            f"applying {action.kind!r} changed a fact; this is a defect in apply_action "
            "itself, not in the action, since the action's fields cannot address a fact"
        )
    return new_deck


def _apply_unchecked(
    deck: Deck,
    action: SetTypeScale
    | SetAccent
    | SetColumnBalance
    | SetEmphasis
    | SetCommunicationMode
    | SwapComponent
    | SwapGlyph
    | SetIconColour
    | AssignIcons,
    *,
    pins: Sequence[LayoutPin],
    slots_of: SlotLookup,
    glyph_for: ConceptLookup,
) -> Deck:
    """Apply `action` to a deep copy of `deck` and return it, unchecked.

    Does the actual mutation and the address/pin validation that guards it; the fingerprint
    check that catches a bug here lives in `apply_action`, one layer up.
    """
    new_deck = deck.model_copy(deep=True)
    slide = _find_slide(new_deck, action.slide_id)

    if isinstance(action, SetTypeScale):
        slide.style.type_scale = action.scale

    elif isinstance(action, SetAccent):
        slide.style.accent = action.accent

    elif isinstance(action, SetColumnBalance):
        slide.style.column_balance = action.balance

    elif isinstance(action, SetEmphasis):
        if action.block_id is not None and not any(
            block.id == action.block_id for block in slide.blocks
        ):
            raise UnknownAddressError(
                f"block_id {action.block_id!r} is not on the face of slide {action.slide_id!r}"
            )
        slide.style.emphasis_block_id = action.block_id

    elif isinstance(action, SetCommunicationMode):
        if _is_pinned(slide, pins, "communication_mode"):
            raise PinnedTargetError(
                f"slide {action.slide_id!r} has a pinned communication_mode"
            )
        slide.communication_mode = action.mode

    elif isinstance(action, SwapComponent):
        target_slots = slots_of(action.component)
        if target_slots is None:
            raise UnknownAddressError(f"unknown component {action.component!r}")
        if _is_pinned(slide, pins, "component"):
            raise PinnedTargetError(f"slide {action.slide_id!r} has a pinned component")

        face_slots = {block.slot for block in slide.blocks}
        unmapped = sorted(slot for slot in face_slots if slot not in action.slot_map)
        if unmapped:
            raise ActionRejected(
                f"slot_map does not cover slot(s) {', '.join(unmapped)} on slide "
                f"{action.slide_id!r}; an unmapped block would be orphaned"
            )
        unknown_targets = sorted(
            {dst for dst in action.slot_map.values() if dst not in target_slots}
        )
        if unknown_targets:
            raise ActionRejected(
                f"slot_map maps to slot(s) {', '.join(unknown_targets)} that component "
                f"{action.component!r} does not have"
            )

        slide.component = action.component
        for block in slide.blocks:
            block.slot = action.slot_map[block.slot]

    elif isinstance(action, AssignIcons):
        _assign_icons(slide, action, slots_of=slots_of, glyph_for=glyph_for)

    elif isinstance(action, SwapGlyph):
        block = _find_icon_block(slide, action.block_id)
        glyph_id = glyph_for(action.concept)
        if glyph_id is None:
            raise UnknownAddressError(f"unknown icon concept {action.concept!r}")
        assert block.icon is not None  # guaranteed by Block's kind/payload agreement
        block.icon.concept = action.concept
        block.icon.glyph_id = glyph_id

    elif isinstance(action, SetIconColour):
        block = _find_icon_block(slide, action.block_id)
        assert block.icon is not None  # guaranteed by Block's kind/payload agreement
        block.icon.color_token = action.color_token

    else:  # pragma: no cover - Action is a closed, exhaustively-handled union
        raise AssertionError(f"unhandled action kind: {action.kind!r}")

    return new_deck
