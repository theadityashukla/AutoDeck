"""Components 13-15: `framework_diagram`, `timeline`, `chart_focus`.

SCAFFOLD (Opus). Sonnet: implement each body, then DELETE every `@_SCAFFOLD` marker and
the `_SCAFFOLD` definition. The markers are strict, so a test that starts passing with its
marker still on fails the suite — no scaffold marker can survive the fill.

What is distinctive about these three, and therefore what the tests are for: none of them
draws its main content itself. Two hand the body to `diagrams.place_diagram` and one to
`charts.place_chart`. So the tests pin the *seams* — what the component must not do on the
engine's behalf — rather than re-testing the engines, which have their own suites.
"""

from __future__ import annotations

import pytest

_SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")

NAMES = ("framework_diagram", "timeline", "chart_focus")


@_SCAFFOLD
@pytest.mark.parametrize("name", NAMES)
def test_each_renders_its_preview_example(name: str) -> None:
    """`<module>.render` draws `preview.EXAMPLES[name]` onto a blank dev-token slide
    without raising."""
    raise NotImplementedError


@_SCAFFOLD
@pytest.mark.parametrize("name", NAMES)
def test_the_registry_answers_for_each(name: str) -> None:
    """`spec_for(name, tokens)` returns a spec, and `name` is not in
    `components_missing_previews()` — its golden PNG is committed."""
    raise NotImplementedError


@_SCAFFOLD
@pytest.mark.parametrize("name", NAMES)
def test_an_overlong_headline_is_rejected_before_render(name: str) -> None:
    """`check_overflow` reports the `headline` slot for a headline far past its budget,
    without any render happening."""
    raise NotImplementedError


@_SCAFFOLD
@pytest.mark.parametrize("name", ["framework_diagram", "timeline"])
def test_the_diagram_title_is_never_drawn(name: str) -> None:
    """Give the example's `DiagramSpec` the title "UNMISTAKABLE-DIAGRAM-TITLE", render, and
    assert that string appears in no shape's text. The headline is the slide's one voice."""
    raise NotImplementedError


@_SCAFFOLD
def test_timeline_refuses_a_diagram_that_is_not_a_sequence() -> None:
    """A `two_by_two` `DiagramSpec` in `TimelineContent` makes `timeline.render` raise
    `ValueError` whose message names "two_by_two". A timeline must never draw a 2x2."""
    raise NotImplementedError


@_SCAFFOLD
@pytest.mark.parametrize("name", ["framework_diagram", "timeline"])
def test_diagram_components_group_nothing_and_embed_no_picture(name: str) -> None:
    """Saved PPTX: zero `<p:grpSp>` on the slide, zero `ppt/media/` parts, and at least one
    `<a:schemeClr` — every node individually selectable and theme-coloured (D10/D11)."""
    raise NotImplementedError


@_SCAFFOLD
def test_chart_focus_draws_one_chart_and_one_source_line() -> None:
    """Exactly one chart graphic frame on the slide, zero `ppt/media/` parts, and the
    source text appears exactly once — the chart's own, not a second `frame.caption`."""
    raise NotImplementedError


@_SCAFFOLD
def test_chart_focus_reserves_the_takeaway_before_the_chart() -> None:
    """A takeaway far past one line raises `LayoutOverflowError` from `chart_focus.render`
    rather than being drawn with the chart squeezed to fit around it."""
    raise NotImplementedError


@_SCAFFOLD
def test_a_node_label_under_its_word_budget_can_still_overflow_at_render() -> None:
    """Build a valid `DiagramSpec` whose node label is within `max_label_words` but uses
    words long enough not to fit its box, and assert `framework_diagram.render` raises
    `LayoutOverflowError`. Pins the documented limitation: diagram labels are protected
    physically only at render, not by `check_overflow`."""
    raise NotImplementedError


@_SCAFFOLD
def test_all_fifteen_components_are_registered_and_previewed() -> None:
    """`known_components()` has exactly the fifteen PHASE-3A names and
    `components_missing_previews()` is empty — the phase's exit criterion, asserted."""
    raise NotImplementedError


@_SCAFFOLD
@pytest.mark.parametrize("name", ["framework_diagram", "timeline"])
def test_diagram_led_examples_pass_the_grammar_lints(name: str) -> None:
    """The preview example, as a slide, produces no blocking D13 finding from
    `autodeck.design.grammar` in `diagram_led` mode (<=1 diagram, <=60 words)."""
    raise NotImplementedError
