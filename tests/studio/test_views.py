"""Pure views: the compact deck text the model reads, and the JSON the interface reads."""

from __future__ import annotations

from typing import Any

from autodeck.studio.conversation import (
    THREAD_LINE,
    ProposalRecord,
    RenderManifest,
    ThreadLine,
    ThreadRecord,
)
from autodeck.studio.models import ChangeEntry, ChangeLog, DeckArtifact, DiffItem, Slide
from autodeck.studio.views import (
    change_line,
    change_view,
    changes_view,
    clip,
    deck_outline,
    flat,
    messages_view,
    proposal_view,
    render_view,
    slide_detail,
    thread_summary,
)
from tests.studio.helpers import T0, T1, T2

FIXTURE_OUTLINE = """\
Deck `inference-readout`: Serving costs: pilot readout (4 slides)
Brief [decided]: audience: Northwind's digital leadership team | goal: Agree to move the \
assistant pilot onto the optimised serving stack | notes: Illustrative figures for the \
Phase 0 fixture; not client data.
Storyline [decided]:
  p1. Serving cost, not model quality, now limits the assistant
  p2. The optimised stack cut cost per request sharply in the pilot
  p3. Moving now is low risk and pays back within a quarter
Design concept [provisional]: Quiet and editorial: one strong number per slide, everything \
else recedes.
Design system: none
Slides:
  1. s1 [decided] serves p1 | placed | intent: Open with the decision we are asking for, \
set large on a dark ground.
     "Pilot readout" / "Serving cost now decides how far the assistant can go" / "What the \
optimised stack changed, and what we propose"
  2. s2 [decided] serves p2 | placed | intent: One large number, with what it means as a \
quiet line beside it.
     "Cost per request fell by 41% in the pilot" / "41%" / "Same answers, same latency \
target, on the same hardware."
  3. s3 [provisional] serves p2 | placed | intent: Show cost per request by week, with the \
switch-over week emphasised.
     "The drop came in the week we switched stacks and held" / chart: column, 6 categories, \
1 series / "Week 3 is the switch. Nothing else changed."
  4. s4 [provisional] serves p3 | placed | intent: Close on the proposal as three short \
steps, each in its own quiet panel.
     "We propose moving the assistant this quarter" / "Move all assistant traffic to the new \
stack" / "Keep the old stack warm for two weeks" / "Review cost and quality at the end of \
the quarter\""""

DIGEST_A, DIGEST_B, DIGEST_C = "a" * 64, "b" * 64, "c" * 64


def test_flat_and_clip() -> None:
    assert flat("  two\n lines\t here ") == "two lines here"
    assert clip("abcdef", 6) == "abcdef"
    assert clip("abcdefg", 6) == "abcde…"


def test_deck_outline_of_the_fixture_is_exact(base_deck: DeckArtifact) -> None:
    assert deck_outline(base_deck) == FIXTURE_OUTLINE


def test_deck_outline_of_an_empty_deck() -> None:
    deck = DeckArtifact(id="x", client="c", project="p")
    assert deck_outline(deck) == (
        "Deck `x`: (untitled) (0 slides)\n"
        "Brief: none\n"
        "Storyline [provisional]: none\n"
        "Design concept: none\n"
        "Design system: none\n"
        "Slides: none"
    )


def test_deck_outline_of_an_unplaced_slide_and_clipping(base_deck: DeckArtifact) -> None:
    data = base_deck.model_dump()
    data["slides"] = [
        {"id": "s9", "blocks": []},
        {"id": "s8", "blocks": [{"id": "t", "kind": "text", "text": "x" * 20}]},
    ]
    deck = DeckArtifact.model_validate(data)
    text = deck_outline(deck, max_text=10)
    assert "Deck `inference-readout`: Serving costs: pilot readout (2 slides)" in text
    assert text.endswith(
        "Slides:\n"
        "  1. s9 [provisional] serves - | no layout | intent: -\n"
        "     (no blocks)\n"
        "  2. s8 [provisional] serves - | no layout | intent: -\n"
        '     "xxxxxxxxx…"'
    )


def test_singular_counts(base_deck: DeckArtifact) -> None:
    data = base_deck.model_dump()
    data["slides"] = [data["slides"][2]]
    data["slides"][0]["blocks"][1]["chart"]["categories"] = ["Wk 1"]
    data["slides"][0]["blocks"][1]["chart"]["series"][0]["values"] = [7.1]
    data["slides"][0]["layout"]["elements"][1]["emphasis"] = []
    deck = DeckArtifact.model_validate(data)
    text = deck_outline(deck)
    assert "(1 slide)" in text and "chart: column, 1 category, 1 series" in text


def test_slide_detail(base_deck: DeckArtifact) -> None:
    text = slide_detail(base_deck, "s2")
    first, blank, rest = text.split("\n", 2)
    assert first == "Slide s2 (2 of 4) in deck inference-readout" and blank == ""
    assert Slide.model_validate_json(rest) == base_deck.slide("s2")


def _entry(
    entry_id: str, parent: str | None, before: str, after: str, **kw: Any
) -> ChangeEntry:
    data: dict[str, Any] = {
        "id": entry_id,
        "parent_id": parent,
        "diff": [DiffItem(path=f"title{entry_id}", kind="changed", before="a", after="b")],
        "instruction": "Make it\tshorter",
        "thread_id": "t0001",
        "layer": "composition",
        "model_id": "scripted",
        "created_at": T1,
        "before_digest": before,
        "after_digest": after,
    }
    data.update(kw)
    return ChangeEntry.model_validate(data)


def _log() -> ChangeLog:
    first = _entry("c0001", None, DIGEST_A, DIGEST_B)
    second = _entry("c0002", "c0001", DIGEST_B, DIGEST_C, undone=True, created_at=T2)
    return ChangeLog(
        artifact_id="deck", initial_digest=DIGEST_A, head="c0001", entries=[first, second]
    )


def test_change_line() -> None:
    log = _log()
    assert (
        change_line(log.entries[0])
        == "c0001 live | composition | scripted | t0001 | Make it shorter"
    )
    assert change_line(log.entries[1]).startswith("c0002 undone | ")


def test_changes_view_newest_first_with_undo_and_redo_targets() -> None:
    view = changes_view(_log())
    assert view["artifact_id"] == "deck" and view["head"] == "c0001"
    assert view["can_undo"] is True and view["can_redo"] is True
    assert [e["id"] for e in view["entries"]] == ["c0002", "c0001"]
    newest, oldest = view["entries"]
    assert newest["can_redo"] and not newest["can_undo"] and not newest["live"]
    assert oldest["can_undo"] and oldest["is_head"] and oldest["live"]
    assert oldest["lines"] == ["~ titlec0001: 'a' -> 'b'"] and oldest["truncated"] is False
    assert oldest["created_at"] == "2026-11-13T09:05:00+00:00"
    assert change_view(_log().entries[0], _log()) == oldest


def test_render_view() -> None:
    manifest = RenderManifest(
        digest="0123456789ab", slide_ids=["s1", "s2"], rendered=True, images=["a.png", "b.png"]
    )
    view = render_view(manifest, base="/api/x/renders")
    assert view is not None
    assert view["images"] == [
        "/api/x/renders/0123456789ab/1.png",
        "/api/x/renders/0123456789ab/2.png",
    ]
    assert render_view(None, base="/x") is None
    failed = render_view(
        RenderManifest(digest="0123456789ab", slide_ids=["s1"], rendered=False, note="no LO"),
        base="/x",
    )
    assert failed is not None and failed["images"] == [] and failed["note"] == "no LO"


def _lines() -> list[ThreadLine]:
    raw: list[dict[str, Any]] = [
        {"kind": "user", "turn_id": "u0001", "origin": "context", "text": "CONTEXT"},
        {"kind": "user", "turn_id": "u0001", "origin": "owner", "text": "Build it"},
        {
            "kind": "assistant",
            "turn_id": "u0001",
            "step": 1,
            "text": "Looking.",
            "tool_calls": [{"id": "k1", "name": "view_deck", "arguments": {}}],
            "model_id": "scripted",
        },
        {
            "kind": "tool",
            "turn_id": "u0001",
            "step": 1,
            "tool_call_id": "k1",
            "tool_name": "view_deck",
            "text": "outline",
            "summary": "viewed deck d (0 slides)",
        },
        {
            "kind": "assistant",
            "turn_id": "u0001",
            "step": 2,
            "text": "Done.",
            "model_id": "scripted",
        },
        {
            "kind": "turn_end",
            "turn_id": "u0001",
            "turn_kind": "talk",
            "stop_reason": "replied",
            "model_id": "scripted",
            "steps": 2,
        },
        {
            "kind": "note",
            "note": "proposal_dismissed",
            "ref": "p0001",
            "text": "The owner dismissed proposal p0001: x",
        },
        {"kind": "user", "turn_id": "u0002", "origin": "owner", "text": "Next"},
    ]
    return [
        THREAD_LINE.validate_python({**line, "seq": i, "created_at": T1})
        for i, line in enumerate(raw, start=1)
    ]


def test_messages_view_groups_a_turn_and_hides_context() -> None:
    view = messages_view(_lines())
    assert [item["type"] for item in view] == ["user", "assistant", "note", "user"]
    user, assistant, note, pending = view
    assert user["text"] == "Build it" and user["origin"] == "owner"
    assert assistant["texts"] == ["Looking.", "Done."]
    assert assistant["tools"] == [
        {"name": "view_deck", "summary": "viewed deck d (0 slides)", "error": False}
    ]
    assert assistant["kind"] == "talk" and assistant["stop_reason"] == "replied"
    assert assistant["model_id"] == "scripted" and assistant["change_ids"] == []
    assert note["ref"] == "p0001" and note["note"] == "proposal_dismissed"
    assert pending["text"] == "Next"
    assert "CONTEXT" not in str(view)


def test_thread_summary() -> None:
    record = ThreadRecord(
        id="t0001",
        client="c",
        project="p",
        created_at=T0,
        opening="fresh",
        context_digest=DIGEST_A,
        model_id="scripted",
    )
    summary = thread_summary(record, _lines())
    assert summary["turns"] == 1 and summary["preview"] == "Build it"
    assert summary["last_activity"] == "2026-11-13T09:05:00+00:00"
    empty = thread_summary(record, [])
    assert empty["turns"] == 0 and empty["preview"] == ""
    assert empty["last_activity"] == "2026-11-13T09:00:00+00:00"


def test_proposal_view(base_deck: DeckArtifact) -> None:
    record = ProposalRecord.model_validate(
        {
            "id": "p0001",
            "thread_id": "t0001",
            "turn_id": "u0002",
            "artifact_id": "deck",
            "summary": "Openings",
            "options": [
                {
                    "id": "A",
                    "label": "Number",
                    "text": "x",
                    "candidates": [
                        {"slide": base_deck.slides[1].model_dump(), "replaces": "s1"}
                    ],
                },
                {"id": "B", "label": "Question", "text": "y"},
                {
                    "id": "C",
                    "label": "Extra",
                    "text": "z",
                    "candidates": [
                        {
                            "slide": {**base_deck.slides[1].model_dump(), "id": "x"},
                            "insert_at": 3,
                        }
                    ],
                },
            ],
            "created_at": T1,
        }
    )
    view = proposal_view(record, previews={"A": ["/img/1.png"]})
    assert view["status"] == "open" and view["chosen"] is None and view["resolved_at"] is None
    assert view["options"][0]["slide_ids"] == ["s2"]
    assert view["options"][0]["placements"] == [
        {"slide_id": "s2", "replaces": "s1", "insert_at": None}
    ]
    assert view["options"][0]["applies"] == "Replaces slide s1"  # no deck: the id
    with_deck = proposal_view(record, deck=base_deck)
    assert with_deck["options"][0]["applies"] == "Replaces slide 1"
    assert with_deck["options"][1]["applies"] == ""
    assert with_deck["options"][2]["applies"] == "Inserts a slide at position 3"
    assert with_deck["options"][2]["placements"][0]["insert_at"] == 3
    gone = base_deck.model_copy(update={"slides": base_deck.slides[1:]})
    assert proposal_view(record, deck=gone)["options"][0]["applies"] == "Replaces slide s1"
    old = ProposalRecord.model_validate(
        {
            **record.model_dump(exclude={"options"}),
            "options": [
                {
                    "id": "A",
                    "label": "Old",
                    "text": "x",
                    "slides": [base_deck.slides[1].model_dump()],
                }
            ],
        }
    )
    assert "was not recorded" in proposal_view(old)["options"][0]["applies"]
    assert view["options"][0]["previews"] == ["/img/1.png"]
    assert view["options"][1]["previews"] == []


def test_slide_order_is_one_compact_line(base_deck: DeckArtifact) -> None:
    from autodeck.studio.views import slide_order

    line = slide_order(base_deck)
    assert line.startswith("1. s1 ") and "; 2. s2 " in line and "\n" not in line
    assert slide_order(base_deck.model_copy(update={"slides": []})) == "(no slides)"
