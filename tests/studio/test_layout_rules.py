"""Studio layout rules (`layout_rules`): a line through text or a chart, and text or a line
straddling a card's edge. Boundaries are tested on synthetic slides; the measured behaviour
is tested on slides the designer model really produced (`fixtures/designed_slides`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autodeck.design.layout_kit import Canvas
from autodeck.design.theme.tokens import DesignTokens, Palette
from autodeck.studio import layout_rules
from autodeck.studio.layout_rules import (
    LINE_THROUGH_CHART,
    LINE_THROUGH_TEXT,
    STRADDLE,
    check_layout_rules,
)
from autodeck.studio.models import Slide
from autodeck.studio.render_adapter import check_slide
from tests.studio.helpers import FONTS_AVAILABLE, dev_tokens

pytestmark = pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "designed_slides"

# ---------------------------------------------------------------------------
# Real slides
# ---------------------------------------------------------------------------

#: Every designed slide whose rules fire, judged true by looking at its render (see the
#: Phase 2-3 doc). All others were looked at and are clean.
EXPECTED: dict[str, set[tuple[str, str]]] = {
    "real_run/1-serve-before-buy": {(LINE_THROUGH_TEXT, "unmeasured")},
    "real_run/4-approve-benchmark": {
        (LINE_THROUGH_TEXT, "capacity_label"),
        (STRADDLE, "shape 3"),
    },
    "bench/sol-s7-case-none": {(LINE_THROUGH_TEXT, "cost-figure")},
    "bench/luna-s5-caching-demand-curve": {(LINE_THROUGH_TEXT, "hero21")},
    "bench/sol-s2-inference-demand-curve": {(LINE_THROUGH_CHART, "share_chart")},
}


def _load(path: Path) -> tuple[Slide, DesignTokens]:
    data = json.loads(path.read_text(encoding="utf-8"))
    base = dev_tokens()
    merged = base.palette.model_dump()
    merged.update(data["palette"])
    tokens = base.model_copy(update={"palette": Palette.model_validate(merged)})
    return Slide.model_validate(data["slide"]), tokens


def _fixture_names() -> list[str]:
    return sorted(
        str(p.relative_to(FIXTURES).with_suffix("")) for p in FIXTURES.rglob("*.json")
    )


def test_there_are_thirty_four_designed_slides() -> None:
    assert len(_fixture_names()) == 34


@pytest.mark.parametrize("name", _fixture_names())
def test_designed_slide_findings(name: str) -> None:
    slide, tokens = _load(FIXTURES / f"{name}.json")
    found = {(f.check, f.block_id) for f in check_layout_rules(slide, tokens)}
    assert found == EXPECTED.get(name, set())


@pytest.mark.parametrize(
    "name", ["real_run/1-serve-before-buy", "real_run/4-approve-benchmark"]
)
def test_the_two_known_flaws_fail_check_slide(name: str) -> None:
    """The real run reported these clean; `check_slide` (what every caller uses) now fails."""
    slide, tokens = _load(FIXTURES / f"{name}.json")
    checks = {f.check for f in check_slide(slide, tokens)}
    assert checks & {LINE_THROUGH_TEXT, STRADDLE}


def test_finding_messages_say_what_to_do() -> None:
    slide, tokens = _load(FIXTURES / "real_run/4-approve-benchmark.json")
    messages = {f.check: f.message for f in check_layout_rules(slide, tokens)}
    assert "move it clear" in messages[LINE_THROUGH_TEXT]
    assert "wholly" in messages[STRADDLE]


# ---------------------------------------------------------------------------
# Synthetic boundaries (slide 960 x 540 pt; frames in percent)
# ---------------------------------------------------------------------------

W, H = 960.0, 540.0


def pct(x: float, y: float, w: float, h: float) -> dict[str, float]:
    return {"x": x / W * 100, "y": y / H * 100, "w": w / W * 100, "h": h / H * 100}


def text(block_id: str, frame: dict[str, float], **kw: Any) -> dict[str, Any]:
    return {
        "type": "text",
        "block_id": block_id,
        "frame": frame,
        "role": "display",
        "size_pt": 40,
        "color": "dk1",
        **kw,
    }


def shape(kind: str, frame: dict[str, float], **kw: Any) -> dict[str, Any]:
    kw.setdefault("fill", "lt2") if kind != "line" else kw.setdefault("line", "dk2")
    return {"type": "shape", "shape": kind, "frame": frame, **kw}


def slide_of(elements: list[dict[str, Any]], words: str = "HELLO") -> Slide:
    if not any(e["type"] == "text" for e in elements):
        # every block must be placed: park the word in the top right corner, clear of all
        corner = text("w", pct(860, 10, 80, 20), role="caption", size_pt=10)
        elements = [*elements, corner]
    return Slide.model_validate(
        {
            "id": "t",
            "intent": "test",
            "blocks": [{"id": "w", "kind": "text", "text": words}],
            "layout": {"background": "lt1", "elements": elements},
        }
    )


TOKENS = dev_tokens()
CANVAS = Canvas(TOKENS)
FRAME = pct(100, 200, 400, 80)


def ink() -> layout_rules.Box:
    probe = slide_of([text("w", FRAME)])
    element = probe.layout.elements[0]  # type: ignore[union-attr]
    box = layout_rules.frame_box(CANVAS, element.frame)
    return layout_rules._ink_lines(CANVAS, element, "HELLO", box)[0]


def hline(y: float, x: float = 50, length: float = 700) -> dict[str, Any]:
    return shape("line", pct(x, y - 1, length, 2), line_pt=1.5)


def rules_found(elements: list[dict[str, Any]]) -> set[str]:
    return {f.check for f in check_layout_rules(slide_of(elements), TOKENS)}


def test_a_line_through_the_middle_of_text_is_found() -> None:
    box = ink()
    assert rules_found([text("w", FRAME), hline(box.y + box.height / 2)]) == {LINE_THROUGH_TEXT}


def test_a_line_at_the_foot_of_the_text_is_an_underline_not_a_finding() -> None:
    box = ink()
    assert rules_found([text("w", FRAME), hline(box.bottom + 2)]) == set()
    assert rules_found([text("w", FRAME), hline(box.bottom)]) == set()


def test_a_line_above_the_text_is_not_a_finding() -> None:
    box = ink()
    assert rules_found([text("w", FRAME), hline(box.y - 4)]) == set()


def test_a_line_that_ends_where_the_text_starts_only_touches() -> None:
    box = ink()
    y = box.y + box.height / 2
    assert rules_found([text("w", FRAME), hline(y, x=10, length=box.x - 10)]) == set()
    assert rules_found([text("w", FRAME), hline(y, x=10, length=box.x - 10 + 20)]) == {
        LINE_THROUGH_TEXT
    }


def test_a_line_in_the_empty_part_of_a_wide_frame_is_not_a_finding() -> None:
    """The word is ~150pt wide in a 400pt frame; a rule to the right of it is clear."""
    box = ink()
    assert box.width < 250
    y = box.y + box.height / 2
    assert rules_found([text("w", FRAME), hline(y, x=box.right + 20, length=200)]) == set()


def test_a_vertical_line_through_text_is_found_and_beside_it_is_not() -> None:
    box = ink()
    through = shape("line", pct(box.x + box.width / 2, 150, 2, 200), line_pt=1.5)
    beside = shape("line", pct(box.right + 15, 150, 2, 200), line_pt=1.5)
    assert rules_found([text("w", FRAME), through]) == {LINE_THROUGH_TEXT}
    assert rules_found([text("w", FRAME), beside]) == set()


def test_a_thin_filled_rect_is_a_rule_too() -> None:
    box = ink()
    bar = shape("rect", pct(50, box.y + box.height / 2, 700, 1.5), fill="dk2")
    assert rules_found([text("w", FRAME), bar]) == {LINE_THROUGH_TEXT}


def test_a_line_across_a_chart_is_found_and_along_its_edge_is_not() -> None:
    chart = {
        "id": "c",
        "kind": "chart",
        "chart": {
            "chart_type": "bar",
            "title": "t",
            "categories": ["a", "b"],
            "series": [{"name": "s", "values": [1.0, 2.0]}],
            "x_axis_label": "x",
            "y_axis_label": "y",
        },
    }
    frame = pct(100, 100, 400, 300)
    visual = {"type": "chart", "block_id": "c", "frame": frame}

    def found(y: float) -> set[str]:
        s = Slide.model_validate(
            {
                "id": "t",
                "intent": "t",
                "blocks": [chart],
                "layout": {"background": "lt1", "elements": [visual, hline(y)]},
            }
        )
        return {f.check for f in check_layout_rules(s, TOKENS)}

    assert found(250) == {LINE_THROUGH_CHART}
    assert found(402) == set()
    assert found(98) == set()


# -- straddle ---------------------------------------------------------------


def test_text_wholly_inside_a_card_is_clean() -> None:
    card = shape("rounded_rect", pct(60, 170, 520, 150))
    assert rules_found([card, text("w", FRAME)]) == set()


def test_text_wholly_outside_a_card_is_clean() -> None:
    card = shape("rect", pct(600, 170, 300, 150))
    assert rules_found([card, text("w", FRAME)]) == set()


def test_text_across_a_card_edge_is_found() -> None:
    box = ink()
    card = shape("rect", pct(box.x + 60, 170, 400, 150))
    assert rules_found([card, text("w", FRAME)]) == {STRADDLE}


def test_text_ending_on_the_edge_within_tolerance_is_clean() -> None:
    box = ink()
    card = shape("rect", pct(box.right - 2, 170, 300, 150))
    assert rules_found([card, text("w", FRAME)]) == set()
    card = shape("rect", pct(box.right - 10, 170, 300, 150))
    assert rules_found([card, text("w", FRAME)]) == {STRADDLE}


def test_text_across_a_band_top_is_found_by_its_ink_not_its_frame() -> None:
    """The frame (200 to 280) is cut by a band from 270, the ink (above 262) is not."""
    box = ink()
    clear = shape("rect", pct(0, box.bottom + 5, 960, 100))
    assert box.bottom + 5 < 280
    assert rules_found([clear, text("w", FRAME)]) == set()
    cut = shape("rect", pct(0, box.bottom - 10, 960, 100))
    assert rules_found([cut, text("w", FRAME)]) == {STRADDLE}


def test_a_full_bleed_background_shape_is_not_a_ground_to_straddle() -> None:
    ground = shape("rect", pct(0, 0, 960, 540))
    assert rules_found([ground, text("w", FRAME)]) == set()


def test_a_shape_drawn_after_the_text_is_not_judged() -> None:
    """Such a shape paints over the text; v2's `hidden_text` reports that."""
    box = ink()
    card = shape("rect", pct(box.x + 60, 170, 400, 150))
    assert rules_found([text("w", FRAME), card]) == set()


def test_nested_cards_each_judge_on_their_own() -> None:
    box = ink()
    panel = shape("rect", pct(40, 150, 800, 250))
    inner = shape("rounded_rect", pct(60, 170, 520, 150), fill="lt1")
    assert rules_found([panel, inner, text("w", FRAME)]) == set()
    cutting = shape("rounded_rect", pct(box.x + 60, 170, 300, 150), fill="lt1")
    assert rules_found([panel, cutting, text("w", FRAME)]) == {STRADDLE}


def test_a_thin_vertical_bar_is_a_rule_not_a_ground_for_text() -> None:
    bar = shape("rect", pct(150, 100, 2, 300), fill="dk2")
    assert rules_found([bar, text("w", FRAME)]) == {LINE_THROUGH_TEXT}


def test_a_line_that_runs_into_a_band_is_found() -> None:
    band = shape("rect", pct(0, 400, 960, 140))
    assert rules_found([band, shape("line", pct(480, 70, 2, 380), line_pt=1.5)]) == {STRADDLE}


def test_a_line_that_ends_at_a_band_or_lies_wholly_inside_it_is_clean() -> None:
    band = shape("rect", pct(0, 400, 960, 140))
    assert rules_found([band, shape("line", pct(480, 70, 2, 332), line_pt=1.5)]) == set()
    assert rules_found([band, shape("line", pct(480, 410, 2, 100), line_pt=1.5)]) == set()


def test_a_line_that_ends_inside_a_card_it_started_in_is_clean() -> None:
    card = shape("rect", pct(100, 100, 400, 300))
    assert rules_found([card, hline(200, x=120, length=300)]) == set()
    assert rules_found([card, hline(200, x=50, length=300)]) == {STRADDLE}


def test_text_that_is_not_text_blocks_does_not_break_the_rules() -> None:
    assert check_layout_rules(slide_of([shape("rect", pct(0, 0, 960, 540))]), TOKENS) == []


def test_a_slide_without_a_layout_has_no_rule_findings() -> None:
    slide = slide_of([text("w", FRAME)]).model_copy(update={"layout": None})
    assert check_layout_rules(slide, TOKENS) == []
