"""The `autodeck knowledge` commands, and the seed corpus they operate on.

Two different things are tested here and it is worth being clear which is which:

- **The commands**, against throwaway fixtures. Ordinary unit tests.
- **The committed seed corpus**, against the real `knowledge/` directory. Task 1.9's exit
  criterion is "folders validate", and a fixture validating proves nothing about the folders
  actually in the repo. These tests are what stop the seed rotting — a required file deleted
  in a later phase, a `claims.md` block edited into invalid YAML, a paper removed without
  its claims — and they fail on the change rather than months later when someone runs a
  build.

`ingest` is deliberately not exercised end to end: it needs Docling's model weights, which
CI will never have (that split is why `document_from_docling` is pure). What is tested here
is everything around the conversion call.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from autodeck.cli import app
from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore
from tests.test_knowledge import build_knowledge

runner = CliRunner()

#: The real thing, not a fixture.
SEED_ROOT = Path(__file__).resolve().parent.parent / "knowledge"
SEED_PROJECT = "llm-inference-efficiency"


# ---------------------------------------------------------------------------
# The committed seed corpus (task 1.9)
# ---------------------------------------------------------------------------


def test_the_seed_corpus_validates() -> None:
    """Task 1.9's exit criterion, asserted against the folders in the repository."""
    result = runner.invoke(app, ["knowledge", "validate", "--knowledge-root", str(SEED_ROOT)])
    assert result.exit_code == 0, result.output
    assert SEED_PROJECT in result.output


def test_the_seed_project_has_papers_and_claims() -> None:
    """A seed with no evidence in it would validate and still be useless."""
    from autodeck.knowledge.loader import KnowledgeLoader

    project = KnowledgeLoader(SEED_ROOT).load_project(SEED_PROJECT)
    assert project.papers, "the seed project must ship its PDFs — see papers/SOURCES.md"
    assert project.claims, "the seed project must ship curated claims (task 1.7)"


def test_every_seed_claim_points_at_a_paper_that_exists() -> None:
    """The failure this catches: a paper renamed or dropped, its claims left behind.

    `doc_id` is the PDF's filename stem, so a claim naming a `doc_id` with no matching file
    is a citation that can never resolve — and it would only surface at build time, inside
    a stack trace, long after the rename that caused it.
    """
    from autodeck.knowledge.loader import KnowledgeLoader

    project = KnowledgeLoader(SEED_ROOT).load_project(SEED_PROJECT)
    available = {pdf.stem for pdf in project.papers}
    orphans = sorted({claim.doc_id for claim in project.claims} - available)
    assert not orphans, (
        f"claims reference missing papers: {orphans}. Available: {sorted(available)}"
    )


def test_the_seed_clients_are_isolated_from_each_other() -> None:
    """A4 against the real folders, which is why a second seed client exists at all."""
    from autodeck.knowledge.context_assembler import ContextAssembler
    from autodeck.knowledge.loader import ClientIsolationError, KnowledgeLoader

    clients = KnowledgeLoader(SEED_ROOT).client_names()
    assert len(clients) >= 2, "A4 needs two real client folders to be demonstrable"

    first, second = clients[0], clients[1]
    assembler = ContextAssembler(SEED_ROOT, client=first, project=SEED_PROJECT)
    with pytest.raises(ClientIsolationError):
        assembler.namespace.read(SEED_ROOT / "clients" / second / "client.md")


def test_a_seed_client_assembles_without_naming_the_other() -> None:
    """`check_text` is a backstop for a name pasted into curated markdown."""
    from autodeck.knowledge.context_assembler import ContextAssembler
    from autodeck.knowledge.loader import KnowledgeLoader

    for client in KnowledgeLoader(SEED_ROOT).client_names():
        assembler = ContextAssembler(SEED_ROOT, client=client, project=SEED_PROJECT)
        context = assembler.assemble()
        assembler.check_text(context.to_prompt_context(), label=f"{client} context")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_reports_a_missing_required_file(tmp_path: Path) -> None:
    root = build_knowledge(tmp_path)
    (root / "clients" / "acme" / "value_prop.md").unlink()

    result = runner.invoke(app, ["knowledge", "validate", "--knowledge-root", str(root)])
    assert result.exit_code == 1
    assert "value_prop.md" in result.output


def test_validate_on_an_empty_root_is_an_error(tmp_path: Path) -> None:
    """Silence would read as success, and an empty knowledge root never is."""
    result = runner.invoke(app, ["knowledge", "validate", "--knowledge-root", str(tmp_path)])
    assert result.exit_code == 2
    assert "no knowledge folders" in result.output


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


def test_ingest_rejects_an_unknown_project(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["knowledge", "ingest", "nope", "--knowledge-root", str(build_knowledge(tmp_path))],
    )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_ingest_reports_a_project_with_no_pdfs(tmp_path: Path) -> None:
    root = build_knowledge(tmp_path)
    (root / "projects" / "attention-efficiency" / "papers" / "kaplan2024.pdf").unlink()

    result = runner.invoke(
        app,
        [
            "knowledge",
            "ingest",
            "attention-efficiency",
            "--knowledge-root",
            str(root),
            "--corpus-root",
            str(tmp_path / "corpus"),
        ],
    )
    assert result.exit_code == 2
    assert "no PDFs" in result.output


def test_ingest_skips_papers_already_in_the_store(tmp_path: Path) -> None:
    """Resumability: a run interrupted three papers in must not start over.

    Asserted by the absence of a Docling call — the store is pre-populated, so reaching the
    converter at all would need model weights and would fail loudly.
    """
    root = build_knowledge(tmp_path)
    corpus = tmp_path / "corpus"
    store = DocumentStore(corpus / "attention-efficiency")
    store.add(
        Document(doc_id="kaplan2024", source_path="kaplan2024.pdf", page_count=1, elements=[])
    )

    result = runner.invoke(
        app,
        [
            "knowledge",
            "ingest",
            "attention-efficiency",
            "--knowledge-root",
            str(root),
            "--corpus-root",
            str(corpus),
        ],
    )
    assert result.exit_code == 0
    assert "skipped" in result.output


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------


def element(element_id: str, text: str, *, kind: str = "text") -> DocumentElement:
    return DocumentElement(
        element_id=element_id,
        doc_id="paper-1",
        kind=kind,  # type: ignore[arg-type]
        page=2,
        bbox=(72.0, 100.0, 523.0, 130.0),
        reading_order=0,
        text=text,
    )


def ingested(tmp_path: Path, *elements: DocumentElement) -> Path:
    corpus = tmp_path / "corpus"
    DocumentStore(corpus / "attention-efficiency").add(
        Document(
            doc_id="paper-1",
            source_path="paper-1.pdf",
            page_count=4,
            elements=list(elements),
        )
    )
    return corpus


def test_ask_prints_a_verified_citation(tmp_path: Path) -> None:
    """The Phase 1 milestone as a command: a question in, a hash-verified citation out."""
    corpus = ingested(tmp_path, element("e1", "Throughput rose to 671 sequences per second."))
    result = runner.invoke(
        app,
        [
            "knowledge",
            "ask",
            "attention-efficiency",
            "throughput sequences per second",
            "--corpus-root",
            str(corpus),
        ],
    )
    assert result.exit_code == 0
    assert "VERIFIED" in result.output
    assert "p.2" in result.output


def test_ask_marks_an_uncitable_hit_rather_than_hiding_it(tmp_path: Path) -> None:
    """A searcher needs to know the difference; silently dropping it teaches nothing."""
    figure = element("fig1", "", kind="figure")
    figure.description = "[VLM figure description] Bar chart of throughput by batch size."
    corpus = ingested(tmp_path, figure)

    result = runner.invoke(
        app,
        [
            "knowledge",
            "ask",
            "attention-efficiency",
            "bar chart throughput batch size",
            "--corpus-root",
            str(corpus),
        ],
    )
    assert result.exit_code == 0
    assert "NOT CITABLE" in result.output
    assert "VERIFIED" not in result.output


def test_ask_without_an_ingested_corpus_says_what_to_run(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "knowledge",
            "ask",
            "attention-efficiency",
            "anything",
            "--corpus-root",
            str(tmp_path / "corpus"),
        ],
    )
    assert result.exit_code == 2
    assert "knowledge ingest" in result.output


def test_ask_refuses_a_client_that_does_not_own_the_project(tmp_path: Path) -> None:
    """A4 reaches the CLI too — `--client` binds the search to one namespace."""
    corpus = ingested(tmp_path, element("e1", "Throughput rose to 671 sequences per second."))
    result = runner.invoke(
        app,
        [
            "knowledge",
            "ask",
            "attention-efficiency",
            "throughput",
            "--client",
            "nonexistent-client",
            "--knowledge-root",
            str(build_knowledge(tmp_path)),
            "--corpus-root",
            str(corpus),
        ],
    )
    assert result.exit_code == 1
    assert "not found" in result.output
