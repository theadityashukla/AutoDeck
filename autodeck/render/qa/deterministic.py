"""Deterministic render QA — pure arithmetic over a rendered PPTX (Phase 3b, task 3b.2).

SCAFFOLD (Opus). Sonnet implements. Tests: `tests/test_deterministic_qa.py`.

**No model is involved, and none may be.** Every check here is arithmetic on shape
geometry, run sizes and theme colours read from the file. A model judging "does this
overlap" would be the one part of QA that could not be reproduced.

**Every failure must be fixable by a token or a slot adjustment** (PHASE-3B). So each finding
carries a `remedy` naming which, and a finding that neither can fix is typed
`"catalog_gap"`: it goes back to the Phase 3a catalog as a component design gap rather than
being special-cased in the renderer (PHASE-3B's third escalation trigger). The type makes
that routing impossible to skip.

**What this deliberately does not check: text overflowing its box.** That is the budget
engine's job, before render (§6.7). The brief is explicit — if deterministic QA starts
catching overflow routinely, the budgets are wrong and must be fixed upstream, not netted
here. A net that catches it quietly would hide the budget defect.

The four checks:

1. **Overlap** — two *text-bearing* shapes whose bounding boxes intersect by more than
   `OVERLAP_TOLERANCE_PT` in both dimensions. Text over a filled non-text shape (a panel, a
   chevron) is intended and is the contrast check's business, not this one's.
2. **Safe area** — any shape extending outside `Canvas(tokens).safe`.
3. **Minimum size** — any text run whose size is below `tokens.typography.minimum`. A run
   with no explicit size inherits from the theme and is resolved through it, not skipped.
4. **Contrast** — WCAG 2.x contrast ratio between each text run's colour and the fill of the
   top-most filled shape behind it (else the slide background). Threshold `CONTRAST_NORMAL`,
   or `CONTRAST_LARGE` for text ≥ `LARGE_TEXT_PT`, or ≥ `LARGE_BOLD_TEXT_PT` if bold.
   `schemeClr` resolves through the tokens palette; `sysClr` through its `lastClr` — note
   PHASE-3A §6.5: LibreOffice renders `sysClr` literally, so the rendered PNG and this check
   may disagree for `dk1`/`lt1` text, and the check follows the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from autodeck.design.theme.tokens import DesignTokens

OVERLAP_TOLERANCE_PT: Final = 1.0
"""Touching edges and sub-point rounding are not overlap."""

CONTRAST_NORMAL: Final = 4.5
CONTRAST_LARGE: Final = 3.0
LARGE_TEXT_PT: Final = 18.0
LARGE_BOLD_TEXT_PT: Final = 14.0
"""WCAG 2.x AA thresholds and its definition of large text. Named, sourced, not tuned."""

QACheck = Literal["overlap", "outside safe area", "below minimum size", "insufficient contrast"]
RemedyKind = Literal["token", "slot", "catalog_gap"]


@dataclass(frozen=True)
class QAFinding:
    check: QACheck
    slide_id: str
    """From the renderer's `autodeck:<id>` tag."""
    shapes: tuple[str, ...]
    """Shape names involved — one, or two for an overlap."""
    measured: float
    threshold: float
    remedy: RemedyKind
    remedy_detail: str
    """What to change: a token name ("typography.minimum", "palette.accent3") or a slot
    ("quote.attribution"), or for a catalog gap, which component and why no token or slot
    fixes it."""


def run_deterministic_qa(pptx: Path, tokens: DesignTokens) -> list[QAFinding]:
    """All four checks over every tagged slide in `pptx`, in slide then shape order.

    Contract: pure — reads the file, writes nothing, no model, no LibreOffice. Deterministic
    ordering. Remedy assignment: contrast → `token` (the colour); minimum size → `token`
    (`typography.minimum` or the role's size); outside safe area and overlap → `slot` when
    the shapes belong to a component slot the catalog declares, else `catalog_gap`.
    Untagged slides raise `ValueError` — findings must be attributable.
    """
    raise NotImplementedError("scaffold: Sonnet fills this in")


def contrast_ratio(foreground_hex: str, background_hex: str) -> float:
    """WCAG 2.x: (L1 + 0.05) / (L2 + 0.05), L the relative luminance with sRGB linearisation
    (channel ≤ 0.04045 → c/12.92, else ((c+0.055)/1.055)^2.4). Symmetric in its arguments;
    black on white is 21.0."""
    raise NotImplementedError("scaffold: Sonnet fills this in")
