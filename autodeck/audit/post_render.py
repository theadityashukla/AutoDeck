"""The post-render audit: prove the rendered file still says what the verified IR says.

SCAFFOLD (Opus). Sonnet implements. Tests: `tests/test_post_render.py`. Task 3b.8.

PHASE-3B names two halves of one guarantee and says neither alone is sufficient:
**prevention** — the aesthetic loop's closed action set cannot express an edit
(`autodeck/ir/actions.py`) — and **detection**, this module: whatever the pipeline did, read
the rendered PPTX back and check it against the IR it was rendered from. Detection is what
catches the thing prevention could not anticipate: a component that formats a figure, a
template with a number baked in, a renderer bug that truncates a sentence.

Three checks, each independent:

1. **A2 on rendered text** — `numeric_linter.lint_rendered_slides` over each slide's face and
   notes text. A numeral that reached the page without reaching the IR blocks.
2. **Claim survival** — every claim site's `claim.text` appears in its slide's rendered text
   (face for face claims, notes for notes claims), compared with
   `autodeck.ingest.provenance.normalise_for_match`, which tolerates whitespace, case and
   unicode form and nothing else. This catches what A2 cannot: a sentence changed without
   touching a number ("reduces" → "eliminates").
3. **Shape of the file** — every IR slide rendered exactly once and no extra slides; and no
   `ppt/media/` image part unless the deck has a `figure` block (D10/D11: charts, diagrams
   and icons are native, so an image part anywhere else is a fallback that should not exist).

PHASE-3B's escalation trigger applies to every finding here: **a discrepancy is not tuned
away — it means something in the pipeline is rewriting content, and the mechanism must be
found.** So every finding names the slide, the check, and the expected and actual text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from autodeck.audit.numeric_linter import NumericReport
from autodeck.ir.models import Deck

PostRenderCheck = Literal[
    "claim altered in render",
    "slide missing from render",
    "unexpected slide in render",
    "image part without a figure",
]


@dataclass(frozen=True)
class PostRenderFinding:
    check: PostRenderCheck
    slide_id: str
    detail: str
    """Names what was expected and what was found."""


@dataclass(frozen=True)
class PostRenderReport:
    numeric: NumericReport
    findings: tuple[PostRenderFinding, ...] = field(default=())

    @property
    def passes(self) -> bool:
        """True only when the rendered numeric lint passes and there are no findings."""
        raise NotImplementedError("scaffold: Sonnet fills this in")


def post_render_audit(deck: Deck, pptx: Path) -> PostRenderReport:
    """Run all three checks on `pptx` against `deck`, the IR it was rendered from.

    Contract: uses `autodeck.render.extract.extract_slide_text`; an `ExtractionError`
    propagates (an unattributable file is not auditable, so it is not "no findings"). Walks
    claims through `deck.claim_sites()` — the one enumeration — so diagram-node claims and
    notes claims are checked like face claims. Pure apart from reading the file.
    """
    raise NotImplementedError("scaffold: Sonnet fills this in")
