"""What the lead can read: knowledge files always, ingested documents where they exist,
everything through the engagement's guard."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore
from autodeck.knowledge.loader import ClientIsolationError
from autodeck.studio.engagement import Engagement, create_engagement
from autodeck.studio.errors import SourceNotFoundError
from autodeck.studio.sources import READ_WINDOW, SourceLibrary
from tests.studio.helpers import CLIENT, OTHER_CLIENT, PROJECT, T0


def _engagement(knowledge_root: Path, workspace_root: Path) -> Engagement:
    client = knowledge_root / "clients" / CLIENT
    (client / "engagements").mkdir()
    (client / "engagements" / "kickoff.md").write_text(
        "# Kickoff\n\nThe pilot ran for six weeks.\n\nServing cost was the main worry.\n",
        encoding="utf-8",
    )
    (client / "memory").mkdir()
    (client / "memory" / f"{PROJECT}.md").write_text("# Memory\n", encoding="utf-8")
    return create_engagement(
        CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )


def _element(doc: str, n: int, page: int, kind: str, text: str) -> DocumentElement:
    return DocumentElement(
        element_id=f"{doc}-{n}",
        doc_id=doc,
        kind=kind,  # type: ignore[arg-type]
        page=page,
        bbox=(10.0, 10.0 + n, 100.0, 20.0 + n),
        reading_order=n,
        text=text,
    )


def _corpus(corpus_root: Path) -> None:
    store = DocumentStore(corpus_root / PROJECT)
    store.add(
        Document(
            doc_id="kwon-2023",
            source_path="papers/kwon.pdf",
            title="PagedAttention",
            page_count=2,
            elements=[
                _element("kwon-2023", 0, 1, "title", "Efficient memory management for serving"),
                _element(
                    "kwon-2023", 1, 1, "text", "KV cache memory is wasted by fragmentation."
                ),
                _element("kwon-2023", 2, 2, "section_header", "Evaluation"),
                _element("kwon-2023", 3, 2, "text", "Throughput improves two to four times."),
            ],
        )
    )


def test_lists_knowledge_files_but_not_memory(
    knowledge_root: Path, workspace_root: Path
) -> None:
    library = SourceLibrary(
        _engagement(knowledge_root, workspace_root), corpus_root=Path("/nonexistent")
    )
    ids = [s.id for s in library.list()]
    assert ids == [
        "knowledge:client/client.md",
        "knowledge:client/engagements/kickoff.md",
        "knowledge:client/value_prop.md",
        "knowledge:project/claims.md",
        "knowledge:project/project.md",
    ]
    first = library.list()[0]
    size = len(f"# {CLIENT}\n")
    assert (first.kind, first.title, first.detail) == (
        "knowledge",
        "client/client.md",
        f"{size} characters",
    )
    assert library.document_ids() == []


def test_reads_a_knowledge_file_in_windows(knowledge_root: Path, workspace_root: Path) -> None:
    engagement = _engagement(knowledge_root, workspace_root)
    big = knowledge_root / "projects" / PROJECT / "notes.md"
    big.write_text("x" * (READ_WINDOW + 5), encoding="utf-8")
    library = SourceLibrary(engagement, corpus_root=Path("/nonexistent"))
    first = library.read("knowledge:project/notes.md")
    total = READ_WINDOW + 5
    assert first.text.startswith(
        f"knowledge:project/notes.md (characters 1-{READ_WINDOW} of {total})\n\n"
    )
    assert first.text.endswith(f"(more: read again with offset {READ_WINDOW})")
    assert first.summary == f"read knowledge:project/notes.md 1-{READ_WINDOW} of {total}"
    rest = library.read("knowledge:project/notes.md", offset=READ_WINDOW)
    assert rest.text.endswith("xxxxx") and "(more:" not in rest.text
    with pytest.raises(SourceNotFoundError):
        library.read("knowledge:project/notes.md", offset=total)
    with pytest.raises(SourceNotFoundError):
        library.read("knowledge:project/notes.md", page=2)


@pytest.mark.parametrize(
    "bad",
    [
        "knowledge:client/../../contoso-health/client.md",
        f"knowledge:client/../{OTHER_CLIENT}/client.md",
        "knowledge:/etc/passwd",
        "knowledge:client//client.md",
        "knowledge:client\\client.md",
        "knowledge:elsewhere/client.md",
        "knowledge:client/memory/llm-inference-efficiency.md",
        "doc:../x",
        "doc:missing",
        "file:client.md",
    ],
)
def test_malformed_or_foreign_ids_are_unknown(
    knowledge_root: Path, workspace_root: Path, bad: str
) -> None:
    library = SourceLibrary(
        _engagement(knowledge_root, workspace_root), corpus_root=Path("/nonexistent")
    )
    with pytest.raises(SourceNotFoundError):
        library.read(bad)


def test_a_symlink_into_another_client_is_never_listed_or_read(
    knowledge_root: Path, workspace_root: Path
) -> None:
    engagement = _engagement(knowledge_root, workspace_root)
    secret = knowledge_root / "clients" / OTHER_CLIENT / "client.md"
    os.symlink(secret, knowledge_root / "clients" / CLIENT / "borrowed.md")
    library = SourceLibrary(engagement, corpus_root=Path("/nonexistent"))
    assert "knowledge:client/borrowed.md" not in [s.id for s in library.list()]
    with pytest.raises(ClientIsolationError):
        library.read("knowledge:client/borrowed.md")
    assert all("borrowed" not in hit.source_id for hit in library.search(OTHER_CLIENT))


def test_documents_are_listed_and_read_by_outline_and_page(
    knowledge_root: Path, workspace_root: Path, tmp_path: Path
) -> None:
    _corpus(tmp_path / "corpus")
    library = SourceLibrary(
        _engagement(knowledge_root, workspace_root), corpus_root=tmp_path / "corpus"
    )
    sources = library.list()
    assert sources[-1].id == "doc:kwon-2023" and sources[-1].detail == "2 pages"
    assert sources[-1].title == "PagedAttention"
    outline = library.read("doc:kwon-2023")
    assert outline.text.splitlines() == [
        "kwon-2023: PagedAttention (2 pages)",
        "p.1 Efficient memory management for serving",
        "p.2 Evaluation",
    ]
    assert outline.summary == "outline of kwon-2023"
    page = library.read("doc:kwon-2023", page=2)
    assert page.text.startswith("kwon-2023 p.2")
    assert "Throughput improves two to four times." in page.text
    assert page.summary == "read kwon-2023 p.2: 2 elements"
    with pytest.raises(SourceNotFoundError, match="1"):
        library.read("doc:kwon-2023", page=7)


def test_search_takes_from_both_kinds(
    knowledge_root: Path, workspace_root: Path, tmp_path: Path
) -> None:
    _corpus(tmp_path / "corpus")
    library = SourceLibrary(
        _engagement(knowledge_root, workspace_root), corpus_root=tmp_path / "corpus"
    )
    hits = library.search("serving cost memory", limit=4)
    knowledge = [h for h in hits if h.source_id.startswith("knowledge:")]
    documents = [h for h in hits if h.source_id.startswith("doc:")]
    assert knowledge and documents and len(hits) <= 4
    assert hits.index(knowledge[-1]) < hits.index(documents[0])
    assert knowledge[0].source_id == "knowledge:client/engagements/kickoff.md"
    assert knowledge[0].text == "Serving cost was the main worry." and knowledge[0].page is None
    assert documents[0].page in (1, 2)
    assert library.search("zebra") == []


def test_search_fills_from_one_side_when_the_other_is_short(
    knowledge_root: Path, workspace_root: Path
) -> None:
    library = SourceLibrary(
        _engagement(knowledge_root, workspace_root), corpus_root=Path("/nonexistent")
    )
    hits = library.search("pilot weeks serving cost worry", limit=2)
    assert len(hits) == 2 and all(h.source_id.startswith("knowledge:") for h in hits)
