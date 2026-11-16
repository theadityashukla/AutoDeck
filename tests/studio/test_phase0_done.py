"""Phase 0's "done when", end to end (v3 plan §12):

    a hand-written base deck renders to PPTX and previews, and an edit to it can be made,
    listed and undone.

Two versions: one in the default suite (PPTX only; needs the fonts, not LibreOffice) and
one under the `render` marker that also rasterises previews. Both pin exact undo: after the
undo, `current.json` is byte-identical to what it was before the edit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio import changelog as cl
from autodeck.studio.diff import describe
from autodeck.studio.edits import set_block_text
from autodeck.studio.engagement import create_engagement, open_engagement
from autodeck.studio.models import DeckArtifact
from autodeck.studio.render import build_pptx, render_artifact
from autodeck.studio.store import ArtifactStore
from tests.studio.helpers import ARTIFACT_ID, CLIENT, FONTS_AVAILABLE, PROJECT, T0, T1


def _edit_list_undo(store: ArtifactStore) -> None:
    """Make an edit, list it, undo it; assert the artifact is back byte for byte."""
    before_bytes = store.paths.current.read_bytes()
    deck = store.load()

    edited = set_block_text(
        deck, slide_id="s2", block_id="heading", text="Cost per request fell 41% in six weeks"
    )
    entry = store.apply(
        edited,
        instruction="Tighten the slide two heading.",
        thread_id="t-phase0",
        layer="composition",
        model_id="human",
        now=T1,
    )
    assert store.paths.current.read_bytes() != before_bytes
    assert describe(entry.diff) == [
        "~ slides[s2].blocks[heading].text: 'Cost per request fell by 41% in the pilot' -> "
        "'Cost per request fell 41% in six weeks'"
    ]
    assert cl.listing(store.changelog()) == [
        "c0001 live composition human t-phase0 2026-11-13T09:05:00+00:00 "
        "Tighten the slide two heading."
    ]

    undone = store.undo()
    assert undone.id == "c0001" and undone.undone
    assert store.paths.current.read_bytes() == before_bytes
    assert store.load() == deck
    assert cl.listing(store.changelog())[0].startswith("c0001 undone ")


def _open_fixture_artifact(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact
) -> ArtifactStore:
    create_engagement(
        CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )
    engagement = open_engagement(
        CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root
    )
    engagement.create_artifact(base_deck)
    return engagement.artifact_store(ARTIFACT_ID)


@pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")
def test_phase0_done_pptx(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact, tokens: DesignTokens
) -> None:
    store = _open_fixture_artifact(knowledge_root, workspace_root, base_deck)
    built = build_pptx(store.load(), tokens=tokens, out_path=store.paths.renders / "deck.pptx")
    assert built.path.is_file() and built.placeholders == {}
    assert built.slide_ids == ("s1", "s2", "s3", "s4")
    _edit_list_undo(store)


@pytest.mark.render
def test_phase0_done_with_previews(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact, tokens: DesignTokens
) -> None:
    store = _open_fixture_artifact(knowledge_root, workspace_root, base_deck)
    report = render_artifact(store.load(), tokens=tokens, out_dir=store.paths.renders)
    assert report.built.placeholders == {}
    assert report.previews.rendered, report.previews.note
    assert len(report.previews.images) == 4
    for line in report.timing_lines():
        print(line)  # visible with `pytest -s`: the plan's preview-speed measurement
    _edit_list_undo(store)
