"""Task 23.5: the Phase 2-3 edits (`edits.py`): briefs, composition results, the design-system
reference, swaps, and small text changes that keep the brief in step."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autodeck.studio import edits
from autodeck.studio.errors import EditError
from autodeck.studio.models import (
    DEFAULT_SYSTEM_ID,
    ComposedFrom,
    CompositionFailure,
    DeckArtifact,
    DesignSystemRef,
    Slide,
    SlideBrief,
    brief_digest,
    composition_status,
    effective_system,
)
from autodeck.studio.serialise import dump_artifact
from tests.studio.helpers import flow_brief, flow_designed, flow_draft, load_fixture_deck

NEW_HEADER = "Quantisation cuts the bill by 38%"


def designed_slide(slide_id: str = "s2", design: str = "default") -> Slide:
    data = flow_designed(slide_id, design)["slide"]
    b = flow_brief(slide_id)
    return Slide(
        id=slide_id, intent=b.intent, brief=b, blocks=data["blocks"], layout=data["layout"]
    )


def composed_for(
    b: SlideBrief, system: tuple[str, int] = (DEFAULT_SYSTEM_ID, 1)
) -> ComposedFrom:
    return ComposedFrom(
        brief_digest=brief_digest(b),
        system_id=system[0],
        system_version=system[1],
        model_id="scripted/designer",
    )


def deck_with_fresh_s2() -> DeckArtifact:
    deck = DeckArtifact(id="d", client="c", project="p")
    deck, _, _ = edits.set_slide_brief(deck, "s2", flow_brief("s2"))
    return edits.apply_composition(
        deck, "s2", designed_slide("s2"), composed_for(flow_brief("s2"))
    )


def state(deck: DeckArtifact, slide_id: str = "s2") -> str:
    return composition_status(deck.slide(slide_id), effective_system(deck)).state


def test_set_slide_brief_creates_and_updates_without_touching_the_design() -> None:
    deck = load_fixture_deck()
    before = dump_artifact(deck)
    new, is_new, position = edits.set_slide_brief(deck, "s9", flow_brief("s2"), position=2)
    assert (is_new, position) == (True, 2) and dump_artifact(deck) == before
    slide = new.slide("s9")
    assert slide.brief == flow_brief("s2") and slide.intent == flow_brief("s2").intent
    assert slide.blocks == [] and slide.layout is None and slide.marker == "provisional"
    assert new.slide_ids()[1] == "s9"
    appended, _, at = edits.set_slide_brief(deck, "s10", flow_brief("s3"), serves=["p1"])
    assert at == 5 and appended.slide("s10").serves == ["p1"]

    fresh = deck_with_fresh_s2()
    updated, is_new, _ = edits.set_slide_brief(fresh, "s2", flow_brief("s3"))
    assert not is_new
    assert updated.slide("s2").blocks == fresh.slide("s2").blocks
    assert updated.slide("s2").composed == fresh.slide("s2").composed
    assert state(updated) == "stale"
    with pytest.raises(EditError, match="1 .. 2"):
        edits.set_slide_brief(fresh, "s7", flow_brief("s1"), position=3)
    with pytest.raises(ValidationError):
        edits.set_slide_brief(deck, "s11", flow_brief("s1"), serves=["p99"])


def test_apply_composition_keeps_the_slides_own_fields_and_clears_a_failure() -> None:
    deck = DeckArtifact(id="d", client="c", project="p")
    deck, _, _ = edits.set_slide_brief(deck, "s2", flow_brief("s2"))
    failure = CompositionFailure(
        brief_digest=brief_digest(flow_brief("s2")),
        system_id=DEFAULT_SYSTEM_ID,
        system_version=1,
        model_id="scripted/designer",
        attempts=4,
        findings=["[text_fit] hero: too small"],
    )
    deck = edits.record_compose_failure(deck, "s2", failure)
    assert state(deck) == "failed" and deck.slide("s2").layout is None
    data = deck.model_dump()
    data["slides"][0]["speaker_notes"] = "Say the number first."
    data["slides"][0]["marker"] = "decided"
    deck = DeckArtifact.model_validate(data)
    composed = composed_for(flow_brief("s2"))
    done = edits.apply_composition(deck, "s2", designed_slide("s2"), composed)
    slide = done.slide("s2")
    assert slide.composed == composed and slide.compose_failure is None
    assert slide.speaker_notes == "Say the number first." and slide.marker == "decided"
    assert slide.layout == designed_slide("s2").layout
    assert state(done) == "fresh"


def test_a_failure_keeps_the_previous_design() -> None:
    fresh = deck_with_fresh_s2()
    failure = CompositionFailure(
        brief_digest=brief_digest(flow_brief("s2")),
        system_id="demand-curve",
        system_version=1,
        model_id="m",
        attempts=4,
    )
    failed = edits.record_compose_failure(fresh, "s2", failure)
    assert failed.slide("s2").layout == fresh.slide("s2").layout
    assert failed.slide("s2").composed == fresh.slide("s2").composed
    with pytest.raises(EditError):
        edits.record_compose_failure(load_fixture_deck(), "s1", failure)


def test_apply_composition_refuses_a_brief_that_changed_meanwhile() -> None:
    fresh = deck_with_fresh_s2()
    rebriefed, _, _ = edits.set_slide_brief(fresh, "s2", flow_brief("s3"))
    with pytest.raises(EditError, match="changed while it was being composed"):
        edits.apply_composition(
            rebriefed, "s2", designed_slide("s2"), composed_for(flow_brief("s2"))
        )
    with pytest.raises(EditError):
        edits.apply_composition(
            fresh, "s9", designed_slide("s2"), composed_for(flow_brief("s2"))
        )


def test_set_design_system_makes_designed_slides_stale_by_fingerprint() -> None:
    fresh = deck_with_fresh_s2()
    draft = flow_draft("Demand curve")
    ref = DesignSystemRef(id="demand-curve", version=1, marker="decided", palette=draft.palette)
    moved = edits.set_design_system(fresh, ref)
    assert moved.design_system == ref and moved.slides == fresh.slides
    assert state(moved) == "stale"


def test_swap_slides() -> None:
    deck = load_fixture_deck()
    assert edits.swap_slides(deck, "s1", "s3").slide_ids() == ["s3", "s2", "s1", "s4"]
    with pytest.raises(EditError):
        edits.swap_slides(deck, "s1", "s9")
    with pytest.raises(EditError):
        edits.swap_slides(deck, "s1", "s1")


def test_retitle_keeps_a_fresh_slide_fresh() -> None:
    fresh = deck_with_fresh_s2()
    new = edits.retitle_slide(fresh, "s2", f"  {NEW_HEADER} ")
    slide = new.slide("s2")
    assert slide.brief is not None and slide.brief.header == NEW_HEADER
    assert slide.block("header").text == NEW_HEADER
    assert state(new) == "fresh"
    assert slide.composed is not None
    assert slide.composed.brief_digest == brief_digest(slide.brief)


def test_retitle_of_a_stale_or_undesigned_slide_changes_only_the_brief() -> None:
    fresh = deck_with_fresh_s2()
    ref = DesignSystemRef(
        id="demand-curve", version=1, palette=flow_draft("Demand curve").palette
    )
    stale = edits.set_design_system(fresh, ref)
    new = edits.retitle_slide(stale, "s2", NEW_HEADER)
    assert new.slide("s2").block("header").text == NEW_HEADER
    assert new.slide("s2").composed == stale.slide("s2").composed
    assert state(new) == "stale"
    bare = DeckArtifact(id="d", client="c", project="p")
    bare, _, _ = edits.set_slide_brief(bare, "s1", flow_brief("s1"))
    assert edits.retitle_slide(bare, "s1", "New").slide("s1").brief.header == "New"  # type: ignore[union-attr]
    with pytest.raises(EditError, match="no brief"):
        edits.retitle_slide(load_fixture_deck(), "s1", "New")
    with pytest.raises(EditError):
        edits.retitle_slide(fresh, "s2", "two\nlines")


def test_set_designed_text_keeps_the_brief_in_step() -> None:
    fresh = deck_with_fresh_s2()
    new = edits.set_designed_text(fresh, "s2", "p1", "8-bit weights, not 16-bit")
    slide = new.slide("s2")
    assert slide.brief is not None
    assert slide.brief.content.points[0] == "8-bit weights, not 16-bit"
    assert state(new) == "fresh"
    header = edits.set_designed_text(fresh, "s2", "header", "Quantisation\ncuts cost by 38%")
    assert header.slide("s2").brief.header == "Quantisation cuts cost by 38%"  # type: ignore[union-attr]
    assert header.slide("s2").block("header").text == "Quantisation\ncuts cost by 38%"
    label = edits.set_designed_text(fresh, "s2", "hero-label", "lower cost each month")
    assert label.slide("s2").brief == fresh.slide("s2").brief
    assert state(label) == "fresh"
    plain = edits.set_designed_text(load_fixture_deck(), "s2", "number", "38%")
    assert plain == edits.set_block_text(
        load_fixture_deck(), slide_id="s2", block_id="number", text="38%"
    )
    with pytest.raises(EditError, match="chart"):
        edits.set_designed_text(fresh, "s2", "chart", "x")
