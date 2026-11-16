"""The one-sentence description of a change-log entry (`change_summary.py`), built from real
edits and real diffs, for every kind of change Phase 2-3 makes."""

from __future__ import annotations

from datetime import UTC, datetime

from autodeck.studio import edits
from autodeck.studio.change_summary import change_summary, humanise_id
from autodeck.studio.compose import draft_system
from autodeck.studio.diff import diff_artifacts
from autodeck.studio.models import (
    ChangeEntry,
    ComposedFrom,
    CompositionFailure,
    DeckArtifact,
    Slide,
    brief_digest,
)
from tests.studio.helpers import flow_brief, flow_designed, flow_draft

NOW = datetime(2026, 1, 1, tzinfo=UTC)
NUMBERS = {"s1": 1, "s2": 2, "s3": 3}


def entry(before: DeckArtifact, after: DeckArtifact) -> ChangeEntry:
    return ChangeEntry(
        id="c0001",
        diff=diff_artifacts(before, after),
        instruction="x",
        thread_id="t0001",
        layer="direction",
        model_id="m",
        created_at=NOW,
        before_digest="a" * 64,
        after_digest="b" * 64,
    )


def briefed() -> DeckArtifact:
    deck = DeckArtifact(id="d", client="c", project="p")
    for sid in ("s1", "s2", "s3"):
        deck, _, _ = edits.set_slide_brief(deck, sid, flow_brief(sid))
    return deck


def composed_from(sid: str, system_id: str = "default", version: int = 1) -> ComposedFrom:
    return ComposedFrom(
        brief_digest=brief_digest(flow_brief(sid)),
        system_id=system_id,
        system_version=version,
        model_id="m",
    )


def designed(deck: DeckArtifact, sid: str, system_id: str = "default") -> DeckArtifact:
    brief = flow_brief(sid)
    data = flow_designed(sid)["slide"]
    slide = Slide(
        id=sid, intent=brief.intent, brief=brief, blocks=data["blocks"], layout=data["layout"]
    )
    return edits.apply_composition(deck, sid, slide, composed_from(sid, system_id))


def summary(before: DeckArtifact, after: DeckArtifact, **kw: object) -> str:
    return change_summary(entry(before, after), numbers=NUMBERS, **kw)  # type: ignore[arg-type]


def test_a_slide_added_with_a_brief_and_without() -> None:
    empty = DeckArtifact(id="d", client="c", project="p")
    one, _, _ = edits.set_slide_brief(empty, "s1", flow_brief("s1"))
    header = flow_brief("s1").header
    assert summary(empty, one) == f"Wrote the brief for slide 1: {header}"
    plain = edits.upsert_slide(empty, Slide(id="s9", intent="x"))[0]
    assert change_summary(entry(empty, plain)) == "Added slide s9"
    assert change_summary(entry(plain, empty)) == "Removed slide s9"


def test_the_first_design_and_a_redesign_in_a_new_system() -> None:
    deck = briefed()
    first = designed(deck, "s2")
    assert summary(deck, first) == "Designed slide 2"
    ref = draft_system(flow_draft("Demand curve")).model_copy(update={"id": "demand-curve"})
    moved = edits.set_design_system(first, ref.ref(marker="decided"))
    named = {("demand-curve", 1): "Demand curve"}
    namer = lambda sid, v: named.get((sid, v))  # noqa: E731
    redone = designed(moved, "s2", "demand-curve")
    assert summary(moved, redone, system_name=namer) == "Redesigned slide 2 in Demand curve"
    assert summary(moved, redone) == "Redesigned slide 2 in Demand curve"  # slug fallback
    # a design adopted by name
    assert summary(first, moved, system_name=namer) == (
        "Adopted the design Demand curve (version 1)"
    )
    assert (
        summary(
            moved,
            edits.set_design_system(
                moved, ref.ref(marker="decided").model_copy(update={"marker": "provisional"})
            ),
        )
        == "Marked the design provisional"
    )


def test_a_failed_composition_is_described_as_such() -> None:
    deck = designed(briefed(), "s3")
    failure = CompositionFailure(
        brief_digest=brief_digest(flow_brief("s3")),
        system_id="default",
        system_version=1,
        model_id="m",
        attempts=4,
        findings=["[text_fit] x"],
    )
    failed = edits.record_compose_failure(deck, "s3", failure)
    assert summary(deck, failed) == "Slide 3 could not be designed after 4 attempts"


def test_briefs_retitles_and_wording() -> None:
    deck = designed(briefed(), "s2")
    retitled = edits.retitle_slide(deck, "s2", "Quantisation cuts the bill by 38%")
    old = flow_brief("s2").header
    assert (
        summary(deck, retitled)
        == f"Retitled slide 2: {old} → Quantisation cuts the bill by 38%"
    )
    changed = flow_brief("s2").model_copy(update={"notes": "Different notes."})
    rebriefed, _, _ = edits.set_slide_brief(deck, "s2", changed)
    assert summary(deck, rebriefed) == "Updated the brief for slide 2"
    block = next(b for b in deck.slide("s2").blocks if b.id == "hero-label")
    reworded = edits.set_designed_text(deck, "s2", block.id, "a different label")
    assert summary(deck, reworded) == "Reworded text on slide 2"


def test_order_markers_and_the_deck_level_parts() -> None:
    deck = briefed()
    assert summary(deck, edits.swap_slides(deck, "s2", "s3")) == "Swapped slides 2 and 3"
    moved = edits.move_slide(deck, slide_id="s3", to_index=0)
    assert summary(deck, moved) == "Moved slide 3 to position 1"
    three = edits.move_slide(deck, slide_id="s1", to_index=2)
    assert summary(deck, three) == "Moved slide 1 to position 3"
    marked = edits.set_slide_marker(deck, slide_id="s2", marker="decided")
    assert summary(deck, marked) == "Marked slide 2 as decided"
    assert summary(deck, edits.remove_slide(deck, slide_id="s2")) == "Removed slide s2"


def test_several_things_are_joined_and_capped() -> None:
    deck = briefed()
    after = deck
    for sid in ("s1", "s2", "s3"):
        after = designed(after, sid)
    text = summary(deck, after)
    assert text == "Designed slide 1; Designed slide 2; Designed slide 3"
    ref = draft_system(flow_draft("Demand curve")).model_copy(update={"id": "demand-curve"})
    more = edits.swap_slides(
        edits.set_design_system(after, ref.ref(marker="decided")), "s1", "s2"
    )
    assert summary(after, more) == (
        "Adopted the design Demand curve (version 1); Swapped slides 1 and 2"
    )
    assert summary(deck, more) == (
        "Adopted the design Demand curve (version 1); Swapped slides 1 and 2; "
        "Designed slide 1; and 2 more"
    )


def test_humanise_id() -> None:
    assert humanise_id("demand-curve") == "Demand curve"
    assert humanise_id("serving_control-room") == "Serving control room"
