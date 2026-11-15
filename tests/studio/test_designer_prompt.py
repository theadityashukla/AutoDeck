# ruff: noqa: E501
"""Task 23.6: the designer's prompt and user message (`designer_prompt.py`), moved from the
bench (`bench/slides/run.py`), and the prompt file itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.studio.design import DesignSystem, default_design_system
from autodeck.studio.designer_prompt import (
    NO_DIRECTION,
    PLACEHOLDERS,
    brief_user_text,
    designer_system_prompt,
    master_text,
    palette_text,
    vocabulary_text,
)
from autodeck.studio.errors import StudioConfigError
from autodeck.studio.models import SlideBrief
from autodeck.studio.prompt import DESIGNER_PROMPT_PATH
from tests.studio.helpers import dev_tokens, flow_brief, flow_draft

S2_TEXT = """# Slide brief
Slide id: s2
Header: Quantisation alone cuts serving cost by 38%

What the slide must make the audience conclude:
The single biggest saving comes from one technique: 8-bit weights take monthly serving cost from $412k to $255k without changing the answers.

## Content (the only content you may put on the slide)

Points:
- 8-bit weights instead of 16-bit
- Same answer quality on 2,000 test questions

Key figures:
- 38%: lower monthly serving cost

Chart (bar), categories: Before, After
- Monthly serving cost ($k): 412, 255
Emphasise: After

Notes (what matters; not for the slide):
38% is the hero; the before and after is quieter evidence.

## Design system
Name: Demand curve
Concept: The assistant's traffic over a day is what the bill follows, so each slide is built along one line on a night-blue ground, with peach marking the one thing to look at.
Rules:
- The background is night blue; each slide has one dominant horizontal line.
- Peach marks exactly one thing per slide; everything else is cool grey or blue.
- No boxes around text; at least a third of the slide stays empty.

Design this slide and call write_slide."""


def demand_curve() -> DesignSystem:
    draft = flow_draft("Demand curve")
    return DesignSystem(id="demand-curve", version=1, marker="decided", **draft.model_dump())


def test_the_brief_user_text_is_exact() -> None:
    assert brief_user_text("s2", flow_brief("s2"), demand_curve()) == S2_TEXT


def test_an_empty_brief_and_the_default_system() -> None:
    brief = SlideBrief(header="Thank you", intent="Close the talk.")
    text = brief_user_text("end", brief, default_design_system(dev_tokens()))
    assert text == (
        "# Slide brief\nSlide id: end\nHeader: Thank you\n\n"
        "What the slide must make the audience conclude:\nClose the talk.\n\n"
        "## Content (the only content you may put on the slide)\n\n"
        "(nothing beyond the header)\n\n## Design system\n"
        f"{NO_DIRECTION}\n\nDesign this slide and call write_slide."
    )
    figure_only = SlideBrief.model_validate(
        {"header": "h", "intent": "i", "content": {"figures": [{"value": "38%"}]}}
    )
    assert "Key figures:\n- 38%\n" in brief_user_text("x", figure_only, demand_curve())


def test_the_palette_text_lists_slots_roles_background_and_pairs() -> None:
    text = palette_text(demand_curve())
    lines = text.split("\n")
    assert lines[0].startswith("- dk1: #0B1420 -- ink:")
    assert lines[3].startswith("- lt2: #0F1D30 -- night:")
    assert "Background: lt2" in lines
    assert "Text pairs that pass the contrast check: lt1 on lt2, dk2 on lt2," in text
    assert lines[-1] == "Colour tokens are used by name (for example `accent1`), never as hex."
    default = palette_text(default_design_system(dev_tokens()))
    assert "- lt1: #FFFFFF\n" in default  # no role, no " -- "


def test_master_and_vocabulary_are_the_benchs() -> None:
    master = master_text(dev_tokens())
    assert master.startswith("Slide: 960 x 540 pt (16:9).")
    assert "Minimum text size 10pt" in master
    assert master.split("\n")[-1].startswith("Source band: none.")
    vocabulary = vocabulary_text()
    assert vocabulary.startswith("Slide:\n  id: str")
    assert "speaker_notes" not in vocabulary.split("Block:")[0]
    assert "source_note" not in vocabulary
    assert "ColorToken: dk1, lt1, dk2, lt2, accent1" in vocabulary
    assert "icon `glyph_id` must be one of:" in vocabulary


def test_the_system_prompt_fills_every_placeholder(tmp_path: Path) -> None:
    text = designer_system_prompt(dev_tokens(), demand_curve())
    assert not any(p in text for p in PLACEHOLDERS)
    assert "- lt2: #0F1D30 -- night" in text and "Slide: 960 x 540 pt" in text
    broken = tmp_path / "designer.md"
    broken.write_text("no placeholders here", encoding="utf-8")
    with pytest.raises(StudioConfigError):
        designer_system_prompt(dev_tokens(), demand_curve(), template_path=broken)


def test_the_designer_prompt_keeps_what_the_bench_proved() -> None:
    text = " ".join(DESIGNER_PROMPT_PATH.read_text(encoding="utf-8").split())
    for phrase in (
        "Why a generic slide is a failure here",
        "one line of `display`, `title` or `heading` text is about 1.4 times its point size",
        "Nothing hides text.",
        "The header must appear word for word in one text block",
        "Every chart block uses the brief's chart data exactly",
        "the slot named as the ground is the slide `background`",
        "{{MASTER}}",
        "{{PALETTE}}",
        "{{VOCABULARY}}",
    ):
        assert phrase in text, phrase
    assert "This is a test" not in text
