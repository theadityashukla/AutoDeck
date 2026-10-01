"""`render/trial.try_action`: one acceptance rule for every presentation pass."""

from __future__ import annotations

import pytest

SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


@SCAFFOLD
def test_an_acceptable_action_returns_the_new_deck_and_leaves_the_input_alone() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_an_ir_rejection_propagates_unchanged() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_a_render_failure_becomes_does_not_render_with_the_reason_prefix() -> None:
    """Monkeypatch `render_deck` in trial's namespace to raise `LayoutOverflowError` →
    `DoesNotRender`, `str(exc).startswith(DOES_NOT_RENDER_PREFIX)`, `__cause__` set."""
    raise NotImplementedError


@SCAFFOLD
def test_environment_failures_propagate() -> None:
    """`FontNotFoundError` and `RenderBlocked` from the trial render are not rejections."""
    raise NotImplementedError


@SCAFFOLD
def test_a_new_grammar_finding_is_a_regression_and_a_fixed_one_is_fine() -> None:
    """A `SwapComponent` that moves a slide with a diagram into a second-diagram situation,
    or an `AssignIcons` that creates an icon+chart+diagram pileup → `GrammarRegression`
    naming the finding. An action that removes a finding is accepted."""
    raise NotImplementedError


@SCAFFOLD
def test_the_aesthetic_loop_uses_try_action() -> None:
    """Monkeypatch `autodeck.render.trial.try_action` to record calls; run the aesthetic loop
    with one proposed action → it was called once. (One acceptance rule, not two.)"""
    raise NotImplementedError
