"""`render/trial.try_action`: one acceptance rule for every presentation pass."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from autodeck.design.fonts import FontNotFoundError
from autodeck.design.layout_kit import LayoutOverflowError
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.actions import (
    ActionRejected,
    AssignIcons,
    SetAccent,
    SetCommunicationMode,
    UnknownAddressError,
    fact_fingerprint,
)
from autodeck.ir.models import Block, Deck
from autodeck.pipeline.orchestrator import RenderBlocked
from autodeck.render import trial
from autodeck.render.qa.aesthetic import catalog_slot_lookup, library_concept_lookup
from autodeck.render.trial import (
    DOES_NOT_RENDER_PREFIX,
    DoesNotRender,
    GrammarRegression,
    try_action,
)
from tests.test_aesthetic import FakeCritic, FakeRasteriser, _deck, reply, tokens_for

SLOTS = catalog_slot_lookup()
GLYPHS = library_concept_lookup()


def _try(deck: Deck, action: object, tmp_path: Path, **overrides: Any) -> Deck:
    kwargs: dict[str, Any] = {
        "tokens": tokens_for(),
        "scratch": tmp_path / "trial.pptx",
        "slots_of": SLOTS,
        "glyph_for": GLYPHS,
    }
    kwargs.update(overrides)
    return try_action(deck, action, **kwargs)


def _wordy(deck: Deck, words: int, *, mode: str | None) -> Deck:
    """`deck` with slide s1's first `points` block replaced by `words` words of framing."""
    copy = deck.model_copy(deep=True)
    slide = copy.slides[0]
    slide.blocks = [
        Block(id=b.id, kind="framing", slot=b.slot, text=" ".join(["word"] * words))
        if b.id == "s1-point-a"
        else b
        for b in slide.blocks
    ]
    slide.communication_mode = mode  # type: ignore[assignment]
    return copy


def test_an_acceptable_action_returns_the_new_deck_and_leaves_the_input_alone(
    tmp_path: Path,
) -> None:
    deck = _deck()
    before = deck.model_dump()

    result = _try(deck, SetAccent(slide_id="s1", accent="accent2"), tmp_path)

    assert result.slides[0].style.accent == "accent2"
    assert deck.model_dump() == before
    assert fact_fingerprint(result) == fact_fingerprint(deck)
    assert (tmp_path / "trial.pptx").exists(), "the trial render went to the scratch path"


def test_an_ir_rejection_propagates_unchanged(tmp_path: Path) -> None:
    with pytest.raises(UnknownAddressError, match="unknown slide_id 'nope'") as raised:
        _try(_deck(), SetAccent(slide_id="nope", accent="accent2"), tmp_path)
    assert type(raised.value) is UnknownAddressError
    assert not (tmp_path / "trial.pptx").exists(), "nothing was rendered for a refused action"


def test_a_render_failure_becomes_does_not_render_with_the_reason_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Monkeypatch `render_deck` in trial's namespace to raise `LayoutOverflowError` ->
    `DoesNotRender`, `str(exc).startswith(DOES_NOT_RENDER_PREFIX)`, `__cause__` set."""
    overflow = LayoutOverflowError("headline does not fit")

    def failing(deck: Deck, *, tokens: DesignTokens, out_path: Path) -> Any:
        raise overflow

    monkeypatch.setattr(trial, "render_deck", failing)

    with pytest.raises(DoesNotRender) as raised:
        _try(_deck(), SetAccent(slide_id="s1", accent="accent2"), tmp_path)

    assert isinstance(raised.value, ActionRejected)
    assert str(raised.value).startswith(DOES_NOT_RENDER_PREFIX)
    assert str(raised.value) == "does not render: LayoutOverflowError: headline does not fit"
    assert raised.value.__cause__ is overflow


@pytest.mark.parametrize(
    "environment_failure",
    [
        FontNotFoundError("the regular face of font family 'Inter' was not found"),
        RenderBlocked("r1", ["a claim is contradicted"]),
    ],
)
def test_environment_failures_propagate(
    environment_failure: Exception, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`FontNotFoundError` and `RenderBlocked` from the trial render are not rejections."""

    def failing(deck: Deck, *, tokens: DesignTokens, out_path: Path) -> Any:
        raise environment_failure

    monkeypatch.setattr(trial, "render_deck", failing)

    with pytest.raises(type(environment_failure)) as raised:
        _try(_deck(), SetAccent(slide_id="s1", accent="accent2"), tmp_path)
    assert not isinstance(raised.value, ActionRejected)


def test_a_new_grammar_finding_is_a_regression_and_a_fixed_one_is_fine(tmp_path: Path) -> None:
    """Word budgets are the one D13 lint the actions can move (via the mode): a 70-word
    slide is within `text_led`'s 90 but over `icon_anchored`'s 50, so setting the mode
    one way adds a finding, naming it, and the other way removes one. A finding that is
    already there and stays is not new."""
    within = _wordy(_deck(), 70, mode="text_led")
    over = _wordy(_deck(), 70, mode="icon_anchored")

    with pytest.raises(GrammarRegression, match="word budget") as raised:
        _try(within, SetCommunicationMode(slide_id="s1", mode="icon_anchored"), tmp_path)
    assert isinstance(raised.value, ActionRejected)
    assert "slide s1" in str(raised.value)

    fixed = _try(over, SetCommunicationMode(slide_id="s1", mode="text_led"), tmp_path)
    assert fixed.slides[0].communication_mode == "text_led"

    # Equal is accepted: the finding was there before and this action did not add it.
    unchanged = _try(over, SetAccent(slide_id="s1", accent="accent2"), tmp_path)
    assert unchanged.slides[0].style.accent == "accent2"


def test_an_assign_icons_pileup_is_a_regression(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A slide that already carries a chart and a diagram, given an icon, is D13's named
    pileup. No registered component places all three, so the render is stubbed out here and
    only the grammar step is under test."""
    from tests.test_actions import make_chart, make_diagram

    deck = _deck()
    deck.slides[0].blocks += [
        Block(id="chart1", kind="chart", slot="chart", chart=make_chart()),
        Block(id="diagram1", kind="diagram", slot="diagram", diagram=make_diagram()),
    ]
    monkeypatch.setattr(trial, "render_deck", lambda deck, *, tokens, out_path: None)

    def slots_of(component: str) -> frozenset[str] | None:
        slots = SLOTS(component)
        return None if slots is None else slots | {"icon", "chart", "diagram"}

    with pytest.raises(GrammarRegression, match="pileup"):
        _try(
            deck,
            AssignIcons(slide_id="s1", slot="icon", concepts=["growth"]),
            tmp_path,
            slots_of=slots_of,
        )


def test_advisory_findings_do_not_reject(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Six icons on a slide that already has a few blocks trips the advisory concept count;
    only blocking findings reject, or a complete `icon_pillars` slide could never be built."""
    deck = _deck()
    monkeypatch.setattr(trial, "render_deck", lambda deck, *, tokens, out_path: None)

    def slots_of(component: str) -> frozenset[str] | None:
        slots = SLOTS(component)
        return None if slots is None else slots | {"icon"}

    result = _try(
        deck,
        AssignIcons(slide_id="s1", slot="icon", concepts=["growth"] * 6),
        tmp_path,
        slots_of=slots_of,
    )
    assert len([b for b in result.slides[0].blocks if b.kind == "icon"]) == 6


def test_the_aesthetic_loop_uses_try_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Monkeypatch `autodeck.render.trial.try_action` to record calls; run the aesthetic loop
    with one proposed action -> it was called once. (One acceptance rule, not two.)"""
    from autodeck.render.qa import aesthetic

    monkeypatch.setattr(aesthetic, "run_deterministic_qa", lambda pptx, tokens: [])
    calls: list[object] = []
    real = trial.try_action

    def recording(deck: Deck, action: object, **kwargs: Any) -> Deck:
        calls.append(action)
        return real(deck, action, **kwargs)

    monkeypatch.setattr(trial, "try_action", recording)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("test prompt", encoding="utf-8")
    action = SetAccent(slide_id="s1", accent="accent2")

    result = aesthetic.run_aesthetic_loop(
        _deck(),
        tokens=tokens_for(),
        model=FakeCritic(reply(5.0, action), reply(9.0)),
        work_dir=tmp_path / "work",
        rasterise=FakeRasteriser(),
        prompt_path=prompt,
    )

    assert calls == [action]
    assert result.iterations[0].applied == (action,)


def test_a_grammar_regression_is_a_rejection_in_the_aesthetic_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The loop gains the grammar check: an action that adds a finding is recorded as
    rejected with the `GrammarRegression` reason, like any other rejection."""
    from autodeck.render.qa import aesthetic

    monkeypatch.setattr(aesthetic, "run_deterministic_qa", lambda pptx, tokens: [])
    prompt = tmp_path / "prompt.md"
    prompt.write_text("test prompt", encoding="utf-8")
    deck = _wordy(_deck(), 70, mode="text_led")
    action = SetCommunicationMode(slide_id="s1", mode="icon_anchored")

    result = aesthetic.run_aesthetic_loop(
        deck,
        tokens=tokens_for(),
        model=FakeCritic(reply(5.0, action)),
        work_dir=tmp_path / "work",
        rasterise=FakeRasteriser(),
        prompt_path=prompt,
    )

    assert result.stopped == "all_rejected"
    (rejection,) = result.iterations[0].rejected
    assert "word budget" in rejection.reason
    assert result.deck.slides[0].communication_mode == "text_led"
