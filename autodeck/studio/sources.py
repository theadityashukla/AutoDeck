"""What the lead can read: the engagement's sources, behind its guards (plan §4 "Source").

Phase 1 has two kinds of source:

* **Knowledge files**, always: every `*.md` file under the client's knowledge folder and
  the project's knowledge folder (recursively), except anything under the client's
  `memory/` directory (memory is given to the model separately, as context). Ids are
  `knowledge:client/<path relative to the client folder>` and
  `knowledge:project/<path relative to the project folder>`, with `/` separators.
* **Ingested documents**, only where they exist: the documents in v2's `DocumentStore` at
  `<corpus_root>/<project>` (the same location v2's CLI uses). Ids are `doc:<doc_id>`. The
  project corpus is the project tier, shared by design (D8); a search index over it is
  built in memory with v2's `retrieval.hybrid.build_index` (BM25, no embedder: D2 forbids
  local models and Phase 1 adds no embedding call) and is refused unless it is tagged with
  this engagement's project and no other client, the check v2's `use_index` makes.

No v2 file changes: listing, reading and search are composed from v2's public pieces.

**Isolation (A4).** Every file path passes `engagement.guard` (which resolves symlinks)
before it is listed or read. A knowledge file that resolves into another client's folder is
left out of the listing, and reading it by id raises v2's `ClientIsolationError`. A source
id is parsed, never joined as a path blindly: an id with `..`, an absolute path, a
backslash or an empty segment is unknown (`SourceNotFoundError`), whatever is on disk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from autodeck.ingest.document_store import Document, DocumentStore
from autodeck.knowledge.loader import ClientIsolationError, KnowledgeLoader
from autodeck.retrieval import hybrid
from autodeck.studio.engagement import Engagement
from autodeck.studio.errors import SourceNotFoundError
from autodeck.studio.views import clip, flat

KNOWLEDGE_PREFIX = "knowledge:"
DOC_PREFIX = "doc:"

READ_WINDOW = 12_000
"""Characters of a knowledge file returned by one `read`."""

OUTLINE_HEADINGS = 60
"""A document outline lists at most this many section headings."""

SNIPPET_CHARS = 400
"""A search hit's text is clipped to this many characters (`views.clip`)."""

SourceKind = Literal["knowledge", "document"]


@dataclass(frozen=True)
class SourceInfo:
    """One readable source."""

    id: str
    kind: SourceKind
    title: str
    """Knowledge: the path after the prefix (e.g. `client/client.md`). Document: its
    title, or its doc id when it has none."""
    detail: str
    """Knowledge: `"<n> characters"`. Document: `"<n> pages"` (`page_count`)."""


@dataclass(frozen=True)
class SourceText:
    """What `read` returns: the text for the model and a one-line summary."""

    text: str
    summary: str


@dataclass(frozen=True)
class SearchHit:
    source_id: str
    page: int | None
    """The document page; None for a knowledge file."""
    text: str
    score: float


class SourceLibrary:
    """The sources of one engagement. Construction touches no file; the document index is
    built on the first `search` that needs it and kept for the library's lifetime."""

    def __init__(self, engagement: Engagement, *, corpus_root: Path) -> None:
        self.engagement = engagement
        self.corpus_root = corpus_root
        self._index: hybrid.HybridIndex | None = None

    def knowledge_files(self) -> list[tuple[str, Path]]:
        """`(source id, path)` for every knowledge file, sorted by id.

        Client files under `KnowledgeLoader(knowledge_root).client_root(client)` and project
        files under `.project_root(project)`, `*.md` found with `rglob`, skipping anything
        whose path relative to the client folder starts with `memory/`. A path for which
        `engagement.guard` raises `ClientIsolationError` is skipped silently (never listed).
        """
        loader = KnowledgeLoader(self.engagement.knowledge_root)
        found: list[tuple[str, Path]] = []
        for label, root in (
            ("client", loader.client_root(self.engagement.client)),
            ("project", loader.project_root(self.engagement.project)),
        ):
            if not root.is_dir():
                continue
            for path in root.rglob("*.md"):
                rel = path.relative_to(root)
                if not path.is_file():
                    continue
                if label == "client" and rel.parts[0] == "memory":
                    continue
                try:
                    self.engagement.guard(path)
                except ClientIsolationError:
                    continue
                found.append((f"{KNOWLEDGE_PREFIX}{label}/{rel.as_posix()}", path))
        return sorted(found, key=lambda item: item[0])

    def document_ids(self) -> list[str]:
        """Doc ids in `DocumentStore(corpus_root / project)`, sorted; `[]` when the
        directory does not exist or holds none. The store root passes `engagement.guard`."""
        root = self.corpus_root / self.engagement.project
        self.engagement.guard(root)
        return DocumentStore(root).doc_ids()

    def list(self) -> list[SourceInfo]:
        """Every knowledge file (id order), then every document (id order)."""
        infos: list[SourceInfo] = []
        for source_id, path in self.knowledge_files():
            text = self.engagement.read_knowledge_text(path)
            infos.append(
                SourceInfo(
                    id=source_id,
                    kind="knowledge",
                    title=source_id[len(KNOWLEDGE_PREFIX) :],
                    detail=f"{len(text)} characters",
                )
            )
        store = self._store()
        for doc_id in self.document_ids():
            document = store.get(doc_id)
            infos.append(
                SourceInfo(
                    id=f"{DOC_PREFIX}{doc_id}",
                    kind="document",
                    title=document.title or doc_id,
                    detail=f"{document.page_count} pages",
                )
            )
        return infos

    def read(self, source_id: str, *, page: int | None = None, offset: int = 0) -> SourceText:
        """Read one source.

        Knowledge file (`page` must be None): the characters `[offset, offset +
        READ_WINDOW)` of the file. `text` is the header line
        `<source id> (characters <offset + 1>-<end> of <total>)`, a blank line, then the
        window; when more follows, a final blank line and
        `(more: read again with offset <end>)`. `summary`:
        `read <source id> <offset + 1>-<end> of <total>`. An offset at or past the end
        (of a non-empty file) is an error.

        Document, `page` None: the outline. `text` is `<doc id>: <title> (<n> pages)`, then
        one line `p.<page> <flat text>` per `section_header` or `title` element in reading
        order, at most `OUTLINE_HEADINGS`. `summary`: `outline of <doc id>`.

        Document, `page` given: every element on that page in `reading_order`, one
        paragraph each (`retrieval_text()`), after the header `<doc id> p.<page>`.
        `summary`: `read <doc id> p.<page>: <k> elements`. `offset` is ignored.

        A knowledge id is known only when it is exactly one of the ids `knowledge_files()`
        lists (so `..`, absolute paths and `memory/` files are unknown by construction);
        except that an id whose file exists under the client or project folder but was
        left out of the listing because `engagement.guard` refused it raises
        `ClientIsolationError` rather than `SourceNotFoundError`. A document id is known
        only when it is in `document_ids()`.

        Raises:
            SourceNotFoundError: unknown id or a malformed id (see the module docstring);
                `page` given for a knowledge file; a page with no elements (the message
                gives the range of pages that have text); an offset past the end.
            ClientIsolationError: the file resolves into another client's folder.
        """
        if source_id.startswith(KNOWLEDGE_PREFIX):
            return self._read_knowledge(source_id, page=page, offset=offset)
        if source_id.startswith(DOC_PREFIX):
            return self._read_document(source_id, page=page)
        raise SourceNotFoundError(f"unknown source {source_id!r}")

    def search(self, query: str, *, limit: int = 6) -> list[SearchHit]:
        """Passages matching `query`, from both kinds of source.

        Knowledge files are split into paragraphs (on blank lines; each paragraph
        stripped; empty ones dropped). A paragraph's score is the number of distinct
        tokens of the query (`autodeck.retrieval.hybrid.tokenize`) that occur among its
        tokens; score 0 is not a hit. Best score first; ties keep file id order, then
        paragraph order. A hit's `text` is the paragraph clipped to `SNIPPET_CHARS`
        (`views.clip`); its `page` is None.

        Documents: `retrieval.hybrid.search(index, query, limit=limit)` over the in-memory
        index (see the module docstring); each hit's `text` clipped to `SNIPPET_CHARS`,
        its `page` kept, its score the fused score.

        The result takes up to `ceil(limit / 2)` knowledge hits and up to `limit // 2`
        document hits; if one side has fewer, the other fills the remaining places (still
        at most `limit` in total). Knowledge hits come first, best first, then document
        hits, best first. `[]` when nothing matches.

        Raises:
            ClientIsolationError: the cached index is tagged for another client or project.
        """
        query_tokens = set(hybrid.tokenize(query))
        scored: list[tuple[int, str, str]] = []
        for source_id, path in self.knowledge_files():
            text = self.engagement.read_knowledge_text(path)
            for paragraph in (p.strip() for p in text.split("\n\n")):
                if not paragraph:
                    continue
                score = len(query_tokens & set(hybrid.tokenize(paragraph)))
                if score:
                    scored.append((score, source_id, paragraph))
        scored.sort(key=lambda item: -item[0])  # stable: file id order, paragraph order
        knowledge = [
            SearchHit(
                source_id=source_id,
                page=None,
                text=clip(paragraph, SNIPPET_CHARS),
                score=float(score),
            )
            for score, source_id, paragraph in scored
        ]

        documents: list[SearchHit] = []
        if limit > 0:
            index = self._document_index()
            if index is not None:
                documents = [
                    SearchHit(
                        source_id=f"{DOC_PREFIX}{span.doc_id}",
                        page=span.page,
                        text=clip(span.text, SNIPPET_CHARS),
                        score=span.score,
                    )
                    for span in hybrid.search(index, query, limit=limit)
                ]

        take_k = knowledge[: math.ceil(limit / 2)]
        take_d = documents[: limit // 2]
        spare = limit - len(take_k) - len(take_d)
        if spare > 0:
            take_k = knowledge[: len(take_k) + spare]
            spare = limit - len(take_k) - len(take_d)
            if spare > 0:
                take_d = documents[: len(take_d) + spare]
        return take_k + take_d

    # -- internals ---------------------------------------------------------

    def _store(self) -> DocumentStore:
        root = self.corpus_root / self.engagement.project
        self.engagement.guard(root)
        return DocumentStore(root)

    def _document_index(self) -> hybrid.HybridIndex | None:
        """The in-memory BM25 index over the project corpus, built once; None when the
        corpus has no documents. Checked against this engagement on every use."""
        if self._index is None:
            store = self._store()
            if not store.doc_ids():
                return None
            self._index = hybrid.build_index(
                list(store.documents()), project=self.engagement.project
            )
        index = self._index
        if index.client is not None and index.client != self.engagement.client:
            raise ClientIsolationError(
                f"retrieval index is built for client {index.client!r}, not "
                f"{self.engagement.client!r}"
            )
        if index.project != self.engagement.project:
            raise ClientIsolationError(
                f"retrieval index is for project {index.project!r}, not "
                f"{self.engagement.project!r}"
            )
        return index

    def _knowledge_path(self, source_id: str) -> Path:
        listed = dict(self.knowledge_files())
        if source_id in listed:
            return listed[source_id]
        rest = source_id[len(KNOWLEDGE_PREFIX) :]
        parts = rest.split("/")
        if (
            len(parts) < 2
            or parts[0] not in ("client", "project")
            or "\\" in rest
            or any(part in ("", ".", "..") for part in parts)
        ):
            raise SourceNotFoundError(f"unknown source {source_id!r}")
        loader = KnowledgeLoader(self.engagement.knowledge_root)
        root = (
            loader.client_root(self.engagement.client)
            if parts[0] == "client"
            else loader.project_root(self.engagement.project)
        )
        candidate = root.joinpath(*parts[1:])
        if candidate.is_file():
            # Exists but was not listed: either guard-refused (isolation error) or
            # simply not a source (memory, not markdown).
            self.engagement.guard(candidate)
        raise SourceNotFoundError(f"unknown source {source_id!r}")

    def _read_knowledge(self, source_id: str, *, page: int | None, offset: int) -> SourceText:
        path = self._knowledge_path(source_id)
        if page is not None:
            raise SourceNotFoundError(f"{source_id} is a knowledge file and has no pages")
        text = self.engagement.read_knowledge_text(path)
        total = len(text)
        if offset < 0 or (total > 0 and offset >= total):
            raise SourceNotFoundError(
                f"offset {offset} is outside {source_id} ({total} characters)"
            )
        end = min(offset + READ_WINDOW, total)
        out = f"{source_id} (characters {offset + 1}-{end} of {total})\n\n{text[offset:end]}"
        if end < total:
            out += f"\n\n(more: read again with offset {end})"
        return SourceText(text=out, summary=f"read {source_id} {offset + 1}-{end} of {total}")

    def _read_document(self, source_id: str, *, page: int | None) -> SourceText:
        doc_id = source_id[len(DOC_PREFIX) :]
        if doc_id not in self.document_ids():
            raise SourceNotFoundError(f"unknown source {source_id!r}")
        document: Document = self._store().get(doc_id)
        title = document.title or doc_id
        if page is None:
            headings = sorted(
                (e for e in document.elements if e.kind in ("section_header", "title")),
                key=lambda e: (e.page, e.reading_order),
            )[:OUTLINE_HEADINGS]
            lines = [f"{doc_id}: {title} ({document.page_count} pages)"]
            lines.extend(f"p.{e.page} {flat(e.text)}" for e in headings)
            return SourceText(text="\n".join(lines), summary=f"outline of {doc_id}")
        elements = sorted(
            (e for e in document.elements if e.page == page), key=lambda e: e.reading_order
        )
        if not elements:
            pages = sorted({e.page for e in document.elements})
            have = f"pages with text: {pages[0]}-{pages[-1]}" if pages else "no page has text"
            raise SourceNotFoundError(f"{doc_id} has no elements on page {page} ({have})")
        body = "\n\n".join(e.retrieval_text() for e in elements)
        return SourceText(
            text=f"{doc_id} p.{page}\n\n{body}",
            summary=f"read {doc_id} p.{page}: {len(elements)} elements",
        )
