"""The closed action set (task 3b.5): presentation cannot edit a fact.

SCAFFOLD (Opus). Sonnet: implement each body, then delete every `@_SCAFFOLD` marker and the
`_SCAFFOLD` definition. Strict xfail: a stub that passes while still marked fails the suite.

Three layers are tested separately because each must hold on its own: the types cannot
express an edit; addresses are validated; and the fingerprint catches a mutation the types
did not prevent — including one caused by a bug in `apply_action` itself.
"""

from __future__ import annotations

import pytest

_SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")

# -- layer 1: unrepresentable ------------------------------------------------------------


@_SCAFFOLD
def test_no_action_has_a_field_that_can_carry_content() -> None:
    """Walk `ACTION_TYPES` and every `model_fields` entry. A field whose annotation admits a
    `str` (bare, optional, or inside a dict) must be named in `ADDRESS_FIELDS`; every other
    field must be a `Literal` (optionally `| None`). Fails naming the offending action and
    field. This is the regression guard for the whole invariant: a future action with a
    `note: str` field turns it red until someone argues the field into `ADDRESS_FIELDS`."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_critique_proposing_a_text_edit_is_rejected() -> None:
    """The brief's stated done-when. `ActionList.model_validate` of
    `{"score": 6, "rationale": "tighten", "actions": [{"kind": "edit_text", "slide_id": "s1",
    "block_id": "b1", "text": "Quantisation halves cost"}]}` raises `ValidationError`."""
    raise NotImplementedError


@_SCAFFOLD
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
    raise NotImplementedError


@_SCAFFOLD
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
    raise NotImplementedError


@_SCAFFOLD
def test_the_action_list_is_bounded() -> None:
    """More than eight actions in one `ActionList` fails validation."""
    raise NotImplementedError


# -- layer 2: application, addresses, pins ----------------------------------------------


@_SCAFFOLD
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
    raise NotImplementedError


@_SCAFFOLD
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
    raise NotImplementedError


@_SCAFFOLD
def test_a_component_swap_that_would_orphan_a_block_is_rejected() -> None:
    """A `slot_map` missing one of the slide's face slots raises `ActionRejected` naming the
    slot. Orphaning a block deletes a fact even though no text changed."""
    raise NotImplementedError


@_SCAFFOLD
@pytest.mark.parametrize("target", ["component", "communication_mode"])
def test_a_pinned_target_cannot_be_changed(target: str) -> None:
    """A `LayoutPin` on a message the slide serves makes the corresponding action raise
    `PinnedTargetError`; the same action on an unpinned slide succeeds."""
    raise NotImplementedError


# -- layer 3: detection -------------------------------------------------------------------


@_SCAFFOLD
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
    raise NotImplementedError


@_SCAFFOLD
def test_the_fingerprint_ignores_everything_an_action_may_change() -> None:
    """Change style, component, communication mode, a block's slot and an icon's glyph and
    colour on a copy; the fingerprint is equal."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_buggy_applier_that_edits_a_claim_is_caught() -> None:
    """Monkeypatch `actions._apply_unchecked` to also rewrite a claim's text. `apply_action`
    raises `FactMutationError`. Then also patch `fact_fingerprint` to a constant and assert
    the same call succeeds — proving the green above comes from the check."""
    raise NotImplementedError
