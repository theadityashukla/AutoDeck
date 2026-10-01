"""The art-direction pass (3b.7, B36)."""

from __future__ import annotations

import pytest

SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


@SCAFFOLD
def test_derive_mode_is_a_rule_on_face_content() -> None:
    """Diagram on the face → diagram_led (even with icons too); icons only → icon_anchored;
    neither → text_led; a diagram or icon only in speaker notes does not count."""
    raise NotImplementedError


@SCAFFOLD
def test_every_slide_gets_a_mode_with_its_source() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_a_communication_mode_pin_beats_the_rule_and_a_mismatch_is_noted() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_proposed_actions_go_through_try_action_and_rejections_are_recorded() -> None:
    """A plan with one valid SwapComponent, one swap onto a pinned component, and one
    AssignIcons with an unknown concept → one applied, two rejected with reasons."""
    raise NotImplementedError


@SCAFFOLD
def test_assign_icons_on_an_icon_pillars_slide_makes_it_render_and_icon_anchored() -> None:
    """icon_pillars slide with labels but no icons: before, `render_error` would be set;
    with an AssignIcons for the right count → renders, mode icon_anchored (rule).
    Skip with a clear reason if `icon_pillars` is not registered on this branch."""
    raise NotImplementedError


@SCAFFOLD
def test_a_model_error_still_assigns_rule_modes_and_says_why() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_a_mode_that_breaks_a_word_budget_is_assigned_and_reported_not_refused() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_facts_are_unchanged_on_every_path() -> None:
    """Fingerprint equality after: a full successful plan, a model error, an all-rejected
    plan, and a plan containing AssignIcons."""
    raise NotImplementedError


@SCAFFOLD
def test_the_prompt_lists_messages_slides_components_and_concepts_deterministically() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_a_missing_prompt_fails_before_the_model_is_called() -> None:
    raise NotImplementedError
