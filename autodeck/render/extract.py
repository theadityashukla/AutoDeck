"""Read a rendered PPTX back into text, by IR slide id (Phase 3b, task 3b.8's input).

SCAFFOLD (Opus). Sonnet implements. Tests: `tests/test_post_render.py`.

The post-render audit is only as good as this extraction: text it does not read is text the
audit cannot check. So it reads **everything a reader could see or a chart could plot**:
every text frame on the slide (including table cells and grouped shapes, even though the
renderer groups nothing), every chart's title, axis titles, category labels, series names
**and cached values** from the chart XML (`c:numCache`/`c:strCache`), and the notes page.
Chart values matter most: a renderer that altered a plotted number would otherwise leave no
trace in any text frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ExtractionError(RuntimeError):
    """The file cannot be attributed back to IR slides."""


@dataclass(frozen=True)
class SlideText:
    face: str
    """Every visible text run and chart string/value on the slide, newline-joined."""
    notes: str
    """The notes page's text."""


def extract_slide_text(pptx: Path) -> dict[str, SlideText]:
    """IR slide id → its rendered text.

    Contract: slide ids come from `cSld/@name` with `renderer.SLIDE_TAG_PREFIX` stripped. A
    slide with no tag, or two slides with the same tag, raises `ExtractionError` — text that
    cannot be attributed cannot be audited, and guessing by position is how a moved slide's
    numbers get checked against the wrong citations. Chart values are formatted with `repr`
    of the float, the same way `charts.py` writes them, so the numeric linter sees what it
    would see in the IR. Order within `face` is the shape tree order.
    """
    raise NotImplementedError("scaffold: Sonnet fills this in")
