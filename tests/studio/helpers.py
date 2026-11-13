"""Shared builders for the studio tests (plain functions, so a test that calls an
unimplemented body fails inside the test rather than erroring in a fixture)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from autodeck.design.fonts import is_available
from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio.models import DeckArtifact

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DECK = Path(__file__).resolve().parent / "fixtures" / "base_deck.json"
DEV_TOKENS = REPO_ROOT / "config" / "tokens" / "dev.json"

CLIENT = "northwind-retail"
OTHER_CLIENT = "contoso-health"
PROJECT = "llm-inference-efficiency"
ARTIFACT_ID = "inference-readout"

T0 = datetime(2026, 11, 13, 9, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 13, 9, 5, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 13, 9, 10, 0, tzinfo=UTC)

FONTS_AVAILABLE = is_available("Carlito")
"""config/tokens/dev.json draws in Carlito; layout QA cannot measure without it."""


def load_fixture_deck() -> DeckArtifact:
    return DeckArtifact.model_validate_json(FIXTURE_DECK.read_text(encoding="utf-8"))


def dev_tokens() -> DesignTokens:
    return DesignTokens.load(DEV_TOKENS)


def make_knowledge_root(root: Path) -> Path:
    """A minimal two-client knowledge tree satisfying v2's KnowledgeLoader."""
    for client in (CLIENT, OTHER_CLIENT):
        folder = root / "clients" / client
        folder.mkdir(parents=True)
        (folder / "client.md").write_text(f"# {client}\n", encoding="utf-8")
        (folder / "value_prop.md").write_text("Framing only.\n", encoding="utf-8")
    project = root / "projects" / PROJECT
    project.mkdir(parents=True)
    (project / "project.md").write_text("# Project\n", encoding="utf-8")
    (project / "claims.md").write_text("", encoding="utf-8")
    return root
