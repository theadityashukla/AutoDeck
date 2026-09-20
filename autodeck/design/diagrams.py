"""The diagram engine (task 3a.6): `DiagramSpec` payloads rendered as native shapes.

`autodeck.ir.models` did the type-system work (task 3a.6a) — a geometry-matches-relationship
type, per-geometry node types, a declared word budget, and `GEOMETRIES` as the one lookup for
"what shape, what budget, what anchor". This module turns that IR into a real slide: one
`<p:sp>` (or `<p:cxnSp>`) per node and per connector, every fill and line a `schemeClr` theme
reference, never an image.

## Why this is a function, not a `catalog.register()` entry

`components/catalog.py`'s registration takes a `SlotBuilder` that returns a fixed set of
boxes for a `Canvas` — the box layout does not depend on the content. A diagram's layout
depends on how many nodes it has, so it cannot be expressed as one of those slot builders
without inventing a variant per node count. `GEOMETRIES` is the parallel registry this
module reads instead; `place_diagram` is this phase's equivalent of `renderer_for(...)`,
called directly by whatever component embeds a diagram (`framework_diagram`, `timeline` —
task 3a.4) rather than looked up through the catalog. See PHASE-3A's note on this task for
why unifying the two is deliberately not attempted here.

## What is measured here versus at construction

`DiagramSpec` already enforces the *word* budget (`GEOMETRIES[kind].max_label_words`) at
construction — a label over that word count cannot exist. It cannot know whether those words
render inside the actual box a real deck gives them at a real font, because it may not import
`design/`. That is this module's other job: every label is measured with the exact
`TextStyle` it is drawn with (bold/italic included — the 3a.6 fix `budgets.py`'s module
docstring describes) and placed through `Box.reserve`, so a label that is short enough by
word count but still will not fit raises `LayoutOverflowError` rather than being drawn
past an edge. Nothing here shrinks, truncates or estimates to make a label fit (same rule
`layout_kit` states for itself).

## `spec.title` is not drawn here

`DiagramSpec._labels_fit_the_budget` exempts `title` from the geometry's word budget with
the reason "set in the component's own slot and measured there" — the diagram engine draws
the geometry a component embeds, not the headline around it. A caller that wants the title
shown uses its own headline slot for it, the way `framework_diagram` will.

## Citations

A1 is enforced on `DiagramNode.claim` at construction (`autodeck.ir.models`); nothing here
re-derives nodes, so `DiagramSpec.claim_nodes()`'s identity contract (a verdict written back
through a `ClaimSite` lands on the object actually rendered) holds automatically — this
module draws each geometry's own stored node objects, never a rebuilt copy. What is *not*
done here is printing a citation marker in the shape: the audit report is the citation's
reader-facing home for every other claim in this codebase (`Block`'s renderers all carry the
same "rendered from the block's citation; the audit report is the authority" note), and a
diagram node's claim is no different.

## Geometry math: `construction.md` versus derived here

The chevron overlap ratio, the stack's rest-on taper, and the 2x2's margin/pairing layout are
not given numerically in `references/construction.md` — each is called out at its own
constant with why. Everything else (axis lines crossing at the plot centre, quadrant tints
never boxed, foundation widest at the bottom, chevrons nesting) is read directly from the
"Chevron / path sequence", "True 2x2" and "Four strata" recipes.

Owning phase: 3a (task 3a.6b); the type system (3a.6a) is `autodeck.ir.models`.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable

from autodeck.design.budgets import load_metrics
from autodeck.design.draw import add_autoshape, add_connector
from autodeck.design.layout_kit import (
    Align,
    Box,
    Canvas,
    Frame,
    LayoutOverflowError,
    TextBlock,
    TextStyle,
    VAlign,
)
from autodeck.ir.models import (
    DiagramKind,
    DiagramSpec,
    LayeredStackSpec,
    ProcessFlowSpec,
    TwoByTwoSpec,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _measure(
    canvas: Canvas, text: str, width: float, style: TextStyle, *, what: str
) -> TextBlock:
    """`canvas.measure_block`, raising the same way `Stack.text` does for a word that
    cannot wrap into `width` at all — the diagram engine's own labels get the identical
    "this cannot be rescued by wrapping" message `layout_kit` already uses.
    """
    block = canvas.measure_block(text, width, style)
    if block.too_wide_words:
        raise LayoutOverflowError(
            f"{what}: {', '.join(repr(w) for w in block.too_wide_words[:3])} "
            f"{'is' if len(block.too_wide_words) == 1 else 'are'} wider than the "
            f"{width:.0f}pt available at {style.size:g}pt {style.family}. Wrapping cannot "
            "fix a single over-wide word — shorten it, or give the diagram a wider slot."
        )
    return block


def _place_label(frame: Frame, box: Box, text: str, style: TextStyle, *, what: str) -> None:
    """Measure `text` against `style` in `box`'s width, fit it into `box`'s height, draw it.

    The one place every node/pole/axis label in this module goes through — measured with
    the exact style it draws with, raising `LayoutOverflowError` through `Box.reserve`
    rather than drawing past `box`'s edge.
    """
    block = _measure(frame.canvas, text, box.width, style, what=what)
    fitted = box.reserve(block.height, valign=style.valign, what=what)
    frame.text(fitted, text, style)


def _text_width(style: TextStyle, text: str) -> float:
    """The natural, unwrapped width of `text` at `style` — real glyph metrics, not a guess.

    Distinct from `_measure`: `Canvas.measure_block` answers "how tall at this width",
    which is the wrong question for sizing a margin around a short pole label or axis name.
    This is `budgets.py`'s own `FontMetrics.text_width`, the same measurement `compute_budget`
    is built on.
    """
    metrics = load_metrics(style.family, bold=style.bold, italic=style.italic)
    return metrics.text_width(text, style.size)


def _anchor(
    width: float,
    height: float,
    x: float,
    y: float,
    *,
    halign: Align = "left",
    valign: VAlign = "top",
) -> Box:
    """A `width` x `height` box positioned relative to the point `(x, y)`.

    Reuses `Box.align_within` against a zero-extent box at the point: `align_within`'s
    three horizontal/vertical cases all collapse to that single point when the outer box
    has no width or height, which is exactly a point-anchored placement — `two_by_two`'s
    pole labels, axis names and item labels all sit relative to a point on an axis line or
    a plotted dot, not inside an already-known outer box. No new geometry primitive was
    needed for it, so none was added to `layout_kit`.
    """
    return Box(0, 0, width, height).align_within(
        Box(x, y, 0, 0), horizontal=halign, vertical=valign
    )


# ---------------------------------------------------------------------------
# process_flow — chevron sequence (construction.md, "Chevron / path sequence")
# ---------------------------------------------------------------------------

#: `construction.md` says only "slight negative spacing so points nest" — no number.
#: Derived here: the CHEVRON preset's point/notch is a fixed fraction of its own width
#: (default `adj` 50%), so overlapping adjacent chevrons by about a fifth of one chevron's
#: width tucks each point under the next chevron's notch without the notch eating into the
#: label. Confirmed by eye against a LibreOffice render (`tests/test_diagram_renderers.py`).
_CHEVRON_OVERLAP_RATIO = 0.18

#: A single chevron reads as a flow arrow at a landscape aspect (wide, not tall); given the
#: full available height it would be a tall panel with a barely-there point. Not given by
#: `construction.md`; confirmed by eye. `_render_process_flow` never uses more height than
#: it is given, so a very short box still gets whatever height it has.
_CHEVRON_ASPECT = 2.0

#: python-pptx's `MSO_SHAPE.CHEVRON` default adjustment (`shape.adjustments[0]`), confirmed
#: against a real shape rather than assumed. The OOXML "chevron" preset geometry (ECMA-376
#: §20.1.10.19) cuts the notch tip in from the left edge by `adj * min(w, h) / 2`; at the
#: shape's vertical centre — where a label sits — the *filled* region therefore starts at
#: that notch tip, not at the left edge, and a label centred on the raw bounding box drifts
#: into the unfilled notch. `_CHEVRON_TEXT_PAD` is the extra clearance from that edge and
#: from the point on the right, which the formula does not need but a legible label does.
_CHEVRON_ADJ = 0.5
_CHEVRON_TEXT_PAD = 6.0

#: Gap between a transition's label and the arrow under it, and between that arrow and the
#: bottom of the row reserved for it. `construction.md` gives "2-4pt" for an unrelated
#: recipe's (funnel) vertical gaps; reused here for the same "small but visible" reason.
_TRANSITION_ARROW_GAP = 4.0
_TRANSITION_ROW_GAP = 4.0


def _render_process_flow(frame: Frame, box: Box, spec: DiagramSpec) -> None:
    canvas = frame.canvas
    payload = spec.payload_as(ProcessFlowSpec)
    steps = payload.steps_in_order()
    count = len(steps)

    label_style = canvas.style("body", align="center", valign="middle", bold=True)
    transition_style = canvas.style("caption", color="dk2", align="center", valign="bottom")

    #: `ProcessStep.transition` is the label on the arrow *leaving* that step — one entry
    #: per adjacent pair that declares one, in step order.
    transition_pairs = [
        (first, second) for first, second in itertools.pairwise(steps) if first.transition
    ]

    transition_row: Box | None
    if transition_pairs:
        row_height = max(
            canvas.measure(first.transition or "", box.width, transition_style)
            for first, _ in transition_pairs
        )
        band = row_height + _TRANSITION_ARROW_GAP + _TRANSITION_ROW_GAP
        chevron_row, transition_row = box.split_bottom(band, gutter=0.0)
    else:
        row_height = 0.0
        chevron_row, transition_row = box, None

    # Equal-width chevrons overlapping by `_CHEVRON_OVERLAP_RATIO` of one chevron's own
    # width, spanning exactly `chevron_row.width` end to end.
    step_width = chevron_row.width / (count - (count - 1) * _CHEVRON_OVERLAP_RATIO)
    advance = step_width * (1 - _CHEVRON_OVERLAP_RATIO)
    band = chevron_row.reserve(
        min(chevron_row.height, step_width / _CHEVRON_ASPECT),
        valign="middle",
        what="process_flow chevrons",
    )
    notch_depth = _CHEVRON_ADJ * min(step_width, band.height) / 2

    centers: list[float] = []
    for index, step in enumerate(steps):
        node_box = Box(band.x + index * advance, band.y, step_width, band.height)
        centers.append(node_box.center_x)

        # construction.md: "first or final chevron carries the accent depending on whether
        # the argument emphasizes the start or the destination." Not something
        # `ProcessFlowSpec` declares either way, so the destination (the final step) is the
        # default — the more common consulting narrative ("this is where we land").
        is_destination = index == count - 1
        add_autoshape(
            frame.slide,
            node_box,
            "CHEVRON",
            fill="accent1",
            fill_brightness=0.10 if is_destination else 0.62,
        )
        # Later chevrons are added after earlier ones, so python-pptx's z-order already
        # draws each one on top of its left-hand neighbour — the overlap covers the
        # previous chevron's point rather than being covered by it.

        text_x0 = node_box.x + notch_depth + _CHEVRON_TEXT_PAD
        text_x1 = node_box.right - _CHEVRON_TEXT_PAD
        text_box = Box(text_x0, node_box.y, max(text_x1 - text_x0, 0.0), node_box.height)
        style = label_style.with_(color="lt1" if is_destination else "dk1")
        _place_label(
            frame, text_box, step.label, style, what=f"process_flow step {step.id!r} label"
        )

    if transition_row is None:
        return

    # Transition arrows and labels live in their own row below the chevrons rather than
    # between them: nested chevrons leave no gap wide enough for a label, and
    # `construction.md`'s chevron recipe does not address labelled transitions at all —
    # this row is derived to give `ProcessStep.transition` somewhere to be drawn.
    arrow_y = transition_row.y + row_height + _TRANSITION_ARROW_GAP
    for first, second in transition_pairs:
        x1 = centers[steps.index(first)]
        x2 = centers[steps.index(second)]
        add_connector(
            frame.slide, (x1, arrow_y), (x2, arrow_y), color="dk2", width=1.25, arrow="end"
        )

        segment = Box(x1, transition_row.y, x2 - x1, row_height)
        assert first.transition is not None  # guaranteed by the `transition_pairs` filter
        _place_label(
            frame,
            segment,
            first.transition,
            transition_style,
            what=f"process_flow transition {first.id}->{second.id}",
        )


# ---------------------------------------------------------------------------
# two_by_two — axes crossing at the centre (construction.md, "True 2x2")
# ---------------------------------------------------------------------------

_POLE_GAP = 4.0
_ITEM_LABEL_GAP = 6.0
#: Not sized in `construction.md` for this geometry (only the triangle recipe gives a node
#: size, for a different shape). Kept small on purpose: the geometry's honesty is in each
#: item's *position*, not the size of the dot marking it.
_DOT_DIAMETER = 9.0


def _render_two_by_two(frame: Frame, box: Box, spec: DiagramSpec) -> None:
    canvas = frame.canvas
    payload = spec.payload_as(TwoByTwoSpec)

    pole_style = canvas.style("caption", color="dk2")
    name_style = canvas.style("caption", color="dk2", bold=True)
    item_style = canvas.style("caption", color="dk1", bold=True)

    pole_height = canvas.measure(payload.y_axis.high, box.width, pole_style)
    name_height = canvas.measure(payload.y_axis.name, box.width, name_style)

    # Margins hold the four pole labels plus the two axis names — sized from the labels'
    # own measured extent, never a guessed constant, so a client's own type scale still
    # moves them. Not specified by `construction.md`, which fixes only where the poles sit
    # relative to the axis lines, not how much room their text needs.
    top_margin = pole_height + _POLE_GAP + name_height + _POLE_GAP
    bottom_margin = pole_height + _POLE_GAP
    left_margin = _text_width(pole_style, payload.x_axis.low) + _POLE_GAP
    right_margin = (
        _text_width(pole_style, payload.x_axis.high)
        + _POLE_GAP
        + _text_width(name_style, payload.x_axis.name)
        + _POLE_GAP
    )

    plot = box.inset(top=top_margin, right=right_margin, bottom=bottom_margin, left=left_margin)
    if plot.width <= 0 or plot.height <= 0:
        raise LayoutOverflowError(
            f"two_by_two: the axis labels alone need {left_margin + right_margin:.0f}pt of "
            f"width and {top_margin + bottom_margin:.0f}pt of height, more than the "
            f"{box.width:.0f}x{box.height:.0f}pt this diagram was given. Shorten the axis "
            "labels, or give the diagram a bigger slot."
        )

    # The two axis lines, crossing at the plot's centre — never boxed: "the axes are the
    # geometry" (construction.md). Items are plotted across this same `plot` rectangle, so
    # an item at (0.5, 0.5) lands exactly on the crossing point.
    add_connector(
        frame.slide,
        (plot.x, plot.center_y),
        (plot.right, plot.center_y),
        color="dk2",
        width=1.0,
        arrow="both",
    )
    add_connector(
        frame.slide,
        (plot.center_x, plot.bottom),
        (plot.center_x, plot.y),
        color="dk2",
        width=1.0,
        arrow="both",
    )

    # Pole labels sit just outside the plot, level with their arrowhead (construction.md:
    # "pole labels at each arrowhead"). Each axis's own name sits one step further out
    # again, paired with that axis's HIGH pole — a pairing `construction.md` does not
    # specify (it fixes only the poles), derived here so the name has a consistent home.
    _place_label(
        frame,
        _anchor(
            left_margin - _POLE_GAP,
            pole_height,
            plot.x - _POLE_GAP,
            plot.center_y,
            halign="right",
            valign="middle",
        ),
        payload.x_axis.low,
        pole_style,
        what="two_by_two x_axis low pole",
    )
    high_x_width = _text_width(pole_style, payload.x_axis.high)
    _place_label(
        frame,
        _anchor(
            high_x_width,
            pole_height,
            plot.right + _POLE_GAP,
            plot.center_y,
            halign="left",
            valign="middle",
        ),
        payload.x_axis.high,
        pole_style,
        what="two_by_two x_axis high pole",
    )
    _place_label(
        frame,
        _anchor(
            _text_width(name_style, payload.x_axis.name),
            name_height,
            plot.right + _POLE_GAP * 2 + high_x_width,
            plot.center_y,
            halign="left",
            valign="middle",
        ),
        payload.x_axis.name,
        name_style,
        what="two_by_two x_axis name",
    )

    centered_pole = pole_style.with_(align="center")
    centered_name = name_style.with_(align="center")
    _place_label(
        frame,
        _anchor(
            plot.width,
            pole_height,
            plot.center_x,
            plot.bottom + _POLE_GAP,
            halign="center",
            valign="top",
        ),
        payload.y_axis.low,
        centered_pole,
        what="two_by_two y_axis low pole",
    )
    _place_label(
        frame,
        _anchor(
            plot.width,
            pole_height,
            plot.center_x,
            plot.y - _POLE_GAP,
            halign="center",
            valign="bottom",
        ),
        payload.y_axis.high,
        centered_pole,
        what="two_by_two y_axis high pole",
    )
    _place_label(
        frame,
        _anchor(
            plot.width,
            name_height,
            plot.center_x,
            plot.y - _POLE_GAP * 2 - pole_height,
            halign="center",
            valign="bottom",
        ),
        payload.y_axis.name,
        centered_name,
        what="two_by_two y_axis name",
    )

    # Items — each its own OVAL, plotted at its honest (x, y), with its label beside it
    # (construction.md: "items as labeled dots"; GEOMETRIES' label_anchor: "beside each
    # plotted dot"). `payload.items` is drawn in declared order; two items at the same
    # position overlap honestly rather than being nudged apart, since nudging would be the
    # geometry lying about the tie.
    for item in payload.items:
        item_x = plot.x + item.x * plot.width
        item_y = plot.bottom - item.y * plot.height
        dot_box = _anchor(
            _DOT_DIAMETER, _DOT_DIAMETER, item_x, item_y, halign="center", valign="middle"
        )
        add_autoshape(frame.slide, dot_box, "OVAL", fill="accent1")

        # A point past the axis midline gets its label on the side with more room to the
        # box edge, rather than always to the right — otherwise an item near x=1 would be
        # asked to fit a label past the diagram's own right edge.
        on_left = item.x > 0.5
        edge_x = (
            item_x - _DOT_DIAMETER / 2 - _ITEM_LABEL_GAP
            if on_left
            else item_x + _DOT_DIAMETER / 2 + _ITEM_LABEL_GAP
        )
        available = (edge_x - box.x) if on_left else (box.right - edge_x)
        block = _measure(
            canvas, item.label, available, item_style, what=f"two_by_two item {item.id!r} label"
        )
        label_box = _anchor(
            available,
            block.height,
            edge_x,
            item_y,
            halign="right" if on_left else "left",
            valign="middle",
        )
        style = item_style.with_(align="right" if on_left else "left")
        frame.text(label_box, item.label, style)


# ---------------------------------------------------------------------------
# layered_stack — horizontal bands (construction.md, "Pyramid / strata")
# ---------------------------------------------------------------------------

#: Not given for this geometry; the closest documented number is the funnel recipe's
#: "2-4pt vertical gaps" between stacked bands, reused here for the same reason (visible
#: separation without a gap wide enough to read as a break in the stack).
_STACK_ROW_GUTTER = 3.0
_STACK_LEFT_PAD = 14.0
#: How narrow the apex band gets relative to the foundation, for a `rests_on` stack. A
#: structural cue, not an honest-proportions encoding: `StackLayer` carries no magnitude,
#: only an ordinal `level`, so there is no real quantity for the taper to misrepresent.
_REST_ON_APEX_WIDTH_FRACTION = 0.55
#: Fill brightness at the foundation (darkest, most emphasised) and the apex (lightest).
_STACK_BASE_BRIGHTNESS = 0.22
_STACK_APEX_BRIGHTNESS = 0.78


def _render_layered_stack(frame: Frame, box: Box, spec: DiagramSpec) -> None:
    canvas = frame.canvas
    payload = spec.payload_as(LayeredStackSpec)
    layers = payload.layers_upwards()  # index 0 = level 1 = the foundation
    count = len(layers)

    label_style = canvas.style("body", color="dk1", valign="middle")

    # `split_rows` returns top-to-bottom; reversed, index 0 is the bottom row — the same
    # order as `layers` (bottom first), so the two line up by position.
    rows_bottom_up = list(reversed(box.split_rows(count, gutter=_STACK_ROW_GUTTER)))

    for index, (layer, row) in enumerate(zip(layers, rows_bottom_up, strict=True)):
        fraction = index / (count - 1) if count > 1 else 0.0
        if payload.support == "rests_on":
            # Foundation (index 0) widest; each layer above narrower, apex narrowest — the
            # geometry's whole claim (construction.md: "Four strata ... foundation at the
            # bottom widest if the argument is 'everything rests on this'"). The same
            # foundation-to-apex gradient is applied to the fill, for the same reason: a
            # `rests_on` stack is arguing an emphasis, and darkest-at-the-base is the same
            # emphasis a widest-at-the-base band already makes.
            width_fraction = 1.0 - fraction * (1.0 - _REST_ON_APEX_WIDTH_FRACTION)
            brightness = _STACK_BASE_BRIGHTNESS + fraction * (
                _STACK_APEX_BRIGHTNESS - _STACK_BASE_BRIGHTNESS
            )
        else:
            # `peers`: equal bands, equal fill — a stack of coequals, not a hierarchy. A
            # brightness gradient here would assert the exact ranking `support="peers"`
            # exists to deny.
            width_fraction = 1.0
            brightness = (_STACK_BASE_BRIGHTNESS + _STACK_APEX_BRIGHTNESS) / 2
        band_width = box.width * width_fraction
        band = Box(box.center_x - band_width / 2, row.y, band_width, row.height)

        add_autoshape(
            frame.slide, band, "RECTANGLE", fill="accent1", fill_brightness=brightness
        )

        text_box = band.inset(left=_STACK_LEFT_PAD, right=_STACK_LEFT_PAD)
        _place_label(
            frame,
            text_box,
            layer.label,
            label_style,
            what=f"layered_stack layer {layer.id!r} label",
        )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_RENDERERS: dict[DiagramKind, Callable[[Frame, Box, DiagramSpec], None]] = {
    "process_flow": _render_process_flow,
    "two_by_two": _render_two_by_two,
    "layered_stack": _render_layered_stack,
}


def place_diagram(frame: Frame, box: Box, spec: DiagramSpec) -> None:
    """Draw `spec`'s geometry — nodes and edges only, never `spec.title` — inside `box`.

    Dispatches on `spec.kind` through `GEOMETRIES`'s three modelled geometries. A caller
    holding a `DiagramSpec` at all has already gone through `_geometry_matches_kind`, so
    `spec.kind` is guaranteed to be one of these three; the `KeyError` path below exists
    for a future modelled geometry (task 3a.6a's carried finding — "one more is one more
    payload class plus a `GEOMETRIES` entry") that reaches here before this dict is
    extended to match, not for anything a caller can trigger today.

    Raises:
        LayoutOverflowError: a label, once measured at the style it draws with, does not
            fit the room its node/pole/axis position gives it.
    """
    try:
        renderer = _RENDERERS[spec.kind]
    except KeyError:
        raise NotImplementedError(
            f"diagram kind {spec.kind!r} is registered in GEOMETRIES but this module has no "
            "renderer for it yet — add one and a _RENDERERS entry, the same registration "
            "GEOMETRIES itself asks for."
        ) from None
    renderer(frame, box, spec)
