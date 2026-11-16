"""A read-only store over a redesign run's two sources (Phase 3d, B41, B49).

A redesign cites the client's own deck, which lives in the run-local store
(`runs/<run>/source`), and — only when the person turned the paper check on (B49) — the
project's papers in the corpus store. The A1 resolver, `RetrievedSpan.to_citation`,
`CachedClaim.to_citation`, the validator and `build_index` all take *a* `DocumentStore`, so
`MultiStore` is one: it subclasses it and delegates each document to whichever root holds it.
Nothing else about citation changes — `resolve_quote` is inherited and calls `get`, so there
is still exactly one path from a quote to a `Citation`.

**A4.** It is built per run from exactly the roots it is given, and a run's source root is
`runs/<that run>/source`; another run's deck is on neither root, so it cannot be seen. When
the paper check is off the caller passes no paper root and the corpus is never opened.

**Read-only.** `add` raises: a deck is written by `ingest_deck` into its own store, never
through a view, and nothing may write a document into the project corpus from here.

If both roots hold a document with the same id the run-local deck wins, so a corpus file
can never shadow the client's deck.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from autodeck.ingest.document_store import Document, DocumentStore, IngestError


class MultiStore(DocumentStore):
    def __init__(self, source_root: Path, paper_root: Path | None = None) -> None:
        super().__init__(source_root)
        self._source = DocumentStore(source_root)
        self._papers = DocumentStore(paper_root) if paper_root is not None else None

    @property
    def roots(self) -> tuple[Path, ...]:
        """Exactly the folders this store reads, for the audit trail and the A4 test."""
        return (
            (self._source.root,)
            if self._papers is None
            else (self._source.root, self._papers.root)
        )

    def _stores(self) -> list[DocumentStore]:
        return [self._source] if self._papers is None else [self._source, self._papers]

    def add(self, document: Document) -> Path:
        raise IngestError("a MultiStore is read-only: documents are never written through it")

    def get(self, doc_id: str) -> Document:
        for store in self._stores():
            if doc_id in store.doc_ids():
                return store.get(doc_id)
        raise IngestError(
            f"document {doc_id!r} is in none of this run's sources "
            f"({', '.join(str(r) for r in self.roots)})"
        )

    def doc_ids(self) -> list[str]:
        return sorted({doc_id for store in self._stores() for doc_id in store.doc_ids()})

    def documents(self) -> Iterator[Document]:
        for doc_id in self.doc_ids():
            yield self.get(doc_id)
