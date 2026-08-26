"""Hybrid retrieval, and the rule that a search hit is not a licence to cite.

The load-bearing test is `test_a_retrieved_figure_description_cannot_be_cited`. The Phase 1
brief requires that a provenance-less chunk be *unusable* for a citation — asserted, not
merely documented — and descriptions are the sharp case: §6.3 wants them findable, so they
are deliberately indexed, and a hit on one reads exactly like a hit on real prose.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from autodeck.ingest.document_store import (
    Document,
    DocumentElement,
    DocumentStore,
    UncitableSourceError,
)
from autodeck.knowledge.context_assembler import ClientIsolationError, ContextAssembler
from autodeck.retrieval.hybrid import (
    BM25Index,
    HybridIndex,
    RetrievalError,
    RetrievedSpan,
    build_index,
    cosine,
    search,
    tokenize,
)
from tests.test_knowledge import build_knowledge

THROUGHPUT = "Training throughput rose from 412 to 671 sequences per second."
COST = "Median inference cost per million tokens fell to $0.42 in the Q3 window."
METHOD = "All figures are measured on a single A100-80GB node."


def element(
    element_id: str,
    text: str,
    *,
    kind: str = "text",
    page: int = 1,
    description: str | None = None,
    bbox: tuple[float, float, float, float] = (72.0, 100.0, 523.0, 130.0),
    order: int = 0,
) -> DocumentElement:
    return DocumentElement(
        element_id=element_id,
        doc_id="paper-1",
        kind=kind,  # type: ignore[arg-type]
        page=page,
        bbox=bbox,
        reading_order=order,
        text=text,
        description=description,
    )


def corpus(*elements: DocumentElement, low_provenance: bool = False) -> Document:
    return Document(
        doc_id="paper-1",
        source_path="paper-1.pdf",
        page_count=4,
        elements=list(elements),
        low_provenance=low_provenance,
    )


def standard_document() -> Document:
    return corpus(
        element("e1", THROUGHPUT, order=0),
        element("e2", COST, page=2, order=1),
        element("e3", METHOD, page=4, order=2),
        element(
            "fig1",
            "",
            kind="figure",
            page=2,
            order=3,
            description="A bar chart showing throughput rising from 412 to 671.",
        ),
    )


def standard_index() -> HybridIndex:
    return build_index([standard_document()], project="attention-efficiency")


def stored(tmp_path: Path) -> DocumentStore:
    store = DocumentStore(tmp_path)
    store.add(standard_document())
    return store


# ---------------------------------------------------------------------------
# A1 — a hit is not a licence to cite
# ---------------------------------------------------------------------------


def test_a_retrieved_span_resolves_to_a_verified_citation(tmp_path: Path) -> None:
    store = stored(tmp_path)
    hit = search(standard_index(), "throughput sequences per second")[0]
    citation = hit.to_citation(store, quote="rose from 412 to 671")
    assert citation.page == 1
    assert store.verify_citation(citation)


def test_a_retrieved_figure_description_cannot_be_cited(tmp_path: Path) -> None:
    """The rule the brief requires be asserted rather than documented.

    The description is indexed on purpose — it must be findable — but it can never back a
    claim, and the refusal happens at the point of citing, not by hoping nobody tries.
    """
    store = stored(tmp_path)
    hits = search(standard_index(), "bar chart showing throughput rising")
    figure = next(hit for hit in hits if hit.element_id == "fig1")

    assert not figure.citable
    assert "bar chart" in figure.text  # retrievable...
    with pytest.raises(UncitableSourceError, match="A1 forbids"):
        figure.to_citation(store)  # ...but never citable


def test_a_description_is_findable(tmp_path: Path) -> None:
    """§6.3: descriptions exist to be retrieved. Only citing them is forbidden."""
    hits = search(standard_index(), "bar chart")
    assert any(hit.element_id == "fig1" for hit in hits)


def test_citable_only_filters_out_uncitable_hits() -> None:
    """What a caller assembling evidence should use."""
    hits = search(standard_index(), "throughput rising 412 671", citable_only=True)
    assert hits
    assert all(hit.citable for hit in hits)
    assert all(hit.element_id != "fig1" for hit in hits)


def test_a_low_provenance_document_is_not_indexed() -> None:
    """Plan §9: its content must be unusable for claims, so it is not searchable either.

    Leaving it searchable would put uncitable hits in front of the writer and invite the
    workaround the flag exists to prevent.
    """
    document = corpus(element("e1", THROUGHPUT), low_provenance=True)
    index = build_index([document], project="p")
    assert index.size == 0
    assert search(index, "throughput") == []


def test_an_element_without_provenance_is_retrievable_but_not_citable(tmp_path: Path) -> None:
    document = corpus(element("e1", THROUGHPUT, bbox=(0.0, 0.0, 0.0, 0.0)))
    store = DocumentStore(tmp_path)
    store.add(document)
    hit = search(build_index([document], project="p"), "throughput")[0]
    assert not hit.citable
    with pytest.raises(UncitableSourceError):
        hit.to_citation(store)


def test_a_stale_index_entry_fails_loudly(tmp_path: Path) -> None:
    """The index can go stale; the store is the authority."""
    store = DocumentStore(tmp_path)
    store.add(corpus(element("e1", THROUGHPUT)))
    ghost = RetrievedSpan(
        doc_id="paper-1", element_id="gone", page=1, text="x", score=1.0, citable=True
    )
    with pytest.raises(RetrievalError, match="stale"):
        ghost.to_citation(store)


def test_citing_a_paraphrase_from_a_hit_still_fails(tmp_path: Path) -> None:
    """Retrieval does not relax A1's verbatim requirement."""
    from autodeck.ingest.document_store import QuoteNotFoundError

    store = stored(tmp_path)
    hit = search(standard_index(), "throughput")[0]
    with pytest.raises(QuoteNotFoundError):
        hit.to_citation(store, quote="throughput went up a lot")


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_the_most_relevant_element_ranks_first() -> None:
    assert search(standard_index(), "inference cost per million tokens")[0].element_id == "e2"


def test_an_unrelated_query_returns_nothing() -> None:
    assert search(standard_index(), "photosynthesis chlorophyll") == []


def test_the_limit_is_respected() -> None:
    assert len(search(standard_index(), "throughput cost node figures", limit=2)) == 2


def test_results_are_deterministic() -> None:
    index = standard_index()
    first = [hit.element_id for hit in search(index, "throughput")]
    second = [hit.element_id for hit in search(index, "throughput")]
    assert first == second


def test_bm25_scores_only_matching_elements() -> None:
    index = BM25Index.build([element("e1", THROUGHPUT), element("e2", COST, order=1)])
    scores = index.scores("throughput")
    assert "e1" in scores
    assert "e2" not in scores


def test_bm25_handles_an_empty_index() -> None:
    assert BM25Index.build([]).scores("anything") == {}


def test_an_empty_query_matches_nothing() -> None:
    assert search(standard_index(), "   ") == []


def test_tokenize_shares_the_citation_normalisation() -> None:
    """Otherwise text could be findable but uncitable, or the reverse."""
    assert tokenize("The workﬂow was signiﬁcantly faster") == [
        "the",
        "workflow",
        "was",
        "significantly",
        "faster",
    ]


# ---------------------------------------------------------------------------
# Semantic half
# ---------------------------------------------------------------------------


class FakeEmbedder:
    """Maps text to a bag-of-words vector over a fixed vocabulary.

    Enough to prove fusion works without a network. D2 forbids local models, so the real
    embedder is a cloud call injected the same way.
    """

    vocabulary = ("throughput", "cost", "node", "chart")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(term in text.lower()) for term in self.vocabulary] for text in texts]


def test_semantic_search_contributes_when_an_embedder_is_supplied() -> None:
    embedder = FakeEmbedder()
    index = build_index([standard_document()], project="p", embedder=embedder)
    assert index.has_semantic
    hits = search(index, "cost", embedder=embedder)
    assert hits[0].element_id == "e2"


def test_retrieval_works_without_an_embedder() -> None:
    """The semantic half is optional; BM25 alone is a documented mode, not a silent one."""
    index = standard_index()
    assert not index.has_semantic
    assert search(index, "throughput")


def test_a_mismatched_embedder_response_is_rejected() -> None:
    class Broken:
        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0]]

    with pytest.raises(RetrievalError, match="vectors for"):
        build_index([standard_document()], project="p", embedder=Broken())


def test_cosine_handles_zero_vectors() -> None:
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# A4 — the index carries its namespace
# ---------------------------------------------------------------------------


def test_a_real_index_is_accepted_by_the_isolation_guard(tmp_path: Path) -> None:
    """The guard is structural, so the real HybridIndex is covered without an import."""
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    index = build_index([standard_document()], project="attention-efficiency")
    assert assembler.use_index(index) is index


def test_a_real_index_built_for_another_client_is_refused(tmp_path: Path) -> None:
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    foreign = build_index(
        [standard_document()], project="attention-efficiency", client="globex"
    )
    with pytest.raises(ClientIsolationError, match="globex"):
        assembler.use_index(foreign)


def test_a_project_tier_index_defaults_to_shared() -> None:
    """The corpus belongs to the project, not to any one client (D8)."""
    assert build_index([standard_document()], project="p").client is None
