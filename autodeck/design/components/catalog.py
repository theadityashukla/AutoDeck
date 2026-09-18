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
  `compute_budget` uses everywhere else. `two_column_compare`'s `point` slots are the one
  exception, capped to a single line on purpose — see `_two_column_compare_slots`.

These are upper bounds a slot could use *alone*; they are not a guarantee that every slot
filled to its own limit simultaneously fits the slide. That guarantee still rests on the
renderer's own `LayoutOverflowError` (§6.9's safety net) — this module makes overflow rare
by construction, per the phase brief, not impossible by construction.

Owning phase: 2b (task 2b.2). Geometry is re-derived per call from the caller's own
`DesignTokens`, never cached at import time: margins, gutters and the type scale all come
from the client's theme, and a different client's tokens genuinely move every box edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from autodeck.design.budgets import SlotBudget, compute_budget
from autodeck.design.components.renderers import big_number, two_column_compare
from autodeck.design.layout_kit import Box, Canvas, TextStyle
from autodeck.design.theme.tokens import DesignTokens

#: Any non-empty, non-wrapping text. A single line's height in `budgets.wrap_text` depends
#: only on the font's metrics, size and line spacing — never on which characters are in it
#: — so this exists purely to ask "how tall is one line", not to guess real content.
_CALIBRATION_LINE = "Ag"


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


def _big_number_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/big_number.py` computes for itself.

    Same split calls and gap constants as `render()`/`_render_headline()`/`_render_body()`,
    so a slot's box is a read of the renderer's own arithmetic. The renderer leaves exactly
    one thing undetermined until content exists — how the space between the caption strip
    and the slide edge divides between the headline and the figure block below it — and
    that is the one place this function makes a policy choice, documented in the module
    docstring: each of `headline` and `figure` gets the most height it could use while
    still leaving the other room for one line.
    """
    region, source_area = canvas.content.split_bottom(
        canvas.size("caption") * 1.6, gutter=canvas.gutter
    )

    headline_style = _role_style(canvas, "title", face="major")
    figure_style = _role_style(
        canvas, "display", face="major", size_scale=big_number._FIGURE_SCALE, line_spacing=0.95
    )
    label_style = _role_style(canvas, "heading")

    # The fixed distance `_render_headline` puts between the headline and the figure block:
    # a baseline gap, the rule itself, then a second, larger gap.
    gap_headline_to_body = (
        canvas.baseline * 3 + big_number._RULE_THICKNESS + canvas.baseline * 4
    )

    # The least the figure block ever needs: one line of the figure and one of its label,
    # with no supporting points and no support sentence (`_figure_block_height` adds more
    # only when those are present, so this is the true floor, not a typical case).
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

    figure_one_line = _one_line_height(canvas, figure_style, body_region.width)
    label_one_line = _one_line_height(canvas, label_style, body_region.width)

    figure_height = max(body_region.height - canvas.baseline - label_one_line, 0.0)
    figure_box = body_region.resize(height=figure_height)

    _, after_figure = body_region.split_top(figure_one_line, gutter=canvas.baseline)
    label_box = after_figure  # everything left once the figure has its one reserved line

    _, after_label = after_figure.split_top(label_one_line, gutter=canvas.baseline * 3)
    support_box = after_label  # optional, so it may fairly claim whatever else is left

    return [
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


# ---------------------------------------------------------------------------
# two_column_compare
# ---------------------------------------------------------------------------


def _two_column_compare_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/two_column_compare.py` computes for itself.

    Column width and x-position are genuinely fixed by `Box.split_columns` regardless of
    content, so those are copied exactly. Heights use the same "reserve one line for the
    sibling" policy as `_big_number_slots`, with one deliberate exception: `point`.

    `_row_heights` is what keeps a comparison's two sides level row by row, and the
    renderer's own module docstring names the failure that exists to prevent: "unequal row
    heights make the columns drift apart". A point that wraps to a second line grows *both*
    columns' row at once, visibly, before the panel-height overflow check ever gets a
    chance to fire — so `point` is capped to a single line on purpose, not sized by the
    reserve-headroom rule the other slots use.
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
    min_column_height = (
        two_column_compare._PANEL_PADDING * 2
        + _one_line_height(canvas, title_style, inner_width)
        + chrome
        + point_one_line
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

    def title_box(area: Box) -> Box:
        return area.pad(two_column_compare._PANEL_PADDING).resize(height=title_height)

    def point_box(area: Box) -> Box:
        inner = area.pad(two_column_compare._PANEL_PADDING)
        return inner.inset(left=two_column_compare._MARKER_INSET).resize(height=point_one_line)

    return [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major"),
        ComponentSlot(name="left_title", role="heading", box=title_box(left_area)),
        ComponentSlot(name="right_title", role="heading", box=title_box(right_area)),
        ComponentSlot(name="left_point", role="body", box=point_box(left_area)),
        ComponentSlot(name="right_point", role="body", box=point_box(right_area)),
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


def spec_for(component: str, tokens: DesignTokens) -> ComponentSpec:
    """Build `component`'s slot geometry for one client's theme.

    Rebuilt on every call rather than cached at import time — see the module docstring.

    Raises:
        UnknownComponentError: `component` is not in the catalog.
    """
    try:
        builder = _SLOT_BUILDERS[component]
    except KeyError:
        raise UnknownComponentError(
            f"no catalog entry for {component!r}. Known: {', '.join(known_components())}"
        ) from None
    return ComponentSpec(
        name=component,
        narrative_roles=_NARRATIVE_ROLES[component],
        slots=tuple(builder(Canvas(tokens))),
    )


def _budget(slot: ComponentSlot, tokens: DesignTokens) -> SlotBudget:
    style = slot.style(Canvas(tokens))
    return compute_budget(
        slot=slot.name,
        family=style.family,
        size_pt=style.size,
        width_pt=slot.box.width,
        height_pt=slot.box.height,
        line_spacing=style.line_spacing,
    )


def budget_for(component: str, slot: str, tokens: DesignTokens) -> SlotBudget:
    """The `SlotBudget` for one named slot of `component`, under `tokens`.

    Raises:
        UnknownComponentError: no such component or slot.
    """
    return _budget(spec_for(component, tokens).slot(slot), tokens)


def render_budgets(component: str, tokens: DesignTokens) -> str:
    """A compact block naming every slot's limit, ready to paste into the content prompt.

    §6.7: budgets reach the writer as explicit limits in its prompt, in terms it can hold
    in its head while writing — max characters and max lines, which is what `SlotBudget`
    already exposes through `describe()`. This function only has to assemble them.
    """
    spec = spec_for(component, tokens)
    lines = [f"{spec.name} text budgets:"]
    for slot in spec.slots:
        tag = "" if slot.required else " (optional)"
        lines.append(f"- {_budget(slot, tokens).describe()}{tag}")
    return "\n".join(lines)


def check_overflow(blocks: dict[str, str], component: str, tokens: DesignTokens) -> list[str]:
    """One finding per slot of `component` whose written text does not fit its budget.

    Returns findings rather than raising: the brief requires overflow to be rejected before
    render, but *how* — block the whole build, send one slide back, retry the writer — is
    an orchestrator decision, and Phase 2b's orchestrator wiring is a later task. This
    function only has to be right about which slots overflow.

    A required slot missing from `blocks` entirely is also reported: an omitted headline is
    not "zero overflow", it is a different failure the same deterministic gate should catch
    before render rather than after.
    """
    spec = spec_for(component, tokens)
    findings: list[str] = []
    for slot in spec.slots:
        text = blocks.get(slot.name)
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
