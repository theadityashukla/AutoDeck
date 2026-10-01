"""The closed action set (task 3b.5): presentation cannot edit a fact.

Three layers are tested separately because each must hold on its own: the types cannot
express an edit; addresses are validated; and the fingerprint catches a mutation the types
did not prevent — including one caused by a bug in `apply_action` itself.
"""

from __future__ import annotations

from collections.abc import Callable
from types import UnionType
from typing import Literal, get_args, get_origin

import pytest
from pydantic import TypeAdapter, ValidationError, create_model

from autodeck.ir import actions
from autodeck.ir.actions import (
    ACTION_TYPES,
    ADDRESS_FIELDS,
    Action,
    ActionList,
    ArtAction,
    AssignIcons,
    SetAccent,
    SetColumnBalance,
    SetCommunicationMode,
    SetEmphasis,
    SetIconColour,
    SetTypeScale,
    SwapComponent,
    SwapGlyph,
)
from autodeck.ir.models import (
    Block,
    ChartSeries,
    ChartSpec,
    Citation,
    Claim,
    Deck,
    Derivation,
    DerivationInput,
    DiagramSpec,
    FigureRef,
    IconRef,
    LabelFraming,
    LayoutPin,
    ProcessFlowSpec,
    ProcessStep,
    Slide,
)

# ---------------------------------------------------------------------------
# Deck fixtures and small fakes for the catalog / icon library
# ---------------------------------------------------------------------------

#: The face slots of the "two_col" component, matching the blocks `make_slide` builds.
_CATALOG: dict[str, frozenset[str]] = {
    "two_col": frozenset({"body", "sub", "chart", "diagram", "icon"}),
    "alt_layout": frozenset({"main", "aux", "graph", "flow", "badge"}),
}

_ICONS: dict[str, str] = {"growth": "glyph-1", "rocket": "glyph-rocket"}

_ALT_SLOT_MAP = {
    "body": "main",
    "sub": "aux",
    "chart": "graph",
    "diagram": "flow",
    "icon": "badge",
}


def fake_slots_of(component: str) -> frozenset[str] | None:
    """A small fake standing in for the design catalog (`SlotLookup`)."""
    return _CATALOG.get(component)


def fake_glyph_for(concept: str) -> str | None:
    """A small fake standing in for the icon library (`ConceptLookup`)."""
    return _ICONS.get(concept)


def make_citation(quote: str, **overrides: object) -> Citation:
    fields: dict[str, object] = {
        "doc_id": "doc-1",
        "page": 3,
        "bbox": (10.0, 20.0, 300.0, 44.0),
        "quote": quote,
        "retrieved_by": "writer",
    }
    fields.update(overrides)
    return Citation.for_quote(**fields)  # type: ignore[arg-type]


def make_claim(text: str = "Revenue grew 20% year over year.", **overrides: object) -> Claim:
    fields: dict[str, object] = {"text": text, "citations": [make_citation(text)]}
    fields.update(overrides)
    return Claim(**fields)  # type: ignore[arg-type]


def make_claim_with_derivation() -> Claim:
    citation = make_citation("Revenue rose from $100m to $120m.")
    derivation = Derivation(
        formula="(b - a) / a * 100",
        inputs={
            "a": DerivationInput(value=100.0, citation=citation),
            "b": DerivationInput(value=120.0, citation=citation),
        },
        result=20.0,
        unit="%",
    )
    return Claim(text="Revenue grew 20%.", citations=[citation], derivation=derivation)


def make_diagram() -> DiagramSpec:
    claim_citation = make_citation("Throughput rose from 412 to 671 sequences per second.")
    return DiagramSpec(
        relationship="sequence",
        kind="process_flow",
        process_flow=ProcessFlowSpec(
            steps=[
                ProcessStep(
                    id="n1",
                    label="Ingest",
                    order=1,
                    claim=Claim(text="Throughput reached 671 sps.", citations=[claim_citation]),
                ),
                ProcessStep(
                    id="n2",
                    label="Serve",
                    order=2,
                    framing=LabelFraming(reason="stage_name"),
                ),
            ]
        ),
    )


def make_chart() -> ChartSpec:
    return ChartSpec(
        chart_type="bar",
        categories=["Q1", "Q2"],
        series=[ChartSeries(name="Revenue", values=[10.0, 20.0])],
        source_citations=[make_citation("Q1 revenue was $10m; Q2 revenue was $20m.")],
    )


def make_icon_block(block_id: str = "b5", slot: str = "icon") -> Block:
    return Block(
        id=block_id,
        kind="icon",
        slot=slot,
        icon=IconRef(concept="growth", glyph_id="glyph-1", color_token="accent2"),
    )


def make_slide(
    slide_id: str = "s1",
    *,
    message_ids: tuple[str, ...] = ("m1",),
    component: str = "two_col",
) -> Slide:
    return Slide(
        id=slide_id,
        narrative_role="evidence",
        component=component,
        message_ids=list(message_ids),
        blocks=[
            Block(id="b1", kind="claim", slot="body", claim=make_claim_with_derivation()),
            Block(
                id="b2",
                kind="framing",
                slot="sub",
                text="Serve better before you buy more.",
            ),
            Block(id="b3", kind="chart", slot="chart", chart=make_chart()),
            Block(id="b4", kind="diagram", slot="diagram", diagram=make_diagram()),
            make_icon_block(),
        ],
        speaker_notes=[
            Block(
                id="n1",
                kind="claim",
                slot="notes",
                claim=make_claim(
                    "Ask about the pilot timeline.",
                    citations=[make_citation("Notes source quote.")],
                ),
            ),
        ],
    )


def make_deck(**overrides: object) -> Deck:
    fields: dict[str, object] = {
        "run_id": "run-1",
        "project": "proj",
        "client": "client",
        "audience": "aud",
        "version": 1,
        "theme_ref": "theme-1",
        "component_lib_version": "1.0.0",
        "slides": [make_slide()],
    }
    fields.update(overrides)
    return Deck(**fields)  # type: ignore[arg-type]


def make_two_slide_deck() -> Deck:
    """`s1` unpinned, `s2` served by message `m-pinned` — for the pin tests."""
    return make_deck(
        slides=[
            make_slide("s1", message_ids=("m1",)),
            make_slide("s2", message_ids=("m-pinned",)),
        ]
    )


# -- layer 1: unrepresentable ------------------------------------------------------------


def _admits_str(annotation: object) -> bool:
    """True if `annotation` is `str`, or a union/dict/etc. that can carry one.

    A `Literal["a", "b"]` does not admit `str`: its args are the literal string *values*,
    not the type `str`, so this correctly leaves closed vocabularies alone.
    """
    if annotation is str:
        return True
    args = get_args(annotation)
    if not args:
        return False
    return any(_admits_str(arg) for arg in args)


def _is_literal_or_optional_literal(annotation: object) -> bool:
    if get_origin(annotation) is Literal:
        return True
    if get_origin(annotation) in (UnionType,):
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        return len(non_none) == 1 and get_origin(non_none[0]) is Literal
    return False


def test_no_action_has_a_field_that_can_carry_content() -> None:
    """Walk `ACTION_TYPES` and every `model_fields` entry. A field whose annotation admits a
    `str` (bare, optional, or inside a dict) must be named in `ADDRESS_FIELDS`; every other
    field must be a `Literal` (optionally `| None`). Fails naming the offending action and
    field. This is the regression guard for the whole invariant: a future action with a
    `note: str` field turns it red until someone argues the field into `ADDRESS_FIELDS`."""
    for action_type in ACTION_TYPES:
        for field_name, field_info in action_type.model_fields.items():
            annotation = field_info.annotation
            if _admits_str(annotation):
                assert field_name in ADDRESS_FIELDS, (
                    f"{action_type.__name__}.{field_name} ({annotation!r}) can carry a "
                    "string but is not in ADDRESS_FIELDS"
                )
            else:
                assert _is_literal_or_optional_literal(annotation), (
                    f"{action_type.__name__}.{field_name} ({annotation!r}) is neither an "
                    "address field nor a closed Literal vocabulary"
                )


def test_a_critique_proposing_a_text_edit_is_rejected() -> None:
    """The brief's stated done-when. `ActionList.model_validate` of
    `{"score": 6, "rationale": "tighten", "actions": [{"kind": "edit_text", "slide_id": "s1",
    "block_id": "b1", "text": "Quantisation halves cost"}]}` raises `ValidationError`."""
    with pytest.raises(ValidationError):
        ActionList.model_validate(
            {
                "score": 6,
                "rationale": "tighten",
                "actions": [
                    {
                        "kind": "edit_text",
                        "slide_id": "s1",
                        "block_id": "b1",
                        "text": "Quantisation halves cost",
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    "smuggled",
    [
        {"kind": "set_accent", "slide_id": "s1", "accent": "accent2", "text": "new claim"},
        {"kind": "set_emphasis", "slide_id": "s1", "block_id": "b1", "citation": {}},
        {
            "kind": "swap_component",
            "slide_id": "s1",
            "component": "quote",
            "slot_map": {},
            "quote": "edited",
        },
    ],
)
def test_a_content_field_smuggled_onto_a_legal_action_is_rejected(smuggled: dict) -> None:
    """`extra="forbid"`: each payload raises `ValidationError` when parsed as an
    `ActionList` action — it is rejected, not silently stripped."""
    with pytest.raises(ValidationError):
        ActionList.model_validate({"score": 1, "rationale": "x", "actions": [smuggled]})


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "set_accent", "slide_id": "s1", "accent": "#FF0000"},
        {"kind": "set_type_scale", "slide_id": "s1", "scale": "32pt"},
        {"kind": "set_column_balance", "slide_id": "s1", "balance": "63/37"},
    ],
)
def test_literal_values_and_free_geometry_are_unrepresentable(bad: dict) -> None:
    """A literal colour, a point size and a numeric split all fail validation: the loop may
    only choose among named options, never request geometry."""
    with pytest.raises(ValidationError):
        ActionList.model_validate({"score": 1, "rationale": "x", "actions": [bad]})


def test_the_action_list_is_bounded() -> None:
    """More than eight actions in one `ActionList` fails validation."""
    nine_actions = [{"kind": "set_accent", "slide_id": "s1", "accent": "accent2"}] * 9
    with pytest.raises(ValidationError):
        ActionList.model_validate({"score": 1, "rationale": "x", "actions": nine_actions})


# -- layer 2: application, addresses, pins ----------------------------------------------


@pytest.mark.parametrize(
    "action_kind",
    [
        "set_type_scale",
        "set_accent",
        "set_column_balance",
        "set_emphasis",
        "set_communication_mode",
        "swap_component",
        "swap_glyph",
        "set_icon_colour",
    ],
)
def test_each_action_changes_its_target_and_no_fact(action_kind: str) -> None:
    """Build a deck with a cited claim, a framing block, a chart, a diagram and an icon.
    Apply one legal action of `action_kind`. Assert the targeted field changed, the
    fingerprint is unchanged, and the input deck is unmodified (compare `model_dump()`)."""
    deck = make_deck()
    before_dump = deck.model_dump()
    before_fp = actions.fact_fingerprint(deck)

    action: Action
    if action_kind == "set_type_scale":
        action = SetTypeScale(slide_id="s1", scale="spacious")
    elif action_kind == "set_accent":
        action = SetAccent(slide_id="s1", accent="accent4")
    elif action_kind == "set_column_balance":
        action = SetColumnBalance(slide_id="s1", balance="lead_left")
    elif action_kind == "set_emphasis":
        action = SetEmphasis(slide_id="s1", block_id="b2")
    elif action_kind == "set_communication_mode":
        action = SetCommunicationMode(slide_id="s1", mode="diagram_led")
    elif action_kind == "swap_component":
        action = SwapComponent(slide_id="s1", component="alt_layout", slot_map=_ALT_SLOT_MAP)
    elif action_kind == "swap_glyph":
        action = SwapGlyph(slide_id="s1", block_id="b5", concept="rocket")
    elif action_kind == "set_icon_colour":
        action = SetIconColour(slide_id="s1", block_id="b5", color_token="accent6")
    else:  # pragma: no cover
        raise AssertionError(action_kind)

    new_deck = actions.apply_action(
        deck, action, slots_of=fake_slots_of, glyph_for=fake_glyph_for
    )
    new_slide = new_deck.slides[0]

    if action_kind == "set_type_scale":
        assert new_slide.style.type_scale == "spacious"
    elif action_kind == "set_accent":
        assert new_slide.style.accent == "accent4"
    elif action_kind == "set_column_balance":
        assert new_slide.style.column_balance == "lead_left"
    elif action_kind == "set_emphasis":
        assert new_slide.style.emphasis_block_id == "b2"
    elif action_kind == "set_communication_mode":
        assert new_slide.communication_mode == "diagram_led"
    elif action_kind == "swap_component":
        assert new_slide.component == "alt_layout"
        assert {block.id: block.slot for block in new_slide.blocks} == {
            "b1": "main",
            "b2": "aux",
            "b3": "graph",
            "b4": "flow",
            "b5": "badge",
        }
    elif action_kind == "swap_glyph":
        icon_block = next(block for block in new_slide.blocks if block.id == "b5")
        assert icon_block.icon is not None
        assert icon_block.icon.concept == "rocket"
        assert icon_block.icon.glyph_id == "glyph-rocket"
    elif action_kind == "set_icon_colour":
        icon_block = next(block for block in new_slide.blocks if block.id == "b5")
        assert icon_block.icon is not None
        assert icon_block.icon.color_token == "accent6"

    assert actions.fact_fingerprint(new_deck) == before_fp
    assert deck.model_dump() == before_dump


@pytest.mark.parametrize(
    "case",
    [
        "unknown slide",
        "unknown block",
        "unknown component",
        "unknown concept",
        "emphasis on a notes block",
        "glyph swap on a non-icon block",
    ],
)
def test_bad_addresses_are_rejected(case: str) -> None:
    """Each case raises `UnknownAddressError` (or `ActionRejected` for the non-icon case)."""
    deck = make_deck()

    action: Action
    if case == "unknown slide":
        action = SetTypeScale(slide_id="nope", scale="compact")
        expected: type[Exception] = actions.UnknownAddressError
    elif case == "unknown block":
        action = SetEmphasis(slide_id="s1", block_id="nope")
        expected = actions.UnknownAddressError
    elif case == "unknown component":
        action = SwapComponent(slide_id="s1", component="nope", slot_map={})
        expected = actions.UnknownAddressError
    elif case == "unknown concept":
        action = SwapGlyph(slide_id="s1", block_id="b5", concept="nope")
        expected = actions.UnknownAddressError
    elif case == "emphasis on a notes block":
        action = SetEmphasis(slide_id="s1", block_id="n1")
        expected = actions.UnknownAddressError
    elif case == "glyph swap on a non-icon block":
        action = SwapGlyph(slide_id="s1", block_id="b1", concept="growth")
        expected = actions.ActionRejected
    else:  # pragma: no cover
        raise AssertionError(case)

    with pytest.raises(expected):
        actions.apply_action(deck, action, slots_of=fake_slots_of, glyph_for=fake_glyph_for)


def test_a_component_swap_that_would_orphan_a_block_is_rejected() -> None:
    """A `slot_map` missing one of the slide's face slots raises `ActionRejected` naming the
    slot. Orphaning a block deletes a fact even though no text changed."""
    deck = make_deck()
    action = SwapComponent(
        slide_id="s1",
        component="alt_layout",
        slot_map={"body": "main", "sub": "aux", "chart": "graph", "diagram": "flow"},
    )
    with pytest.raises(actions.ActionRejected, match="icon"):
        actions.apply_action(deck, action, slots_of=fake_slots_of, glyph_for=fake_glyph_for)


@pytest.mark.parametrize("target", ["component", "communication_mode"])
def test_a_pinned_target_cannot_be_changed(target: str) -> None:
    """A `LayoutPin` on a message the slide serves makes the corresponding action raise
    `PinnedTargetError`; the same action on an unpinned slide succeeds."""
    deck = make_two_slide_deck()
    pin = LayoutPin(
        message_id="m-pinned",
        target=target,  # type: ignore[arg-type]
        value="alt_layout" if target == "component" else "diagram_led",
    )

    if target == "component":
        pinned_action: Action = SwapComponent(
            slide_id="s2", component="alt_layout", slot_map=_ALT_SLOT_MAP
        )
        unpinned_action: Action = SwapComponent(
            slide_id="s1", component="alt_layout", slot_map=_ALT_SLOT_MAP
        )
    else:
        pinned_action = SetCommunicationMode(slide_id="s2", mode="diagram_led")
        unpinned_action = SetCommunicationMode(slide_id="s1", mode="diagram_led")

    with pytest.raises(actions.PinnedTargetError):
        actions.apply_action(
            deck, pinned_action, pins=[pin], slots_of=fake_slots_of, glyph_for=fake_glyph_for
        )

    result = actions.apply_action(
        deck, unpinned_action, pins=[pin], slots_of=fake_slots_of, glyph_for=fake_glyph_for
    )
    assert result is not None


# -- layer 3: detection -------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        "claim text",
        "a citation quote",
        "a verdict",
        "a derivation input",
        "framing text",
        "a chart value",
        "a diagram node label",
        "a deleted block",
        "a speaker-note claim",
    ],
)
def test_the_fingerprint_sees_every_kind_of_fact(mutation: str) -> None:
    """Mutate a copy of the deck directly in the named way; its fingerprint differs."""
    deck = make_deck()
    before = actions.fact_fingerprint(deck)
    copy = deck.model_copy(deep=True)
    slide = copy.slides[0]

    if mutation == "claim text":
        assert slide.blocks[0].claim is not None
        slide.blocks[0].claim.text = "A different claim entirely."
    elif mutation == "a citation quote":
        assert slide.blocks[0].claim is not None
        slide.blocks[0].claim.citations[0].quote = "A different quote entirely."
    elif mutation == "a verdict":
        assert slide.blocks[0].claim is not None
        slide.blocks[0].claim.verdict = "contradicted"
    elif mutation == "a derivation input":
        assert slide.blocks[0].claim is not None
        assert slide.blocks[0].claim.derivation is not None
        slide.blocks[0].claim.derivation.inputs["a"].value = 999.0
    elif mutation == "framing text":
        slide.blocks[1].text = "A completely different framing sentence."
    elif mutation == "a chart value":
        assert slide.blocks[2].chart is not None
        slide.blocks[2].chart.series[0].values[0] = 999.0
    elif mutation == "a diagram node label":
        assert slide.blocks[3].diagram is not None
        slide.blocks[3].diagram.process_flow.steps[0].label = "Relabeled"  # type: ignore[union-attr]
    elif mutation == "a deleted block":
        slide.blocks.pop(3)  # the diagram; the trailing icon block is no longer a fact (B36)
    elif mutation == "a speaker-note claim":
        assert slide.speaker_notes[0].claim is not None
        slide.speaker_notes[0].claim.text = "A different notes claim."
    else:  # pragma: no cover
        raise AssertionError(mutation)

    assert actions.fact_fingerprint(copy) != before


def test_the_fingerprint_ignores_everything_an_action_may_change() -> None:
    """Change style, component, communication mode, a block's slot and an icon's glyph and
    colour on a copy; the fingerprint is equal."""
    deck = make_deck()
    before = actions.fact_fingerprint(deck)
    copy = deck.model_copy(deep=True)
    slide = copy.slides[0]

    slide.style.type_scale = "compact"
    slide.style.accent = "accent5"
    slide.style.column_balance = "lead_right"
    slide.style.emphasis_block_id = "b1"
    slide.component = "alt_layout"
    slide.communication_mode = "diagram_led"
    slide.blocks[0].slot = "renamed_slot"
    icon_block = next(block for block in slide.blocks if block.kind == "icon")
    assert icon_block.icon is not None
    icon_block.icon.glyph_id = "new-glyph"
    icon_block.icon.color_token = "accent6"
    icon_block.icon.concept = "new-concept"

    assert actions.fact_fingerprint(copy) == before


def test_a_buggy_applier_that_edits_a_claim_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch `actions._apply_unchecked` to also rewrite a claim's text. `apply_action`
    raises `FactMutationError`. Then also patch `fact_fingerprint` to a constant and assert
    the same call succeeds — proving the green above comes from the check."""
    deck = make_deck()
    original_apply_unchecked = actions._apply_unchecked

    def sabotaged(deck: Deck, action: Action, **kwargs: object) -> Deck:
        new_deck = original_apply_unchecked(deck, action, **kwargs)  # type: ignore[arg-type]
        claim_block = new_deck.slides[0].blocks[0]
        assert claim_block.claim is not None
        claim_block.claim.text = "sabotaged by a buggy applier"
        return new_deck

    monkeypatch.setattr(actions, "_apply_unchecked", sabotaged)

    action = SetAccent(slide_id="s1", accent="accent2")
    with pytest.raises(actions.FactMutationError):
        actions.apply_action(deck, action, slots_of=fake_slots_of, glyph_for=fake_glyph_for)

    monkeypatch.setattr(actions, "fact_fingerprint", lambda deck: ("constant",))
    result = actions.apply_action(
        deck, action, slots_of=fake_slots_of, glyph_for=fake_glyph_for
    )
    assert result.slides[0].blocks[0].claim is not None
    assert result.slides[0].blocks[0].claim.text == "sabotaged by a buggy applier"


def test_icon_actions_cannot_reach_an_icon_in_the_speaker_notes() -> None:
    """`SwapGlyph` and `SetIconColour` addressed at an icon block that lives in
    `speaker_notes` -> `UnknownAddressError` whose message says the block is in the notes,
    not on the face. The same actions on a face icon still apply. (Notes are not drawn, so
    the vision model cannot have seen that icon.)"""
    deck = make_deck()
    deck.slides[0].speaker_notes.append(make_icon_block("n2", slot="notes"))
    before_dump = deck.model_dump()

    notes_actions: list[Action] = [
        SwapGlyph(slide_id="s1", block_id="n2", concept="rocket"),
        SetIconColour(slide_id="s1", block_id="n2", color_token="accent6"),
    ]
    for action in notes_actions:
        with pytest.raises(actions.UnknownAddressError, match="speaker notes, not on the face"):
            actions.apply_action(deck, action, slots_of=fake_slots_of, glyph_for=fake_glyph_for)
    assert deck.model_dump() == before_dump

    swapped = actions.apply_action(
        deck,
        SwapGlyph(slide_id="s1", block_id="b5", concept="rocket"),
        slots_of=fake_slots_of,
        glyph_for=fake_glyph_for,
    )
    recoloured = actions.apply_action(
        deck,
        SetIconColour(slide_id="s1", block_id="b5", color_token="accent6"),
        slots_of=fake_slots_of,
        glyph_for=fake_glyph_for,
    )
    face_icon = next(block for block in swapped.slides[0].blocks if block.id == "b5")
    assert face_icon.icon is not None and face_icon.icon.concept == "rocket"
    face_icon = next(block for block in recoloured.slides[0].blocks if block.id == "b5")
    assert face_icon.icon is not None and face_icon.icon.color_token == "accent6"


def _facts_with(deck: Deck, mutate: Callable[[Slide], None]) -> bool:
    """Whether mutating a copy of `deck`'s first slide changes the fingerprint."""
    copy = deck.model_copy(deep=True)
    mutate(copy.slides[0])
    return actions.fact_fingerprint(copy) != actions.fact_fingerprint(deck)


def test_icon_blocks_are_not_facts_but_every_other_block_still_is() -> None:
    """B36: adding, removing or replacing an icon block leaves `fact_fingerprint` unchanged;
    removing a framing, claim, chart, diagram or figure block still changes it."""
    deck = make_deck()
    deck.slides[0].blocks.append(
        Block(
            id="b6",
            kind="figure",
            slot="fig",
            figure=FigureRef(asset_id="fig-1", citation=make_citation("A figure quote.")),
        )
    )

    def remove(block_id: str) -> Callable[[Slide], None]:
        def run(slide: Slide) -> None:
            slide.blocks = [b for b in slide.blocks if b.id != block_id]

        return run

    def add_icon(slide: Slide) -> None:
        slide.blocks.append(make_icon_block("b9", slot="icon"))

    def replace_icon(slide: Slide) -> None:
        slide.blocks = [b for b in slide.blocks if b.kind != "icon"]
        slide.blocks.append(make_icon_block("b8", slot="icon"))

    def add_notes_icon(slide: Slide) -> None:
        slide.speaker_notes.append(make_icon_block("n9", slot="notes"))

    assert not _facts_with(deck, remove("b5"))  # the icon
    assert not _facts_with(deck, add_icon)
    assert not _facts_with(deck, replace_icon)
    assert not _facts_with(deck, add_notes_icon)

    for fact_block in ("b1", "b2", "b3", "b4", "b6"):  # claim, framing, chart, diagram, figure
        assert _facts_with(deck, remove(fact_block)), fact_block


def _assign(deck: Deck, action: AssignIcons) -> Deck:
    return actions.apply_action(deck, action, slots_of=fake_slots_of, glyph_for=fake_glyph_for)


def test_assign_icons_replaces_the_slots_icons_in_order() -> None:
    """Two existing icons in the slot -> replaced by three new ones with ids `slot.icon1..3`,
    concepts and glyphs from `glyph_for`, `color_token` applied; other slots untouched;
    fingerprint unchanged (via `apply_action`)."""
    deck = make_deck()
    deck.slides[0].blocks.append(make_icon_block("b6", slot="icon"))
    deck.slides[0].blocks.append(make_icon_block("b7", slot="badge"))
    before_dump = deck.model_dump()

    result = _assign(
        deck,
        AssignIcons(
            slide_id="s1",
            slot="icon",
            concepts=["rocket", "growth", "rocket"],
            color_token="accent4",
        ),
    )

    assert deck.model_dump() == before_dump
    blocks = result.slides[0].blocks
    in_slot = [b for b in blocks if b.slot == "icon"]
    assert [b.id for b in in_slot] == ["icon.icon1", "icon.icon2", "icon.icon3"]
    assert all(b.kind == "icon" and b.icon is not None for b in in_slot)
    icons = [b.icon for b in in_slot if b.icon is not None]
    assert [(i.concept, i.glyph_id, i.color_token) for i in icons] == [
        ("rocket", "glyph-rocket", "accent4"),
        ("growth", "glyph-1", "accent4"),
        ("rocket", "glyph-rocket", "accent4"),
    ]
    # Everything outside the slot is untouched, including the other slot's icon.
    assert [b.id for b in blocks if b.slot != "icon"] == ["b1", "b2", "b3", "b4", "b7"]
    assert actions.fact_fingerprint(result) == actions.fact_fingerprint(deck)


def test_assign_icons_works_on_a_slot_with_no_icons_yet() -> None:
    deck = make_deck()
    deck.slides[0].blocks = [b for b in deck.slides[0].blocks if b.kind != "icon"]
    result = _assign(deck, AssignIcons(slide_id="s1", slot="icon", concepts=["growth"]))
    added = result.slides[0].blocks[-1]
    assert added.id == "icon.icon1" and added.icon is not None
    assert added.icon.color_token == "accent1"


def test_assign_icons_rejections() -> None:
    """Unknown slot for the component -> UnknownAddressError; unknown concept ->
    UnknownAddressError naming it; a non-icon face block in the slot -> ActionRejected;
    an id collision with a non-icon block -> ActionRejected; more than six concepts or none
    -> ValidationError at parse."""
    deck = make_deck()
    before_dump = deck.model_dump()

    with pytest.raises(actions.UnknownAddressError, match="not a slot of component"):
        _assign(deck, AssignIcons(slide_id="s1", slot="nope", concepts=["growth"]))
    with pytest.raises(actions.UnknownAddressError, match="'warp'"):
        _assign(deck, AssignIcons(slide_id="s1", slot="icon", concepts=["growth", "warp"]))
    with pytest.raises(actions.UnknownAddressError, match="unknown slide_id"):
        _assign(deck, AssignIcons(slide_id="nope", slot="icon", concepts=["growth"]))

    with pytest.raises(actions.ActionRejected, match="never displace content") as displaced:
        _assign(deck, AssignIcons(slide_id="s1", slot="body", concepts=["growth"]))
    assert not isinstance(displaced.value, actions.UnknownAddressError)

    collide = make_deck()
    collide.slides[0].blocks.append(
        Block(id="icon.icon1", kind="framing", slot="sub", text="Squatting on the id")
    )
    with pytest.raises(actions.ActionRejected, match="collide"):
        _assign(collide, AssignIcons(slide_id="s1", slot="icon", concepts=["growth"]))

    assert deck.model_dump() == before_dump

    with pytest.raises(ValidationError):
        AssignIcons(slide_id="s1", slot="icon", concepts=[])
    with pytest.raises(ValidationError):
        AssignIcons(slide_id="s1", slot="icon", concepts=["growth"] * 7)
    with pytest.raises(ValidationError):
        AssignIcons.model_validate(
            {"slide_id": "s1", "slot": "icon", "concepts": ["growth"], "text": "Up 40%"}
        )


def test_assign_icons_is_not_in_the_aesthetic_vocabulary() -> None:
    """`ActionList.model_validate` of an `assign_icons` action fails; `ArtAction` accepts it
    and refuses `set_communication_mode`, `swap_glyph` and `set_icon_colour`."""
    assign = {"kind": "assign_icons", "slide_id": "s1", "slot": "icon", "concepts": ["growth"]}
    with pytest.raises(ValidationError):
        ActionList.model_validate({"score": 5, "rationale": "x", "actions": [assign]})

    adapter = TypeAdapter(ArtAction)
    assert isinstance(adapter.validate_python(assign), AssignIcons)
    for refused in (
        {"kind": "set_communication_mode", "slide_id": "s1", "mode": "text_led"},
        {"kind": "swap_glyph", "slide_id": "s1", "block_id": "b5", "concept": "rocket"},
        {
            "kind": "set_icon_colour",
            "slide_id": "s1",
            "block_id": "b5",
            "color_token": "accent2",
        },
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(refused)


def test_every_art_action_is_covered_by_the_content_field_guard() -> None:
    """`ArtAction`'s members must be in `ACTION_TYPES`, or the walk in
    `test_no_action_has_a_field_that_can_carry_content` would not see them."""
    members = get_args(get_args(ArtAction)[0])
    assert members and set(members) <= set(ACTION_TYPES)


def test_the_content_guard_still_catches_a_stray_string_field() -> None:
    """With `slot` and `concepts` admitted to `ADDRESS_FIELDS`, a free-text field added to
    `AssignIcons` must still be flagged: the whitelist names fields, not types."""
    assert "note" not in ADDRESS_FIELDS
    assert {"slot", "concepts"} <= ADDRESS_FIELDS
    leaky = create_model("Leaky", __base__=AssignIcons, note=(str, ""))
    flagged = [
        name
        for name, info in leaky.model_fields.items()
        if _admits_str(info.annotation) and name not in ADDRESS_FIELDS
    ]
    assert flagged == ["note"]
