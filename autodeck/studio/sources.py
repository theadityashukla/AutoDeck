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

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from autodeck.studio.engagement import Engagement

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

    def knowledge_files(self) -> list[tuple[str, Path]]:
        """`(source id, path)` for every knowledge file, sorted by id.

        Client files under `KnowledgeLoader(knowledge_root).client_root(client)` and project
        files under `.project_root(project)`, `*.md` found with `rglob`, skipping anything
        whose path relative to the client folder starts with `memory/`. A path for which
        `engagement.guard` raises `ClientIsolationError` is skipped silently (never listed).
        """
        raise NotImplementedError

    def document_ids(self) -> list[str]:
        """Doc ids in `DocumentStore(corpus_root / project)`, sorted; `[]` when the
        directory does not exist or holds none. The store root passes `engagement.guard`."""
        raise NotImplementedError

    def list(self) -> list[SourceInfo]:
        """Every knowledge file (id order), then every document (id order)."""
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError
