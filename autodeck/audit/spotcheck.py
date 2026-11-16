"""GATE 1a evidence: render each citation's bbox onto its source page (§7 Phase 1).

The gate is *"the owner spot-checks 10 citations against the source PDFs. All 10 must
resolve exactly — correct page, bbox pointing at the right region, quote verbatim."* Done
by hand that means opening a PDF, finding page 7, and mentally mapping `(53.6, 222.9,
295.7, 315.3)` onto the paper — for ten citations, in a coordinate space with two possible
origins. That is tedious enough that it gets skimmed, and a skimmed gate is the failure the
gate exists to prevent.

So this renders the page and draws the box. The check becomes "does the red rectangle sit
around the quoted sentence", which takes a second per citation and cannot be fudged.

**It deliberately does not decide.** Nothing here returns a pass or a fail, and no summary
says "10/10 correct". The verdict is the owner's (plan §0.3, A7); the job of this module is
to make forming it cheap. What it *can* assert mechanically — that the quote hash still
verifies — it reports separately from the visual question, because a hash check passing
says nothing about whether the box is on the right part of the page. That is exactly the
bug this rendering exists to catch: a mirrored bbox hash-verifies perfectly.

Owning phase: 1.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from autodeck.ingest.document_store import DocumentStore
from autodeck.ir.models import Citation

#: Render resolution. PDF user-space is 72 units to the inch, so 150 dpi is a 2.08x scale —
#: enough that a bbox off by a line is obvious, without producing 5 MB pages.
RENDER_DPI = 150

#: Bright red, thick. This is a proofreading mark, not a design element; it has to survive
#: being looked at quickly on a laptop screen next to dense body text.
BOX_COLOUR = (220, 0, 0)
BOX_WIDTH = 4


class SpotCheckError(RuntimeError):
    """A spot-check page could not be rendered."""


@dataclass(frozen=True)
class SpotCheck:
    """One citation, rendered for human inspection."""

    citation: Citation
    image: Path
    hash_verified: bool
    """Whether the quote still resolves against the stored document.

    Reported *alongside* the image, never instead of it. A vertically mirrored bbox
    hash-verifies — the quote is unchanged, only its location is wrong — so this being
    True is not evidence the citation is correct.
    """
    source_pdf: Path | None = None
    label: str = ""


def render_citation(
    citation: Citation,
    pdf: Path,
    output: Path,
    *,
    dpi: int = RENDER_DPI,
) -> Path:
    """Render the citation's page with its bbox drawn on top.

    Raises:
        SpotCheckError: `pdftoppm` is unavailable or the page could not be rendered.
    """
    from PIL import Image, ImageDraw

    page_png = _render_page(pdf, citation.page, dpi=dpi)
    try:
        image = Image.open(page_png).convert("RGB")
        scale = dpi / 72.0
        x0, y0, x1, y1 = (value * scale for value in citation.bbox)
        ImageDraw.Draw(image).rectangle([x0, y0, x1, y1], outline=BOX_COLOUR, width=BOX_WIDTH)
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output)
    finally:
        shutil.rmtree(page_png.parent, ignore_errors=True)
    return output


def _render_page(pdf: Path, page: int, *, dpi: int) -> Path:
    """Rasterise one page with poppler's `pdftoppm`."""
    if shutil.which("pdftoppm") is None:
        raise SpotCheckError(
            "pdftoppm not found. Spot-check rendering needs poppler-utils "
            "(`apt install poppler-utils`, `brew install poppler`). Without it the GATE 1a "
            "check falls back to reading coordinates by hand, which is what this avoids."
        )

    directory = Path(tempfile.mkdtemp(prefix="autodeck-spotcheck-"))
    prefix = directory / "page"
    try:
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page),
                "-l",
                str(page),
                "-r",
                str(dpi),
                "-png",
                str(pdf),
                str(prefix),
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise SpotCheckError(
            f"could not render page {page} of {pdf.name}: "
            f"{exc.stderr.decode('utf-8', 'replace').strip()}"
        ) from exc

    rendered = sorted(directory.glob("page*.png"))
    if not rendered:
        shutil.rmtree(directory, ignore_errors=True)
        raise SpotCheckError(
            f"pdftoppm produced no image for page {page} of {pdf.name}. The document has "
            "fewer pages than the citation claims, which means the citation is wrong."
        )
    return rendered[0]


def build_spot_checks(
    citations: list[tuple[Citation, str]],
    store: DocumentStore,
    papers: dict[str, Path],
    output_dir: Path,
    *,
    dpi: int = RENDER_DPI,
) -> list[SpotCheck]:
    """Render every citation that has a source PDF available.

    Args:
        citations: `(citation, label)` pairs. The label is what the reviewer reads as
            context — usually the claim the citation is meant to support, since checking a
            box against a page only answers half the question. The other half is whether
            the quoted sentence actually supports the claim, and only a human can judge it.
        papers: `doc_id` -> PDF path.

    A citation whose PDF is missing is still returned, with `image` pointing nowhere and
    `source_pdf` None — dropping it would make the sheet look complete when a citation
    could not be checked at all.
    """
    checks: list[SpotCheck] = []
    for index, (citation, label) in enumerate(citations, start=1):
        pdf = papers.get(citation.doc_id)
        verified = store.verify_citation(citation)
        if pdf is None or not pdf.exists():
            checks.append(
                SpotCheck(
                    citation=citation,
                    image=output_dir / f"{index:02d}-missing.png",
                    hash_verified=verified,
                    source_pdf=None,
                    label=label,
                )
            )
            continue
        image = render_citation(
            citation,
            pdf,
            output_dir / f"{index:02d}-{citation.doc_id}-p{citation.page}.png",
            dpi=dpi,
        )
        checks.append(
            SpotCheck(
                citation=citation,
                image=image,
                hash_verified=verified,
                source_pdf=pdf,
                label=label,
            )
        )
    return checks


def write_index(checks: list[SpotCheck], path: Path) -> Path:
    """Write the reviewer's worksheet.

    Markdown with the images inline, one section per citation, and an explicit unticked
    checkbox for each. The checkbox is the point: it is the owner's verdict, recorded by
    the owner, and nothing in this repository ticks it (A7).
    """
    lines = [
        "# GATE 1a — citation spot-check",
        "",
        f"{len(checks)} citation(s). The gate asks for **10, all resolving exactly**.",
        "",
        "For each one below, check three things against the rendered page:",
        "",
        "1. **Page** — is this the page the quote is actually on?",
        "2. **Box** — does the red rectangle sit around the quoted text?",
        "3. **Quote** — is the quoted string verbatim, and does it support the claim?",
        "",
        "The third is the one no machine can answer. A quote can be verbatim, correctly",
        "boxed, and still not support the claim it was attached to.",
        "",
        "> `hash verified` below means the stored text still matches the citation's",
        "> sha256. It is **not** evidence the box is in the right place — a vertically",
        "> mirrored bbox hash-verifies perfectly, which is the bug this sheet exists to",
        "> catch. Judge the image.",
        "",
        "---",
        "",
    ]

    for index, check in enumerate(checks, start=1):
        citation = check.citation
        lines.append(f"## {index}. `{citation.doc_id}` — page {citation.page}")
        lines.append("")
        if check.label:
            lines.append(f"**Claim:** {check.label}")
            lines.append("")
        lines.append(f"**Quote:** “{citation.quote.strip()}”")
        lines.append("")
        lines.append(
            f"**bbox:** `{tuple(round(v, 1) for v in citation.bbox)}` · "
            f"**sha256:** `{citation.quote_sha256[:16]}…` · "
            f"**hash verified:** {'yes' if check.hash_verified else '**NO**'}"
        )
        lines.append("")
        if check.source_pdf is None:
            lines.append(
                "> **Source PDF not found — this citation could not be rendered and "
                "therefore cannot be checked.** Treat it as a failure of the gate, not as "
                "an absence of evidence."
            )
        else:
            lines.append(f"![citation {index}]({check.image.name})")
        lines.append("")
        lines.append(f"- [ ] Citation {index} resolves exactly")
        lines.append("")
        lines.append("---")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
