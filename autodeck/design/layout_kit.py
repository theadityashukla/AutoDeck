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

Owning phase: 0 (spike 0.5); the API shape is Opus-tier per docs/MODEL_ROUTING.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pptx.util import Emu, Pt

from autodeck.design.budgets import SlotBudget, compute_budget, wrap_text
from autodeck.design.theme.tokens import EMU_PER_POINT, DesignTokens

Align = Literal["left", "center", "right"]
VAlign = Literal["top", "middle", "bottom"]


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
        **overrides: object,
    ) -> TextStyle:
        """A `TextStyle` from the type scale.

        The single place a renderer obtains type. Body-ish roles get the theme's line
        height by default because prose needs the leading; display roles are set tight,
        since generous leading on a 100pt figure just opens a hole.
        """
        size = self.size(role)
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
        natural = wrap_text(text, style.family, style.size, width).height_pt
        paragraph_gaps = max(text.count("\n"), 0)
        return natural * style.line_spacing + style.space_after * paragraph_gaps

    def fit(self, text: str, box: Box, style: TextStyle) -> Box:
        """`box` shrunk to the height the text actually needs.

        Lets a renderer place what follows against real measured text rather than against a
        guessed header height — the mechanism that removes most of v1's vertical drift.
        """
        return box.resize(height=self.measure(text, box.width, style))

    def budget(self, slot: str, box: Box, style: TextStyle) -> SlotBudget:
        """The text budget for a slot occupying `box` (§6.7)."""
        return compute_budget(
            slot=slot,
            family=style.family,
            size_pt=style.size,
            width_pt=box.width,
            height_pt=box.height,
            line_spacing=style.line_spacing,
        )
