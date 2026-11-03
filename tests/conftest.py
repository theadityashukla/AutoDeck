"""Suite-wide settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# The CLI loads ./.env at startup (autodeck/dotenv.py). Tests run from the repo root, where a
# developer's real keys live; they must never reach a test.
os.environ["AUTODECK_NO_DOTENV"] = "1"


@pytest.fixture(autouse=True)
def _owner_memory_in_tmp(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The owner's agent memory (B77) is under the home folder; tests must never touch it."""
    folder = tmp_path_factory.mktemp("owner-memory")
    monkeypatch.setenv("AUTODECK_OWNER_MEMORY", str(Path(folder) / "owner.md"))
