"""The lead's tools through v2's ToolBox: edits recorded with layer, model and instruction;
refusals as error results; isolation never leaks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from autodeck.agents.tools.registry import ToolBox, ToolResult
from autodeck.providers.base import ToolCall
from autodeck.studio import tool_args
from autodeck.studio.conversation import ProposalOption
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
    concept = harness.call("set_design_concept", text="Quiet and editorial.")
    assert concept.summary == "set the design concept"
    entries = [e for _, e in harness.ledger.changes]
    assert [e.id for e in entries] == ["c0001", "c0002", "c0003"]
    assert {(e.instruction, e.thread_id, e.model_id) for e in entries} == {
        ("Build the deck", "t0001", "scripted/test")
    }
    assert [e.layer for e in entries] == ["direction"] * 3
    assert brief.text.startswith(f"Recorded change c0001 on {ARTIFACT_ID}:")
    log = harness.engagement.artifact_store(ARTIFACT_ID).changelog()
    assert [e.id for e in log.entries] == ["c0001", "c0002", "c0003"]


@needs_fonts
def test_write_slide_reports_the_layout_check(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    result = harness.call("write_slide", slide=_slide(base_deck, "s2", id="s9"), position=1)
    assert not result.error
    assert result.summary == "wrote slide s9 (new, position 1): layout passed"
    assert "Layout check passed." in result.text
    assert harness.ledger.changes[-1][1].layer == "composition"
    crowded = _slide(base_deck, "s4")
    for element in crowded["layout"]["elements"]:
        if element.get("block_id") == "heading":
            element["size_pt"] = 240
    result = harness.call("write_slide", slide=crowded)
    assert not result.error and "layout finding" in result.summary
    assert "replaced, position 5" in result.summary
    assert "Layout check found:" in result.text


def test_write_slide_without_layout(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    data = _slide(base_deck, "s2", id="s9", layout=None)
    result = harness.call("write_slide", slide=data)
    assert result.summary == "wrote slide s9 (new, position 5): no layout yet"


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
    unknown_point = harness.call(
        "write_slide", slide=_slide(base_deck, "s2", id="s9", serves=["p9"])
    )
    assert unknown_point.error and "p9" in unknown_point.text
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
    harness.call("set_block_text", slide_id="s2", block_id="number", text="38%")
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


@needs_fonts
def test_propose_records_options_without_changing_the_deck(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    before = harness.engagement.artifact_store(ARTIFACT_ID).current_text()
    candidate = _slide(base_deck, "s2", id="s1b", serves=["p1"])
    result = harness.call(
        "propose",
        summary="Two openings",
        options=[
            {
                "label": "Number",
                "text": "Open on 41%.",
                "slides": [{"slide": candidate, "replaces": "s1"}],
            },
            {"label": "Question", "text": "Open on the question."},
        ],
    )
    assert not result.error and result.summary == "proposed p0001: 2 options"
    assert harness.engagement.artifact_store(ARTIFACT_ID).current_text() == before
    record = ProposalStore(harness.engagement).load("p0001")
    assert record.artifact_id == ARTIFACT_ID and [o.id for o in record.options] == ["A", "B"]
    assert record.thread_id == "t0001" and record.turn_id == "u0001"
    assert [p.id for p in harness.ledger.proposals] == ["p0001"]
    assert harness.ledger.changes == []
    # What applying it does is on the record.
    assert [(c.slide.id, c.replaces, c.insert_at) for c in record.options[0].candidates] == [
        ("s1b", "s1", None)
    ]


def test_propose_requires_replace_or_insert_for_every_candidate(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    candidate = _slide(base_deck, "s2", id="s1b", serves=["p1"])

    def propose(slide: dict[str, Any]) -> ToolResult:
        return harness.call(
            "propose",
            summary="Opening",
            options=[{"label": "N", "text": "x", "slides": [slide]}],
        )

    for bad in (
        {"slide": candidate},
        {"slide": candidate, "replaces": "s1", "insert_at": 1},
        candidate,  # the old shape: a bare slide
    ):
        result = propose(bad)
        assert result.error, bad
    assert "replaces" in propose({"slide": candidate}).text
    # Checked against the deck as it is now.
    gone = propose({"slide": candidate, "replaces": "nope"})
    assert gone.error and "no longer in deck" in gone.text
    far = propose({"slide": candidate, "insert_at": 9})
    assert far.error and "outside 1" in far.text
    taken = propose({"slide": _slide(base_deck, "s2", id="s3"), "insert_at": 1})
    assert taken.error and "already has a slide" in taken.text
    assert harness.engagement.paths.proposal_ids() == []
    ok = propose({"slide": candidate, "insert_at": 2})
    assert not ok.error


def test_propose_refuses_unplaced_candidates(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    result = harness.call(
        "propose",
        summary="One opening",
        options=[{"label": "N", "text": "x", "slides": [_slide(base_deck, "s2", layout=None)]}],
    )
    assert result.error and "layout" in result.text
    assert harness.engagement.paths.proposal_ids() == []


@needs_fonts
def test_apply_option(harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    candidate = _slide(base_deck, "s2", id="s1b", serves=["p1"])
    options = [
        {"label": "Number", "text": "x", "slides": [{"slide": candidate, "replaces": "s1"}]},
        {"label": "Question", "text": "y"},
    ]
    harness.call("propose", summary="Openings", options=options)
    text_only = harness.call("apply_option", proposal_id="p0001", option_id="B")
    assert text_only.error and "no candidate slides" in text_only.text
    applied = harness.call("apply_option", proposal_id="p0001", option_id="A")
    assert not applied.error and applied.summary == "applied option A of p0001"
    record = ProposalStore(harness.engagement).load("p0001")
    assert (record.status, record.chosen, record.resolved_by) == ("accepted", "A", "chat")
    assert harness.deck().slide("s1").intent == base_deck.slide("s2").intent
    assert harness.ledger.changes[-1][1].layer == "composition"
    harness.call("propose", summary="Again", options=options)
    ProposalStore(harness.engagement).resolve(
        "p0002", status="dismissed", chosen=None, by="owner", now=T0
    )
    dismissed = harness.call("apply_option", proposal_id="p0002", option_id="A")
    assert dismissed.error and "dismissed" in dismissed.text


@needs_fonts
def test_an_option_meant_to_replace_the_opening_replaces_it(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    """The first real-model run: three alternative openings, each one candidate with a new
    id; picking one added a fourth slide and the model said slide 1 was replaced."""
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    before = harness.deck()
    candidate = _slide(base_deck, "s2", id="s1b", serves=[])
    harness.call(
        "propose",
        summary="Alternative openings",
        options=[
            {"label": "B", "text": "x", "slides": [{"slide": candidate, "replaces": "s1"}]},
            {"label": "C", "text": "y"},
        ],
    )
    applied = harness.call("apply_option", proposal_id="p0001", option_id="A")
    assert not applied.error
    after = harness.deck()
    assert len(after.slides) == len(before.slides)
    assert after.slides[0].intent == candidate["intent"] != before.slides[0].intent
    assert after.slide_ids() == before.slide_ids()  # the replaced slide's id is kept
    assert after.slides[0].serves == before.slides[0].serves  # its storyline links too
    assert after.slides[1:] == before.slides[1:]
    # The result says what happened, in words the model can repeat.
    assert "Replaced slide 1 (id s1 kept) with the new slide" in applied.text
    assert "Slide order now: 1. s1 " in applied.text and "; 2. s2 " in applied.text


@needs_fonts
def test_apply_option_inserts_at_the_stated_position(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    candidate = _slide(base_deck, "s2", id="extra", serves=["p1"])
    harness.call(
        "propose",
        summary="Add a slide",
        options=[{"label": "A", "text": "x", "slides": [{"slide": candidate, "insert_at": 2}]}],
    )
    applied = harness.call("apply_option", proposal_id="p0001", option_id="A")
    assert not applied.error
    assert harness.deck().slide_ids() == ["s1", "extra", "s2", "s3", "s4"]
    assert "Inserted new slide 'extra'" in applied.text and "as slide 2" in applied.text
    assert "Slide order now: 1. s1 " in applied.text and "; 2. extra " in applied.text


@needs_fonts
def test_apply_option_refuses_when_the_deck_no_longer_fits_and_stays_open(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    candidate = _slide(base_deck, "s2", id="s1b", serves=[])
    harness.call(
        "propose",
        summary="Openings",
        options=[
            {"label": "B", "text": "x", "slides": [{"slide": candidate, "replaces": "s1"}]}
        ],
    )
    assert not harness.call("remove_slide", slide_id="s1").error
    deck_before = harness.deck()
    refused = harness.call("apply_option", proposal_id="p0001", option_id="A")
    assert refused.error and "no longer in deck" in refused.text
    assert "write_slide" in refused.text and "propose again" in refused.text
    assert harness.deck() == deck_before
    assert ProposalStore(harness.engagement).load("p0001").status == "open"


@needs_fonts
def test_apply_option_refuses_an_old_record_that_never_said_replace_or_insert(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    store = ProposalStore(harness.engagement)
    store.create(
        thread_id="t0001",
        turn_id="u0001",
        artifact_id=ARTIFACT_ID,
        summary="Old",
        options=[
            ProposalOption.model_validate(
                {
                    "id": "A",
                    "label": "Old",
                    "text": "x",
                    "slides": [_slide(base_deck, "s2", id="s1b")],
                }
            )
        ],
        now=T0,
    )
    refused = harness.call("apply_option", proposal_id="p0001", option_id="A")
    assert refused.error and "editing tools" in refused.text
    assert store.load("p0001").status == "open"


def test_write_slide_names_its_fields_and_still_refuses_unknown_ones(
    harness_args: tuple[Path, Path, Path], base_deck: DeckArtifact
) -> None:
    harness = _harness(harness_args)
    _with_fixture(harness, base_deck)
    description = next(s for s in harness.box.specs if s.name == "write_slide").description
    for field in ("id", "intent", "blocks", "speaker_notes", "layout", "marker", "serves"):
        assert field in description
    schema = tool_args.WriteSlideArgs.model_json_schema()
    assert all(f in schema["$defs"]["Slide"]["properties"] for f in ("intent", "serves"))
    assert "rationale" in tool_args.SLIDE_FIELDS_HELP  # said plainly: there is none
    result = harness.call(
        "write_slide", slide={**_slide(base_deck, "s1"), "rationale": "because"}
    )
    assert result.error and "rationale" in result.text


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
