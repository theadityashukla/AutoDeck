"""Workspace agent tests: knowledge inventory, provider keys.

Tests for autodeck/ui/workspace.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodeck.ingest.document_store import Document
from autodeck.ui.api import Roots
from autodeck.ui.workspace import keys_view, knowledge_view


@pytest.fixture
def roots(tmp_path: Path) -> Roots:
    """Roots with empty knowledge and corpus folders."""
    (tmp_path / "knowledge" / "projects").mkdir(parents=True)
    (tmp_path / "knowledge" / "clients").mkdir(parents=True)
    (tmp_path / "corpus").mkdir(parents=True)
    return Roots(
        knowledge=tmp_path / "knowledge",
        corpus=tmp_path / "corpus",
        runs=tmp_path / "runs",
        env="dev",
    )


# ---------------------------------------------------------------------------
# knowledge_view: projects and papers
# ---------------------------------------------------------------------------


def test_knowledge_view_returns_empty_lists_when_no_projects(roots: Roots) -> None:
    result = knowledge_view(roots)
    assert result == {"projects": [], "clients": []}


def test_knowledge_view_lists_projects(roots: Roots) -> None:
    # Create a minimal project
    proj_dir = roots.knowledge / "projects" / "test-proj"
    proj_dir.mkdir(parents=True)
    (proj_dir / "project.md").write_text("# Test Project\n\nA test.", encoding="utf-8")
    (proj_dir / "claims.md").write_text("# Claims\n\nEmpty.", encoding="utf-8")

    result = knowledge_view(roots)
    assert len(result["projects"]) == 1
    assert result["projects"][0]["name"] == "test-proj"
    assert result["projects"][0]["papers"] == []
    assert result["projects"][0]["curated_claims"] == 0  # No YAML blocks


def test_knowledge_view_lists_papers(roots: Roots) -> None:
    # Create a project with papers
    proj_dir = roots.knowledge / "projects" / "test-proj"
    papers_dir = proj_dir / "papers"
    papers_dir.mkdir(parents=True)
    (proj_dir / "project.md").write_text("# Project", encoding="utf-8")
    (proj_dir / "claims.md").write_text("# Claims", encoding="utf-8")
    (papers_dir / "paper1.pdf").write_bytes(b"fake pdf")
    (papers_dir / "paper2.pdf").write_bytes(b"fake pdf")

    result = knowledge_view(roots)
    papers = result["projects"][0]["papers"]
    assert len(papers) == 2
    assert papers[0]["file"] == "paper1.pdf"
    assert papers[0]["doc_id"] == "paper1"
    assert papers[1]["file"] == "paper2.pdf"


def test_knowledge_view_marks_papers_not_ingested_by_default(roots: Roots) -> None:
    # Create a project with papers but no ingested documents
    proj_dir = roots.knowledge / "projects" / "test-proj"
    papers_dir = proj_dir / "papers"
    papers_dir.mkdir(parents=True)
    (proj_dir / "project.md").write_text("# Project", encoding="utf-8")
    (proj_dir / "claims.md").write_text("# Claims", encoding="utf-8")
    (papers_dir / "paper1.pdf").write_bytes(b"fake pdf")

    result = knowledge_view(roots)
    papers = result["projects"][0]["papers"]
    assert papers[0]["ingested"] is False
    assert papers[0]["pages"] is None


def test_knowledge_view_marks_papers_as_ingested(roots: Roots) -> None:
    # Create a project with papers and an ingested document
    proj_dir = roots.knowledge / "projects" / "test-proj"
    papers_dir = proj_dir / "papers"
    papers_dir.mkdir(parents=True)
    (proj_dir / "project.md").write_text("# Project", encoding="utf-8")
    (proj_dir / "claims.md").write_text("# Claims", encoding="utf-8")
    (papers_dir / "paper1.pdf").write_bytes(b"fake pdf")

    # Add the document to the store
    doc = Document(
        doc_id="paper1",
        source_path="paper1.pdf",
        page_count=28,
        elements=[],
    )
    store_dir = roots.corpus / "test-proj"
    store_dir.mkdir(parents=True)
    store_path = store_dir / "paper1.json"
    store_path.write_text(json.dumps(doc.model_dump(mode="json"), indent=2), encoding="utf-8")

    result = knowledge_view(roots)
    papers = result["projects"][0]["papers"]
    assert papers[0]["ingested"] is True
    assert papers[0]["pages"] == 28


def test_knowledge_view_counts_curated_claims(roots: Roots) -> None:
    # Create a project with some claims
    proj_dir = roots.knowledge / "projects" / "test-proj"
    proj_dir.mkdir(parents=True)
    (proj_dir / "project.md").write_text("# Project", encoding="utf-8")
    claims_text = """
# Claims

```yaml
claim: "Test claim"
doc_id: "test"
page: 1
quote: "quote"
```

```yaml
claim: "Another claim"
doc_id: "test"
page: 2
quote: "quote2"
```
"""
    (proj_dir / "claims.md").write_text(claims_text, encoding="utf-8")

    result = knowledge_view(roots)
    assert result["projects"][0]["curated_claims"] == 2


# ---------------------------------------------------------------------------
# knowledge_view: clients
# ---------------------------------------------------------------------------


def test_knowledge_view_lists_clients(roots: Roots) -> None:
    # Create a minimal client
    client_dir = roots.knowledge / "clients" / "test-client"
    client_dir.mkdir(parents=True)
    (client_dir / "client.md").write_text("# Test Client\n\nA test.", encoding="utf-8")
    (client_dir / "value_prop.md").write_text("# Positioning\n\nPlain.", encoding="utf-8")

    result = knowledge_view(roots)
    assert len(result["clients"]) == 1
    assert result["clients"][0]["name"] == "test-client"


def test_knowledge_view_extracts_client_summary(roots: Roots) -> None:
    client_dir = roots.knowledge / "clients" / "test-client"
    client_dir.mkdir(parents=True)
    (client_dir / "client.md").write_text(
        "# Test Client\n\nA regional health system.", encoding="utf-8"
    )
    (client_dir / "value_prop.md").write_text("# Positioning\n\nBrief.", encoding="utf-8")

    result = knowledge_view(roots)
    assert result["clients"][0]["summary"] == "A regional health system."


def test_knowledge_view_extracts_positioning(roots: Roots) -> None:
    client_dir = roots.knowledge / "clients" / "test-client"
    client_dir.mkdir(parents=True)
    (client_dir / "client.md").write_text("# Test\n\nWho.", encoding="utf-8")
    (client_dir / "value_prop.md").write_text(
        "# Positioning\n\nPlain evidence summary.", encoding="utf-8"
    )

    result = knowledge_view(roots)
    assert result["clients"][0]["positioning"] == "Plain evidence summary."


def test_knowledge_view_truncates_long_summaries(roots: Roots) -> None:
    client_dir = roots.knowledge / "clients" / "test-client"
    client_dir.mkdir(parents=True)
    # Create text longer than 280 chars
    long_text = "A " * 150  # Creates 300 characters
    (client_dir / "client.md").write_text(f"# Test\n\n{long_text}", encoding="utf-8")
    (client_dir / "value_prop.md").write_text("# Pos\n\nX.", encoding="utf-8")

    result = knowledge_view(roots)
    summary = result["clients"][0]["summary"]
    assert len(summary) <= 283  # 280 + "..."
    assert summary.endswith("...")


def test_knowledge_view_counts_past_decks(roots: Roots) -> None:
    client_dir = roots.knowledge / "clients" / "test-client"
    decks_dir = client_dir / "decks"
    decks_dir.mkdir(parents=True)
    (client_dir / "client.md").write_text("# Test", encoding="utf-8")
    (client_dir / "value_prop.md").write_text("# Pos", encoding="utf-8")
    (decks_dir / "deck1.pptx").write_bytes(b"fake")
    (decks_dir / "deck2.pptx").write_bytes(b"fake")

    result = knowledge_view(roots)
    assert result["clients"][0]["past_decks"] == 2


def test_knowledge_view_counts_engagement_notes(roots: Roots) -> None:
    client_dir = roots.knowledge / "clients" / "test-client"
    eng_dir = client_dir / "engagements"
    eng_dir.mkdir(parents=True)
    (client_dir / "client.md").write_text("# Test", encoding="utf-8")
    (client_dir / "value_prop.md").write_text("# Pos", encoding="utf-8")
    (eng_dir / "note1.md").write_text("Note 1")
    (eng_dir / "note2.md").write_text("Note 2")

    result = knowledge_view(roots)
    assert result["clients"][0]["engagement_notes"] == 2


def test_knowledge_view_detects_template(roots: Roots) -> None:
    client_dir = roots.knowledge / "clients" / "test-client"
    theme_dir = client_dir / "theme"
    theme_dir.mkdir(parents=True)
    (client_dir / "client.md").write_text("# Test", encoding="utf-8")
    (client_dir / "value_prop.md").write_text("# Pos", encoding="utf-8")
    (theme_dir / "template.pptx").write_bytes(b"fake")

    result = knowledge_view(roots)
    assert result["clients"][0]["has_template"] is True


def test_knowledge_view_no_template_by_default(roots: Roots) -> None:
    client_dir = roots.knowledge / "clients" / "test-client"
    client_dir.mkdir(parents=True)
    (client_dir / "client.md").write_text("# Test", encoding="utf-8")
    (client_dir / "value_prop.md").write_text("# Pos", encoding="utf-8")

    result = knowledge_view(roots)
    assert result["clients"][0]["has_template"] is False


def test_knowledge_view_detects_custom_theme(roots: Roots) -> None:
    client_dir = roots.knowledge / "clients" / "test-client"
    theme_dir = client_dir / "theme"
    theme_dir.mkdir(parents=True)
    (client_dir / "client.md").write_text("# Test", encoding="utf-8")
    (client_dir / "value_prop.md").write_text("# Pos", encoding="utf-8")
    (theme_dir / "tokens.json").write_text("{}")

    result = knowledge_view(roots)
    assert result["clients"][0]["theme"] == "custom"


def test_knowledge_view_no_theme_by_default(roots: Roots) -> None:
    client_dir = roots.knowledge / "clients" / "test-client"
    client_dir.mkdir(parents=True)
    (client_dir / "client.md").write_text("# Test", encoding="utf-8")
    (client_dir / "value_prop.md").write_text("# Pos", encoding="utf-8")

    result = knowledge_view(roots)
    assert result["clients"][0]["theme"] is None


# ---------------------------------------------------------------------------
# keys_view
# ---------------------------------------------------------------------------


def test_keys_view_lists_all_providers(roots: Roots, monkeypatch) -> None:
    # Clear any existing env vars
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = keys_view("dev-mistral")
    var_names = {k["var"] for k in result["keys"]}
    assert "MISTRAL_API_KEY" in var_names
    assert "OPENAI_API_KEY" in var_names
    assert "ANTHROPIC_API_KEY" in var_names


def test_keys_view_shows_set_status(roots: Roots, monkeypatch) -> None:
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")

    result = keys_view("dev-mistral")
    by_var = {k["var"]: k for k in result["keys"]}
    assert by_var["MISTRAL_API_KEY"]["set"] is True
    assert by_var["OPENAI_API_KEY"]["set"] is False
    assert by_var["ANTHROPIC_API_KEY"]["set"] is False


def test_keys_view_never_returns_key_value(roots: Roots, monkeypatch) -> None:
    """Critical: ensure no part of the key value appears in the response."""
    secret_key = "very-secret-api-key-12345"
    monkeypatch.setenv("MISTRAL_API_KEY", secret_key)

    result = keys_view("dev-mistral")
    result_str = str(result)

    # Verify the secret is not in the response at all
    assert secret_key not in result_str
    assert "very-secret" not in result_str
    assert "12345" not in result_str


def test_keys_view_shows_provider_names(roots: Roots) -> None:
    result = keys_view("dev-mistral")
    providers = {k["provider"] for k in result["keys"]}
    assert "mistral" in providers
    assert "openai" in providers
    assert "claude" in providers


def test_keys_view_shows_needed_by(roots: Roots) -> None:
    # The dev environment should need at least one provider
    result = keys_view("dev-mistral")
    # This depends on the config, so we just check structure
    assert all("needed_by" in k and isinstance(k["needed_by"], list) for k in result["keys"])


def test_keys_view_needed_by_is_sorted(roots: Roots) -> None:
    result = keys_view("dev-mistral")
    for key_info in result["keys"]:
        assert key_info["needed_by"] == sorted(key_info["needed_by"])


def test_keys_view_gracefully_handles_missing_config(
    roots: Roots, tmp_path: Path, monkeypatch
) -> None:
    # Temporarily move the config file
    from autodeck.providers import registry

    monkeypatch.setattr(registry, "DEFAULT_CONFIG_PATH", tmp_path / "nonexistent.yaml")

    # Should not crash, just return what it can
    result = keys_view("dev-mistral")
    assert "keys" in result
    assert len(result["keys"]) > 0  # Should still know about the providers


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_knowledge_view_and_keys_view_work_together(roots: Roots, monkeypatch) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "test")

    # Set up some knowledge
    proj_dir = roots.knowledge / "projects" / "test-proj"
    proj_dir.mkdir(parents=True)
    (proj_dir / "project.md").write_text("# Project", encoding="utf-8")
    (proj_dir / "claims.md").write_text("# Claims", encoding="utf-8")

    client_dir = roots.knowledge / "clients" / "test-client"
    client_dir.mkdir(parents=True)
    (client_dir / "client.md").write_text("# Client", encoding="utf-8")
    (client_dir / "value_prop.md").write_text("# Value", encoding="utf-8")

    # Both should work
    knowledge = knowledge_view(roots)
    keys = keys_view("dev-mistral")

    assert knowledge["projects"][0]["name"] == "test-proj"
    assert knowledge["clients"][0]["name"] == "test-client"
    assert any(k["set"] for k in keys["keys"])
