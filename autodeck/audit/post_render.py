"""The post-render audit: prove the rendered file still says what the verified IR says.

PHASE-3B names two halves of one guarantee and says neither alone is sufficient:
**prevention** — the aesthetic loop's closed action set cannot express an edit
(`autodeck/ir/actions.py`) — and **detection**, this module: whatever the pipeline did, read
the rendered PPTX back and check it against the IR it was rendered from. Detection is what
catches the thing prevention could not anticipate: a component that formats a figure, a
template with a number baked in, a renderer bug that truncates a sentence.

Three checks, each independent:

1. **A2 on rendered text** — `numeric_linter.lint_rendered_slides` over each slide's face and
   notes text. A numeral that reached the page without reaching the IR blocks. The caption
   band's own "Source: doc p.N" line is excluded first: `numeric_linter.ALLOWLIST`'s own
   docstring names exactly this gap — "Phase 3b's post-render run will meet slide numbers and
   footer chrome, and the right fix there is for the text extractor to hand over body text
   rather than for this linter to guess which '7' was a page number" — and a page number is
   never itself quoted verbatim inside the citation it labels, so every clean render would
   otherwise fail A2 on its own citation captions. `_strip_caption_lines` is that fix's
   landing point, applied only to the numeric-lint input; claim survival and the shape checks
   below still see the caption, since neither of them asks whether a number traces anywhere.
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

**Found while building 3b's demo deck, escalated rather than worked around here: a diagram
node's claim fails claim survival on every clean render where its `claim.text` differs from
its `label`.** This module's own contract says diagram-node claims are "checked like face
claims" (`deck.claim_sites()` walks them in), which means against the rendered *face* text.
But `autodeck.design.diagrams.place_diagram` draws only `node.label` for every geometry
(`process_flow`, `two_by_two`, `layered_stack`) and never `node.claim.text` — the same
asymmetry `numeric_linter._diagram_scopes` already treats as two separate scopes because they
routinely differ. `label != claim.text` is not an edge case; it is the documented shape of
`preview.EXAMPLES["framework_diagram"]`'s own "enterprise" node (a short label, a longer
cited sentence backing it), committed as the golden example. So any diagram node built the
way that example is built — the normal way — gives a "claim altered in render" finding here
even though nothing rewrote anything: the claim was never printed verbatim anywhere for it to
survive as. Two fixes are possible and neither is this module's or `diagrams.py`'s alone to
pick: extend the diagram renderer to make a claimed node's full text reachable somewhere on
the slide (notes? a tooltip-like caption?), or redefine what "survives" means for a diagram
node claim — its `label`, not its `claim.text`, mirroring the numeric linter's own treatment.
Not loosened here; the check as specified is implemented exactly, and this is what it finds.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from autodeck.audit.numeric_linter import NumericReport, lint_rendered_slides
from autodeck.ingest.provenance import normalise_for_match
from autodeck.ir.models import Deck
from autodeck.render.extract import SlideText, extract_slide_text

PostRenderCheck = Literal[
    "claim altered in render",
    "slide missing from render",
    "unexpected slide in render",
    "image part without a figure",
]

_MEDIA_PREFIX = "ppt/media/"


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
        return self.numeric.passes and not self.findings


def _strip_caption_lines(text: str) -> str:
    """Drop every "Source: ..." caption line before handing text to the numeric linter.

    `renderer.source_line` (via `charts.source_line`) writes the citation caption as its own
    line, always starting `"Source: "`. Its page numbers are chrome the linter cannot tell
    from content — see the module docstring's note on `numeric_linter.ALLOWLIST`. Claim
    survival and the shape checks still see the caption; only this input is filtered.
    """
    return "\n".join(line for line in text.split("\n") if not line.startswith("Source: "))


def _claim_survives(claim_text: str, rendered_text: str) -> bool:
    """Whether `claim_text` appears in `rendered_text`, tolerating only whitespace, case and
    unicode-form differences. A separate, named function so a test can monkeypatch it to
    prove the check in `post_render_audit` is what makes the "reduces" → "eliminates" tamper
    fail — see `test_disabling_claim_survival_lets_the_word_change_through`."""
    return normalise_for_match(claim_text) in normalise_for_match(rendered_text)


def post_render_audit(deck: Deck, pptx: Path) -> PostRenderReport:
    """Run all three checks on `pptx` against `deck`, the IR it was rendered from.

    Contract: uses `autodeck.render.extract.extract_slide_text`; an `ExtractionError`
    propagates (an unattributable file is not auditable, so it is not "no findings"). Walks
    claims through `deck.claim_sites()` — the one enumeration — so diagram-node claims and
    notes claims are checked like face claims. Pure apart from reading the file.
    """
    rendered = extract_slide_text(pptx)

    findings: list[PostRenderFinding] = []
    findings.extend(_shape_findings(deck, rendered))
    findings.extend(_claim_survival_findings(deck, rendered))
    findings.extend(_image_part_findings(deck, pptx))

    deck_ids = {slide.id for slide in deck.slides}
    lintable = {sid: text for sid, text in rendered.items() if sid in deck_ids}
    rendered_text = {
        sid: _strip_caption_lines(f"{text.face}\n{text.notes}")
        for sid, text in lintable.items()
    }
    numeric = lint_rendered_slides(deck, rendered_text)

    return PostRenderReport(numeric=numeric, findings=tuple(findings))


def _shape_findings(deck: Deck, rendered: dict[str, SlideText]) -> list[PostRenderFinding]:
    deck_ids = [slide.id for slide in deck.slides]
    rendered_ids = set(rendered)

    findings = [
        PostRenderFinding(
            check="slide missing from render",
            slide_id=slide_id,
            detail=f"IR slide {slide_id!r} has no corresponding tagged slide in the render",
        )
        for slide_id in deck_ids
        if slide_id not in rendered_ids
    ]
    findings.extend(
        PostRenderFinding(
            check="unexpected slide in render",
            slide_id=slide_id,
            detail=f"rendered slide tagged {slide_id!r} names no slide in the IR deck",
        )
        for slide_id in sorted(rendered_ids - set(deck_ids))
    )
    return findings


def _claim_survival_findings(
    deck: Deck, rendered: dict[str, SlideText]
) -> list[PostRenderFinding]:
    findings: list[PostRenderFinding] = []
    for site in deck.claim_sites():
        slide_text = rendered.get(site.slide_id)
        if slide_text is None:
            continue  # already reported as "slide missing from render"

        haystack = slide_text.notes if site.in_speaker_notes else slide_text.face
        if not _claim_survives(site.claim.text, haystack):
            where = "notes" if site.in_speaker_notes else "face"
            findings.append(
                PostRenderFinding(
                    check="claim altered in render",
                    slide_id=site.slide_id,
                    detail=(
                        f"expected claim {site.claim.text!r} to appear in the rendered "
                        f"{where} text; rendered {where} text was {haystack!r}"
                    ),
                )
            )
    return findings


def _image_part_findings(deck: Deck, pptx: Path) -> list[PostRenderFinding]:
    has_figure = any(block.figure is not None for block in deck.all_blocks())
    if has_figure:
        return []

    with zipfile.ZipFile(pptx) as archive:
        media = sorted(name for name in archive.namelist() if name.startswith(_MEDIA_PREFIX))
    if not media:
        return []

    return [
        PostRenderFinding(
            check="image part without a figure",
            slide_id="",
            detail=(
                f"{pptx} contains {', '.join(media)} but the IR deck has no `figure` block; "
                "D10/D11 require charts, diagrams and icons to be native, never a picture"
            ),
        )
    ]
