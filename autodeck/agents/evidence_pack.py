"""The deterministic evidence one compose call sees (Phase 3c).

Draft-first compose writes a whole deck from one prompt, so it cannot be handed per-slide
retrieval. Instead code builds a single *evidence pack* up front: curated `claims.md`
entries first (small, pre-verified, high value), then retrieved corpus spans, trimmed to a
token budget. No model is involved, so the same inputs always produce the same pack and the
audit trail can record exactly what the writer was shown.

**Client isolation (A4).** This module opens no knowledge folder and no corpus. It sees only
what the caller passes in. The caller assembles the inputs the way `cli.content` does:

    context = ContextAssembler(
        knowledge_root, client=deck.client, project=deck.project
    ).assemble()
    claims = KnowledgeLoader(knowledge_root).load_project(deck.project).claims
    docs = list(DocumentStore(corpus_root / deck.project).documents())
    index = build_index(docs, project=deck.project)
    pack = build_evidence_pack(
        prompt, project_md=context.project_md, claims=claims, index=index
    )

Rendering and matching reuse `content.py` (`render_evidence`, `_gather_claims`), and the
pack's claims/spans are what `content.resolve_blocks` must be given: the model is shown
exactly the evidence the resolver will accept citations against — no third path.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from autodeck.agents.content import _gather_claims, render_evidence
from autodeck.ingest.deck_source import DOC_ID_PREFIX
from autodeck.ingest.document_store import Document
from autodeck.ir.models import ProvenanceMode
from autodeck.knowledge.loader import CachedClaim
from autodeck.retrieval.hybrid import HybridIndex, RetrievedSpan, search

MAX_QUERIES = 12

PER_SECTION = 2
"""Opening paragraphs taken from each section by `section_lead_spans`."""

_BOILERPLATE_HEADING = re.compile(
    r"\b(?:references?|bibliography|acknowledge?ments?|declarations?|funding|conflicts? of "
    r"interest|author contributions?|data availability|supplementary|open access|appendix|"
    r"proofs?|lemma|theorem|definition|corollary|key points)\b",
    re.I,
)
"""Prompt plus at most this many project_md theme lines in total."""

PAPER_QUERIES = 24
"""A redesign's paper check searches for more lines: the deck has more to confirm."""

_THEME_LINE = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")


@dataclass(frozen=True)
class EvidencePack:
    claims: tuple[CachedClaim, ...]
    """Curated `claims.md` entries included, in first-matched order."""
    spans: tuple[RetrievedSpan, ...]
    """Retrieved spans included, citable and not (as `content.py` keeps them)."""
    text: str
    """`render_evidence(claims, spans)` — exactly what the model is shown."""
    queries: tuple[str, ...]
    """The queries that built the pack, for the audit trail."""
    dropped: int
    """Spans cut from the end to fit the budget."""
    approx_tokens: int
    """Estimate only: `len(text) // 4`. Not a tokenizer count."""


def theme_queries(prompt: str, project_md: str, *, limit: int = MAX_QUERIES) -> tuple[str, ...]:
    """The prompt, then project_md's headings and list items, trimmed and de-duplicated."""
    queries: list[str] = []
    seen: set[str] = set()
    candidates = [
        prompt,
        *(m.group(1) for line in project_md.splitlines() if (m := _THEME_LINE.match(line))),
    ]
    for candidate in candidates:
        query = " ".join(candidate.split())
        if query and query not in seen:
            seen.add(query)
            queries.append(query)
        if len(queries) >= limit:
            break
    return tuple(queries)


def section_lead_spans(
    index: HybridIndex, *, per_section: int = PER_SECTION
) -> tuple[RetrievedSpan, ...]:
    """The opening paragraphs of every section of every document, in reading order.

    Run XLP2 (2026-10-13): spans retrieved for the prompt and `project.md` filled 8.5k of a
    24k-token pack and missed the review's headline HbA1c result, its adverse-event summary
    and its cardiovascular outcome, so the writer could not cite them. Using the section
    headings as search queries did not help: BM25 returned the headings themselves. A
    reader skims a paper by reading the first paragraphs under each heading, and those are
    where a paper states its results. Boilerplate sections (references, acknowledgements,
    proofs) are skipped. Deterministic: same corpus, same spans.
    """
    out: list[RetrievedSpan] = []
    elements = sorted(
        index.elements.values(), key=lambda e: (e.doc_id, e.page, e.reading_order)
    )
    taking = 0
    for element in elements:
        if element.kind == "section_header":
            heading = " ".join(element.text.split())
            taking = 0 if _BOILERPLATE_HEADING.search(heading) else per_section
            continue
        if taking and element.kind == "text" and element.is_citable and len(element.text) > 80:
            out.append(
                RetrievedSpan(
                    doc_id=element.doc_id,
                    element_id=element.element_id,
                    page=element.page,
                    text=element.retrieval_text(),
                    score=0.0,
                    citable=True,
                )
            )
            taking -= 1
    return tuple(out)


def build_evidence_pack(
    prompt: str,
    *,
    project_md: str,
    claims: Sequence[CachedClaim],
    index: HybridIndex,
    budget_tokens: int = 24_000,
    per_query: int = 8,
    max_queries: int = MAX_QUERIES,
    extra_queries: Sequence[str] = (),
    section_leads: bool = True,
) -> EvidencePack:
    """Build the evidence for one compose call. Deterministic: same inputs, same pack.

    Queries, in priority order: the prompt, then `extra_queries` (what the person answered
    at clarify), then `project_md`'s theme lines. After the retrieved spans come (with
    `section_leads`) the opening paragraphs of every section of the corpus. Curated claims whose vocabulary
    overlaps any query come first and are never trimmed; spans follow, unioned across
    queries in first-seen order (deduplicated on `(doc_id, page, text)`), then cut from the
    end until `approx_tokens <= budget_tokens`, so the lowest-priority queries are trimmed
    first. Receives only what the caller gives it; it opens no knowledge folder.
    """
    themed = theme_queries(prompt, project_md, limit=max_queries)
    extras = tuple(" ".join(q.split()) for q in extra_queries if q.strip())
    queries = tuple(dict.fromkeys((*themed[:1], *extras, *themed[1:])))

    picked: list[CachedClaim] = []
    seen_claims: set[tuple[str, int, str]] = set()
    spans: list[RetrievedSpan] = []
    seen_spans: set[tuple[str, int, str]] = set()
    for query in queries:
        for claim in _gather_claims(query, claims):
            key = (claim.doc_id, claim.page, claim.quote)
            if key not in seen_claims:
                seen_claims.add(key)
                picked.append(claim)
        for span in search(index, query, limit=per_query, citable_only=False):
            key = (span.doc_id, span.page, span.text)
            if key not in seen_spans:
                seen_spans.add(key)
                spans.append(span)
    if section_leads:
        for span in section_lead_spans(index):
            key = (span.doc_id, span.page, span.text)
            if key not in seen_spans:
                seen_spans.add(key)
                spans.append(span)

    dropped = 0
    text = render_evidence(picked, spans)
    while spans and len(text) // 4 > budget_tokens:
        spans.pop()
        dropped += 1
        text = render_evidence(picked, spans)

    return EvidencePack(
        claims=tuple(picked),
        spans=tuple(spans),
        text=text,
        queries=queries,
        dropped=dropped,
        approx_tokens=len(text) // 4,
    )


def document_spans(deck: Document) -> tuple[RetrievedSpan, ...]:
    """One span per element of a whole document, in page order (reading order within one).

    Used for the client's deck (slide = page) and, in `normal` mode, the person's own
    conversation (message = page).

    Citable elements are citable spans; a picture or chart is kept as a non-citable span so
    the rendering can say "slide 4 has a picture whose content we cannot read" rather than
    dropping it silently. Each span names its own `element_id`, which is what lets
    `RetrievedSpan.to_citation` resolve a quote inside exactly that element.
    """
    spans: list[RetrievedSpan] = []
    for element in sorted(deck.elements, key=lambda e: (e.page, e.reading_order)):
        if not element.is_citable:
            # A picture or chart: say it is there, never offer it as something to quote.
            if element.retrieval_text().strip():
                spans.append(_deck_span(deck, element, element.retrieval_text(), citable=False))
            continue
        # The element's own `text` — what the resolver matches — never `retrieval_text`,
        # which appends every table cell a second time and so shows the writer a "sentence"
        # that exists nowhere on the slide. A table is shown one row per line, each row
        # resolving inside the same element.
        rows = element.text.splitlines() if element.table else [element.text]
        spans.extend(
            _deck_span(deck, element, row, citable=True) for row in rows if row.strip()
        )
    return tuple(spans)


deck_spans = document_spans  # the redesign's name for it, kept for existing callers


def conversation_section(spans: Sequence[RetrievedSpan]) -> str:
    """The never-trimmed "from you" section: a heading, then the spans one per line in the
    same format `render_evidence` gives every other span (so a quote copied from here is
    flattened exactly as the resolver's tolerant matcher expects). Empty for no spans."""
    if not spans:
        return ""
    doc_id = spans[0].doc_id
    return (
        f'# What you told us (citable as "from you"; doc id {doc_id})\n\n'
        + render_evidence((), spans)
    )


def with_conversation(
    pack: EvidencePack, doc: Document | None, mode: ProvenanceMode
) -> EvidencePack:
    """Add what the person typed to a pack, in `normal` mode only (B55).

    `strict` returns `pack` unchanged — the conversation is omitted from the evidence here,
    and a `Deck` validator refuses a `conversation--` citation anyway. In `normal` the
    section goes *before* the corpus evidence and the conversation's spans lead `spans`; this
    runs after `build_evidence_pack` has trimmed to its budget, so the conversation is never
    cut (it is the person's own words, and small).
    """
    if mode != "normal" or doc is None:
        return pack
    spans = document_spans(doc)
    if not spans:
        return pack
    text = conversation_section(spans) + "\n\n" + pack.text
    return replace(
        pack, spans=(*spans, *pack.spans), text=text, approx_tokens=len(text) // 4
    )


def _deck_span(deck: Document, element, text: str, *, citable: bool) -> RetrievedSpan:  # type: ignore[no-untyped-def]
    return RetrievedSpan(
        doc_id=deck.doc_id,
        element_id=element.element_id,
        page=element.page,
        text=text,
        score=0.0,
        citable=citable,
    )


def render_deck(deck: Document, spans: Sequence[RetrievedSpan]) -> str:
    """The whole deck, slide by slide, each element rendered by `render_evidence`.

    The same function renders every other span, so a quote copied from here is whitespace-
    flattened exactly as the resolver's tolerant matcher expects. Slides with no text are
    still listed: the writer must see that slide N exists.
    """
    by_slide: dict[int, list[RetrievedSpan]] = {}
    for span in spans:
        by_slide.setdefault(span.page, []).append(span)
    blocks: list[str] = []
    for slide in range(1, deck.page_count + 1):
        items = by_slide.get(slide)
        body = render_evidence((), items) if items else "(no text on this slide)"
        blocks.append(f"## slide {slide}\n{body}")
    return "\n\n".join(blocks)


def build_redesign_pack(
    deck: Document,
    *,
    check_papers: bool = False,
    project_md: str = "",
    claims: Sequence[CachedClaim] = (),
    index: HybridIndex | None = None,
    budget_tokens: int = 24_000,
    per_query: int = 8,
) -> EvidencePack:
    """The evidence for a redesign: the WHOLE deck in slide order (a deck is small enough to
    send whole, so nothing is retrieved or trimmed), and — only when `check_papers` — the
    normal paper pack built from the deck's own text (B49: the paper check is opt-in).

    The paper half reuses `build_evidence_pack`, queried with each line of the
    deck's text, over `index` (which may also hold the deck itself; its spans are dropped
    from the paper half so nothing appears twice). It is trimmed to `budget_tokens` minus
    the deck; the deck is never trimmed. Receives only what the caller gives it (A4).
    """
    spans = deck_spans(deck)
    text = (
        f"# The client's deck: {deck.title or deck.doc_id} "
        f"({deck.page_count} slides, document id `{deck.doc_id}`)\n\n"
        + render_deck(deck, spans)
    )
    picked: tuple[CachedClaim, ...] = ()
    queries: tuple[str, ...] = ()
    dropped = 0
    if check_papers and index is not None:
        # The deck's own lines are the queries: a figure on a slide is what a paper should
        # confirm, so each line of each slide is searched for (deduplicated, capped).
        lines = [
            " ".join(line.split())[:160]
            for e in sorted(deck.elements, key=lambda e: (e.page, e.reading_order))
            if e.is_citable
            for line in e.text.splitlines()
            if line.strip()
        ]
        themes = "\n".join([*(f"- {t}" for t in lines), project_md])
        paper = build_evidence_pack(
            deck.title or deck.doc_id,
            project_md=themes,
            claims=claims,
            index=index,
            budget_tokens=max(budget_tokens - len(text) // 4, 1_000),
            per_query=per_query,
            max_queries=PAPER_QUERIES,
        )
        paper_spans = tuple(s for s in paper.spans if not s.doc_id.startswith(DOC_ID_PREFIX))
        picked, queries, dropped = paper.claims, paper.queries, paper.dropped
        spans = (*spans, *paper_spans)
        if picked or paper_spans:
            text += (
                "\n\n# Project papers — only to support what the deck already says, never "
                "to add to it\n\n" + render_evidence(picked, paper_spans)
            )
    return EvidencePack(
        claims=picked,
        spans=tuple(spans),
        text=text,
        queries=queries,
        dropped=dropped,
        approx_tokens=len(text) // 4,
    )
