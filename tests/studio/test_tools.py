"""The lead's tools through v2's ToolBox: edits recorded with layer, model and instruction;
refusals as error results; isolation never leaks.

Phase 2-3 retired the Phase 1 tests of `write_slide`, `set_design_concept` and `propose` /
`apply_option` with whole candidate slides (the lead no longer writes layouts); their
replacements are in `test_tools_phase23.py`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from autodeck.agents.tools.registry import ToolBox, ToolResult
from autodeck.providers.base import ToolCall
from autodeck.studio.engagement import Engagement, create_engagement
from autodeck.studio.models import DeckArtifact
from autodeck.studio.proposals import ProposalStore
from autodeck.studio.sources import SourceLibrary
from autodeck.studio.tools import (
    ISOLATION_REFUSAL,
    NO_CHANGE_REFUSAL,
    TOOL_NAMES,
    ToolContext,
    TurnLedger,
    build_toolbox,
    instruction_line,
)
from tests.studio.helpers import (
    ARTIFACT_ID,
    CLIENT,
    FONTS_AVAILABLE,
    OTHER_CLIENT,
    PROJECT,
    T0,
    StepClock,
    dev_tokens,
)

needs_fonts = pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")


class Harness:
    def __init__(self, engagement: Engagement, corpus_root: Path) -> None:
        self.engagement = engagement
        self.ledger = TurnLedger()
        self.ctx = ToolContext(
            engagement=engagement,
            thread_id="t0001",
            turn_id="u0001",
            instruction="Build the deck",
            model_id="scripted/test",
            tokens=dev_tokens(),
            sources=SourceLibrary(engagement, corpus_root=corpus_root),
            proposals=ProposalStore(engagement),
            ledger=self.ledger,
            clock=StepClock(),
        )
        self.box: ToolBox = build_toolbox(self.ctx)
        self.n = 0

    def call(self, tool: str, /, **arguments: Any) -> ToolResult:
        self.n += 1
        return self.box.dispatch(ToolCall(id=f"k{self.n}", name=tool, arguments=arguments))

    def deck(self) -> DeckArtifact:
        return self.engagement.artifact_store(ARTIFACT_ID).load()


@pytest.fixture
def harness_args(
    knowledge_root: Path, workspace_root: Path, tmp_path: Path
) -> tuple[Path, Path, Path]:
    return knowledge_root, workspace_root, tmp_path / "corpus"


def _harness(args: tuple[Path, Path, Path]) -> Harness:
    """Built inside each test (it calls studio code), never in a fixture."""
    knowledge_root, workspace_root, corpus_root = args
    engagement = create_engagement(
        CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )
    return Harness(engagement, corpus_root)


def _with_fixture(h: Harness, base_deck: DeckArtifact) -> None:
    h.engagement.create_artifact(base_deck)


def _slide(base_deck: DeckArtifact, source: str, **changes: Any) -> dict[str, Any]:
    data = base_deck.slide(source).model_dump(mode="json")
    data.update(changes)
    return data


def test_the_vocabulary_is_registered_in_order(harness_args: tuple[Path, Path, Path]) -> None:
    harness = _harness(harness_args)
    assert [s.name for s in harness.box.specs] == list(TOOL_NAMES)


def test_instruction_line() -> None:
    assert instruction_line("  Make it\n shorter  ") == "Make it shorter"
    assert instruction_line("x" * 300).endswith("…") and len(instruction_line("x" * 300)) == 200
    assert instruction_line("   ") == "(no instruction)"


def test_deck_tools_need_a_deck_first(harness_args: tuple[Path, Path, Path]) -> None:
    harness = _harness(harness_args)
    result = harness.call("view_deck")
    assert result.error and "create_deck" in result.text


def test_create_deck_once(harness_args: tuple[Path, Path, Path]) -> None:
    harness = _harness(harness_args)
    result = harness.call("create_deck", artifact_id=ARTIFACT_ID, title="Readout")
    assert not result.error and result.summary == f"created deck {ARTIFACT_ID}"
    assert harness.ledger.created == [ARTIFACT_ID] and harness.ledger.changes == []
    assert harness.deck().title == "Readout" and harness.deck().slides == []
    again = harness.call("create_deck", artifact_id="second")
    assert again.error and ARTIFACT_ID in again.text
    view = harness.call("view_deck")
    assert view.summary == f"viewed deck {ARTIFACT_ID} (0 slides)"
    assert view.text.startswith(f"Deck `{ARTIFACT_ID}`: Readout (0 slides)")


def test_edits_record_instruction_thread_layer_and_model(
    harness_args: tuple[Path, Path, Path],
) -> None:
    harness = _harness(harness_args)
    harness.call("create_deck", artifact_id=ARTIFACT_ID)
    brief = harness.call("set_brief", audience="Board", goal="Approve", marker="decided")
    assert not brief.error and brief.summary == "set the brief"
    story = harness.call(
        "set_storyline", points=[{"text": "One"}, {"text": "Two"}], marker="provisional"
    )
    assert story.summary == "set the storyline (2 points)"
    entries = [e for _, e in harness.ledger.changes]
    assert [e.id for e in entries] == ["c0001", "c0002"]
    assert {(e.instruction, e.thread_id, e.model_id) for e in entries} == {
        ("Build the deck", "t0001", "scripted/test")
    }
    assert [e.layer for e in entries] == ["direction"] * 2
    assert brief.text.startswith(f"Recorded change c0001 on {ARTIFACT_ID}:")
    log = harness.engagement.artifact_store(ARTIFACT_ID).changelog()
    assert [e.id for e in log.entries] == ["c0001", "c0002"]


def test_refusals_come_back_as_errors(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    chart = harness.call("set_block_text", slide_id="s3", block_id="chart", text="x")
    assert chart.error and "chart" in chart.text
    missing = harness.call("view_slide", slide_id="s9")
    assert missing.error and "s9" in missing.text
    same = harness.call("set_block_text", slide_id="s2", block_id="number", text="41%")
    assert same.error and same.text == f"ERROR: {NO_CHANGE_REFUSAL}"
    bad_args = harness.call("move_slide", slide_id="s1")
    assert bad_args.error and bad_args.summary == "move_slide: invalid arguments"
    assert harness.ledger.changes == []


def test_structure_tools(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    assert harness.call("move_slide", slide_id="s4", position=1).summary == (
        "moved slide s4 to position 1"
    )
    assert harness.call("remove_slide", slide_id="s2").summary == "removed slide s2"
    assert harness.call("set_marker", target="slide:s3", marker="decided").summary == (
        "marked slide:s3 decided"
    )
    assert harness.deck().slide_ids() == ["s4", "s1", "s3"]
    assert harness.deck().slide("s3").marker == "decided"


def test_undo_and_redo(harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    before = harness.engagement.artifact_store(ARTIFACT_ID).current_text()
    harness.call("move_slide", slide_id="s4", position=1)
    undo = harness.call("undo")
    assert not undo.error and undo.summary == "undid c0001: Build the deck"
    assert harness.engagement.artifact_store(ARTIFACT_ID).current_text() == before
    redo = harness.call("redo")
    assert redo.summary == "redid c0001: Build the deck"
    assert [e.id for _, e in harness.ledger.undone] == ["c0001"]
    assert [e.id for _, e in harness.ledger.redone] == ["c0001"]
    harness.call("undo")
    nothing = harness.call("undo")
    assert nothing.error


def test_sources_tools(harness_args: tuple[Path, Path, Path]) -> None:
    harness = _harness(harness_args)
    listing = harness.call("list_sources")
    assert listing.summary == "4 sources"
    assert "knowledge:client/client.md | client/client.md |" in listing.text
    read = harness.call("read_source", source_id="knowledge:project/project.md")
    assert not read.error and "# Project" in read.text
    found = harness.call("search_sources", query="Framing")
    assert found.summary == 'search "Framing": 1 passages'
    assert found.text.startswith("[knowledge:client/value_prop.md] Framing only.")
    nothing = harness.call("search_sources", query="zebra")
    assert nothing.text == "No passages match."


def test_isolation_refusals_leak_nothing(
    harness_args: tuple[Path, Path, Path], knowledge_root: Path
) -> None:
    harness = _harness(harness_args)
    secret = knowledge_root / "clients" / OTHER_CLIENT / "client.md"
    secret.write_text("# contoso-health\n\nTOP SECRET PIPELINE\n", encoding="utf-8")
    os.symlink(secret, knowledge_root / "clients" / CLIENT / "borrowed.md")
    result = harness.call("read_source", source_id="knowledge:client/borrowed.md")
    assert result.error and result.text == f"ERROR: {ISOLATION_REFUSAL}"
    traversal = harness.call(
        "read_source", source_id=f"knowledge:client/../{OTHER_CLIENT}/client.md"
    )
    assert traversal.error and "TOP SECRET" not in traversal.text
    assert OTHER_CLIENT not in result.text


def test_load_skill_only_the_allowed_ones(harness_args: tuple[Path, Path, Path]) -> None:
    harness = _harness(harness_args)
    ok = harness.call("load_skill", name="storyline")
    assert not ok.error and ok.text.startswith("## Skill: storyline\n\n")
    assert ok.summary == "loaded skill storyline"
    refused = harness.call("load_skill", name="citations")
    assert refused.error and "storyline" in refused.text
