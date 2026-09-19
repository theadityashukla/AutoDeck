"""What text budgets look like once a component has a name — the content prompt's contract.

`budgets.py` can turn a box into a limit; nothing before this module turned a *component*
into a box. Without it the content agent has a measurement engine and nowhere to point it,
which is exactly v1's failure arriving one layer up: overflow was fought at render time
because nothing upstream declared how much a slot could hold. §6.7 requires slot budgets to
reach the writer as hard constraints *before* it writes, and this is the module that makes
"the slot" a concrete thing with a width and a height rather than a synonym for "some text".

Phase 3a (task 3a.3) grows this into the full ~15-30 component registry the plan describes
(§6.6); this is deliberately the two components that exist after Phase 0's design spike,
`big_number` and `two_column_compare`, and nothing else. Building the registry shape now,
ahead of the components it would hold, is the kind of premature structure the phase brief
warns against.

## Where the geometry comes from

A slot's box is read off the renderer that already computes it, not invented here — see
`docs/phases/PHASE-2B.md`'s 2b.2 entry. Two kinds of number appear:

* **Width and column position** are genuinely fixed by the renderer's own `Box` arithmetic
  (`split_columns`, `split_bottom`, padding constants) and do not depend on what the writer
  puts in any slot. These are copied exactly.
* **Height**, for a slot the renderer sizes to its own measured content (`canvas.fit`), has
  no single fixed value in the renderer — by design, since that is precisely what lets a
  one-line headline and a two-line headline both produce a correctly-laid-out slide. A
  *budget* still needs a number, so each such slot gets the most height it could use while
  guaranteeing every sibling slot still has room for at least one line of its own text —
  never the whole remaining region, which would make the budget vacuous, and never a made-up
  constant, since the "one line" reservation is measured from the same real font metrics
  `compute_budget` uses everywhere else. `two_column_compare`'s `point` slots keep a single
  line on purpose — see `_two_column_compare_slots` for what that cap actually buys, which
  turns out **not** to be the row-parity argument an earlier version of this docstring made.

These are upper bounds a slot could use *alone*; they are not a guarantee that every slot
filled to its own limit simultaneously fits the slide. That guarantee still rests on the
renderer's own `LayoutOverflowError` (§6.9's safety net) — this module makes overflow rare
by construction, per the phase brief, not impossible by construction.

## Repeatable slots: a real content model is a list, not one string

Two real cases have content that is a **list** of independent, roughly-one-line items
rather than one block of prose: `two_column_compare`'s columns carry several `points`, not
one, and `big_number.supporting_points` is a list too. A `ComponentSlot` with
`repeatable=True` declares that shape: `box` is the whole area the stack may use, `item_box`
is the area **one** item gets, and `row_gap` is the gap the renderer actually puts between
rows — read off the renderer's own gutter constant, never invented. `check_overflow` checks
each item against `item_box` and the whole stack against `box`; `budget_for` on a repeatable
slot returns the per-item budget, since that is the number a writer can hold in its head
while composing one bullet.

`big_number.supporting_points` carries a second wrinkle: writing it switches the renderer
to a **two-column layout** (`_render_body`), so `figure`, `figure_label` and `support` are
each half the width they are when `supporting_points` is empty. `spec_for` takes
`has_supporting_points` to select which geometry applies, and `check_overflow` infers it
from whether the caller's own `blocks` mapping has a non-empty `supporting_points` entry —
a caller checking real content never has to know the flag exists.

Owning phase: 2b (task 2b.2). Geometry is re-derived per call from the caller's own
`DesignTokens`, never cached at import time: margins, gutters and the type scale all come
from the client's theme, and a different client's tokens genuinely move every box edge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from autodeck.design.budgets import SlotBudget, compute_budget
from autodeck.design.components.renderers import big_number, two_column_compare
from autodeck.design.layout_kit import Box, Canvas, TextStyle
from autodeck.design.theme.tokens import DesignTokens

#: The component library's version, and the only definition of it.
#:
#: A6 requires the build manifest to record it, and `Deck.component_lib_version` records it
#: too — a deck laid out against different slot geometry is a different deck even from the
#: same IR. Two literals would be two answers to one question, and the manifest's would be
#: the one nobody noticed had gone stale, so both read this. Bump it whenever a slot's box,
#: its style, or the set of components changes.
COMPONENT_LIB_VERSION = "0.1.0"

#: Any non-empty, non-wrapping text. A single line's height in `budgets.wrap_text` depends
#: only on the font's metrics, size and line spacing — never on which characters are in it
#: — so this exists purely to ask "how tall is one line", not to guess real content.
_CALIBRATION_LINE = "Ag"

#: What a slot's real content looks like: one block of prose, or — for a `repeatable`
#: slot — a list of independent, roughly-one-line items.
BlockValue = str | Sequence[str]


class UnknownComponentError(ValueError):
    """No catalog entry for a component or slot name.

    A `KeyError` would read naturally here, but every other unknown-name failure in the
    design system (`layout_kit.Canvas.size`, `draw.theme_color`) raises `ValueError` with
    the valid options listed in the message, and matching that is worth more than the
    marginal precision of a different exception type.
    """


@dataclass(frozen=True)
class ComponentSlot:
    """One text slot inside a component: where it sits, and what type-scale role it uses.

    `role` names one of `Canvas.style`'s roles (display/title/heading/body/caption) so a
    slot's type size and default line spacing always come from the theme, never a number
    written here. A slot rendered *off* that role — `big_number`'s figure, at 2x the
    display size — says so through `size_scale`, itself lifted from the renderer's own
    `_FIGURE_SCALE` constant rather than a fresh guess at "how much bigger".
    """

    name: str
    role: str
    box: Box
    face: Literal["major", "minor"] = "minor"
    size_scale: float = 1.0
    line_spacing: float | None = None
    """Overrides the role's default line spacing when the renderer's own style does — e.g.
    the figure is set at 0.95 rather than the tight 1.15 `display`/`title`/`heading` share.
    `None` means "use whatever `Canvas.style` gives that role", not "single-spaced"."""
    required: bool = True
    repeatable: bool = False
    """True when this slot holds a LIST of independent, roughly-one-line items stacked top
    to bottom — `two_column_compare`'s `points`, `big_number.supporting_points` — rather
    than one block of prose. `box` is then the whole area the stack may use; `item_box` and
    `row_gap` say what one item gets and what separates two of them."""
    item_box: Box | None = None
    """Only set when `repeatable`: the box ONE item may use. Same width as `box`; height is
    one line at this slot's `role`, read the same way every other height in this module is —
    measured, not guessed."""
    row_gap: float = 0.0
    """Vertical gap between stacked items. Only meaningful when `repeatable`; always the
    renderer's own gap constant between rows, never invented here."""

    def style(self, canvas: Canvas) -> TextStyle:
        """The exact `TextStyle` the renderer builds for this slot, from `canvas`'s tokens."""
        style = canvas.style(self.role, face=self.face)
        overrides: dict[str, object] = {}
        if self.size_scale != 1.0:
            overrides["size"] = style.size * self.size_scale
        if self.line_spacing is not None:
            overrides["line_spacing"] = self.line_spacing
        return style.with_(**overrides) if overrides else style


@dataclass(frozen=True)
class ComponentSpec:
    """A component's name, the narrative jobs it can do, and its slots."""

    name: str
    narrative_roles: tuple[str, ...]
    slots: tuple[ComponentSlot, ...]

    def slot(self, name: str) -> ComponentSlot:
        for candidate in self.slots:
            if candidate.name == name:
                return candidate
        known = ", ".join(s.name for s in self.slots)
        raise UnknownComponentError(f"{self.name!r} has no slot {name!r}. Known: {known}")


def _one_line_height(canvas: Canvas, style: TextStyle, width: float) -> float:
    """The height of exactly one line in `style` at `width`.

    Used only to reserve headroom for a *sibling* slot — never to guess how much text that
    sibling will actually hold. See the module docstring's "where the geometry comes from".
    """
    return canvas.measure(_CALIBRATION_LINE, width, style)


def _role_style(
    canvas: Canvas,
    role: str,
    *,
    face: Literal["major", "minor"] = "minor",
    size_scale: float = 1.0,
    line_spacing: float | None = None,
) -> TextStyle:
    """`ComponentSlot.style`'s logic, usable before a `ComponentSlot` exists yet — the slot
    builders below need a style to measure headroom with before they can build the slot
    that will eventually carry the same parameters."""
    style = canvas.style(role, face=face)
    overrides: dict[str, object] = {}
    if size_scale != 1.0:
        overrides["size"] = style.size * size_scale
    if line_spacing is not None:
        overrides["line_spacing"] = line_spacing
    return style.with_(**overrides) if overrides else style


# ---------------------------------------------------------------------------
# big_number
# ---------------------------------------------------------------------------


def _big_number_slots(
    canvas: Canvas, *, has_supporting_points: bool = False
) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/big_number.py` computes for itself.

    Same split calls and gap constants as `render()`/`_render_headline()`/`_render_body()`,
    so a slot's box is a read of the renderer's own arithmetic. The renderer leaves exactly
    one thing undetermined until content exists — how the space between the caption strip
    and the slide edge divides between the headline and the figure block below it — and
    that is the one place this function makes a policy choice, documented in the module
    docstring: each of `headline` and `figure` gets the most height it could use while
    still leaving the other room for one line.

    `has_supporting_points` mirrors `_render_body`'s own branch exactly: the moment
    `supporting_points` is non-empty, the renderer halves `body_region` into a figure column
    and a points column (`region.split_columns(2, canvas.gutter * 2)`), so `figure`,
    `figure_label` and `support` are each half the width they are otherwise. Getting this
    wrong is the carried finding from reviewing 2b.2 — the catalog had no slot for
    `supporting_points` at all, so the three slots it did declare were silently wrong by
    half in exactly the mode the codebase's own example (`design/spikes.py`) uses.
    """
    region, source_area = canvas.content.split_bottom(
        canvas.size("caption") * 1.6, gutter=canvas.gutter
    )

    headline_style = _role_style(canvas, "title", face="major")
    figure_style = _role_style(
        canvas, "display", face="major", size_scale=big_number._FIGURE_SCALE, line_spacing=0.95
    )
    label_style = _role_style(canvas, "heading")
    point_style = _role_style(canvas, "body")

    # The fixed distance `_render_headline` puts between the headline and the figure block:
    # a baseline gap, the rule itself, then a second, larger gap.
    gap_headline_to_body = (
        canvas.baseline * 3 + big_number._RULE_THICKNESS + canvas.baseline * 4
    )

    # The least the figure block ever needs: one line of the figure and one of its label,
    # with no supporting points and no support sentence (`_figure_block_height` adds more
    # only when those are present, so this is the true floor, not a typical case). Measured
    # at the full region width: whether a one-line calibration string wraps does not depend
    # on which of the (equal) half-widths it is measured against once columns split, so the
    # reservation is the same either way and only the final boxes' widths differ below.
    min_figure_block = (
        _one_line_height(canvas, figure_style, region.width)
        + canvas.baseline
        + _one_line_height(canvas, label_style, region.width)
    )
    headline_height = max(region.height - gap_headline_to_body - min_figure_block, 0.0)
    headline_box = region.resize(height=headline_height)

    # Mirror image: bound the figure block by assuming the headline takes only one line.
    headline_one_line = _one_line_height(canvas, headline_style, region.width)
    _, body_region = region.split_top(headline_one_line, gutter=gap_headline_to_body)

    # `_render_body`'s own branch: split into a figure column and a points column, or don't.
    if has_supporting_points:
        content_region, points_region = body_region.split_columns(2, canvas.gutter * 2)
    else:
        content_region, points_region = body_region, None

    figure_one_line = _one_line_height(canvas, figure_style, content_region.width)
    label_one_line = _one_line_height(canvas, label_style, content_region.width)

    figure_height = max(body_region.height - canvas.baseline - label_one_line, 0.0)
    figure_box = content_region.resize(height=figure_height)

    _, after_figure = content_region.split_top(figure_one_line, gutter=canvas.baseline)
    label_box = after_figure  # everything left once the figure has its one reserved line

    _, after_label = after_figure.split_top(label_one_line, gutter=canvas.baseline * 3)
    support_box = after_label  # optional, so it may fairly claim whatever else is left

    slots = [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major"),
        ComponentSlot(
            name="figure",
            role="display",
            box=figure_box,
            face="major",
            size_scale=big_number._FIGURE_SCALE,
            line_spacing=0.95,
        ),
        ComponentSlot(name="figure_label", role="heading", box=label_box),
        ComponentSlot(name="support", role="body", box=support_box, required=False),
        ComponentSlot(name="source", role="caption", box=source_area, required=False),
    ]

    if points_region is not None:
        # The bound the renderer itself already guards with: `_render_body` raises
        # `LayoutOverflowError` if `block_height > region.height`, where its `region` is
        # this function's `body_region` — so `body_region.height` is not invented here, it
        # is the same ceiling the render-time safety net already enforces.
        point_one_line = _one_line_height(canvas, point_style, points_region.width)
        slots.append(
            ComponentSlot(
                name="supporting_points",
                role="body",
                box=points_region.resize(height=body_region.height),
                item_box=points_region.resize(height=point_one_line),
                row_gap=canvas.baseline * 2.5,  # `_render_supporting_points`'s own gutter.
                repeatable=True,
                required=False,
            )
        )
    return slots


# ---------------------------------------------------------------------------
# two_column_compare
# ---------------------------------------------------------------------------


def _two_column_compare_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/two_column_compare.py` computes for itself.

    Column width and x-position are genuinely fixed by `Box.split_columns` regardless of
    content, so those are copied exactly. Heights use the same "reserve one line for the
    sibling" policy as `_big_number_slots`.

    **`point`'s single-line cap — corrected.** An earlier version of this docstring justified
    capping `point` to one line by claiming a wrapped point would "grow both columns' row at
    once... before the panel-height overflow check ever gets a chance to fire", as if
    wrapping broke row parity. Checked against the renderer, that is not true: `_row_heights`
    measures each row's real height with `canvas.measure` — wrapped or not — and takes the
    max across both columns for that row, so the two sides stay level regardless of how many
    lines a point wraps to. Row parity survives wrapping by construction; it was never what
    the cap protected.

    The cap is kept anyway, on a different and honest justification: a comparison `point` is
    meant to be a scannable phrase, and a point that wraps to a paragraph stops reading as a
    bullet next to its neighbour, cap or no cap. The real content model — `points`, plural,
    several per column — is `left_points`/`right_points` below, and *that* is where the
    carried finding from reviewing 2b.2 lived: multi-point columns had no budget coverage
    at all, singular `point` covering only the single-item case `design/spikes.py` never
    actually exercises alone.
    """
    region, source_area = canvas.content.split_bottom(
        canvas.size("caption") * 1.6, gutter=canvas.gutter
    )
    left_area, right_area = region.split_columns(2, canvas.gutter * 1.5)

    headline_style = _role_style(canvas, "title", face="major")
    title_style = _role_style(canvas, "heading")  # face defaults to minor, unlike big_number
    point_style = _role_style(canvas, "body")

    inner_width = left_area.width - two_column_compare._PANEL_PADDING * 2
    text_width = inner_width - two_column_compare._MARKER_INSET

    # `_content_height`'s fixed chrome: gap under the title, the rule, gap under the rule.
    chrome = canvas.baseline * 1.5 + two_column_compare._RULE_THICKNESS + canvas.baseline * 3
    point_one_line = _one_line_height(canvas, point_style, text_width)
    title_one_line = _one_line_height(canvas, title_style, inner_width)
    min_column_height = (
        two_column_compare._PANEL_PADDING * 2 + title_one_line + chrome + point_one_line
    )
    gap_after_headline = canvas.baseline * 5

    headline_height = max(region.height - gap_after_headline - min_column_height, 0.0)
    headline_box = region.resize(height=headline_height)

    headline_one_line = _one_line_height(canvas, headline_style, region.width)
    _, body_area = region.split_top(headline_one_line, gutter=gap_after_headline)

    # `panel_height` in the renderer is the *max* of the two columns' own content heights,
    # and the overflow check compares that max against `body_area.height` — so neither
    # column alone may exceed it either, and both share one height ceiling here.
    title_height = max(
        body_area.height - two_column_compare._PANEL_PADDING * 2 - chrome - point_one_line,
        0.0,
    )
    # The row stack's own ceiling, symmetric with `title_height` above: title gets the most
    # height it can use while reserving one line for the row stack; the row stack gets the
    # most height it can use while reserving one line for the title. Neither reservation
    # assumes how many rows the writer actually uses — `check_overflow` is what checks the
    # real count, against whichever of `left_points`/`right_points` the writer filled in.
    points_height = max(
        body_area.height - two_column_compare._PANEL_PADDING * 2 - chrome - title_one_line,
        0.0,
    )

    def title_box(area: Box) -> Box:
        return area.pad(two_column_compare._PANEL_PADDING).resize(height=title_height)

    def point_box(area: Box) -> Box:
        inner = area.pad(two_column_compare._PANEL_PADDING)
        return inner.inset(left=two_column_compare._MARKER_INSET).resize(height=point_one_line)

    def points_box(area: Box) -> Box:
        inner = area.pad(two_column_compare._PANEL_PADDING)
        return inner.inset(left=two_column_compare._MARKER_INSET).resize(height=points_height)

    row_gap = canvas.baseline * 2.5  # `_render_column`'s own gap between rows.

    return [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major"),
        ComponentSlot(name="left_title", role="heading", box=title_box(left_area)),
        ComponentSlot(name="right_title", role="heading", box=title_box(right_area)),
        # Not required: the real content model is `left_points`/`right_points` below, a
        # LIST of several. These singular slots stay for a caller that genuinely has one
        # point, and requiring them would reject a slide that only ever fills the plural
        # form.
        ComponentSlot(name="left_point", role="body", box=point_box(left_area), required=False),
        ComponentSlot(
            name="right_point", role="body", box=point_box(right_area), required=False
        ),
        ComponentSlot(
            name="left_points",
            role="body",
            box=points_box(left_area),
            item_box=point_box(left_area),
            row_gap=row_gap,
            repeatable=True,
            required=False,
        ),
        ComponentSlot(
            name="right_points",
            role="body",
            box=points_box(right_area),
            item_box=point_box(right_area),
            row_gap=row_gap,
            repeatable=True,
            required=False,
        ),
        ComponentSlot(name="source", role="caption", box=source_area, required=False),
    ]


# ---------------------------------------------------------------------------
# The catalog itself
# ---------------------------------------------------------------------------

_SLOT_BUILDERS = {
    "big_number": _big_number_slots,
    "two_column_compare": _two_column_compare_slots,
}

_NARRATIVE_ROLES: dict[str, tuple[str, ...]] = {
    "big_number": ("headline metric", "single-figure proof point"),
    "two_column_compare": ("comparison", "recommendation"),
}


def known_components() -> list[str]:
    return sorted(_SLOT_BUILDERS)


def spec_for(
    component: str, tokens: DesignTokens, *, has_supporting_points: bool = False
) -> ComponentSpec:
    """Build `component`'s slot geometry for one client's theme.

    Rebuilt on every call rather than cached at import time — see the module docstring.

    Args:
        has_supporting_points: only meaningful for `big_number`. Selects the two-column
            geometry `_render_body` switches to the moment `supporting_points` is
            non-empty — narrower `figure`/`figure_label`/`support` and an extra
            `supporting_points` slot. Ignored by every other component.

    Raises:
        UnknownComponentError: `component` is not in the catalog.
    """
    try:
        builder = _SLOT_BUILDERS[component]
    except KeyError:
        raise UnknownComponentError(
            f"no catalog entry for {component!r}. Known: {', '.join(known_components())}"
        ) from None
    canvas = Canvas(tokens)
    slots = (
        builder(canvas, has_supporting_points=has_supporting_points)
        if component == "big_number"
        else builder(canvas)
    )
    return ComponentSpec(
        name=component,
        narrative_roles=_NARRATIVE_ROLES[component],
        slots=tuple(slots),
    )


def _budget(slot: ComponentSlot, tokens: DesignTokens) -> SlotBudget:
    """The `SlotBudget` for a whole (non-repeatable) slot's own box."""
    style = slot.style(Canvas(tokens))
    return compute_budget(
        slot=slot.name,
        family=style.family,
        size_pt=style.size,
        width_pt=slot.box.width,
        height_pt=slot.box.height,
        line_spacing=style.line_spacing,
    )


def _item_budget(slot: ComponentSlot, tokens: DesignTokens) -> SlotBudget:
    """The `SlotBudget` for ONE item of a `repeatable` slot.

    This, not `_budget`, is the number a writer composing a single bullet needs — `_budget`
    on a repeatable slot's own `box` would describe the whole stack's height as if it were
    one line's budget, which no single item is meant to fill alone.
    """
    assert slot.item_box is not None, f"{slot.name!r} is not repeatable"
    style = slot.style(Canvas(tokens))
    return compute_budget(
        slot=f"{slot.name} (each item)",
        family=style.family,
        size_pt=style.size,
        width_pt=slot.item_box.width,
        height_pt=slot.item_box.height,
        line_spacing=style.line_spacing,
    )


def _max_items(slot: ComponentSlot) -> int:
    """How many items fit in a repeatable slot's stack, gaps included.

    `n` items need `n * item_height + (n - 1) * row_gap`; solving that for the box's own
    height gives the floor below. Used only to tell the writer a number it can hold in its
    head — `check_overflow` re-derives the same bound from the real item count it is given,
    rather than trusting this estimate.
    """
    assert slot.item_box is not None, f"{slot.name!r} is not repeatable"
    row = slot.item_box.height + slot.row_gap
    if row <= 0:
        return 0
    return max(int((slot.box.height + slot.row_gap + 1e-6) // row), 0)


def budget_for(
    component: str, slot: str, tokens: DesignTokens, *, has_supporting_points: bool = False
) -> SlotBudget:
    """The `SlotBudget` for one named slot of `component`, under `tokens`.

    For a `repeatable` slot this is the **per-item** budget (see `_item_budget`), since that
    is the constraint a writer composing one bullet actually needs.

    Raises:
        UnknownComponentError: no such component or slot.
    """
    resolved = spec_for(component, tokens, has_supporting_points=has_supporting_points).slot(
        slot
    )
    return _item_budget(resolved, tokens) if resolved.repeatable else _budget(resolved, tokens)


def render_budgets(component: str, tokens: DesignTokens) -> str:
    """A compact block naming every slot's limit, ready to paste into the content prompt.

    §6.7: budgets reach the writer as explicit limits in its prompt, in terms it can hold
    in its head while writing — max characters and max lines, which is what `SlotBudget`
    already exposes through `describe()`. This function only has to assemble them.

    For `big_number`, the widths above assume `supporting_points` stays empty; a note and
    the narrower alternative are appended, because the writer decides which mode it is in
    by whether it writes that field, not by reading a flag this function cannot see yet.
    """
    spec = spec_for(component, tokens)
    lines = [f"{spec.name} text budgets:"]
    for slot in spec.slots:
        lines.append(f"- {_describe_slot(slot, tokens)}{_optional_tag(slot)}")

    if component == "big_number":
        narrow = spec_for(component, tokens, has_supporting_points=True)
        lines.append(
            "if you write supporting_points: figure/figure_label/support share the slide "
            "with them in two columns and are NARROWER than the widths above:"
        )
        for name in ("figure", "figure_label", "support", "supporting_points"):
            slot = narrow.slot(name)
            lines.append(f"  - {_describe_slot(slot, tokens)}{_optional_tag(slot)}")
    return "\n".join(lines)


def _describe_slot(slot: ComponentSlot, tokens: DesignTokens) -> str:
    if not slot.repeatable:
        return _budget(slot, tokens).describe()
    item = _item_budget(slot, tokens)
    return (
        f"{slot.name}: a LIST of items, up to {_max_items(slot)} of them, each at most "
        f"{item.max_lines} line(s), roughly {item.max_chars} characters, at "
        f"{item.size_pt:g}pt {item.family}"
    )


def _optional_tag(slot: ComponentSlot) -> str:
    return "" if slot.required else " (optional)"


def check_overflow(
    blocks: Mapping[str, BlockValue], component: str, tokens: DesignTokens
) -> list[str]:
    """One finding per slot of `component` whose written content does not fit its budget.

    Returns findings rather than raising: the brief requires overflow to be rejected before
    render, but *how* — block the whole build, send one slide back, retry the writer — is
    an orchestrator decision, and Phase 2b's orchestrator wiring is a later task. This
    function only has to be right about which slots overflow.

    A required slot missing from `blocks` entirely is also reported: an omitted headline is
    not "zero overflow", it is a different failure the same deterministic gate should catch
    before render rather than after.

    For `big_number`, whether `supporting_points` is a non-empty entry in `blocks` decides
    which geometry `figure`/`figure_label`/`support` are checked against — the caller never
    has to pass a separate flag for content it is already handing over.

    A `repeatable` slot's value is a `Sequence[str]`: each item is checked against the
    slot's per-item budget, and the whole list's stacked height (items plus the gaps between
    them) is checked against the slot's own box — the aggregate check the singular `point`
    slots never had, which is the carried finding this function closes.
    """
    has_supporting_points = component == "big_number" and bool(blocks.get("supporting_points"))
    spec = spec_for(component, tokens, has_supporting_points=has_supporting_points)
    findings: list[str] = []
    for slot in spec.slots:
        value = blocks.get(slot.name)
        if slot.repeatable:
            findings.extend(_check_repeatable(component, slot, value, tokens))
            continue
        text = value if isinstance(value, str) else None
        if not text:
            if slot.required:
                findings.append(f"{component}.{slot.name}: required slot is missing or empty")
            continue
        budget = _budget(slot, tokens)
        if not budget.fits(text):
            findings.append(
                f"{component}.{slot.name}: {len(text)} characters does not fit "
                f"({budget.describe()})"
            )
    return findings


def _items_of(value: BlockValue | None) -> list[str]:
    """Normalise a repeatable slot's value to a list, tolerating a bare string as one item."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [item for item in value if item]


def _check_repeatable(
    component: str, slot: ComponentSlot, value: BlockValue | None, tokens: DesignTokens
) -> list[str]:
    assert slot.item_box is not None, f"{slot.name!r} is not repeatable"
    items = _items_of(value)
    if not items:
        if slot.required:
            return [f"{component}.{slot.name}: required slot is missing or empty"]
        return []

    item_budget = _item_budget(slot, tokens)
    findings = [
        f"{component}.{slot.name}[{index}]: {len(item)} characters does not fit "
        f"({item_budget.describe()})"
        for index, item in enumerate(items)
        if not item_budget.fits(item)
    ]

    total_height = len(items) * slot.item_box.height + max(len(items) - 1, 0) * slot.row_gap
    if total_height > slot.box.height + 1e-6:
        findings.append(
            f"{component}.{slot.name}: {len(items)} item(s) need {total_height:.0f}pt "
            f"stacked but only {slot.box.height:.0f}pt is available"
        )
    return findings
