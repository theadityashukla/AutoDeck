"""The art-direction pass (3b.7, B36)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from autodeck.agents import art_direction
from autodeck.agents.art_direction import (
    ArtDirectionPlan,
    ArtDirectionResult,
    ModeDecision,
    _art_direction_prompt,
    derive_mode,
    run_art_direction,
)
from autodeck.design.components.catalog import known_components, registration
from autodeck.design.icons.library import available_concepts
from autodeck.ir.actions import (
    ArtAction,
    AssignIcons,
    SetAccent,
    SwapComponent,
    fact_fingerprint,
)
from autodeck.ir.models import (
    Block,
    ChartSeries,
    ChartSpec,
    Deck,
    DeckBrief,
    KeyMessage,
    LayoutPin,
    Slide,
)
from autodeck.providers.base import ProviderError, RateLimitError
from autodeck.render.qa.aesthetic import catalog_slot_lookup
from tests.test_actions import make_citation, make_diagram, make_icon_block
from tests.test_aesthetic import _claim_block, _deck, _framing_block, tokens_for

# ---------------------------------------------------------------------------
# Fixtures and fakes
# ---------------------------------------------------------------------------

PIN_M1_COMPONENT = LayoutPin(message_id="m1", target="component", value="bullets_supporting")
CTA_CLAIM = "The kernel rewrite cut cost per token by 41%."


class FakeArtModel:
    """Returns a queued `ArtDirectionPlan` — or raises a queued exception — per call."""

    def __init__(self, *replies: ArtDirectionPlan | Exception) -> None:
        self._queue = list(replies)
        self.prompts: list[str] = []
        self.systems: list[str | None] = []

    @property
    def calls(self) -> int:
        return len(self.prompts)

    def complete_structured(
        self,
        prompt: str,
        response_model: type[ArtDirectionPlan],
        *,
        system: str | None = None,
    ) -> ArtDirectionPlan:
        assert response_model is ArtDirectionPlan
        self.prompts.append(prompt)
        self.systems.append(system)
        assert self._queue, "FakeArtModel was called more times than the test queued replies"
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def plan(*actions: ArtAction, rationale: str = "because") -> ArtDirectionPlan:
    return ArtDirectionPlan(rationale=rationale, actions=list(actions))


@pytest.fixture
def prompt_file(tmp_path: Path) -> Path:
    path = tmp_path / "art_direction.md"
    path.write_text("You are the art director. (test prompt)", encoding="utf-8")
    return path


def make_brief(*pins: LayoutPin) -> DeckBrief:
    return DeckBrief(
        run_id="r1",
        objective="Decide whether to fund the serving rewrite.",
        audience="CTO",
        key_messages=[
            KeyMessage(id="m1", text="The rewrite cut cost per token."),
            KeyMessage(id="m2", text="Rollout can start in Q1."),
        ],
        layout_pins=list(pins),
    )


def make_deck() -> Deck:
    """s1: bullets (m1, with notes); s2: a closing_cta (m2) that can be swapped to bullets."""
    deck = _deck()
    deck.slides[1] = Slide(
        id="s2",
        narrative_role="close",
        component="closing_cta",
        message_ids=["m2"],
        blocks=[
            _claim_block("headline", CTA_CLAIM, block_id="s2-headline"),
            _framing_block("cta", "Approve the rollout.", block_id="s2-cta"),
        ],
    )
    return deck


def run(
    deck: Deck,
    model: FakeArtModel,
    tmp_path: Path,
    prompt_file: Path,
    *,
    brief: DeckBrief | None = None,
    **overrides: Any,
) -> ArtDirectionResult:
    return run_art_direction(
        deck,
        brief=brief or make_brief(),
        tokens=tokens_for(),
        model=model,
        work_dir=tmp_path / "work",
        prompt_path=prompt_file,
        **overrides,
    )


def with_icon_slot(component: str) -> frozenset[str] | None:
    """The real catalog's slots plus an `icon` slot, so an icon concept can be the thing under
    test rather than the missing slot (no registered component on this branch has one)."""
    slots = catalog_slot_lookup()(component)
    return None if slots is None else slots | {"icon"}


def slide_with(*blocks: Block, notes: tuple[Block, ...] = ()) -> Slide:
    return Slide(
        id="sx",
        narrative_role="test",
        component="bullets_supporting",
        blocks=list(blocks),
        speaker_notes=list(notes),
    )


# ---------------------------------------------------------------------------
# The mode rule
# ---------------------------------------------------------------------------


def test_derive_mode_is_a_rule_on_face_content() -> None:
    """Diagram on the face -> diagram_led (even with icons too); icons only -> icon_anchored;
    neither -> text_led; a diagram or icon only in speaker notes does not count."""
    text = _framing_block("points", "Plain words.", block_id="t")
    diagram = Block(id="d", kind="diagram", slot="diagram", diagram=make_diagram())
    icon = make_icon_block("i", slot="icon")
    chart = Block(
        id="c",
        kind="chart",
        slot="chart",
        chart=ChartSpec(
            chart_type="bar",
            categories=["Q1", "Q2"],
            series=[ChartSeries(name="Revenue", values=[1.0, 2.0])],
            source_citations=[make_citation("Q1 revenue was $1m; Q2 revenue was $2m.")],
        ),
    )

    assert derive_mode(slide_with(text)) == "text_led"
    assert derive_mode(slide_with(text, chart)) == "text_led"
    assert derive_mode(slide_with(text, icon)) == "icon_anchored"
    assert derive_mode(slide_with(text, diagram)) == "diagram_led"
    assert derive_mode(slide_with(text, icon, diagram)) == "diagram_led"
    assert derive_mode(slide_with(text, notes=(diagram, icon))) == "text_led"
    assert derive_mode(slide_with()) == "text_led"


def test_every_slide_gets_a_mode_with_its_source(tmp_path: Path, prompt_file: Path) -> None:
    deck = make_deck()
    model = FakeArtModel(plan())

    result = run(deck, model, tmp_path, prompt_file)

    assert list(result.modes) == ["s1", "s2"]
    assert all(
        decision == ModeDecision(mode="text_led", source="rule")
        for decision in result.modes.values()
    )
    assert [slide.communication_mode for slide in result.deck.slides] == [
        "text_led",
        "text_led",
    ]
    assert result.stopped == "ok" and result.detail == "" and result.render_error == ""
    assert result.rationale == "because"
    assert model.calls == 1
    assert model.systems == ["You are the art director. (test prompt)"]
    assert (tmp_path / "work" / "art_directed.pptx").exists()
    assert all(slide.communication_mode is None for slide in deck.slides), "input not mutated"


def test_a_communication_mode_pin_beats_the_rule_and_a_mismatch_is_noted(
    tmp_path: Path, prompt_file: Path
) -> None:
    agreeing = LayoutPin(message_id="m2", target="communication_mode", value="text_led")
    disagreeing = LayoutPin(message_id="m1", target="communication_mode", value="icon_anchored")
    brief = make_brief(disagreeing, agreeing)

    result = run(make_deck(), FakeArtModel(plan()), tmp_path, prompt_file, brief=brief)

    s1, s2 = result.modes["s1"], result.modes["s2"]
    assert (s1.mode, s1.source) == ("icon_anchored", "pin")
    assert "icon_anchored" in s1.note and "text_led" in s1.note
    assert (s2.mode, s2.source, s2.note) == ("text_led", "pin", "")
    # The pin's value is on the deck, even though `apply_action` refuses to override a pin.
    assert result.deck.slides[0].communication_mode == "icon_anchored"


def test_a_pin_that_is_not_a_mode_falls_back_to_the_rule_and_says_so(
    tmp_path: Path, prompt_file: Path
) -> None:
    brief = make_brief(LayoutPin(message_id="m1", target="communication_mode", value="loud"))

    result = run(make_deck(), FakeArtModel(plan()), tmp_path, prompt_file, brief=brief)

    decision = result.modes["s1"]
    assert (decision.mode, decision.source) == ("text_led", "rule")
    assert "'loud'" in decision.note


def test_conflicting_pins_honour_the_first_and_say_so(
    tmp_path: Path, prompt_file: Path
) -> None:
    deck = make_deck()
    deck.slides[0].message_ids = ["m1", "m2"]
    brief = make_brief(
        LayoutPin(message_id="m1", target="communication_mode", value="icon_anchored"),
        LayoutPin(message_id="m2", target="communication_mode", value="diagram_led"),
    )

    result = run(deck, FakeArtModel(plan()), tmp_path, prompt_file, brief=brief)

    decision = result.modes["s1"]
    assert (decision.mode, decision.source) == ("icon_anchored", "pin")
    assert "'diagram_led'" in decision.note
    assert result.deck.slides[0].communication_mode == "icon_anchored"


def test_a_pin_on_another_message_does_not_apply(tmp_path: Path, prompt_file: Path) -> None:
    brief = make_brief(
        LayoutPin(message_id="m2", target="communication_mode", value="diagram_led")
    )
    result = run(make_deck(), FakeArtModel(plan()), tmp_path, prompt_file, brief=brief)
    assert result.modes["s1"].source == "rule"
    assert result.modes["s2"].source == "pin"


# ---------------------------------------------------------------------------
# Proposed actions
# ---------------------------------------------------------------------------


def test_proposed_actions_go_through_try_action_and_rejections_are_recorded(
    tmp_path: Path, prompt_file: Path
) -> None:
    """A plan with one valid SwapComponent, one swap onto a pinned component, and one
    AssignIcons with an unknown concept -> one applied, two rejected with reasons."""
    brief = make_brief(
        LayoutPin(message_id="m1", target="component", value="bullets_supporting")
    )
    good = SwapComponent(
        slide_id="s2",
        component="bullets_supporting",
        slot_map={"headline": "headline", "cta": "points"},
    )
    pinned = SwapComponent(
        slide_id="s1",
        component="closing_cta",
        slot_map={"headline": "headline", "points": "cta"},
    )
    unknown_concept = AssignIcons(slide_id="s2", slot="icon", concepts=["warp"])
    model = FakeArtModel(plan(good, pinned, unknown_concept))

    result = run(
        make_deck(), model, tmp_path, prompt_file, brief=brief, slots_of=with_icon_slot
    )

    assert result.applied == [good]
    assert [r.action for r in result.rejected] == [pinned, unknown_concept]
    assert "pinned component" in result.rejected[0].reason
    assert "'warp'" in result.rejected[1].reason
    assert result.deck.slides[1].component == "bullets_supporting"
    assert result.deck.slides[0].component == "bullets_supporting"


def test_actions_are_tried_against_the_deck_the_earlier_ones_produced(
    tmp_path: Path, prompt_file: Path
) -> None:
    first = SetAccent(slide_id="s1", accent="accent3")
    second = SetAccent(slide_id="s2", accent="accent4")
    result = run(make_deck(), FakeArtModel(plan(first, second)), tmp_path, prompt_file)
    assert result.applied == [first, second]
    assert [s.style.accent for s in result.deck.slides] == ["accent3", "accent4"]


def test_the_pass_goes_through_the_shared_acceptance_rule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, prompt_file: Path
) -> None:
    calls: list[object] = []
    real = art_direction.trial.try_action

    def recording(deck: Deck, action: object, **kwargs: Any) -> Deck:
        calls.append(action)
        assert kwargs["scratch"] == tmp_path / "work" / "trial.pptx"
        return real(deck, action, **kwargs)

    monkeypatch.setattr(art_direction.trial, "try_action", recording)
    action = SetAccent(slide_id="s1", accent="accent3")
    run(make_deck(), FakeArtModel(plan(action)), tmp_path, prompt_file)
    assert calls == [action]


def icon_pillars_slide() -> Slide:
    return Slide(
        id="s1",
        narrative_role="capabilities",
        component="icon_pillars",
        message_ids=["m1"],
        blocks=[
            _framing_block("headline", "Three things we do well", block_id="p-headline"),
            _framing_block("pillar_label", "Fast", block_id="p-label1"),
            _framing_block("pillar_label", "Safe", block_id="p-label2"),
            _framing_block("pillar_label", "Cheap", block_id="p-label3"),
        ],
    )


def test_assign_icons_on_an_icon_pillars_slide_makes_it_render_and_icon_anchored(
    tmp_path: Path, prompt_file: Path
) -> None:
    """icon_pillars slide with labels but no icons: before, `render_error` would be set;
    with an AssignIcons for the right count -> renders, mode icon_anchored (rule).
    Real render: `icon_pillars` is registered (B35)."""
    deck = make_deck()
    deck.slides = [icon_pillars_slide()]
    concepts = ["speed", "security", "growth"]

    before = run(deck, FakeArtModel(plan()), tmp_path / "before", prompt_file)
    assert before.render_error, "labels without icons do not render"
    assert before.modes["s1"].mode == "text_led"

    assign = AssignIcons(slide_id="s1", slot="pillar_icon", concepts=concepts)
    after = run(deck, FakeArtModel(plan(assign)), tmp_path / "after", prompt_file)

    assert after.applied == [assign] and after.rejected == []
    assert after.render_error == ""
    assert (after.modes["s1"].mode, after.modes["s1"].source) == ("icon_anchored", "rule")
    icons = [b for b in after.deck.slides[0].blocks if b.kind == "icon"]
    assert [b.id for b in icons] == [f"pillar_icon.icon{i}" for i in (1, 2, 3)]
    assert [b.icon.concept for b in icons if b.icon] == concepts
    assert fact_fingerprint(after.deck) == fact_fingerprint(deck)


# ---------------------------------------------------------------------------
# Failure paths and invariants
# ---------------------------------------------------------------------------


def test_a_model_error_still_assigns_rule_modes_and_says_why(
    tmp_path: Path, prompt_file: Path
) -> None:
    deck = make_deck()
    model = FakeArtModel(RateLimitError("quota exhausted"))

    result = run(deck, model, tmp_path, prompt_file)

    assert result.stopped == "model_error"
    assert result.detail == "RateLimitError: quota exhausted"
    assert result.applied == [] and result.rejected == [] and result.rationale == ""
    assert [d.source for d in result.modes.values()] == ["rule", "rule"]
    assert [s.communication_mode for s in result.deck.slides] == ["text_led", "text_led"]
    assert result.render_error == ""


def test_an_error_that_is_not_a_provider_error_propagates(
    tmp_path: Path, prompt_file: Path
) -> None:
    assert not issubclass(KeyError, ProviderError)
    with pytest.raises(KeyError):
        run(make_deck(), FakeArtModel(KeyError("bug")), tmp_path, prompt_file)


def test_a_mode_that_breaks_a_word_budget_is_assigned_and_reported_not_refused(
    tmp_path: Path, prompt_file: Path
) -> None:
    deck = make_deck()
    deck.slides[0].blocks[1] = _framing_block(
        "points", " ".join(["word"] * 70), block_id="s1-point-a"
    )
    brief = make_brief(
        LayoutPin(message_id="m1", target="communication_mode", value="icon_anchored")
    )

    result = run(deck, FakeArtModel(plan()), tmp_path, prompt_file, brief=brief)

    assert result.deck.slides[0].communication_mode == "icon_anchored"
    assert result.rejected == []
    budget = [f for f in result.grammar if f.check == "word budget"]
    assert len(budget) == 1 and "slide s1" in budget[0].location


def test_facts_are_unchanged_on_every_path(tmp_path: Path, prompt_file: Path) -> None:
    """Fingerprint equality after: a full successful plan, a model error, an all-rejected
    plan, and a plan containing AssignIcons."""
    swap = SwapComponent(
        slide_id="s2",
        component="bullets_supporting",
        slot_map={"headline": "headline", "cta": "points"},
    )
    accent = SetAccent(slide_id="s1", accent="accent2")
    icons = AssignIcons(
        slide_id="s1", slot="pillar_icon", concepts=["growth", "speed", "trust"]
    )
    bad = SetAccent(slide_id="nope", accent="accent2")

    scenarios: dict[str, tuple[FakeArtModel, dict[str, Any]]] = {
        "successful": (FakeArtModel(plan(swap, accent)), {}),
        "model error": (FakeArtModel(RateLimitError("slow down")), {}),
        "all rejected": (FakeArtModel(plan(bad)), {}),
        "assign icons": (FakeArtModel(plan(icons)), {}),
    }
    for name, (model, overrides) in scenarios.items():
        deck = make_deck()
        if name == "assign icons":
            deck.slides[0] = icon_pillars_slide()
        before = deck.model_dump()
        result = run(deck, model, tmp_path / name.replace(" ", "-"), prompt_file, **overrides)
        assert fact_fingerprint(result.deck) == fact_fingerprint(deck), name
        assert deck.model_dump() == before, name
        if name == "assign icons":
            assert result.applied == [icons] and result.rejected == []
            assert [b.kind for b in result.deck.slides[0].blocks].count("icon") == 3
            assert result.modes["s1"].mode == "icon_anchored"
            assert result.render_error == ""
        if name == "successful":
            assert result.applied == [swap, accent]


def test_a_missing_prompt_fails_before_the_model_is_called(tmp_path: Path) -> None:
    model = FakeArtModel(plan())
    with pytest.raises(FileNotFoundError, match=r"art_direction\.md"):
        run_art_direction(
            make_deck(),
            brief=make_brief(),
            tokens=tokens_for(),
            model=model,
            work_dir=tmp_path / "work",
            prompt_path=tmp_path / "art_direction.md",
        )
    assert model.calls == 0


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------


def test_the_prompt_lists_messages_slides_components_and_concepts_deterministically() -> None:
    deck = make_deck()
    deck.slides[0].blocks.append(
        Block(id="s1-diagram", kind="diagram", slot="diagram", diagram=make_diagram())
    )
    deck.slides[0].blocks.append(make_icon_block("s1-icon", slot="icon"))
    deck.slides[0].blocks.append(
        Block(
            id="s1-chart",
            kind="chart",
            slot="chart",
            chart=ChartSpec(
                chart_type="bar",
                title="Cost per token by quarter",
                categories=["Q1", "Q2"],
                series=[ChartSeries(name="Cost", values=[1.0, 2.0])],
                source_citations=[make_citation("Q1 cost was $1; Q2 cost was $2.")],
            ),
        )
    )
    deck.slides[0].style.accent = "accent3"
    brief = make_brief(
        LayoutPin(message_id="m1", target="component", value="bullets_supporting")
    )
    slots_of = catalog_slot_lookup()

    prompt = _art_direction_prompt(deck, brief, slots_of=slots_of)

    assert prompt == _art_direction_prompt(deck.model_copy(deep=True), brief, slots_of=slots_of)
    # Brief: objective, messages in order, pins.
    assert "Decide whether to fund the serving rewrite." in prompt
    assert prompt.index("m1: The rewrite cut cost per token.") < prompt.index(
        "m2: Rollout can start in Q1."
    )
    assert "m1  component  bullets_supporting" in prompt
    # Slides: header fields, and the words (the model needs them to judge meaning).
    assert prompt.index("slide s1") < prompt.index("slide s2")
    assert "narrative_role: test" in prompt and "message_ids: m1" in prompt
    assert "accent=accent3" in prompt
    assert "s1-headline  claim  headline  " + CTA_CLAIM in prompt
    assert (
        "s1-point-a  framing  points  The attention kernel rewrite removed the bottleneck."
        in prompt
    )
    assert "s1-chart  chart  chart  chart: Cost per token by quarter" in prompt
    assert "s1-icon  icon  icon  icon: growth" in prompt
    assert "s1-diagram  diagram  diagram  diagram (process_flow): Ingest; Serve" in prompt
    # Every component with its roles and slots; icon concepts; vocabularies.
    for name in known_components():
        assert f"  {name} | {'; '.join(registration(name).narrative_roles)} | " in prompt
    assert (
        "  bullets_supporting | supporting evidence; headline argument | headline, points"
        in prompt
    )
    assert ", ".join(available_concepts()) in prompt
    assert "type_scale: " in prompt and "accent2" in prompt
    # What the model must not be handed as something to edit: nothing but words to read, and
    # notes, which are not drawn, are not listed.
    assert "Mention the rollout order" not in prompt
    # Distinct inputs, distinct prompts.
    other = deck.model_copy(deep=True)
    other.slides[0].style.accent = "accent5"
    assert _art_direction_prompt(other, brief, slots_of=slots_of) != prompt


def test_the_prompt_defaults_work_for_a_real_run(tmp_path: Path, prompt_file: Path) -> None:
    """`run_art_direction`'s default lookups are the aesthetic loop's, and the prompt it
    sends is the one `_art_direction_prompt` builds from them."""
    model = FakeArtModel(plan())
    deck = make_deck()
    run(deck, model, tmp_path, prompt_file)
    assert model.prompts == [
        _art_direction_prompt(deck, make_brief(), slots_of=catalog_slot_lookup())
    ]
