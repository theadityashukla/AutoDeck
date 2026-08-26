"""Hybrid retrieval over the document store — the long-tail path only (D8, §6.5).

Retrieval is a **fallback**, not the primary knowledge route. The curated `claims.md`
library is the main road; this exists for the paper long tail where no curated claim
covers the question.

**Elements are the chunks.** There is no chunker in this module, and that is the whole
design. v1 chunked text into windows that structurally could not carry `(doc_id, page,
bbox)` — which is precisely why it is being replaced (`legacy/v1/LEGACY.md`). Here the
retrievable unit is a `DocumentElement`, which already carries provenance from ingestion,
so a search result cannot exist without a resolvable source span. Provenance is preserved
by construction rather than reattached afterwards, and reattachment is where it gets lost.

**A search hit is not a licence to cite.** `RetrievedSpan.to_citation()` goes back through
`DocumentStore.resolve_quote`, so the store's rules still apply: figures, page furniture
and VLM descriptions are retrievable but raise `UncitableSourceError` when cited. That
matters here more than anywhere, because descriptions are *deliberately* indexed (§6.3
wants them findable) and a hit on one reads exactly like a hit on real prose.

Owning phase: 1 (task 1.8).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from autodeck.ingest.document_store import (
    Document,
    DocumentElement,
    DocumentStore,
    UncitableSourceError,
)
from autodeck.ingest.provenance import normalise_for_match
from autodeck.ir.models import Citation, RetrievedBy

#: Okapi BM25 parameters. The standard defaults; `k1` controls term-frequency saturation
#: and `b` the length normalisation.
BM25_K1 = 1.5
BM25_B = 0.75

#: Reciprocal-rank-fusion constant. Ranks, not raw scores, are fused — BM25 scores and
#: cosine similarities live on incomparable scales, and normalising them requires knowing
#: the score distribution, which varies per query. RRF sidesteps that entirely.
RRF_K = 60

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, normalised the same way quotes are.

    Shares `normalise_for_match` with the citation resolver so that a ligature or curly
    quote cannot make text findable but uncitable, or the reverse.
    """
    return _TOKEN.findall(normalise_for_match(text))


class RetrievalError(RuntimeError):
    """Retrieval could not be performed."""


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievedSpan:
    """One search hit, bound to the element it came from.

    Carries `element_id` rather than loose text, so the citation is always resolved from
    the store rather than reconstructed from whatever the index happened to hold. An index
    can go stale; the store is the authority.
    """

    doc_id: str
    element_id: str
    page: int
    text: str
    """What was indexed — for a figure this includes the VLM description, which is why it
    is not automatically quotable."""
    score: float
    citable: bool
    """Whether this element can back a claim at all. False for figures, page furniture, and
    anything without usable provenance."""

    def to_citation(
        self,
        store: DocumentStore,
        *,
        quote: str | None = None,
        retrieved_by: RetrievedBy = "writer",
    ) -> Citation:
        """Resolve this hit into a verified citation.

        Args:
            store: the document store. The authority on where text is now.
            quote: the exact span to cite. Defaults to the element's full text; pass the
                sentence actually used, since A1 wants the span that backs the claim rather
                than the paragraph containing it.

        Raises:
            UncitableSourceError: this span cannot back a fact — a figure, page furniture,
                or a VLM description. Retrievable is not the same as citable (§6.3).
            QuoteNotFoundError: `quote` is not verbatim in the element.
        """
        if not self.citable:
            raise UncitableSourceError(
                f"retrieved span {self.element_id!r} is not citable. It was indexed so it "
                "could be found — figure descriptions are metadata (§6.3) — but A1 forbids "
                "it backing a claim. Cite the caption or the prose that discusses it."
            )
        element = store.get(self.doc_id).element(self.element_id)
        if element is None:
            raise RetrievalError(
                f"element {self.element_id!r} is in the index but not in the store; the "
                "index is stale and must be rebuilt"
            )
        return store.resolve_quote(
            self.doc_id,
            quote if quote is not None else element.text,
            retrieved_by=retrieved_by,
            element_id=self.element_id,
        )


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------


@dataclass
class BM25Index:
    """Okapi BM25 over document elements.

    Implemented here rather than pulled in as a dependency: it is forty lines of
    well-specified arithmetic, and owning it means the tokenizer can be shared with the
    citation resolver — which is what stops text being findable but uncitable.
    """

    element_ids: list[str] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)
    term_frequencies: list[Counter[str]] = field(default_factory=list)
    lengths: list[int] = field(default_factory=list)
    document_frequency: Counter[str] = field(default_factory=Counter)
    average_length: float = 0.0

    @classmethod
    def build(cls, elements: Sequence[DocumentElement]) -> BM25Index:
        index = cls()
        for element in elements:
            tokens = tokenize(element.retrieval_text())
            index.element_ids.append(element.element_id)
            index.doc_ids.append(element.doc_id)
            index.term_frequencies.append(Counter(tokens))
            index.lengths.append(len(tokens))
            index.document_frequency.update(set(tokens))
        total = sum(index.lengths)
        index.average_length = total / len(index.lengths) if index.lengths else 0.0
        return index

    def scores(self, query: str) -> dict[str, float]:
        """BM25 score per element id. Absent ids scored zero and omitted."""
        terms = tokenize(query)
        if not terms or not self.element_ids:
            return {}

        count = len(self.element_ids)
        scores: dict[str, float] = {}

        for position, element_id in enumerate(self.element_ids):
            frequencies = self.term_frequencies[position]
            length = self.lengths[position]
            total = 0.0
            for term in terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                # Robertson/Sparck-Jones IDF with the +0.5 smoothing that keeps common
                # terms from going negative.
                appearances = self.document_frequency[term]
                idf = math.log(1 + (count - appearances + 0.5) / (appearances + 0.5))
                denominator = frequency + BM25_K1 * (
                    1 - BM25_B + BM25_B * (length / self.average_length or 1.0)
                )
                total += idf * (frequency * (BM25_K1 + 1)) / denominator
            if total > 0:
                scores[element_id] = total
        return scores


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class Embedder(Protocol):
    """Turns text into vectors.

    A protocol rather than a concrete class because D2 forbids local models: a real
    embedder calls a cloud API through the provider layer. Injecting it keeps retrieval
    testable without a network and lets the semantic half be omitted entirely.
    """

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


# ---------------------------------------------------------------------------
# Hybrid index
# ---------------------------------------------------------------------------


@dataclass
class HybridIndex:
    """A searchable index over one project's corpus.

    Carries `client` and `project` so `ContextAssembler.use_index` can refuse a foreign
    one (A4). An index is the leak that touches no files — another client's text arrives
    through search results — so the namespace travels with it rather than being inferred.
    `client=None` means project-tier and shared, which is the normal case: the corpus is
    the project's, not any one client's.
    """

    project: str
    client: str | None = None
    elements: dict[str, DocumentElement] = field(default_factory=dict)
    bm25: BM25Index = field(default_factory=BM25Index)
    vectors: dict[str, list[float]] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.elements)

    @property
    def has_semantic(self) -> bool:
        return bool(self.vectors)


def build_index(
    documents: Sequence[Document],
    *,
    project: str,
    client: str | None = None,
    embedder: Embedder | None = None,
) -> HybridIndex:
    """Index every element that carries retrievable text.

    Elements from a `low_provenance` document are **excluded**. Plan §9 requires flagging
    such documents for human review and making their content unusable for claims; leaving
    them searchable would put uncitable hits in front of the writer and invite exactly the
    workaround the flag exists to prevent.
    """
    usable: list[DocumentElement] = []
    for document in documents:
        if document.low_provenance:
            continue
        usable.extend(
            element for element in document.elements if element.retrieval_text().strip()
        )

    index = HybridIndex(
        project=project,
        client=client,
        elements={element.element_id: element for element in usable},
        bm25=BM25Index.build(usable),
    )

    if embedder is not None and usable:
        texts = [element.retrieval_text() for element in usable]
        vectors = embedder.embed(texts)
        if len(vectors) != len(usable):
            raise RetrievalError(
                f"embedder returned {len(vectors)} vectors for {len(usable)} elements"
            )
        index.vectors = {
            element.element_id: vector for element, vector in zip(usable, vectors, strict=True)
        }

    return index


def search(
    index: HybridIndex,
    query: str,
    *,
    limit: int = 8,
    embedder: Embedder | None = None,
    citable_only: bool = False,
) -> list[RetrievedSpan]:
    """Search the index, fusing lexical and semantic rankings.

    Args:
        citable_only: drop hits that cannot back a claim. Off by default — the writer
            often wants to *read* a figure description even though it can never be cited —
            but a caller assembling evidence should turn it on.

    Fusion is by reciprocal rank, not by score: BM25 scores and cosine similarities are on
    incomparable scales and their distributions shift per query, so any normalisation would
    be a guess. Ranks are comparable by construction.
    """
    lexical = index.bm25.scores(query)
    rankings: list[list[str]] = [_ranked(lexical)]

    if embedder is not None and index.has_semantic:
        query_vector = embedder.embed([query])[0]
        semantic = {
            element_id: cosine(query_vector, vector)
            for element_id, vector in index.vectors.items()
        }
        rankings.append(_ranked(semantic))

    fused = _reciprocal_rank_fusion(rankings)

    spans: list[RetrievedSpan] = []
    for element_id, score in fused:
        element = index.elements.get(element_id)
        if element is None:
            continue
        if citable_only and not element.is_citable:
            continue
        spans.append(
            RetrievedSpan(
                doc_id=element.doc_id,
                element_id=element.element_id,
                page=element.page,
                text=element.retrieval_text(),
                score=score,
                citable=element.is_citable,
            )
        )
        if len(spans) >= limit:
            break
    return spans


def _ranked(scores: dict[str, float]) -> list[str]:
    """Element ids best-first. Ties broken by id so results are deterministic."""
    return [key for key, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


def _reciprocal_rank_fusion(rankings: Sequence[Sequence[str]]) -> list[tuple[str, float]]:
    """Fuse ranked lists: an item's score is the sum of `1 / (k + rank)` across lists."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for position, element_id in enumerate(ranking):
            fused[element_id] = fused.get(element_id, 0.0) + 1.0 / (RRF_K + position + 1)
    return sorted(fused.items(), key=lambda item: (-item[1], item[0]))
