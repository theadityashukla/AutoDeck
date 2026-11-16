"""A deterministic table of contents of the corpus, for an agent that must choose where to look.

Built from section headers alone: cheap, stable (same corpus, same text, so a resumed session's
provider cache keys hold) and enough to pick a page to `read_passage`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from autodeck.ingest.document_store import Document
from autodeck.knowledge.loader import CachedClaim

MAX_HEADINGS = 40
MAX_HEADING_CHARS = 80


def build_corpus_map(documents: Sequence[Document], claims: Sequence[CachedClaim]) -> str:
    if not documents:
        return "(no documents)"
    out: list[str] = []
    for doc in sorted(documents, key=lambda d: d.doc_id):
        out.append(f"## {doc.doc_id} — {doc.title or ''} ({doc.page_count} pages)")
        headers = sorted(
            (e for e in doc.elements if e.kind == "section_header"),
            key=lambda e: (e.page, e.reading_order),
        )[:MAX_HEADINGS]
        by_page: dict[int, list[str]] = defaultdict(list)
        for element in headers:
            heading = " ".join(element.text.split())[:MAX_HEADING_CHARS]
            if heading:
                by_page[element.page].append(heading)
        out.extend(f"- p.{page}: {'; '.join(h)}" for page, h in sorted(by_page.items()))
        out.append("")
    out.append(
        f"## Curated claims (claims.md): {len(claims)} — call read_claims to see and cite them"
    )
    return "\n".join(out)
