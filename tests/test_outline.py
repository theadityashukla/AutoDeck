"""The outline agent and the GATE 1 review surface.

Two properties carry the most weight:

- **The outline has nowhere to put prose.** `SlideDraft` has no text field, which is a
  stronger guarantee than a prompt asking for none — an outline header would reach the
  content stage looking like a settled decision, and it would have arrived with no citation
  through a door A1 does not watch.
- **Neither module repairs drift from the brief.** The outline agent fixes structural
  impossibilities and reports even those; the review reports and fixes nothing. An agent
  that quietly repaired its own output would hide exactly what GATE 1's reviewer is there
  to see.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.agents.outline import (
    CATALOG,
    OutlineDraft,
    OutlineError,
    SlideDraft,
    build_outline,
)
from autodeck.audit.gate1 import review_outline
from autodeck.ir.models import DeckBrief, KeyMessage, LayoutPin, OpenRisk

PROMPT = Path("prompts/outline.md")


class Scripted:
    def __init__(self, draft: OutlineDraft) -> None:
        self.draft = draft
        self.prompts: list[str] = []

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        self.system = system
        return self.draft


class Broken:
    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider down")


def brief(**overrides) -> DeckBrief:  # type: ignore[no-untyped-def]
    payload: dict[str, object] = {
        "run_id": "northwind-2026-08",
        "objective": "Decide whether to serve better or buy more GPUs.",
        "audience": "CTO and two engineering leads",
        "key_messages": [
            KeyMessage(
                id="km1", text="KV-cache waste bounds throughput.", evidence_status="supported"
            ),
            KeyMessage(
                id="km2",
                text="Quantisation is the cheapest first phase.",
                evidence_status="supported",
            ),
        ],
        "approved_by": "aditya",
    }
    payload.update(overrides)
    return DeckBrief(**payload)  # type: ignore[arg-type]


def slide(
    slide_id: str = "s1",
    *,
    component: str = "bullets_supporting",
    messages: list[str] | None = None,
    intent: str = "Establish that the constraint is memory, not compute.",
    role: str = "evidence",
    **extra,  # type: ignore[no-untyped-def]
) -> SlideDraft:
    return SlideDraft(
        id=slide_id,
        narrative_role=role,
        component=component,
        intent=intent,
        message_ids=messages if messages is not None else ["km1"],
        **extra,
    )


def outline_for(the_brief: DeckBrief, *slides: SlideDraft, notes: str | None = None):  # type: ignore[no-untyped-def]
    model = Scripted(OutlineDraft(slides=list(slides), notes=notes))
    result = build_outline(
        the_brief,
        model,
        client="northwind-retail",
        project="llm-inference-efficiency",
        theme_ref="knowledge/clients/northwind-retail/theme/tokens.json",
        component_lib_version="0.1.0",
        prompt_path=PROMPT,
    )
    return result, model


# ---------------------------------------------------------------------------
# No prose, and a signed brief
# ---------------------------------------------------------------------------


def test_a_slide_draft_has_nowhere_to_put_prose() -> None:
    """Stronger than asking the model not to write any."""
    for forbidden in ("text", "header", "body", "blocks"):
        assert forbidden not in SlideDraft.model_fields


def test_the_outline_carries_no_blocks() -> None:
    result, _ = outline_for(
        brief(), slide("s1", messages=["km1"]), slide("s2", messages=["km2"])
    )
    assert all(not s.blocks and not s.speaker_notes for s in result.deck.slides)
    assert all(s.intent for s in result.deck.slides)


def test_an_unsigned_brief_is_refused() -> None:
    """An outline built from an unsigned draft is an outline nobody agreed to (A7)."""
    with pytest.raises(OutlineError, match="no approver"):
        outline_for(brief(approved_by=None), slide())


def test_a_provider_failure_is_reported_not_swallowed() -> None:
    with pytest.raises(OutlineError, match="outline generation failed"):
        build_outline(
            brief(),
            Broken(),  # type: ignore[arg-type]
            client="c",
            project="p",
            theme_ref="t",
            component_lib_version="0.1.0",
            prompt_path=PROMPT,
        )


def test_a_missing_prompt_is_a_hard_error(tmp_path: Path) -> None:
    with pytest.raises(OutlineError, match="no inline fallback"):
        build_outline(
            brief(),
            Scripted(OutlineDraft(slides=[slide()])),  # type: ignore[arg-type]
            client="c",
            project="p",
            theme_ref="t",
            component_lib_version="0.1.0",
            prompt_path=tmp_path / "nope.md",
        )


# ---------------------------------------------------------------------------
# Structural correction, always reported
# ---------------------------------------------------------------------------


def test_an_unknown_component_is_dropped_and_reported() -> None:
    """It would otherwise fail at render time, three phases away, as a missing template."""
    result, _ = outline_for(
        brief(),
        slide("s1", messages=["km1"]),
        slide("s2", component="mega_hero_banner", messages=["km2"]),
    )
    assert [s.id for s in result.deck.slides] == ["s1"]
    assert any("not in the catalog" in c for c in result.corrections)


def test_a_fabricated_message_id_is_dropped_and_reported() -> None:
    """GATE 1's coverage check must not be satisfiable by an invented id."""
    result, _ = outline_for(brief(), slide("s1", messages=["km1", "km99"]))
    assert result.deck.slides[0].message_ids == ["km1"]
    assert any("km99" in c for c in result.corrections)


def test_duplicate_slide_ids_are_renamed() -> None:
    result, _ = outline_for(
        brief(), slide("s1", messages=["km1"]), slide("s1", messages=["km2"])
    )
    assert len({s.id for s in result.deck.slides}) == 2


def test_an_outline_of_only_bad_slides_fails_loudly() -> None:
    with pytest.raises(OutlineError, match="no usable slides"):
        outline_for(brief(), slide("s1", component="nonsense"))


def test_every_catalog_component_is_accepted() -> None:
    for component in CATALOG:
        result, _ = outline_for(brief(), slide("s1", component=component, messages=["km1"]))
        assert result.deck.slides[0].component == component


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------


def test_an_honoured_pin_records_no_deviation() -> None:
    pinned = brief(
        layout_pins=[LayoutPin(message_id="km1", target="component", value="big_number")]
    )
    result, _ = outline_for(pinned, slide("s1", component="big_number", messages=["km1"]))
    assert result.deck.slides[0].pin_deviation is None


def test_an_unhonoured_pin_is_recorded_even_when_the_model_says_nothing() -> None:
    """The case worth catching is the pin the model dropped without noticing — precisely
    the case where it will not have written an explanation."""
    pinned = brief(
        layout_pins=[LayoutPin(message_id="km1", target="component", value="big_number")]
    )
    result, _ = outline_for(
        pinned, slide("s1", component="bullets_supporting", messages=["km1"])
    )

    deviation = result.deck.slides[0].pin_deviation
    assert deviation is not None
    assert "big_number" in deviation
    assert "bullets_supporting" in deviation


def test_the_models_own_explanation_is_kept_alongside() -> None:
    pinned = brief(
        layout_pins=[LayoutPin(message_id="km1", target="component", value="big_number")]
    )
    result, _ = outline_for(
        pinned,
        slide(
            "s1",
            component="bullets_supporting",
            messages=["km1"],
            pin_deviation="No single figure carries this message.",
        ),
    )
    assert "No single figure" in (result.deck.slides[0].pin_deviation or "")


def test_a_diagram_kind_pin_is_not_reported_as_a_deviation() -> None:
    """The outline assigns components, not diagram geometry — that is Phase 3a's engine.
    Reporting it here would be a false alarm every time."""
    pinned = brief(
        layout_pins=[LayoutPin(message_id="km1", target="diagram_kind", value="two_by_two")]
    )
    result, _ = outline_for(
        pinned, slide("s1", component="framework_diagram", messages=["km1"])
    )
    assert result.deck.slides[0].pin_deviation is None


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def test_weak_evidence_is_flagged_to_the_model_at_the_point_of_use() -> None:
    weak = brief(
        key_messages=[
            KeyMessage(id="km1", text="Cost falls 90%.", evidence_status="thin"),
        ],
        open_risks=[OpenRisk(message_id="km1", description="one source", accepted_by="aditya")],
    )
    _, model = outline_for(weak, slide("s1", messages=["km1"]))
    assert "do not give this slide a component that" in model.prompts[0]


def test_open_risks_reach_the_model() -> None:
    risky = brief(
        key_messages=[
            KeyMessage(id="km1", text="Cost falls 90%.", evidence_status="unsupported")
        ],
        open_risks=[
            OpenRisk(
                message_id="km1",
                description="Nothing measures currency cost.",
                accepted_by="aditya",
                mitigation="State as an assumption.",
            )
        ],
    )
    _, model = outline_for(risky, slide("s1", messages=["km1"]))
    assert "do not drop them" in model.prompts[0]
    assert "State as an assumption" in model.prompts[0]


def test_the_catalog_is_offered_to_the_model() -> None:
    _, model = outline_for(brief(), slide("s1", messages=["km1"]))
    assert "closing_cta" in model.prompts[0]


# ---------------------------------------------------------------------------
# GATE 1 review
# ---------------------------------------------------------------------------


def reviewed(the_brief: DeckBrief, *slides: SlideDraft):  # type: ignore[no-untyped-def]
    result, _ = outline_for(the_brief, *slides)
    return review_outline(result.deck, the_brief)


def test_a_complete_outline_passes_the_mechanical_checks() -> None:
    report = reviewed(brief(), slide("s1", messages=["km1"]), slide("s2", messages=["km2"]))
    assert report.mechanical_checks_pass
    assert report.blocking == []


def test_an_uncovered_key_message_blocks() -> None:
    report = reviewed(brief(), slide("s1", messages=["km1"]))
    assert not report.mechanical_checks_pass
    assert any("km2" in f.detail for f in report.blocking)


def test_a_missing_must_include_blocks() -> None:
    report = reviewed(
        brief(must_include=["cost per conversation"]),
        slide("s1", messages=["km1"]),
        slide("s2", messages=["km2"]),
    )
    assert any(f.check == "must_include" for f in report.blocking)


def test_a_present_must_include_passes() -> None:
    report = reviewed(
        brief(must_include=["cost per conversation"]),
        slide("s1", messages=["km1"], intent="Show cost per conversation today."),
        slide("s2", messages=["km2"]),
    )
    assert not any(f.check == "must_include" for f in report.blocking)


def test_a_must_avoid_appearing_blocks() -> None:
    report = reviewed(
        brief(must_avoid=["10x"]),
        slide("s1", messages=["km1"], intent="Lead with the 10x headline."),
        slide("s2", messages=["km2"]),
    )
    assert any(f.check == "must_avoid" for f in report.blocking)


def test_a_flagged_pin_deviation_is_advisory_not_blocking() -> None:
    """The criterion is "honoured, OR its deviation explicitly flagged"."""
    pinned = brief(
        layout_pins=[LayoutPin(message_id="km1", target="component", value="big_number")]
    )
    report = reviewed(
        pinned,
        slide("s1", component="bullets_supporting", messages=["km1"]),
        slide("s2", messages=["km2"]),
    )
    pin_findings = [f for f in report.findings if f.check == "layout pin"]
    assert pin_findings and all(f.severity == "advisory" for f in pin_findings)
    assert report.mechanical_checks_pass


def test_a_pin_on_an_unserved_message_blocks() -> None:
    pinned = brief(layout_pins=[LayoutPin(message_id="km2", target="component", value="quote")])
    report = reviewed(pinned, slide("s1", messages=["km1"]))
    assert any(f.check == "layout pin" and f.severity == "blocking" for f in report.blocking)


def test_going_over_the_length_target_blocks() -> None:
    report = reviewed(
        brief(length_target=1), slide("s1", messages=["km1"]), slide("s2", messages=["km2"])
    )
    assert any(f.check == "length" and f.severity == "blocking" for f in report.findings)


def test_coming_in_under_target_is_only_advisory() -> None:
    """The prompt tells the outline to come in under rather than drop a key message to hit
    a number; blocking a short deck would push against that, and coverage is checked
    separately anyway."""
    report = reviewed(
        brief(length_target=9), slide("s1", messages=["km1"]), slide("s2", messages=["km2"])
    )
    length = [f for f in report.findings if f.check == "length"]
    assert length and length[0].severity == "advisory"


def test_a_dropped_open_risk_blocks() -> None:
    risky = brief(
        key_messages=[
            KeyMessage(id="km1", text="a", evidence_status="supported"),
            KeyMessage(id="km2", text="Cost falls 90%.", evidence_status="unsupported"),
        ],
        open_risks=[OpenRisk(message_id="km2", description="no source", accepted_by="aditya")],
    )
    report = reviewed(risky, slide("s1", messages=["km1"]))
    assert any(f.check == "open risk" for f in report.blocking)


def test_a_confident_component_on_weak_evidence_is_advisory() -> None:
    """A8: a big_number slide is a claim of confidence."""
    weak = brief(
        key_messages=[KeyMessage(id="km1", text="Cost falls 90%.", evidence_status="thin")],
        open_risks=[OpenRisk(message_id="km1", description="one source", accepted_by="aditya")],
    )
    report = reviewed(weak, slide("s1", component="big_number", messages=["km1"]))

    overstated = [f for f in report.findings if f.check == "component overstates evidence"]
    assert overstated and overstated[0].severity == "advisory"
    assert report.mechanical_checks_pass  # advisory does not block


def test_unprobed_messages_are_surfaced() -> None:
    """'Nobody looked' reads far too much like 'it's fine' — only this report separates
    them for the reviewer."""
    drafted = brief(key_messages=[KeyMessage(id="km1", text="a", evidence_status="unprobed")])
    report = reviewed(drafted, slide("s1", messages=["km1"]))
    assert any(f.check == "unprobed messages" for f in report.advisory)


def test_the_report_says_it_is_not_the_gate() -> None:
    """A clean mechanical run must not read as an approval."""
    report = reviewed(brief(), slide("s1", messages=["km1"]), slide("s2", messages=["km2"]))
    text = report.render()
    assert "no check here answers that" in text
    assert "autodeck approve" in text


def test_reviewing_against_another_runs_brief_is_refused() -> None:
    result, _ = outline_for(brief(), slide("s1", messages=["km1"]))
    with pytest.raises(ValueError, match="a GATE 1 review compares"):
        review_outline(result.deck, brief(run_id="someone-else"))
