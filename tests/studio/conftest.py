"""Fixtures for the studio tests. None of them calls studio code that is not a model, so a
missing body shows up as a test failure, not a fixture error."""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio.models import DeckArtifact
from tests.studio.helpers import dev_tokens, load_fixture_deck, make_knowledge_root


@pytest.fixture
def base_deck() -> DeckArtifact:
    return load_fixture_deck()


@pytest.fixture
def tokens() -> DesignTokens:
    return dev_tokens()


@pytest.fixture
def knowledge_root(tmp_path: Path) -> Path:
    return make_knowledge_root(tmp_path / "knowledge")


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """Always a temporary directory: tests never write to the repo's workspace/."""
    return tmp_path / "workspace"
