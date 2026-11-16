"""Phase 2-3 models (lead-owned, written in full): briefs, the palette, composition
fingerprints and the staleness rule."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from autodeck.studio.models import (
    DEFAULT_SYSTEM_ID,
    STALE_BRIEF,
    STALE_SYSTEM,
    BriefChart,
    ComposedFrom,
    CompositionFailure,
    DeckArtifact,
    DesignPalette,
    DesignSystemRef,
    Slide,
    SlideBrief,
    brief_digest,
    composition_status,
    deck_composition,
    effective_system,
)

PALETTE = {
    "dk1": "#0b1420",
    "lt1": "FFFFFF",
    "dk2": "#A8B8CF",
    "lt2": "#0F1D30",
    "accent1": "#F2A57E",
    "accent2": "#7FA6D8",
    "accent3": "#2B4466",
    "accent4": "#1A2E4A",
    "accent5": "#24395A",
    "accent6": "#5A7396",
}


def brief(**changes: Any) -> SlideBrief:
    data: dict[str, Any] = {
        "header": "Quantisation alone cuts serving cost by 38%",
        "intent": "One technique carries the saving.",
        "content": {
            "points": ["8-bit weights instead of 16-bit"],
            "figures": [{"value": "38%", "label": "lower serving cost"}],
            "chart": {
                "kind": "bar",
                "categories": ["Before", "After"],
                "series": [{"name": "Cost ($k)", "values": [412, 255]}],
                "emphasis": ["After"],
            },
        },
    }
    data.update(changes)
    return SlideBrief.model_validate(data)


LAYOUT = {
    "background": "lt1",
    "elements": [
        {
            "type": "text",
            "block_id": "h",
            "frame": {"x": 6, "y": 10, "w": 80, "h": 20},
            "role": "title",
        }
    ],
}


def designed(b: SlideBrief, *, system: tuple[str, int] = (DEFAULT_SYSTEM_ID, 1)) -> Slide:
    return Slide(
        id="s2",
        intent=b.intent,
        brief=b,
        blocks=[{"id": "h", "kind": "text", "text": b.header}],  # type: ignore[list-item]
        layout=LAYOUT,  # type: ignore[arg-type]
        composed=ComposedFrom(
            brief_digest=brief_digest(b),
            system_id=system[0],
            system_version=system[1],
            model_id="scripted/designer",
        ),
    )


def test_palette_normalises_hex_and_refuses_bad_values() -> None:
    palette = DesignPalette.model_validate(PALETTE)
    assert palette.dk1 == "0B1420" and palette.lt1 == "FFFFFF"
    assert palette.hex("accent1") == "F2A57E"
    with pytest.raises(KeyError):
        palette.hex("hyperlink")
    with pytest.raises(ValidationError, match="six-digit hex"):
        DesignPalette.model_validate({**PALETTE, "lt2": "#12345"})
    with pytest.raises(ValidationError):
        DesignPalette.model_validate({k: v for k, v in PALETTE.items() if k != "accent6"})


def test_a_design_system_ref_carries_its_palette_and_old_refs_still_load() -> None:
    ref = DesignSystemRef(id="demand-curve", version=2, palette=PALETTE)  # type: ignore[arg-type]
    assert ref.palette is not None and ref.palette.lt2 == "0F1D30"
    assert DesignSystemRef.model_validate({"id": "x", "version": 1}).palette is None


def test_brief_validation() -> None:
    with pytest.raises(ValidationError, match="one non-blank line"):
        brief(header="Two\nlines")
    with pytest.raises(ValidationError):
        brief(header="x" * 161)
    with pytest.raises(ValidationError, match="emphasis"):
        BriefChart.model_validate(
            {
                "kind": "bar",
                "categories": ["A"],
                "series": [{"name": "n", "values": [1]}],
                "emphasis": ["B"],
            }
        )
    with pytest.raises(ValidationError, match="one value per category"):
        BriefChart.model_validate(
            {"kind": "line", "categories": ["A", "B"], "series": [{"name": "n", "values": [1]}]}
        )
    with pytest.raises(ValidationError):
        brief(content={"points": ["  "]})
    with pytest.raises(ValidationError):
        brief(extra="no")


def test_brief_digest_is_a_fingerprint_of_every_field() -> None:
    a = brief()
    assert brief_digest(a) == brief_digest(brief())
    assert len(brief_digest(a)) == 64
    assert brief_digest(a) != brief_digest(brief(notes="38% is the hero"))
    changed = brief(content={"points": ["8-bit weights instead of 16-bit."]})
    assert brief_digest(a) != brief_digest(changed)


def test_slide_invariants_for_briefs_and_composition() -> None:
    b = brief()
    with pytest.raises(ValidationError, match="intent must equal"):
        Slide(id="s1", intent="something else", brief=b)
    with pytest.raises(ValidationError, match="composed slide has a brief and a layout"):
        Slide(
            id="s1",
            intent=b.intent,
            brief=b,
            composed=ComposedFrom(
                brief_digest=brief_digest(b),
                system_id="default",
                system_version=1,
                model_id="m",
            ),
        )
    failure = CompositionFailure(
        brief_digest=brief_digest(b),
        system_id="default",
        system_version=1,
        model_id="m",
        attempts=4,
        findings=["[text_fit] h: too small"],
    )
    with pytest.raises(ValidationError, match="needs a brief"):
        Slide(id="s1", compose_failure=failure)
    with pytest.raises(ValidationError, match="one non-blank line"):
        CompositionFailure.model_validate({**failure.model_dump(), "findings": ["a\nb"]})
    assert Slide(id="s1", intent=b.intent, brief=b).layout is None


def test_staleness_rule() -> None:
    b = brief()
    default = (DEFAULT_SYSTEM_ID, 1)
    assert composition_status(Slide(id="x"), default).state == "unbriefed"
    assert composition_status(Slide(id="s2", intent=b.intent, brief=b), default).state == (
        "undesigned"
    )
    fresh = designed(b)
    assert composition_status(fresh, default).state == "fresh"
    moved = composition_status(fresh, ("demand-curve", 1))
    assert (moved.state, moved.reasons) == ("stale", (STALE_SYSTEM,))
    b2 = brief(notes="new")
    rebriefed = fresh.model_copy(update={"brief": b2})
    assert composition_status(rebriefed, default).reasons == (STALE_BRIEF,)
    both = composition_status(rebriefed, ("demand-curve", 1))
    assert both.reasons == (STALE_BRIEF, STALE_SYSTEM)


def test_a_failure_counts_only_for_the_current_brief_and_system() -> None:
    b = brief()
    failure = CompositionFailure(
        brief_digest=brief_digest(b),
        system_id="demand-curve",
        system_version=1,
        model_id="m",
        attempts=4,
    )
    slide = designed(b).model_copy(update={"compose_failure": failure})
    assert composition_status(slide, ("demand-curve", 1)).state == "failed"
    # Recorded for another system: ignored, the slide reads by its composition.
    assert composition_status(slide, (DEFAULT_SYSTEM_ID, 1)).state == "fresh"
    assert composition_status(slide, ("demand-curve", 2)).state == "stale"


def test_effective_system_and_deck_composition() -> None:
    b = brief()
    deck = DeckArtifact(
        id="d",
        client="c",
        project="p",
        slides=[designed(b), Slide(id="s9")],
    )
    assert effective_system(deck) == (DEFAULT_SYSTEM_ID, 1)
    assert {k: v.state for k, v in deck_composition(deck).items()} == {
        "s2": "fresh",
        "s9": "unbriefed",
    }
    moved = deck.model_copy(
        update={"design_system": DesignSystemRef(id="demand-curve", version=1)}
    )
    assert effective_system(moved) == ("demand-curve", 1)
    assert deck_composition(moved)["s2"].state == "stale"
