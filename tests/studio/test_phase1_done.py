"""Phase 1's "done when", end to end with the scripted model (v3 plan §12):

    the owner builds a short deck over two separate threads, and the second thread picks
    up correctly with no transcript.

Thread one builds a three-slide deck on the real knowledge pair northwind-retail /
llm-inference-efficiency, offers two openings (dismissed by the owner), and answers a
question. Thread two is opened fresh: the test asserts that the model's first message is
exactly the context built from state plus the recap request, that this context is a pure
function of the workspace (deleting thread one's log changes nothing), that it carries the
deck, its change history and the dismissed proposal, and that it carries none of thread
one's conversation. Thread two then makes a change and undoes it, byte for byte.

The default-suite version uses a stand-in renderer; the `render` version draws the deck
with LibreOffice. Both need the Carlito font, because `write_slide` runs the layout check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.studio.context import build_context
from autodeck.studio.conversation import AssistantLine, ToolLine, UserLine
from autodeck.studio.previews import render_with_libreoffice
from autodeck.studio.prompt import CONTEXT_SEPARATOR, RECAP_REQUEST
from autodeck.studio.scripted import ScriptedModel
from autodeck.studio.threads import ThreadStore
from tests.studio.helpers import (
    CLIENT,
    FONTS_AVAILABLE,
    PROJECT,
    REAL_KNOWLEDGE,
    TWO_THREADS_SCRIPT,
    dev_tokens,
    make_studio,
)

pytestmark = pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")

DECK = "pilot-readout"
OWNER_1 = (
    "Start a short readout deck for Northwind's digital leadership on the serving-cost "
    "pilot: three slides, the ask first."
)
OWNER_2 = "Show me two other ways to open it."
OWNER_3 = "Is the middle slide carrying its weight?"
OWNER_5 = "Make the number on slide 2 38%."
OWNER_6 = "Undo that."


def test_two_threads_pick_up_from_state_with_no_transcript(tmp_path: Path) -> None:
    model = ScriptedModel.from_file(TWO_THREADS_SCRIPT)
    studio, _, _ = make_studio(tmp_path, model, knowledge_root=REAL_KNOWLEDGE)
    engagement = studio.create_engagement(CLIENT, PROJECT, title="Pilot readout")
    threads = ThreadStore(engagement)

    # -- thread one: build, propose (dismissed), talk --------------------------------
    first, recap = studio.open_thread(engagement, title="First draft")
    assert first.opening == "fresh" and recap is None

    built = studio.run_turn(engagement, first.id, text=OWNER_1)
    assert built.turn_kind == "change" and built.stop_reason == "replied"
    assert built.created_artifacts == [DECK]
    assert built.change_ids == ["c0001", "c0002", "c0003", "c0004", "c0005"]

    proposed = studio.run_turn(engagement, first.id, text=OWNER_2)
    assert proposed.turn_kind == "proposal" and proposed.proposal_ids == ["p0001"]
    studio.dismiss_proposal(engagement, first.id, "p0001")

    talked = studio.run_turn(engagement, first.id, text=OWNER_3)
    assert talked.turn_kind == "talk"

    first_lines = threads.read_lines(first.id)
    errors = [line.summary for line in first_lines if isinstance(line, ToolLine) and line.error]
    assert errors == []
    store = engagement.artifact_store(DECK)
    deck = store.load()
    assert deck.slide_ids() == ["s1", "s2", "s3"]
    assert deck.brief is not None and deck.brief.marker == "decided"
    assert deck.storyline.point_ids() == ["p1", "p2", "p3"]

    # -- thread two opens from state ---------------------------------------------------
    calls_before = len(model.calls)
    second, recap = studio.open_thread(engagement, title="Refinement")
    assert second.opening == "returning"
    assert recap is not None and recap.turn_kind == "talk"
    sent = model.calls[calls_before].messages
    context = threads.context_text(second.id)
    assert len(sent) == 1 and sent[0].role == "user"
    assert sent[0].content == f"{context}{CONTEXT_SEPARATOR}{RECAP_REQUEST}"

    owner_memory = studio.settings.owner_memory_path
    assert context == build_context(engagement, owner_memory_path=owner_memory)
    log = threads.paths(first.id).messages
    hidden = log.with_name("hidden.jsonl")
    log.rename(hidden)
    try:
        assert build_context(engagement, owner_memory_path=owner_memory) == context
    finally:
        hidden.rename(log)

    # It carries the state: the deck, its change history, the rejected proposal.
    for needle in (
        f"## {DECK}",
        f"Deck `{DECK}`: Serving costs: pilot readout (3 slides)",
        "p1. Serving cost, not model quality, now limits the assistant",
        "  3. s3 [provisional] serves p3 | placed",
        "- c0005 live | composition | scripted/two-threads | t0001 | ",
        "- c0001 live | direction | scripted/two-threads | t0001 | ",
        "## Dismissed",
        f"- p0001 ({DECK}, thread t0001) [dismissed]: Two other ways to open the deck",
        "  - A. Lead with the number: ",
    ):
        assert needle in context, needle

    # It carries none of thread one's conversation. The owner's first message is on the
    # change-log entries it caused (that is state: the instruction behind a change); the
    # model's replies, and the messages that changed nothing, are nowhere.
    for line in first_lines:
        if isinstance(line, AssistantLine) and line.text.strip():
            assert line.text not in context
        if isinstance(line, UserLine) and line.origin == "owner" and line.text != OWNER_1:
            assert line.text not in context
    assert OWNER_2 not in context and OWNER_3 not in context
    assert context.count(OWNER_1) == 5  # once per entry it caused: c0001-c0005
    assert "Here are two other openings" not in context

    # -- thread two changes the deck and undoes it -------------------------------------
    before = store.current_text()
    changed = studio.run_turn(engagement, second.id, text=OWNER_5)
    assert changed.turn_kind == "change" and changed.change_ids == ["c0006"]
    assert store.load().slide("s2").block("number").text == "38%"
    undone = studio.run_turn(engagement, second.id, text=OWNER_6)
    assert undone.turn_kind == "change" and undone.undone_ids == ["c0006"]
    assert store.current_text() == before

    entries = store.changelog().entries
    assert [(e.id, e.thread_id, e.undone) for e in entries][-1] == ("c0006", second.id, True)
    assert {e.thread_id for e in entries[:5]} == {first.id}
    assert {e.model_id for e in entries} == {"scripted/two-threads"}
    assert [e.layer for e in entries] == [
        "direction",
        "direction",
        "composition",
        "composition",
        "composition",
        "composition",
    ]
    assert entries[5].instruction == OWNER_5
    assert model.remaining == 0 and model.overrun == 0
    assert not (REAL_KNOWLEDGE / "clients" / CLIENT / "memory").exists()


@pytest.mark.render
def test_the_first_draft_renders_with_libreoffice(tmp_path: Path) -> None:
    model = ScriptedModel.from_file(TWO_THREADS_SCRIPT)
    studio, bus, _ = make_studio(
        tmp_path,
        model,
        knowledge_root=REAL_KNOWLEDGE,
        renderer=render_with_libreoffice(dev_tokens()),
    )
    engagement = studio.create_engagement(CLIENT, PROJECT)
    thread, _ = studio.open_thread(engagement)
    studio.run_turn(engagement, thread.id, text=OWNER_1)
    manifest = studio.previews.current(engagement.artifact_store(DECK))
    assert manifest is not None and manifest.rendered, manifest
    assert manifest.slide_ids == ["s1", "s2", "s3"] and manifest.placeholders == {}
    folder = engagement.artifact_store(DECK).paths.render_dir(manifest.digest)
    assert all((folder / image).stat().st_size > 1000 for image in manifest.images)
    ready = [p.event for p in bus.replay(f"{CLIENT}/{PROJECT}/{thread.id}")]
    assert ready[-1].type == "previews_ready"
