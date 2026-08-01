"""Grobid adapter — **stub only**, deliberately unimplemented (task 1.10).

Plan §6.3: *"Keep a Grobid adapter stub only if rigorous bibliographic metadata is later
needed; not in the critical path."* This file exists so that the decision not to build it
is visible in the code rather than only in a plan document, and so nobody re-derives the
question from scratch.

## What Grobid would add, and why it is not needed yet

Grobid extracts *bibliographic* structure — authors, affiliations, a parsed reference list,
citation contexts linking "as shown in [12]" to the actual entry. Docling extracts
*document* structure: reading order, tables, figures, and the page/bbox provenance A1
resolves against. They overlap very little.

Everything AutoDeck currently needs is document structure. A citation is
`(doc_id, page, bbox, verbatim_quote, quote_sha256)` — none of which is bibliographic, and
all of which Docling supplies. Adding Grobid now would mean running a second extraction
service, reconciling two element models, and deciding which wins on disagreement, all to
populate fields nothing reads.

## When to actually build this

Three triggers, any one of which makes it worth the cost:

1. **The audit report must cite in a scholarly format.** Today it cites doc/page/quote,
   which is what a spot-check at GATE 1a needs. If a client wants "Kaplan et al. (2024),
   p. 4" the author list has to come from somewhere, and parsing it out of the title block
   with a regex is exactly the kind of nearly-right that A1 exists to prevent.
2. **Following references becomes a retrieval path.** If the corpus should expand by
   walking citations out of a seed paper, that reference list must be parsed properly.
3. **Deduplicating a corpus by identity rather than filename.** Two PDFs of the same paper
   should be one `doc_id`; DOI-level metadata is how that is decided reliably.

## How it would fit

Grobid is a service (Docker, `grobid/grobid`), which collides with B10 — local development
only, no containers before v3. So this arriving is coupled to that decision changing, or
to accepting a hosted instance. The adapter would enrich `Document` with a
`BibliographicMetadata` block **alongside** Docling's elements, never replacing them:
provenance stays Docling's, because provenance is what A1 resolves against and mixing two
extractors' coordinate systems is a good way to reintroduce the bbox bug Phase 1 already
found once.

Owning phase: 1 (task 1.10) — stub only, by design. Implement only when a trigger above
actually fires.
"""

from __future__ import annotations

from autodeck.ingest.document_store import IngestError


class GrobidNotImplementedError(IngestError):
    """Grobid support does not exist and is not planned.

    Raised rather than silently returning empty metadata, so a caller who reaches for
    bibliographic data discovers immediately that it is not there — instead of building on
    fields that are always `None`.
    """


def extract_bibliographic_metadata(pdf_path: str) -> None:
    """Not implemented. See the module docstring for the triggers that would justify it.

    Raises:
        GrobidNotImplementedError: always.
    """
    raise GrobidNotImplementedError(
        f"Grobid bibliographic extraction is a deliberate stub and was not run on "
        f"{pdf_path!r}. Docling supplies the document structure and page/bbox provenance "
        "that A1 needs; Grobid would add author lists, parsed reference lists and DOIs, "
        "which nothing currently reads. Plan §6.3 keeps it out of the critical path. "
        "Build it when the audit report needs scholarly citation formats, when following "
        "references becomes a retrieval path, or when the corpus needs identity-based "
        "deduplication — and note it is a service, which collides with B10."
    )
