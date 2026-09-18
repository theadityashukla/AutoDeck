"""Text budgets from real glyph metrics — the module that kills v1's overflow problem.

v1 hand-built a layout engine on top of python-pptx and used a vision model as a measuring
instrument; the TextFitter EMU maths and the overflow whack-a-mole both trace to that
(`legacy/v1/LEGACY.md`). v2 inverts it: each component slot declares how much text fits
*before* content is written, the content agent receives that as a hard constraint, and
overflow becomes rare by construction. The render-time geometry check (§6.9) is then a
safety net rather than the primary mechanism.

Horizontal measurement here comes from the **real font file** — glyph advance widths
really do vary per family, and `resolve_family` raises rather than substituting, so a
budget is either computed from the face that will actually render or not computed at all.

Vertical measurement (`LINE_HEIGHT_FACTOR`) is the one exception to "read it from the font
file", and deliberately so: it used to be `hhea.ascent + hhea.descent`, which looked
principled and was wrong by ~7.4%, in the dangerous (under-predicting) direction — see that
constant's docstring for what replaced it and why.

Owning phase: 0 (task 0.4); consumed by the content agent in Phase 2b. The line-height fix
is task 2b.1's follow-up finding, acted on by the same task.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

from autodeck.design.fonts import FontNotFoundError, resolve_family

#: Fallback advance for a glyph the font has no mapping for, as a fraction of em. Only
#: reached for characters genuinely absent from the face, which will render as .notdef
#: anyway — so the measurement matches what the renderer produces.
_NOTDEF_EM = 0.5

#: Single-spaced line-to-line pitch, as a multiple of the point size. This is LibreOffice's
#: own definition of "single" (100%) line spacing for the DrawingML text this codebase
#: writes, i.e. what `paragraph.line_spacing = 1.0` (`draw.py`) actually produces once
#: rendered — **not** a property of any particular font, which is why it is a bare
#: constant rather than something `FontMetrics` carries.
#:
#: It used to be `hhea.ascent + hhea.descent` (~1.117x for Liberation Sans), which reads as
#: principled but under-predicted LibreOffice's real single-spaced pitch by ~7.4% — the
#: dangerous direction, since a budget that under-predicts height passes text that then
#: overflows at render (see this module's own docstring on why that matters more than 7%
#: suggests). The per-font vertical-metrics derivations were checked, in order of how
#: principled they look, before reaching for a constant:
#:
#: - `hhea.ascent + hhea.descent`                                 : 1.117x (the old value)
#: - `hhea.ascent + hhea.descent + hhea.lineGap`                  : 1.150x
#: - `OS/2.usWinAscent + OS/2.usWinDescent`                       : 1.117x (= hhea, above)
#: - `OS/2.sTypoAscender + sTypoDescender + sTypoLineGap`         : 1.088x
#:
#: measured against Liberation Sans, none of which lands on the observed 1.20x — including
#: `lineGap`, the most likely single missing term. The gap is too large to be rounding, and
#: no combination of these fields reaches 1.20x for this font.
#:
#: What actually settles it: measured against five installed families with unrelated
#: vertical metrics (Liberation Sans, Liberation Serif, Liberation Mono, DejaVu Sans, DejaVu
#: Serif — OS/2 typo sums of 1.088x, 1.059x, 1.107x, ~1.200x and ~1.077x respectively, no
#: two alike), LibreOffice's *rendered* line-to-line pitch came out at 1.20x the point size
#: in every single case (`tests/test_budget_check.py`'s
#: `test_the_rendered_pitch_matches_the_predicted_pitch`, render-marked). A quantity that
#: stays fixed while the font's own metrics move all over the place is not being read from
#: the font at all — it is LibreOffice's (and, since `paragraph.line_spacing` writes OOXML
#: `spcPct`, PowerPoint's) own convention for what "single" spacing means, applied uniformly
#: regardless of face. A principled per-font derivation would be preferable if one actually
#: matched, but none does, so a documented empirical constant is the honest choice here, not
#: a wrong principle dressed up as one.
LINE_HEIGHT_FACTOR = 1.20


@dataclass(frozen=True)
class FontMetrics:
    """Advance widths for one face, in em units.

    No vertical metrics: `LINE_HEIGHT_FACTOR` explains why line height is not a per-font
    quantity read off this face's `hhea`/`OS/2` tables, so there is nothing vertical for
    this dataclass to carry.
    """

    family: str
    units_per_em: int
    advances: dict[int, int]
    """Codepoint -> advance width in font units."""
    default_advance: int

    def char_width(self, char: str, size_pt: float) -> float:
        advance = self.advances.get(ord(char), self.default_advance)
        return advance / self.units_per_em * size_pt

    def text_width(self, text: str, size_pt: float) -> float:
        """Width of `text` on one line, in points.

        Sums advance widths. Kerning and ligature substitution are not applied: both make
        text marginally *narrower*, so ignoring them biases budgets conservative, which is
        the correct direction for a constraint whose failure mode is overflow.
        """
        return sum(self.char_width(char, size_pt) for char in text)


@lru_cache(maxsize=32)
def load_metrics(family: str) -> FontMetrics:
    """Read the metrics of `family` from its actual font file.

    Raises:
        FontNotFoundError: the family is not installed (never substituted).
    """
    font_file = resolve_family(family)
    return _read_metrics(font_file.family, font_file.path)


def _read_metrics(family: str, path: Path) -> FontMetrics:
    font = TTFont(str(path), fontNumber=0, lazy=True)
    try:
        units_per_em = int(font["head"].unitsPerEm)  # type: ignore[attr-defined]
        hmtx = font["hmtx"]
        # A face with no usable Unicode cmap cannot be measured against text at all, so
        # this is the same class of failure as a missing font and gets the same treatment.
        cmap = font.getBestCmap()
        if not cmap:
            raise FontNotFoundError(
                f"{family} at {path} has no usable Unicode character map, so text cannot "
                "be measured against it and every budget would be meaningless (B11)."
            )

        advances: dict[int, int] = {}
        for codepoint, glyph_name in cmap.items():
            try:
                advances[codepoint] = int(hmtx[glyph_name][0])  # type: ignore[index]
            except KeyError:
                continue
    finally:
        font.close()

    return FontMetrics(
        family=family,
        units_per_em=units_per_em,
        advances=advances,
        default_advance=int(_NOTDEF_EM * units_per_em),
    )


# ---------------------------------------------------------------------------
# Wrapping and measurement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TextMeasurement:
    """The result of laying `text` out inside a fixed width."""

    lines: list[str]
    width_pt: float
    """Width of the widest line."""
    height_pt: float
    overflow_width: bool
    """A single word too long to fit the box at this size — wrapping cannot help."""

    @property
    def line_count(self) -> int:
        return len(self.lines)


def wrap_text(text: str, family: str, size_pt: float, max_width_pt: float) -> TextMeasurement:
    """Greedy word wrap using real advance widths.

    Matches how PowerPoint and LibreOffice break paragraphs: break on whitespace, never
    mid-word. A word wider than the box is reported through `overflow_width` rather than
    being broken, because the fix is a smaller type size or a different component, not a
    hyphen the renderer would not insert.
    """
    metrics = load_metrics(family)
    space_width = metrics.char_width(" ", size_pt)

    lines: list[str] = []
    overflow = False

    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue

        current: list[str] = []
        current_width = 0.0
        for word in words:
            word_width = metrics.text_width(word, size_pt)
            if word_width > max_width_pt:
                overflow = True
            candidate = word_width if not current else current_width + space_width + word_width
            if current and candidate > max_width_pt:
                lines.append(" ".join(current))
                current, current_width = [word], word_width
            else:
                current.append(word)
                current_width = candidate
        lines.append(" ".join(current))

    widest = max((metrics.text_width(line, size_pt) for line in lines), default=0.0)
    line_height = size_pt * LINE_HEIGHT_FACTOR
    return TextMeasurement(
        lines=lines,
        width_pt=widest,
        height_pt=line_height * len(lines),
        overflow_width=overflow,
    )


def measure_height(
    text: str, family: str, size_pt: float, max_width_pt: float, line_spacing: float = 1.0
) -> float:
    """Rendered height of `text` wrapped to `max_width_pt`, in points."""
    return wrap_text(text, family, size_pt, max_width_pt).height_pt * line_spacing


# ---------------------------------------------------------------------------
# Slot budgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotBudget:
    """How much text a component slot can hold, at the theme's type scale.

    `max_chars` is an estimate the content agent can hold in its head while writing;
    `fits()` is the authority, and the deterministic pre-render check uses that. The
    estimate exists because a prompt cannot call a function mid-sentence.
    """

    slot: str
    family: str
    size_pt: float
    width_pt: float
    height_pt: float
    line_spacing: float
    max_lines: int
    max_chars: int

    def fits(self, text: str) -> bool:
        """Whether `text` renders inside the slot. The authoritative check."""
        measurement = wrap_text(text, self.family, self.size_pt, self.width_pt)
        if measurement.overflow_width:
            return False
        return measurement.height_pt * self.line_spacing <= self.height_pt + 1e-6

    def describe(self) -> str:
        """One line for a content prompt (§6.7: budgets are hard constraints in the prompt)."""
        return (
            f"{self.slot}: at most {self.max_lines} line(s), roughly {self.max_chars} "
            f"characters, at {self.size_pt:g}pt {self.family}"
        )


def compute_budget(
    *,
    slot: str,
    family: str,
    size_pt: float,
    width_pt: float,
    height_pt: float,
    line_spacing: float = 1.0,
) -> SlotBudget:
    """Derive a slot's budget from its box and the font's real metrics.

    The character estimate uses the family's average advance over ASCII letters and a
    space, which tracks a real sentence far better than a fixed characters-per-inch
    constant would.
    """
    metrics = load_metrics(family)
    line_height = size_pt * LINE_HEIGHT_FACTOR * line_spacing
    max_lines = max(int((height_pt + 1e-6) // line_height), 0)

    sample = "abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    average = metrics.text_width(sample, size_pt) / len(sample)
    max_chars = int(max_lines * (width_pt / average)) if average > 0 else 0

    return SlotBudget(
        slot=slot,
        family=family,
        size_pt=size_pt,
        width_pt=width_pt,
        height_pt=height_pt,
        line_spacing=line_spacing,
        max_lines=max_lines,
        max_chars=max_chars,
    )
