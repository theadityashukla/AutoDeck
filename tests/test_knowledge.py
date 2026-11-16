"""Knowledge folders, the claim cache, and A4 client isolation.

The isolation tests use a two-client fixture, as the Phase 1 brief requires, and cover the
paths the brief calls out as non-obvious: cached retrieval indices and
`clients/<c>/decks/`, not just the markdown load. Those two matter because neither looks
like a leak — an index leaks with no file access at all, and reference decks feel like
neutral design assets while being full of another client's facts.

A4 is a **build error, never a warning**. The failure mode is a confidentiality breach.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore
from autodeck.knowledge.context_assembler import (
    ContextAssembler,
    RetrievalIndex,
    assemble_context,
)
from autodeck.knowledge.loader import (
    CachedClaim,
    ClientIsolationError,
    KnowledgeError,
    KnowledgeLoader,
    parse_claims_markdown,
)

CLAIMS_MD = """# Claims — attention-efficiency

Curated and pre-verified. Each still gets an independent verdict at validation (A3);
this is a head start, not a bypass.

```yaml
claim: The kernel rewrite raised training throughput by 62.9%.
doc_id: kaplan2024
page: 4
quote: Training throughput rose from 412 to 671 sequences per second.
tags: [throughput, performance]
```

Some prose between blocks, which the parser ignores.

```yaml
claim: Median inference cost fell to $0.42 per million tokens.
doc_id: kaplan2024
page: 2
quote: Median inference cost per million tokens fell to $0.42.
```
"""


def build_knowledge(tmp_path: Path, *, clients: tuple[str, ...] = ("acme", "globex")) -> Path:
    """A knowledge root with one project and two clients."""
    root = tmp_path / "knowledge"

    project = root / "projects" / "attention-efficiency"
    (project / "papers").mkdir(parents=True)
    (project / "project.md").write_text("Efficiency of attention kernels.", encoding="utf-8")
    (project / "claims.md").write_text(CLAIMS_MD, encoding="utf-8")
    (project / "papers" / "kaplan2024.pdf").write_bytes(b"%PDF-1.5 stub")

    for name in clients:
        client = root / "clients" / name
        (client / "decks").mkdir(parents=True)
        (client / "engagements").mkdir(parents=True)
        (client / "style").mkdir(parents=True)
        (client / "theme").mkdir(parents=True)
        (client / "client.md").write_text(f"{name} context and priorities.", encoding="utf-8")
        (client / "value_prop.md").write_text(f"Why {name} wins.", encoding="utf-8")
        (client / "engagements" / "2026-q1.md").write_text(
            f"{name} Q1 notes.", encoding="utf-8"
        )
        (client / "decks" / "past.pptx").write_bytes(b"PK stub")
        (client / "style" / "headers.yaml").write_text("style: assertion\n", encoding="utf-8")
        (client / "theme" / "tokens.json").write_text("{}", encoding="utf-8")

    return root


# ---------------------------------------------------------------------------
# A4 — client isolation
# ---------------------------------------------------------------------------


def test_a_build_assembles_only_its_own_client(tmp_path: Path) -> None:
    context = assemble_context(
        build_knowledge(tmp_path), client="acme", project="attention-efficiency"
    )
    assert context.client == "acme"
    assert "acme context" in context.client_md
    assert "globex" not in context.to_prompt_context()


def test_reading_another_clients_file_raises(tmp_path: Path) -> None:
    """The direct case: a path under another client's directory."""
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    with pytest.raises(ClientIsolationError, match="belongs to client 'globex'"):
        assembler.namespace.read(root / "clients" / "globex" / "client.md")


def test_a_foreign_reference_deck_raises(tmp_path: Path) -> None:
    """`clients/<c>/decks/` — the likeliest leak, because it feels like a design asset."""
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    globex_deck = root / "clients" / "globex" / "decks" / "past.pptx"
    with pytest.raises(ClientIsolationError, match="globex"):
        assembler.namespace.guard(globex_deck)


def test_own_reference_decks_are_allowed(tmp_path: Path) -> None:
    root = build_knowledge(tmp_path)
    decks = ContextAssembler(
        root, client="acme", project="attention-efficiency"
    ).reference_decks()
    assert len(decks) == 1
    assert "acme" in str(decks[0])


def test_a_foreign_theme_asset_raises(tmp_path: Path) -> None:
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    with pytest.raises(ClientIsolationError):
        assembler.namespace.guard(root / "clients" / "globex" / "theme" / "tokens.json")


def test_own_theme_assets_are_allowed(tmp_path: Path) -> None:
    root = build_knowledge(tmp_path)
    assets = ContextAssembler(
        root, client="acme", project="attention-efficiency"
    ).theme_assets()
    assert any(path.name == "tokens.json" for path in assets)


def test_a_cached_index_from_another_client_is_refused(tmp_path: Path) -> None:
    """The leak that touches no files: another client's text arrives via search results."""
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    foreign = RetrievalIndex(client="globex", project="attention-efficiency")
    with pytest.raises(ClientIsolationError, match="without opening a single file"):
        assembler.use_index(foreign)


def test_a_project_tier_index_is_shared(tmp_path: Path) -> None:
    """D8's whole point: one project's evidence serves several clients."""
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    shared = RetrievalIndex(client=None, project="attention-efficiency")
    assert assembler.use_index(shared) is shared


def test_an_index_for_another_project_is_refused(tmp_path: Path) -> None:
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    with pytest.raises(ClientIsolationError, match="project"):
        assembler.use_index(RetrievalIndex(client="acme", project="something-else"))


def test_ones_own_index_is_accepted(tmp_path: Path) -> None:
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    mine = RetrievalIndex(client="acme", project="attention-efficiency")
    assert assembler.use_index(mine) is mine


def test_text_naming_another_client_is_caught(tmp_path: Path) -> None:
    """The backstop: a client name pasted into curated markdown, which no path check sees."""
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    with pytest.raises(ClientIsolationError, match="globex"):
        assembler.check_text("As we showed globex last quarter, throughput doubled.")


def test_ordinary_prose_does_not_trip_the_backstop(tmp_path: Path) -> None:
    """It matches only names of clients that actually exist, so it cannot fire on prose."""
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    assert assembler.check_text("Throughput rose after the rewrite.")


def test_the_project_tier_is_shared_not_isolated(tmp_path: Path) -> None:
    """Only the client tier is isolated; blocking the project tier would break D8."""
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    project_file = root / "projects" / "attention-efficiency" / "project.md"
    assert assembler.namespace.read(project_file)


def test_a_path_outside_the_knowledge_root_is_not_treated_as_a_client(tmp_path: Path) -> None:
    root = build_knowledge(tmp_path)
    assembler = ContextAssembler(root, client="acme", project="attention-efficiency")
    outside = tmp_path / "somewhere-else.md"
    outside.write_text("unrelated", encoding="utf-8")
    assert assembler.namespace.read(outside) == "unrelated"


def test_both_clients_can_be_built_separately(tmp_path: Path) -> None:
    """Isolation is per build, not a global lock — Phase 4 builds two clients in sequence."""
    root = build_knowledge(tmp_path)
    acme = assemble_context(root, client="acme", project="attention-efficiency")
    globex = assemble_context(root, client="globex", project="attention-efficiency")
    assert "globex" not in acme.to_prompt_context()
    assert "acme" not in globex.to_prompt_context()


def test_the_assembler_records_every_file_it_read(tmp_path: Path) -> None:
    """The audit trail for what entered the prompt."""
    context = assemble_context(
        build_knowledge(tmp_path), client="acme", project="attention-efficiency"
    )
    assert any(path.name == "client.md" for path in context.sources)
    assert any(path.name == "2026-q1.md" for path in context.sources)
    assert all("globex" not in str(path) for path in context.sources)


# ---------------------------------------------------------------------------
# Loader validation (task 1.5)
# ---------------------------------------------------------------------------


def test_a_project_loads_with_its_claims_and_papers(tmp_path: Path) -> None:
    project = KnowledgeLoader(build_knowledge(tmp_path)).load_project("attention-efficiency")
    assert len(project.claims) == 2
    assert [p.name for p in project.papers] == ["kaplan2024.pdf"]


def test_a_client_loads_with_its_overlay(tmp_path: Path) -> None:
    client = KnowledgeLoader(build_knowledge(tmp_path)).load_client("acme")
    assert client.header_profile == {"style": "assertion"}
    assert client.tokens_path is not None
    assert len(client.engagements) == 1


def test_a_missing_required_file_names_it(tmp_path: Path) -> None:
    """An absent file would otherwise load as empty context and produce a generic deck."""
    root = build_knowledge(tmp_path)
    (root / "clients" / "acme" / "value_prop.md").unlink()
    with pytest.raises(KnowledgeError, match=r"value_prop\.md"):
        KnowledgeLoader(root).load_client("acme")


def test_every_missing_file_is_reported_at_once(tmp_path: Path) -> None:
    """One per run turns folder setup into a guessing game."""
    root = build_knowledge(tmp_path)
    (root / "clients" / "acme" / "client.md").unlink()
    (root / "clients" / "acme" / "value_prop.md").unlink()
    with pytest.raises(KnowledgeError) as excinfo:
        KnowledgeLoader(root).load_client("acme")
    assert "client.md" in str(excinfo.value)
    assert "value_prop.md" in str(excinfo.value)


def test_an_unknown_client_lists_the_known_ones(tmp_path: Path) -> None:
    with pytest.raises(KnowledgeError, match="Available: acme, globex"):
        KnowledgeLoader(build_knowledge(tmp_path)).load_client("nobody")


@pytest.mark.parametrize("name", ["", "..", "a/b"])
def test_invalid_folder_names_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(KnowledgeError, match="invalid knowledge folder name"):
        KnowledgeLoader(build_knowledge(tmp_path)).load_client(name)


def test_malformed_header_yaml_is_reported(tmp_path: Path) -> None:
    root = build_knowledge(tmp_path)
    (root / "clients" / "acme" / "style" / "headers.yaml").write_text(
        "[unclosed", encoding="utf-8"
    )
    with pytest.raises(KnowledgeError, match="not valid YAML"):
        KnowledgeLoader(root).load_client("acme")


# ---------------------------------------------------------------------------
# Claim cache (task 1.7)
# ---------------------------------------------------------------------------


def test_claims_parse_from_fenced_yaml_blocks() -> None:
    claims = parse_claims_markdown(CLAIMS_MD)
    assert len(claims) == 2
    assert claims[0].tags == ["throughput", "performance"]
    assert claims[1].page == 2


def test_prose_outside_blocks_is_ignored() -> None:
    assert parse_claims_markdown("# Just prose\n\nNo blocks here.") == []


def test_a_malformed_block_is_reported_with_its_position() -> None:
    text = "```yaml\nclaim: missing everything else\n```"
    with pytest.raises(KnowledgeError, match="block 1 is not a valid claim"):
        parse_claims_markdown(text)


def test_a_non_mapping_block_is_reported() -> None:
    with pytest.raises(KnowledgeError, match="must be a mapping"):
        parse_claims_markdown("```yaml\n- just\n- a list\n```")


def test_a_cached_claim_resolves_through_the_store(tmp_path: Path) -> None:
    """The cache records what was true at curation time; the store knows where text is now."""
    store = DocumentStore(tmp_path / "docs")
    store.add(
        Document(
            doc_id="kaplan2024",
            source_path="kaplan2024.pdf",
            page_count=4,
            elements=[
                DocumentElement(
                    element_id="e1",
                    doc_id="kaplan2024",
                    kind="text",
                    page=4,
                    bbox=(72.0, 100.0, 523.0, 130.0),
                    reading_order=0,
                    text="Training throughput rose from 412 to 671 sequences per second.",
                )
            ],
        )
    )
    claim = parse_claims_markdown(CLAIMS_MD)[0]
    citation = claim.to_citation(store=store)
    assert citation.page == 4
    assert store.verify_citation(citation)


def test_a_stale_cached_claim_fails_loudly(tmp_path: Path) -> None:
    """A re-ingest can move a span; the cache must not paper over that."""
    from autodeck.ingest.document_store import QuoteNotFoundError

    store = DocumentStore(tmp_path / "docs")
    store.add(
        Document(
            doc_id="kaplan2024",
            source_path="kaplan2024.pdf",
            page_count=4,
            elements=[
                DocumentElement(
                    element_id="e1",
                    doc_id="kaplan2024",
                    kind="text",
                    page=4,
                    bbox=(72.0, 100.0, 523.0, 130.0),
                    reading_order=0,
                    text="This paragraph no longer contains the cached sentence.",
                )
            ],
        )
    )
    with pytest.raises(QuoteNotFoundError):
        parse_claims_markdown(CLAIMS_MD)[0].to_citation(store=store)


def test_resolving_without_a_store_is_refused() -> None:
    claim = CachedClaim(claim="x", doc_id="d", page=1, quote="q")
    with pytest.raises(KnowledgeError, match="DocumentStore is required"):
        claim.to_citation()
