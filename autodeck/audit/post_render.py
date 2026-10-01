"""The post-render audit: prove the rendered file still says what the verified IR says.

PHASE-3B names two halves of one guarantee and says neither alone is sufficient:
**prevention** — the aesthetic loop's closed action set cannot express an edit
(`autodeck/ir/actions.py`) — and **detection**, this module: whatever the pipeline did, read
the rendered PPTX back and check it against the IR it was rendered from. Detection is what
catches the thing prevention could not anticipate: a component that formats a figure, a
template with a number baked in, a renderer bug that truncates a sentence.

Four checks, each independent:

1. **A2 on rendered text** — `numeric_linter.lint_rendered_slides` over each slide's face and
   notes text. A numeral that reached the page without reaching the IR blocks. Every caption
   line the IR actually implies for that slide is excluded first:
   `numeric_linter.ALLOWLIST`'s own docstring names exactly this gap — "Phase 3b's post-render
   run will meet slide numbers and footer chrome, and the right fix there is for the text
   extractor to hand over body text rather than for this linter to guess which '7' was a page
   number" — and a page number is never itself quoted verbatim inside the citation it labels,
   so every clean render would otherwise fail A2 on its own citation captions.
   `renderer.expected_caption_lines(slide)` recomputes each slide's real caption(s) from the
   IR with the same `source_line` the render used, and only an **exact** match is dropped —
   never a prefix match, which would let a claim whose own text happens to begin `"Source: "`
   escape A2 (see `test_a_claim_beginning_with_source_is_still_caught_by_a2`). Applied only to
   the numeric-lint input; claim survival and the shape checks below still see the caption,
   since neither of them asks whether a number traces anywhere.
2. **Claim survival** — every claim site's text appears in its slide's rendered text, compared
   with `autodeck.ingest.provenance.normalise_for_match`, which tolerates whitespace, case and
   unicode form and nothing else. This catches what A2 cannot: a sentence changed without
   touching a number ("reduces" → "eliminates"). A face claim checks `claim.text` against the
   face; a notes claim checks it against the notes. **A diagram-node claim is neither of
   those, by construction**: `autodeck.design.diagrams.place_diagram` draws only `node.label`
   on the slide, for every geometry, never `node.claim.text` — the two routinely differ, the
   same asymmetry `numeric_linter._diagram_scopes` already treats as two separate scopes, and
   `preview.EXAMPLES["framework_diagram"]`'s own "enterprise" node is built exactly this way.
   So a node claim is checked in two parts, mirroring that split: its `label` must survive on
   the **face** (what the audience sees), and its `claim.text` must survive in the **notes**
   (`renderer._write_notes` writes every face diagram-node claim there, full text and source
   line, precisely so this has somewhere real to check it against — the presenter holds the
   evidence the slide only gestures at).
3. **Shape of the file** — every IR slide rendered exactly once and no extra slides; and no
   `ppt/media/` image part unless the deck has a `figure` block (D10/D11: charts, diagrams
   and icons are native, so an image part anywhere else is a fallback that should not exist).
4. **Auto-numbered lists** — no `a:buAutoNum` element carries a `startAt` attribute. Such an
   attribute would render a number that PowerPoint computes and the IR does not trace, breaking
   invariant A2 (every number on a slide is traced to its IR source).

PHASE-3B's escalation trigger applies to every finding here: **a discrepancy is not tuned
away — it means something in the pipeline is rewriting content, and the mechanism must be
found.** So every finding names the slide, the check, and the expected and actual text.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from autodeck.audit.numeric_linter import NumericReport, lint_rendered_slides
from autodeck.ingest.provenance import normalise_for_match
from autodeck.ir.models import ClaimSite, Deck, Slide
from autodeck.render.extract import SlideText, extract_slide_text
from autodeck.render.renderer import expected_caption_lines

PostRenderCheck = Literal[
    "claim altered in render",
    "slide missing from render",
    "unexpected slide in render",
    "image part without a figure",
    "auto-numbered item with startAt attribute",
]

_MEDIA_PREFIX = "ppt/media/"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
"""DrawingML namespace for XML element lookups."""


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


def _strip_caption_lines(slide: Slide, text: str) -> str:
    """Drop exactly `slide`'s own caption line(s) before handing text to the numeric linter.

    Recomputes them from the IR with `renderer.expected_caption_lines`, the same
    `source_line` the render used — an **exact** line match, never a prefix — so a page
    number the caption names is chrome the linter never sees (the gap
    `numeric_linter.ALLOWLIST`'s own docstring names), while a claim whose own text happens
    to start `"Source: "` is still handed over untouched, numbers and all. Claim survival
    and the shape checks still see the caption; only this input is filtered.
    """
    expected = expected_caption_lines(slide)
    if not expected:
        return text
    return "\n".join(line for line in text.split("\n") if line not in expected)


def _claim_survives(claim_text: str, rendered_text: str) -> bool:
    """Whether `claim_text` appears in `rendered_text`, tolerating only whitespace, case and
    unicode-form differences. A separate, named function so a test can monkeypatch it to
    prove the check in `post_render_audit` is what makes the "reduces" → "eliminates" tamper
    fail — see `test_disabling_claim_survival_lets_the_word_change_through`."""
    return normalise_for_match(claim_text) in normalise_for_match(rendered_text)


def post_render_audit(deck: Deck, pptx: Path) -> PostRenderReport:
    """Run all four checks on `pptx` against `deck`, the IR it was rendered from.

    Contract: uses `autodeck.render.extract.extract_slide_text`; an `ExtractionError`
    propagates (an unattributable file is not auditable, so it is not "no findings"). Walks
    claims through `deck.claim_sites()` — the one enumeration — so diagram-node claims and
    notes claims are checked (a node claim against the label on the face and its own text in
    the notes; see the module docstring). Pure apart from reading the file.
    """
    rendered = extract_slide_text(pptx)
    slide_by_id = {slide.id: slide for slide in deck.slides}

    findings: list[PostRenderFinding] = []
    findings.extend(_shape_findings(deck, rendered))
    findings.extend(_claim_survival_findings(deck, rendered, slide_by_id))
    findings.extend(_image_part_findings(deck, pptx))
    findings.extend(_auto_number_start_findings(pptx))

    lintable = {sid: text for sid, text in rendered.items() if sid in slide_by_id}
    rendered_text = {
        sid: _strip_caption_lines(slide_by_id[sid], f"{text.face}\n{text.notes}")
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


def _diagram_node_label(slide: Slide, site: ClaimSite) -> str:
    """The label a diagram-node claim site's own node shows on the face.

    `ClaimSite` carries the `Claim`, not the `DiagramNode` it sits on — by design
    (`ir/models.py`'s own docstring: a claim site's setter writes a verdict back through the
    node, but never hands the node itself to a caller). So finding the label means the one
    walk `DiagramSpec.nodes()` already provides, not a second one.
    """
    for block in slide.blocks:
        if block.id == site.block_id and block.diagram is not None:
            for node in block.diagram.nodes:
                if node.id == site.node_id:
                    return node.label
    raise AssertionError(
        f"claim site {site.claim_id!r} names no diagram node on slide {slide.id!r}; "
        "deck.claim_sites() and DiagramSpec.nodes() have disagreed about where it lives"
    )


def _claim_survival_findings(
    deck: Deck, rendered: dict[str, SlideText], slide_by_id: dict[str, Slide]
) -> list[PostRenderFinding]:
    findings: list[PostRenderFinding] = []
    for site in deck.claim_sites():
        slide_text = rendered.get(site.slide_id)
        if slide_text is None:
            continue  # already reported as "slide missing from render"

        if site.node_id is not None:
            findings.extend(
                _node_claim_survival_findings(site, slide_by_id[site.slide_id], slide_text)
            )
            continue

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


def _node_claim_survival_findings(
    site: ClaimSite, slide: Slide, slide_text: SlideText
) -> list[PostRenderFinding]:
    """A diagram-node claim survives in two parts — see the module docstring's check 2."""
    findings: list[PostRenderFinding] = []

    label = _diagram_node_label(slide, site)
    if not _claim_survives(label, slide_text.face):
        findings.append(
            PostRenderFinding(
                check="claim altered in render",
                slide_id=site.slide_id,
                detail=(
                    f"expected diagram node label {label!r} to appear in the rendered face "
                    f"text; rendered face text was {slide_text.face!r}"
                ),
            )
        )

    if not _claim_survives(site.claim.text, slide_text.notes):
        findings.append(
            PostRenderFinding(
                check="claim altered in render",
                slide_id=site.slide_id,
                detail=(
                    f"expected diagram node claim {site.claim.text!r} to appear in the "
                    f"rendered notes text; rendered notes text was {slide_text.notes!r}"
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


def _auto_number_start_findings(pptx: Path) -> list[PostRenderFinding]:
    """Walk every slide's XML and flag any `a:buAutoNum` with a `startAt` attribute.

    Such an attribute makes PowerPoint render a number that the IR does not trace,
    breaking invariant A2 (every number on a slide is traced to its source).
    """
    findings: list[PostRenderFinding] = []

    with zipfile.ZipFile(pptx) as archive:
        # Find all slide XML files (ppt/slides/slide1.xml, ppt/slides/slide2.xml, etc.)
        slide_paths = sorted(
            name
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )

        for slide_path in slide_paths:
            slide_xml = archive.read(slide_path).decode("utf-8")
            root = ET.fromstring(slide_xml)

            # Extract the slide ID from cSld/@name attribute
            # The name has the format "autodeck:<slide_id>"
            cSld = root.find(
                ".//{http://schemas.openxmlformats.org/presentationml/2006/main}cSld"
            )
            if cSld is None:
                continue
            name = cSld.get("name", "")
            if not name.startswith("autodeck:"):
                continue
            slide_id = name[len("autodeck:") :]

            # Find all a:buAutoNum elements with startAt attribute
            for buAutoNum in root.findall(f".//{{{_A_NS}}}buAutoNum"):
                start_at = buAutoNum.get("startAt")
                if start_at is not None:
                    findings.append(
                        PostRenderFinding(
                            check="auto-numbered item with startAt attribute",
                            slide_id=slide_id,
                            detail=(
                                f"auto-numbered item on slide {slide_id!r} has "
                                f"startAt={start_at!r}; PowerPoint renders this number, "
                                "but it is not traced to the IR"
                            ),
                        )
                    )

    return findings
