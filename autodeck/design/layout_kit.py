"""`layout_kit` v0 — the layout vocabulary component renderers are written against.

D5 says PPTX is the medium end to end: components are designed *and* rendered natively,
with no HTML anywhere. The obvious objection is that python-pptx gives you absolute EMU
rectangles and nothing else, which is why v1's design work turned into arithmetic. This
module is the answer to that objection — a small internal layout API that restores the
expressiveness CSS provides (stacks, grids, gutters, baseline rhythm, a token-driven type
scale) **without introducing a second medium**.

The unit of composition is `Box`: an immutable rectangle in points, with methods that
return new boxes. A renderer says `content.split_columns(2, gutter)` rather than computing
`Emu(6553200 - 152400 // 2)`, and the resulting code is reviewable as design intent.

Points are used throughout and converted to EMU only at the python-pptx boundary. Font
sizes, spacing tokens and text budgets are all in points already; doing the arithmetic in
EMU is how v1's TextFitter became unreadable.

## Two layers, and why the second one exists

`Box` and `Canvas` are geometry and measurement. On their own they still leave every
renderer writing the same three-step dance: measure a block of content, work out where it
goes, then draw it — with the measuring code and the drawing code in separate functions
that have to agree. `big_number`'s `_figure_block_height` and `_render_figure` were exactly
that pair, and keeping two functions in step by hand is the same failure `TextStyle` was
introduced to prevent, one level up.

`Frame` and `Stack` are the second layer and they close it. A `Stack` is declared once —
text, rules, gaps, markers, in order — and it both measures and draws *that same
declaration*. There is no second description of the block to drift from the first, so the
class of bug where an element is measured one way and drawn another is not something a
renderer can express any more.

## The rule this module will not break

**No helper here shrinks, truncates or reflows text to make it fit.** `Stack.place` and
`Box.reserve` raise `LayoutOverflowError`; they take no `shrink`, `autofit` or `max_lines`
argument, and none may be added. v1's defining failure was text overflowing at render after
the content agent had been promised it would fit (`budgets.py`), and a kit that quietly
dropped a font size to rescue a slide would reproduce that failure with a friendlier face —
the deck would look fine and the promise would still be broken. Over-budget content is an
error, and what to do about it (rewrite the block, pick another component, send the slide
back) belongs to the caller, which is the only layer that knows.

Owning phase: 0 (spike 0.5); productionised in Phase 3a (task 3a.2). The API shape is
Opus-tier per docs/MODEL_ROUTING.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from pptx.shapes.autoshape import Shape
from pptx.slide import Slide
from pptx.util import Emu, Pt

from autodeck.design.budgets import SlotBudget, compute_budget, load_metrics, wrap_text
from autodeck.design.draw import ThemeColor, add_rect, add_rule, add_text
from autodeck.design.theme.tokens import EMU_PER_POINT, DesignTokens

Align = Literal["left", "center", "right"]
VAlign = Literal["top", "middle", "bottom"]

#: Floating-point slack for "does this fit" — the error of summing a few dozen measured
#: heights, and nothing more. Deliberately far below one point: a real overflow is worth
#: at least a fraction of a line, so this excuses arithmetic noise without excusing text.
FIT_TOLERANCE = 1e-6

#: The leading dash a stacked item is marked with, and the geometry around it. These are
#: kit constants rather than per-renderer ones because a deck in which one component's
#: bullets hang at 17pt and another's at 18pt is a deck with a visible seam down it — and
#: because a component author should not have to decide what a bullet looks like.
MARKER = "—"
MARKER_WIDTH = 10.0
MARKER_INSET = 18.0
#: The marker's own box height, as a multiple of its point size. Only ever holds one short
#: glyph, so this reserves a line rather than measuring one.
MARKER_HEIGHT_FACTOR = 1.4

#: The caption strip's height, as a multiple of the caption size — the band at the foot of
#: a slide that carries the source line. One definition, because the catalog reconstructs
#: this same band to budget the `source` slot and two copies of `* 1.6` would be two
#: answers to one question.
CAPTION_STRIP_FACTOR = 1.6


def pt_to_emu(points: float) -> int:
    return round(points * EMU_PER_POINT)


class LayoutOverflowError(RuntimeError):
    """Content does not fit the region a component gave it.

    Raised by renderers rather than allowed to spill. §6.9 calls the render-time geometry
    check a *safety net*, which only works if the net actually catches — silently drawing
    past the edge is how v1's overflow problem stayed invisible until someone opened the
    deck.
    """


@dataclass(frozen=True)
class TextStyle:
    """Everything that determines both how text *renders* and how tall it *measures*.

    This type exists because of a bug the Phase 0 design spike produced immediately and
    twice: the renderer applied a 1.25 line-spacing multiplier that the measurement
    function knew nothing about, so every measured height was ~20% short and the next
    element was placed on top of the previous one's last line.

    That is the exact failure mode the budget system is supposed to eliminate, arriving
    through the back door — measurement and rendering had drifted apart because they took
    separate arguments. Passing one `TextStyle` to both makes the divergence unrepresentable
    rather than merely discouraged.

    `color` is a token slot name, validated at the drawing boundary; layout has no opinion
    about colour beyond passing it along.
    """

    family: str
    size: float
    color: str = "dk1"
    bold: bool = False
    italic: bool = False
    align: Align = "left"
    valign: VAlign = "top"
    line_spacing: float = 1.0
    space_after: float = 0.0

    def with_(self, **overrides: object) -> TextStyle:
        """A copy with fields replaced — for local variations on a canvas style."""
        from dataclasses import replace

        return replace(self, **overrides)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Box:
    """An immutable rectangle in points, origin top-left.

    Every method returns a new `Box`, so a layout reads as a sequence of transformations
    rather than a set of mutations whose order matters.
    """

    x: float
    y: float
    width: float
    height: float

    # -- derived edges ----------------------------------------------------

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    # -- transformations --------------------------------------------------

    def inset(
        self, top: float = 0, right: float = 0, bottom: float = 0, left: float = 0
    ) -> Box:
        """Shrink inwards. One value insets all four sides via `pad`."""
        return Box(
            x=self.x + left,
            y=self.y + top,
            width=max(self.width - left - right, 0.0),
            height=max(self.height - top - bottom, 0.0),
        )

    def pad(self, amount: float) -> Box:
        return self.inset(top=amount, right=amount, bottom=amount, left=amount)

    def offset(self, dx: float = 0, dy: float = 0) -> Box:
        return Box(self.x + dx, self.y + dy, self.width, self.height)

    def resize(self, *, width: float | None = None, height: float | None = None) -> Box:
        return Box(
            self.x,
            self.y,
            width if width is not None else self.width,
            height if height is not None else self.height,
        )

    # -- subdivision ------------------------------------------------------

    def split_columns(self, count: int, gutter: float = 0.0) -> list[Box]:
        """Divide into `count` equal columns separated by `gutter`."""
        if count < 1:
            raise ValueError("count must be at least 1")
        column_width = (self.width - gutter * (count - 1)) / count
        if column_width <= 0:
            raise ValueError(
                f"{count} columns with a {gutter}pt gutter do not fit in {self.width}pt"
            )
        return [
            Box(self.x + index * (column_width + gutter), self.y, column_width, self.height)
            for index in range(count)
        ]

    def split_rows(self, count: int, gutter: float = 0.0) -> list[Box]:
        """Divide into `count` equal rows separated by `gutter`."""
        if count < 1:
            raise ValueError("count must be at least 1")
        row_height = (self.height - gutter * (count - 1)) / count
        if row_height <= 0:
            raise ValueError(
                f"{count} rows with a {gutter}pt gutter do not fit in {self.height}pt"
            )
        return [
            Box(self.x, self.y + index * (row_height + gutter), self.width, row_height)
            for index in range(count)
        ]

    def grid(self, rows: int, columns: int, gutter: float = 0.0) -> list[list[Box]]:
        """A `rows` x `columns` grid with a uniform gutter."""
        return [row.split_columns(columns, gutter) for row in self.split_rows(rows, gutter)]

    def split_top(self, height: float, gutter: float = 0.0) -> tuple[Box, Box]:
        """Take `height` off the top; return `(taken, remainder)`.

        The workhorse for the common consulting layout — header, then content, then a
        source line — where the header's height depends on how the text wrapped.
        """
        taken = Box(self.x, self.y, self.width, min(height, self.height))
        remaining_y = self.y + taken.height + gutter
        return taken, Box(self.x, remaining_y, self.width, max(self.bottom - remaining_y, 0.0))

    def split_bottom(self, height: float, gutter: float = 0.0) -> tuple[Box, Box]:
        """Take `height` off the bottom; return `(remainder, taken)`."""
        taken_height = min(height, self.height)
        taken = Box(self.x, self.bottom - taken_height, self.width, taken_height)
        return Box(self.x, self.y, self.width, max(taken.y - gutter - self.y, 0.0)), taken

    # -- alignment --------------------------------------------------------

    def align_within(
        self, outer: Box, *, horizontal: Align = "left", vertical: VAlign = "top"
    ) -> Box:
        x = {
            "left": outer.x,
            "center": outer.center_x - self.width / 2,
            "right": outer.right - self.width,
        }[horizontal]
        y = {
            "top": outer.y,
            "middle": outer.center_y - self.height / 2,
            "bottom": outer.bottom - self.height,
        }[vertical]
        return Box(x, y, self.width, self.height)

    def reserve(self, height: float, *, valign: VAlign = "top", what: str = "content") -> Box:
        """A sub-box of exactly `height`, aligned inside this one — or an error.

        The single place the kit decides that something does not fit, so the decision reads
        the same way, and fails the same way, everywhere. `Stack.place` is built on it.

        It raises rather than returning a shorter box on purpose. Handing back a box the
        content does not fit into would leave the caller free to draw into it anyway, which
        is how silent overflow gets back in; this module's docstring has the argument in
        full.

        Raises:
            LayoutOverflowError: `height` exceeds this box's own height.
        """
        if height > self.height + FIT_TOLERANCE:
            raise LayoutOverflowError(
                f"{what} needs {height:.0f}pt but only {self.height:.0f}pt is available. "
                f"Shorten the text, drop an item, or use a component with more room — "
                f"nothing here will shrink text to fit (§6.7: budgets exist so this is "
                f"caught before a render, not during one)."
            )
        y = {
            "top": self.y,
            "middle": self.center_y - height / 2,
            "bottom": self.bottom - height,
        }[valign]
        return Box(self.x, y, self.width, height)

    def snap_to_baseline(self, baseline: float) -> Box:
        """Round `y` down to the nearest baseline multiple.

        Vertical rhythm is what makes a deck of varied components feel like one deck. It
        is invisible when present and unmistakable when absent.
        """
        if baseline <= 0:
            return self
        return Box(self.x, (self.y // baseline) * baseline, self.width, self.height)

    # -- python-pptx boundary ---------------------------------------------

    def as_emu(self) -> tuple[Emu, Emu, Emu, Emu]:
        """`(left, top, width, height)` for a python-pptx shape call."""
        return (
            Emu(pt_to_emu(self.x)),
            Emu(pt_to_emu(self.y)),
            Emu(pt_to_emu(self.width)),
            Emu(pt_to_emu(self.height)),
        )

    def contains(self, other: Box, tolerance: float = 0.5) -> bool:
        """Whether `other` sits inside this box — the deterministic safe-area check (§6.9)."""
        return (
            other.x >= self.x - tolerance
            and other.y >= self.y - tolerance
            and other.right <= self.right + tolerance
            and other.bottom <= self.bottom + tolerance
        )


# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------


class Canvas:
    """The slide, its tokens, and the derived regions a renderer works inside.

    Holding the tokens here is what stops a component reaching for a literal colour or
    point size: everything a renderer needs is on the canvas or on the tokens it carries.
    """

    def __init__(self, tokens: DesignTokens) -> None:
        self.tokens = tokens
        self.width = tokens.slide_width_emu / EMU_PER_POINT
        self.height = tokens.slide_height_emu / EMU_PER_POINT

    @property
    def slide(self) -> Box:
        """The whole slide."""
        return Box(0, 0, self.width, self.height)

    @property
    def safe(self) -> Box:
        """Inside the safe area — nothing may render outside this (§6.9)."""
        return self.slide.pad(self.tokens.spacing.safe_area)

    @property
    def content(self) -> Box:
        """The working area inside the page margins."""
        spacing = self.tokens.spacing
        return self.slide.inset(
            top=spacing.margin_y,
            bottom=spacing.margin_y,
            left=spacing.margin_x,
            right=spacing.margin_x,
        )

    @property
    def caption_strip(self) -> Box:
        """The band at the foot of the content area that carries the source line."""
        return self.content.split_bottom(
            self.size("caption") * CAPTION_STRIP_FACTOR, gutter=self.gutter
        )[1]

    def body_and_caption(self) -> tuple[Box, Box]:
        """`(body, caption strip)` — the frame almost every component starts from.

        Every component that cites anything needs the same band at the foot of the slide,
        and the catalog needs the identical band to budget the `source` slot. Returning both
        halves of one split is what stops those two ever disagreeing about where the body
        ends, which they would the first time someone adjusted the strip in only one place.
        """
        return self.content.split_bottom(
            self.size("caption") * CAPTION_STRIP_FACTOR, gutter=self.gutter
        )

    @property
    def gutter(self) -> float:
        return self.tokens.spacing.gutter

    @property
    def baseline(self) -> float:
        return self.tokens.spacing.baseline

    # -- type -------------------------------------------------------------

    def size(self, role: str) -> float:
        """A point size from the type scale, by name."""
        try:
            value = getattr(self.tokens.typography, role)
        except AttributeError:
            raise ValueError(f"unknown type-scale role {role!r}") from None
        if not isinstance(value, float | int):
            raise ValueError(f"{role!r} is not a type-scale size")
        return float(value)

    def family(self, role: Literal["major", "minor"]) -> str:
        return self.tokens.typography.major if role == "major" else self.tokens.typography.minor

    def pt(self, points: float) -> Pt:
        return Pt(points)

    def style(
        self,
        role: str,
        *,
        face: Literal["major", "minor"] = "minor",
        scale: float = 1.0,
        **overrides: object,
    ) -> TextStyle:
        """A `TextStyle` from the type scale.

        The single place a renderer obtains type. Body-ish roles get the theme's line
        height by default because prose needs the leading; display roles are set tight,
        since generous leading on a 100pt figure just opens a hole.

        `scale` multiplies the role's size for the rare slot set deliberately off the scale
        — `big_number`'s figure at twice `display`. It is a multiple of a token rather than
        a free point size, so a client's type scale still moves it; a renderer that wants a
        size the scale cannot reach is asking for a token, not for a number.
        """
        size = self.size(role) * scale
        tight = role in ("display", "title", "heading")
        base = TextStyle(
            family=self.family(face),
            size=size,
            line_spacing=1.15 if tight else self.tokens.typography.line_height,
        )
        return base.with_(**overrides) if overrides else base

    # -- text sizing ------------------------------------------------------

    def measure(self, text: str, width: float, style: TextStyle) -> float:
        """Rendered height of `text` at `width`, in points — including leading.

        Accounts for `line_spacing` and inter-paragraph `space_after`, because the renderer
        applies both. A measurement that ignored them is what put an accent rule through a
        headline in the first spike render.
        """
        return self.measure_block(text, width, style).height

    def measure_block(self, text: str, width: float, style: TextStyle) -> TextBlock:
        """The height of `text` at `width` **and** whether it can be wrapped there at all.

        `measure` answers only the first question, and a height alone cannot see the second
        failure: a word wider than its column renders straight past the edge at exactly the
        height a one-line measurement predicts. Wrapping cannot help — the fix is a smaller
        size, a wider box or shorter content — so `Stack` refuses the item rather than
        drawing an overflow that measures as fitting.

        Measured against the face `style` will actually be drawn in, bold and italic
        included. That is the whole of 3a.6's fix at this level: `TextStyle.bold` already
        reached here intact and was then dropped on the floor, so a bold headline was
        wrapped against regular-weight advances and predicted one line short of what it
        renders.
        """
        measurement = wrap_text(
            text, style.family, style.size, width, bold=style.bold, italic=style.italic
        )
        paragraph_gaps = max(text.count("\n"), 0)
        height = measurement.height_pt * style.line_spacing + style.space_after * paragraph_gaps
        too_wide: tuple[str, ...] = ()
        if measurement.overflow_width:
            metrics = load_metrics(style.family, bold=style.bold, italic=style.italic)
            too_wide = tuple(
                word
                for word in dict.fromkeys(text.split())
                if metrics.text_width(word, style.size) > width
            )
        return TextBlock(height=height, lines=tuple(measurement.lines), too_wide_words=too_wide)

    def fit(self, text: str, box: Box, style: TextStyle) -> Box:
        """`box` shrunk to the height the text actually needs.

        Lets a renderer place what follows against real measured text rather than against a
        guessed header height — the mechanism that removes most of v1's vertical drift.
        """
        return box.resize(height=self.measure(text, box.width, style))

    def on(self, slide: Slide) -> Frame:
        """Bind this canvas to a slide. The object a renderer actually works through."""
        return Frame(slide=slide, canvas=self)

    def budget(self, slot: str, box: Box, style: TextStyle) -> SlotBudget:
        """The text budget for a slot occupying `box` (§6.7)."""
        return compute_budget(
            slot=slot,
            family=style.family,
            size_pt=style.size,
            width_pt=box.width,
            height_pt=box.height,
            line_spacing=style.line_spacing,
            bold=style.bold,
            italic=style.italic,
        )


# ---------------------------------------------------------------------------
# Measurement results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TextBlock:
    """What a piece of text does at a given width: how tall, and whether it fits at all."""

    height: float
    lines: tuple[str, ...]
    too_wide_words: tuple[str, ...] = ()
    """Words wider than the box they were measured against.

    Non-empty means wrapping cannot rescue this text at this size and width — it would
    render past the edge while measuring, misleadingly, as exactly one line tall.
    """

    @property
    def line_count(self) -> int:
        return len(self.lines)


# ---------------------------------------------------------------------------
# Frame — a canvas bound to a slide
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    """The slide a component is drawing on, plus the canvas it is laying out against.

    A component renderer holds one of these and nothing else. That is the point: with the
    frame carrying the slide, no renderer helper needs `slide` threaded through its
    signature, and the six-argument private helpers the first two components grew
    (`_render_column(slide, canvas, area, column, row_heights, text_style, title_style)`)
    stop being the natural way to write one.
    """

    slide: Slide
    canvas: Canvas

    # -- regions ----------------------------------------------------------

    def body_and_caption(self) -> tuple[Box, Box]:
        """`(body, caption strip)`, from the canvas — see `Canvas.body_and_caption`."""
        return self.canvas.body_and_caption()

    # -- composition ------------------------------------------------------

    def stack(self, name: str, width: float) -> Stack:
        """A new stack `width` points wide. `name` is what an overflow error will blame."""
        return Stack(self, name, width)

    # -- drawing ----------------------------------------------------------

    def text(self, box: Box, text: str, style: TextStyle) -> Shape:
        """Draw text in `box`, measured nowhere — prefer a `Stack` unless the box is fixed."""
        return add_text(self.slide, box, text, style)

    def caption(self, box: Box, text: str, *, color: str = "accent6") -> Shape | None:
        """The source line at the foot of a slide; nothing at all when there is no source.

        Every component that cites anything ends this way, and the `if content.source:`
        guard around it was copied between the first two renderers verbatim. Returning
        `None` for empty text puts that guard in one place.
        """
        if not text:
            return None
        return self.text(box, text, self.canvas.style("caption", color=color, valign="bottom"))

    def rect(
        self,
        box: Box,
        *,
        fill: str | None = None,
        fill_brightness: float | None = None,
        line: str | None = None,
        line_width: float = 1.0,
    ) -> Shape:
        """A themed rectangle — the panel behind an emphasised column, a card's ground."""
        return add_rect(
            self.slide,
            box,
            fill=fill,
            fill_brightness=fill_brightness,
            line=line,
            line_width=line_width,
        )

    def rule(self, box: Box, *, color: str = "accent1", thickness: float = 2.0) -> Shape:
        """A horizontal rule pinned to `box`'s top-left, at `box`'s width."""
        return add_rule(self.slide, box, color=color, thickness=thickness)

    def icon(self, box: Box, concept: str, *, color: ThemeColor = "accent1") -> list[Shape]:
        """Place a semantic icon inside `box` as native, theme-recolourable shapes (D11).

        `concept` is looked up in the semantic library first — `"risk"`, `"growth"`,
        `"team"` — and falls back to a literal vendored filename, so a renderer asks for an
        idea rather than a glyph name unless it already knows exactly which one it wants.
        See `autodeck.design.icons.library.resolve_icon` for the concept vocabulary and
        `autodeck.design.icons.consistency` for the deck-wide check this does not itself
        perform — placing one icon has no way to know what else the deck has placed.

        Imports locally: `icons.custgeom` already imports `Box`/`pt_to_emu` from this
        module, so a module-level import here would be circular.
        """
        from autodeck.design.icons.custgeom import place_icon
        from autodeck.design.icons.library import resolve_icon

        return place_icon(self.slide, box, resolve_icon(concept), color=color)


# ---------------------------------------------------------------------------
# Stack — the flow the brief named and the kit lacked
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Item:
    """One entry in a stack: the gap above it, the height it takes, and how it draws."""

    gap_before: float
    height: float
    paint: Callable[[Box], None]


class Stack:
    """A sequence of items flowed down a box, each taking the height its content needs.

    Declared first, placed second: `text`/`rule`/`items`/`space` measure and record, and
    `place` decides where the whole block goes and draws it. Nothing is drawn until `place`,
    which is what lets a renderer ask `stack.height` and centre a content-sized block —
    previously a second, hand-written height function per component, kept in step with the
    drawing code by hope.

    Overflow is the part worth getting right. A stack never shrinks to fit and never
    truncates: `place` raises `LayoutOverflowError` through `Box.reserve`, and an item whose
    text cannot wrap into this stack's width at all is refused at the moment it is added,
    where the offending word can still be named. See the module docstring for why silence
    is not an option here.
    """

    def __init__(self, frame: Frame, name: str, width: float) -> None:
        self._frame = frame
        self._canvas = frame.canvas
        self._name = name
        self._width = width
        self._items: list[_Item] = []

    # -- declaring --------------------------------------------------------

    def text(
        self,
        text: str,
        style: TextStyle,
        *,
        gap: float = 0.0,
        min_height: float = 0.0,
        marker: str | None = None,
        marker_style: TextStyle | None = None,
        marker_inset: float = MARKER_INSET,
    ) -> Stack:
        """Add a run of text, `gap` points below whatever precedes it.

        `min_height` holds the item open to at least that height — how a row keeps level
        with its opposite number in another column, and the only reason the two columns of
        a comparison do not drift apart.

        `marker` hangs a dash (or any short glyph) in the left margin and insets the text
        past it; the marker is not measured, since it is one glyph on the item's first line
        by construction.

        Raises:
            LayoutOverflowError: a word in `text` is wider than the stack, so no amount of
                wrapping will fit it.
        """
        inset = marker_inset if marker is not None else 0.0
        block = self._canvas.measure_block(text, self._width - inset, style)
        if block.too_wide_words:
            raise LayoutOverflowError(
                f"{self._name}: {', '.join(repr(w) for w in block.too_wide_words[:3])} "
                f"{'is' if len(block.too_wide_words) == 1 else 'are'} wider than the "
                f"{self._width - inset:.0f}pt this stack has, at {style.size:g}pt "
                f"{style.family}. Wrapping cannot fix a single over-wide word — shorten it, "
                f"or give the component a wider slot."
            )
        height = max(block.height, min_height)
        marker_height = (marker_style or style).size * MARKER_HEIGHT_FACTOR

        def paint(box: Box) -> None:
            if marker is not None:
                self._frame.text(
                    box.resize(width=MARKER_WIDTH, height=marker_height),
                    marker,
                    marker_style or style,
                )
            self._frame.text(box.inset(left=inset), text, style)

        self._items.append(_Item(gap_before=gap, height=height, paint=paint))
        return self

    def items(
        self,
        texts: Iterable[str],
        style: TextStyle,
        *,
        gap: float = 0.0,
        row_gap: float,
        marker: str | None = MARKER,
        marker_style: TextStyle | None = None,
        marker_inset: float = MARKER_INSET,
        min_heights: Sequence[float] = (),
    ) -> Stack:
        """Add a list of items, `row_gap` apart — a bullet list, a set of points.

        The list case rather than the prose case: each item is its own run of text, sized to
        its own content, and `min_heights` (when given, one per index) holds each row open
        to a height decided elsewhere.
        """
        for index, text in enumerate(texts):
            self.text(
                text,
                style,
                gap=gap if index == 0 else row_gap,
                min_height=min_heights[index] if index < len(min_heights) else 0.0,
                marker=marker,
                marker_style=marker_style,
                marker_inset=marker_inset,
            )
        return self

    def rule(
        self,
        *,
        width: float,
        thickness: float,
        color: str = "accent1",
        gap: float = 0.0,
    ) -> Stack:
        """Add an accent rule — the bar under a headline or a column title."""

        def paint(box: Box) -> None:
            self._frame.rule(box.resize(width=width), color=color, thickness=thickness)

        self._items.append(_Item(gap_before=gap, height=thickness, paint=paint))
        return self

    def space(self, height: float, *, gap: float = 0.0) -> Stack:
        """Reserve `height` for nothing.

        A row that is absent on one side of a comparison still has to occupy its height, or
        every row below it stops lining up with its opposite number.
        """
        self._items.append(_Item(gap_before=gap, height=height, paint=lambda _: None))
        return self

    # -- placing ----------------------------------------------------------

    @property
    def height(self) -> float:
        """Total height of everything declared so far, gaps included."""
        return sum(item.gap_before + item.height for item in self._items)

    @property
    def item_heights(self) -> tuple[float, ...]:
        """Each item's own height, gaps excluded — for matching rows across two stacks."""
        return tuple(item.height for item in self._items)

    def place(
        self,
        box: Box,
        *,
        valign: VAlign = "top",
        gutter: float = 0.0,
        snap_baseline: bool = False,
    ) -> Box:
        """Draw the stack inside `box`; return what is left of `box` below it.

        The returned remainder is what makes "headline, then whatever is under it" a single
        expression rather than a `split_top` against a separately measured height.

        `snap_baseline` rounds the block's top down onto the baseline grid, which is what
        keeps two independently-sized blocks on the same slide reading as one rhythm.

        Raises:
            LayoutOverflowError: the stack is taller than `box`.
        """
        placed = box.reserve(self.height, valign=valign, what=self._name)
        if snap_baseline:
            placed = placed.snap_to_baseline(self._canvas.baseline)

        cursor = placed.y
        for item in self._items:
            cursor += item.gap_before
            item.paint(Box(placed.x, cursor, self._width, item.height))
            cursor += item.height

        below = placed.bottom + gutter
        return Box(box.x, below, box.width, max(box.bottom - below, 0.0))
