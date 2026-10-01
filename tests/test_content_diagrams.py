"""B37: the content writer authors process-flow diagrams, and A5 fences their labels."""

from __future__ import annotations

import pytest

SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


@SCAFFOLD
def test_a_proposed_flow_with_cited_and_framed_steps_resolves_to_a_diagram_block() -> None:
    """Steps: one `claim` (quote resolves), two `framing` (stage_name) → a `Block(kind=
    "diagram")` whose ProcessFlowSpec has the three steps in order, the claim's citation
    resolved to the real span, `transition` '' → None."""
    raise NotImplementedError


@SCAFFOLD
def test_one_unresolvable_step_drops_the_whole_diagram_with_a_reason() -> None:
    """A claim step whose quote does not resolve → no diagram block; `rejections` names the
    block and the step. No partial flow is ever produced."""
    raise NotImplementedError


@SCAFFOLD
def test_status_and_payload_must_agree() -> None:
    """status='claim' without claim; status='framing' with framing_reason ''; status=
    'framing' with a claim → each drops the block with a reason."""
    raise NotImplementedError


@SCAFFOLD
def test_non_contiguous_orders_drop_the_block_via_the_ir_validator() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_write_slide_fills_a_framework_diagram_and_a_timeline_slot() -> None:
    """A scripted ContentModel returning a diagram block for each component's diagram slot →
    `write_slide` returns it, budgets checked, no incomplete_slots for `diagram`."""
    raise NotImplementedError


@SCAFFOLD
def test_a5_fences_diagram_labels_titles_and_transitions() -> None:
    """A framed step label "40% cheaper than Oracle" (category_name), a title with a
    superlative, and a transition with a number → each is a blocking demotion of that
    diagram block in `lint_framing`, and `assess_render_safety` blocks the render."""
    raise NotImplementedError


@SCAFFOLD
def test_clean_framed_labels_pass_a5() -> None:
    """ "Discovery", "Pilot", "Scale" as stage_name labels → no findings;
    `text_blocks_checked` counts the diagram once."""
    raise NotImplementedError


@SCAFFOLD
def test_the_prompt_file_documents_the_diagram_schema() -> None:
    """`prompts/content.md` mentions `kind: "diagram"`, `status`, `framing_reason` and the
    five LabelReason values — so the prompt and the schema cannot silently drift."""
    raise NotImplementedError
