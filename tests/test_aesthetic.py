"""The bounded aesthetic loop (task 3b.5): presentation improves, facts cannot move.

Every test here that runs the loop ends by asserting `fact_fingerprint(result.deck) ==
fact_fingerprint(input)` — on the success paths *and* the failure paths. The loop has seven
ways to stop; a fact-preservation check on only the happy one proves nothing about the
others.

Fakes, not LibreOffice: `rasterise` is injected with a function that writes one tiny PNG per
slide, and `model` is a `FakeCritic` that returns a queued `ActionList` (or raises) per call
and records the prompts and image counts it was given. Only the final test is
`render`-marked and uses the real rasteriser. Build decks with the same helpers style as
`tests/test_renderer.py` (a short deck: a bullets slide with a cited claim, a slide with an
icon block on the face, and one with an icon in the notes). The system prompt is a
`tmp_path` file, so these tests do not depend on `prompts/aesthetic_critique.md`'s wording.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pptx import Presentation
from pydantic import ValidationError

from autodeck.audit.numeric_linter import NumericReport
from autodeck.audit.post_render import PostRenderFinding, PostRenderReport
from autodeck.design.components import catalog
from autodeck.design.icons.library import available_concepts, resolve_icon
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir import actions
from autodeck.ir.actions import (
    Action,
    ActionList,
    FactMutationError,
    SetAccent,
    SetTypeScale,
    SwapComponent,
    fact_fingerprint,
)
from autodeck.ir.models import (
    Block,
    Citation,
    Claim,
    Deck,
    LayoutPin,
    Slide,
    SlideStyle,
)
from autodeck.providers.base import (
    ImageInput,
    RateLimitError,
    StructuredOutputError,
)
from autodeck.render.qa import aesthetic
from autodeck.render.qa.aesthetic import (
    AestheticLoopError,
    AestheticResult,
    Iteration,
    LoopConfig,
    RejectedAction,
    _critique_prompt,
    catalog_slot_lookup,
    library_concept_lookup,
    run_aesthetic_loop,
)
from autodeck.render.qa.deterministic import QAFinding
from autodeck.render.renderer import render_deck

TOKENS_DIR = Path(__file__).resolve().parents[1] / "config" / "tokens"

#: Any real installed font does — these tests check the loop's plumbing, never a
#: font-specific value. Same choice `tests/test_renderer.py` makes.
TEST_FAMILY = "Liberation Sans"

#: A real, valid 1x1 PNG. The fake rasteriser writes one per slide.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63f8cfc0f01f0005000201a5f645400000000049454e44ae426082"
)


def tokens_for(family: str = TEST_FAMILY) -> DesignTokens:
    base = DesignTokens.load(TOKENS_DIR / "dev.json")
    return base.model_copy(
        update={
            "typography": base.typography.model_copy(update={"major": family, "minor": family})
        }
    )


# ---------------------------------------------------------------------------
# Fixture builders (same style as `tests/test_renderer.py`)
# ---------------------------------------------------------------------------

_ids = itertools.count(1)


def _next_id() -> str:
    return f"b{next(_ids)}"


def _claim_block(slot: str, text: str, *, block_id: str) -> Block:
    citation = Citation.for_quote(
        quote=text,
        doc_id="vendor-report-d7",
        page=4,
        bbox=(10.0, 20.0, 300.0, 44.0),
        retrieved_by="validator",
    )
    return Block(
        id=block_id,
        kind="claim",
        slot=slot,
        claim=Claim(text=text, citations=[citation], verdict="supported"),
    )


def _framing_block(slot: str, text: str, *, block_id: str | None = None) -> Block:
    return Block(id=block_id or _next_id(), kind="framing", slot=slot, text=text)


CLAIM_TEXT = "The kernel rewrite cut cost per token by 41%."
FRAMING_TEXT = "The attention kernel rewrite removed the bottleneck."
NOTES_TEXT = "Mention the rollout order when presenting."


def _bullets_slide(slide_id: str, *, with_notes: bool = False) -> Slide:
    return Slide(
        id=slide_id,
        narrative_role="test",
        component="bullets_supporting",
        message_ids=["m1"] if slide_id == "s1" else ["m2"],
        blocks=[
            _claim_block("headline", CLAIM_TEXT, block_id=f"{slide_id}-headline"),
            _framing_block("points", FRAMING_TEXT, block_id=f"{slide_id}-point-a"),
            _framing_block(
                "points",
                "Batch composition now adapts to load.",
                block_id=f"{slide_id}-point-b",
            ),
        ],
        speaker_notes=(
            [_framing_block("notes", NOTES_TEXT, block_id=f"{slide_id}-notes-only")]
            if with_notes
            else []
        ),
        style=SlideStyle(),
    )


def _deck() -> Deck:
    """Two bullets slides; the first carries a speaker-notes block.

    No icon block appears on a face here: no registered component has a slot an icon block
    can sit in, so the real render stage would refuse the deck (`UnplacedBlockError`). Icon
    addressing is covered in `tests/test_actions.py`.
    """
    return Deck(
        run_id="r1",
        project="p",
        client="c",
        audience="a",
        version=1,
        theme_ref="t",
        component_lib_version=catalog.COMPONENT_LIB_VERSION,
        slides=[_bullets_slide("s1", with_notes=True), _bullets_slide("s2")],
    )


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def reply(score: float, *actions_: Action, rationale: str = "because") -> ActionList:
    return ActionList(score=score, rationale=rationale, actions=list(actions_))


class FakeCritic:
    """Returns a queued `ActionList` — or raises a queued exception — per `vision` call, and
    records the prompt, system prompt and images it was given."""

    def __init__(self, *replies: ActionList | Exception) -> None:
        self._queue = list(replies)
        self.prompts: list[str] = []
        self.systems: list[str | None] = []
        self.images: list[list[ImageInput]] = []

    @property
    def calls(self) -> int:
        return len(self.prompts)

    def vision(
        self,
        images: list[ImageInput],
        prompt: str,
        response_model: type[ActionList],
        *,
        system: str | None = None,
    ) -> ActionList:
        assert response_model is ActionList
        self.prompts.append(prompt)
        self.systems.append(system)
        self.images.append(list(images))
        assert self._queue, "FakeCritic was called more times than the test queued replies"
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeRasteriser:
    """Writes one tiny PNG per slide of the PPTX it is given, like `render_pptx` would."""

    def __init__(self) -> None:
        self.output_dirs: list[Path] = []

    def __call__(self, pptx: Path, output_dir: Path) -> list[Path]:
        self.output_dirs.append(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        count = len(Presentation(str(pptx)).slides)
        paths: list[Path] = []
        for number in range(1, count + 1):
            path = output_dir / f"slide-{number}.png"
            path.write_bytes(TINY_PNG)
            paths.append(path)
        return paths


@pytest.fixture
def prompt_file(tmp_path: Path) -> Path:
    path = tmp_path / "aesthetic_critique.md"
    path.write_text("You are the aesthetic critic. (test prompt)", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _no_real_qa(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic QA is its own subject (`tests/test_deterministic_qa.py`); here it would
    only make the loop's stop reasons depend on LibreOffice-free geometry arithmetic, so
    stub it to "no findings" unless a test patches it itself or runs the real thing."""
    if request.node.get_closest_marker("render") is not None:
        return
    monkeypatch.setattr(aesthetic, "run_deterministic_qa", lambda pptx, tokens: [])


def _run(
    deck: Deck,
    critic: FakeCritic,
    tmp_path: Path,
    prompt_file: Path,
    *,
    config: LoopConfig = LoopConfig(),  # noqa: B008 - frozen dataclass
    pins: Sequence[LayoutPin] = (),
    rasteriser: FakeRasteriser | None = None,
) -> AestheticResult:
    return run_aesthetic_loop(
        deck,
        tokens=tokens_for(),
        model=critic,
        work_dir=tmp_path / "work",
        pins=pins,
        config=config,
        rasterise=rasteriser or FakeRasteriser(),
        prompt_path=prompt_file,
    )


def _qa_finding() -> QAFinding:
    return QAFinding(
        check="overlap",
        slide_id="s1",
        shapes=("headline", "points"),
        measured=3.0,
        threshold=0.0,
        remedy="slot",
        remedy_detail="bullets_supporting.points",
    )


def _type_scale(deck: Deck, slide_id: str = "s1") -> str:
    return next(slide for slide in deck.slides if slide.id == slide_id).style.type_scale


def _accent(deck: Deck, slide_id: str = "s1") -> str:
    return next(slide for slide in deck.slides if slide.id == slide_id).style.accent


# ---------------------------------------------------------------------------
# A1/A3 — the defining constraint
# ---------------------------------------------------------------------------


def test_a_critique_that_tries_to_edit_text_is_rejected_and_the_deck_is_unchanged(
    tmp_path: Path, prompt_file: Path
) -> None:
    """PHASE-3B.md 3b.5 "done when". Two layers, both asserted:
    1. `ActionList.model_validate_json` on a reply whose action carries `"text": "..."`
       (and one carrying `"citations": [...]`) raises `ValidationError`.
    2. A `FakeCritic` that raises `StructuredOutputError` (what the provider raises after
       its repair attempts on exactly such a reply) -> `stopped == "model_error"`,
       `result.deck == input deck`, fingerprint equal, `detail` names the exception."""
    with_text = (
        '{"score": 5, "rationale": "r", "actions": '
        '[{"kind": "set_type_scale", "slide_id": "s1", "scale": "compact", '
        '"text": "The kernel rewrite cut cost per token by 99%."}]}'
    )
    with_citations = (
        '{"score": 5, "rationale": "r", "actions": '
        '[{"kind": "set_accent", "slide_id": "s1", "accent": "accent2", '
        '"citations": [{"doc_id": "x"}]}]}'
    )
    for payload in (with_text, with_citations):
        with pytest.raises(ValidationError):
            ActionList.model_validate_json(payload)

    deck = _deck()
    before = fact_fingerprint(deck)
    critic = FakeCritic(
        StructuredOutputError(
            "no schema-valid reply", attempts=2, last_error="extra field 'text'", last_raw="{}"
        )
    )

    result = _run(deck, critic, tmp_path, prompt_file)

    assert result.stopped == "model_error"
    assert result.deck == deck
    assert result.best_score is None
    assert "StructuredOutputError" in result.detail
    assert critic.calls == 1
    assert fact_fingerprint(result.deck) == before


def test_fact_mutation_inside_apply_action_propagates_out_of_the_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, prompt_file: Path
) -> None:
    """Sabotage `autodeck.ir.actions._apply_unchecked` to edit a claim's text; run the loop
    with a critic proposing one valid action; assert `FactMutationError` escapes
    `run_aesthetic_loop` (it is never caught — module docstring)."""
    real = actions._apply_unchecked

    def sabotaged(deck: Deck, action: Any, **kwargs: Any) -> Deck:
        new_deck = real(deck, action, **kwargs)
        claim = new_deck.slides[0].blocks[0].claim
        assert claim is not None
        claim.text = "A claim the model rewrote."
        return new_deck

    monkeypatch.setattr(actions, "_apply_unchecked", sabotaged)
    critic = FakeCritic(reply(5.0, SetTypeScale(slide_id="s1", scale="compact")))

    with pytest.raises(FactMutationError):
        _run(_deck(), critic, tmp_path, prompt_file)


# ---------------------------------------------------------------------------
# Stop reasons
# ---------------------------------------------------------------------------


def test_target_score_on_first_look_returns_the_input_deck_after_one_call(
    tmp_path: Path, prompt_file: Path
) -> None:
    """Critic scores 9.0 with actions it would like applied -> `target_reached`, one call,
    no actions applied, `result.deck == input`, `best_score == 9.0`."""
    deck = _deck()
    critic = FakeCritic(reply(9.0, SetTypeScale(slide_id="s1", scale="compact")))

    result = _run(deck, critic, tmp_path, prompt_file)

    assert result.stopped == "target_reached"
    assert critic.calls == 1
    assert result.best_score == 9.0
    assert result.deck == deck
    assert len(result.iterations) == 1
    assert result.iterations[0].applied == ()
    assert result.iterations[0].rejected == ()
    assert fact_fingerprint(result.deck) == fact_fingerprint(deck)


def test_an_empty_action_list_stops_with_no_actions(tmp_path: Path, prompt_file: Path) -> None:
    deck = _deck()
    critic = FakeCritic(reply(6.5))

    result = _run(deck, critic, tmp_path, prompt_file)

    assert result.stopped == "no_actions"
    assert critic.calls == 1
    assert result.best_score == 6.5
    assert result.deck == deck
    assert result.iterations[0].rationale == "because"
    assert fact_fingerprint(result.deck) == fact_fingerprint(deck)


def test_every_action_rejected_stops_with_all_rejected_and_records_each_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, prompt_file: Path
) -> None:
    """Actions addressing an unknown slide, an unknown component, and a pinned component ->
    each appears in `iterations[0].rejected` with the `ActionRejected` message;
    `stopped == "all_rejected"`; no second render happened."""
    renders: list[Path] = []

    def spy(deck: Deck, *, tokens: DesignTokens, out_path: Path) -> Any:
        renders.append(out_path)
        return render_deck(deck, tokens=tokens, out_path=out_path)

    monkeypatch.setattr(aesthetic, "render_deck", spy)

    deck = _deck()
    pin = LayoutPin(message_id="m1", target="component", value="bullets_supporting")
    unknown_slide = SetTypeScale(slide_id="nope", scale="compact")
    unknown_component = SwapComponent(slide_id="s1", component="no_such_component", slot_map={})
    pinned = SwapComponent(
        slide_id="s1",
        component="callout_takeaway",
        slot_map={"headline": "takeaway", "points": "support"},
    )
    critic = FakeCritic(reply(4.0, unknown_slide, unknown_component, pinned))

    result = _run(deck, critic, tmp_path, prompt_file, pins=[pin])

    assert result.stopped == "all_rejected"
    assert len(renders) == 1
    assert not (tmp_path / "work" / "iter-1").exists()
    iteration = result.iterations[0]
    assert iteration.applied == ()
    assert [rejection.action for rejection in iteration.rejected] == [
        unknown_slide,
        unknown_component,
        pinned,
    ]
    reasons = [rejection.reason for rejection in iteration.rejected]
    assert "unknown slide_id 'nope'" in reasons[0]
    assert "unknown component 'no_such_component'" in reasons[1]
    assert "pinned component" in reasons[2]
    assert result.deck == deck
    assert result.best_score == 4.0
    assert fact_fingerprint(result.deck) == fact_fingerprint(deck)


def test_a_rejected_action_does_not_stop_the_valid_ones_after_it(
    tmp_path: Path, prompt_file: Path
) -> None:
    """[unknown slide, valid SetTypeScale] -> the SetTypeScale is applied to the candidate;
    one rejected, one applied recorded."""
    deck = _deck()
    bad = SetTypeScale(slide_id="nope", scale="compact")
    good = SetTypeScale(slide_id="s1", scale="compact")
    critic = FakeCritic(reply(5.0, bad, good), reply(9.0))

    result = _run(deck, critic, tmp_path, prompt_file)

    first = result.iterations[0]
    assert first.applied == (good,)
    assert [rejection.action for rejection in first.rejected] == [bad]
    assert result.stopped == "target_reached"
    assert critic.calls == 2
    assert _type_scale(result.deck) == "compact"
    assert fact_fingerprint(result.deck) == fact_fingerprint(deck)


def test_budget_exhaustion_returns_the_best_scored_deck_not_the_last_candidate(
    tmp_path: Path, prompt_file: Path
) -> None:
    """`max_iterations=3`, scores 5, 7, 6, each with a valid action -> three calls,
    `max_iterations`, returned deck is the one scored 7 (after one round of actions), and the
    third round's actions (never scored) are not in it. Also: ties go to the earlier deck."""
    deck = _deck()
    critic = FakeCritic(
        reply(5.0, SetTypeScale(slide_id="s1", scale="compact")),
        reply(7.0, SetAccent(slide_id="s1", accent="accent2")),
        reply(6.0, SetTypeScale(slide_id="s1", scale="spacious")),
    )

    result = _run(
        deck, critic, tmp_path / "a", prompt_file, config=LoopConfig(max_iterations=3)
    )

    assert result.stopped == "max_iterations"
    assert critic.calls == 3
    assert result.best_score == 7.0
    assert [iteration.score for iteration in result.iterations] == [5.0, 7.0, 6.0]
    # The deck the model scored 7 is the input plus round one's action only.
    assert _type_scale(result.deck) == "compact"
    assert _accent(result.deck) == "accent1"
    assert fact_fingerprint(result.deck) == fact_fingerprint(deck)

    # Ties go to the earlier deck: the same score three times returns the untouched input.
    tied = FakeCritic(
        reply(5.0, SetTypeScale(slide_id="s1", scale="compact")),
        reply(5.0, SetAccent(slide_id="s1", accent="accent2")),
        reply(5.0, SetTypeScale(slide_id="s1", scale="spacious")),
    )
    tied_result = _run(deck, tied, tmp_path / "b", prompt_file)
    assert tied_result.stopped == "max_iterations"
    assert tied_result.best_score == 5.0
    assert tied_result.deck == deck
    assert fact_fingerprint(tied_result.deck) == fact_fingerprint(deck)


def test_a_provider_error_mid_run_returns_the_best_deck_so_far(
    tmp_path: Path, prompt_file: Path
) -> None:
    """Scores 6 then `RateLimitError` -> `model_error`, returned deck is the one scored 6,
    `detail` names `RateLimitError`."""
    deck = _deck()
    critic = FakeCritic(
        reply(6.0, SetTypeScale(slide_id="s1", scale="compact")), RateLimitError("slow down")
    )

    result = _run(deck, critic, tmp_path / "a", prompt_file)

    assert result.stopped == "model_error"
    assert result.best_score == 6.0
    assert result.deck == deck
    assert "RateLimitError" in result.detail
    assert fact_fingerprint(result.deck) == fact_fingerprint(deck)

    # With a second scored deck, the error returns the best scored one — not the candidate
    # rendered for the failed call, which the model never scored.
    later = FakeCritic(
        reply(4.0, SetTypeScale(slide_id="s1", scale="compact")),
        reply(6.0, SetAccent(slide_id="s1", accent="accent2")),
        RateLimitError("slow down"),
    )
    later_result = _run(deck, later, tmp_path / "b", prompt_file)
    assert later_result.stopped == "model_error"
    assert later_result.best_score == 6.0
    assert _type_scale(later_result.deck) == "compact"
    assert _accent(later_result.deck) == "accent1"
    assert fact_fingerprint(later_result.deck) == fact_fingerprint(deck)


def test_a_candidate_with_more_qa_findings_is_reverted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, prompt_file: Path
) -> None:
    """Patch the module's `run_deterministic_qa` to return 0 findings then 2 -> `qa_regression`,
    returned deck is the first, `detail` has both counts. Equal counts must NOT stop the
    loop (second case in the same test)."""

    def patch_counts(*counts: int) -> None:
        queue = list(counts)
        monkeypatch.setattr(
            aesthetic,
            "run_deterministic_qa",
            lambda pptx, tokens: [_qa_finding() for _ in range(queue.pop(0))],
        )

    deck = _deck()

    patch_counts(0, 2)
    critic = FakeCritic(reply(5.0, SetTypeScale(slide_id="s1", scale="compact")))
    result = _run(deck, critic, tmp_path / "a", prompt_file)
    assert result.stopped == "qa_regression"
    assert critic.calls == 1
    assert result.deck == deck
    assert result.best_score == 5.0
    assert "2" in result.detail and "0" in result.detail
    assert fact_fingerprint(result.deck) == fact_fingerprint(deck)

    patch_counts(1, 1)
    equal_critic = FakeCritic(
        reply(5.0, SetTypeScale(slide_id="s1", scale="compact")), reply(9.0)
    )
    equal_result = _run(deck, equal_critic, tmp_path / "b", prompt_file)
    assert equal_result.stopped == "target_reached"
    assert equal_critic.calls == 2
    assert _type_scale(equal_result.deck) == "compact"
    assert fact_fingerprint(equal_result.deck) == fact_fingerprint(deck)


def test_an_input_deck_that_fails_the_audit_never_reaches_the_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, prompt_file: Path
) -> None:
    """Patch `post_render_audit` to fail on iteration 0 -> `AestheticLoopError`, the critic was
    never called. Failing on iteration 1 instead -> `audit_failed`, first deck returned."""
    failing = PostRenderReport(
        numeric=NumericReport(),
        findings=(
            PostRenderFinding(
                check="claim altered in render",
                slide_id="s1",
                detail="expected one sentence, found another",
            ),
        ),
    )
    real_audit = aesthetic.post_render_audit
    deck = _deck()

    monkeypatch.setattr(aesthetic, "post_render_audit", lambda d, pptx: failing)
    critic = FakeCritic()
    with pytest.raises(AestheticLoopError):
        _run(deck, critic, tmp_path / "a", prompt_file)
    assert critic.calls == 0

    audits = iter([real_audit, lambda d, pptx: failing])
    monkeypatch.setattr(aesthetic, "post_render_audit", lambda d, pptx: next(audits)(d, pptx))
    later = FakeCritic(reply(5.0, SetTypeScale(slide_id="s1", scale="compact")))
    result = _run(deck, later, tmp_path / "b", prompt_file)
    assert result.stopped == "audit_failed"
    assert later.calls == 1
    assert result.deck == deck
    assert result.best_score == 5.0
    assert "claim altered in render" in result.detail
    assert fact_fingerprint(result.deck) == fact_fingerprint(deck)


def test_a_missing_prompt_fails_before_any_render_or_model_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    renders: list[Path] = []

    def spy(deck: Deck, *, tokens: DesignTokens, out_path: Path) -> Any:
        renders.append(out_path)
        return render_deck(deck, tokens=tokens, out_path=out_path)

    monkeypatch.setattr(aesthetic, "render_deck", spy)
    missing = tmp_path / "prompts" / "aesthetic_critique.md"
    critic = FakeCritic()

    with pytest.raises(FileNotFoundError, match=r"aesthetic_critique\.md") as excinfo:
        run_aesthetic_loop(
            _deck(),
            tokens=tokens_for(),
            model=critic,
            work_dir=tmp_path / "work",
            rasterise=FakeRasteriser(),
            prompt_path=missing,
        )

    assert "no inline fallback" in str(excinfo.value)
    assert critic.calls == 0
    assert renders == []
    assert not (tmp_path / "work").exists()


# ---------------------------------------------------------------------------
# What the model is shown
# ---------------------------------------------------------------------------


def test_the_prompt_lists_addresses_but_never_claim_text_or_citations() -> None:
    """`_critique_prompt` output contains every slide id and face block id, each catalog
    component with its slots, and the concept list; it contains **no** claim text, no
    citation quote, no doc id, and no notes-block id. Same inputs -> identical string."""
    deck = _deck()
    slots_of = catalog_slot_lookup(tokens_for())

    def build() -> str:
        return _critique_prompt(
            deck,
            qa_findings=[_qa_finding()],
            iteration=0,
            previous=[],
            slots_of=slots_of,
        )

    prompt = build()

    for slide in deck.slides:
        assert slide.id in prompt
        assert slide.component in prompt
        for block in slide.blocks:
            assert block.id in prompt
            assert block.slot in prompt
    for name in catalog.known_components():
        names = slots_of(name)
        assert names is not None
        assert f"{name}: {', '.join(sorted(names))}" in prompt
    for concept in available_concepts():
        assert concept in prompt
    for vocabulary_word in ("compact", "spacious", "accent6", "lead_left", "diagram_led"):
        assert vocabulary_word in prompt
    assert "overlap" in prompt and "bullets_supporting.points" in prompt

    for forbidden in (
        CLAIM_TEXT,
        "cut cost per token",
        FRAMING_TEXT,
        "Batch composition",
        NOTES_TEXT,
        "vendor-report-d7",
        "s1-notes-only",
    ):
        assert forbidden not in prompt

    assert build() == prompt


def test_earlier_rejections_are_fed_back_to_the_model(
    tmp_path: Path, prompt_file: Path
) -> None:
    """The second call's prompt contains the first iteration's rejected action and reason."""
    bad = SetTypeScale(slide_id="nope", scale="compact")
    critic = FakeCritic(reply(5.0, bad, SetAccent(slide_id="s1", accent="accent2")), reply(9.0))

    result = _run(_deck(), critic, tmp_path, prompt_file)

    assert result.stopped == "target_reached"
    rejection = result.iterations[0].rejected[0]
    assert isinstance(rejection, RejectedAction)
    assert "unknown slide_id 'nope'" in rejection.reason
    second = critic.prompts[1]
    assert bad.model_dump_json() in second
    assert rejection.reason in second
    assert "score 5.0" in second
    assert "EARLIER LOOKS" not in critic.prompts[0]
    # The system prompt is the file, verbatim, on every call.
    assert critic.systems == [prompt_file.read_text(encoding="utf-8")] * 2


def test_the_model_is_shown_one_image_per_slide_of_the_current_render(
    tmp_path: Path, prompt_file: Path
) -> None:
    rasteriser = FakeRasteriser()
    critic = FakeCritic(reply(5.0, SetTypeScale(slide_id="s1", scale="compact")), reply(9.0))

    result = _run(_deck(), critic, tmp_path, prompt_file, rasteriser=rasteriser)

    work = tmp_path / "work"
    assert rasteriser.output_dirs == [work / "iter-0" / "png", work / "iter-1" / "png"]
    for call_images in critic.images:
        assert len(call_images) == 2
        assert all(
            image.data == TINY_PNG and image.media_type == "image/png" for image in call_images
        )
    assert [len(iteration.images) for iteration in result.iterations] == [2, 2]
    first: Iteration = result.iterations[0]
    assert all(path.parent == work / "iter-0" / "png" for path in first.images)
    assert all(path.exists() for path in first.images)
    assert (work / "iter-0" / "deck.pptx").exists()
    assert (work / "iter-1" / "deck.pptx").exists()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def test_catalog_slot_lookup_matches_the_registry_and_returns_none_for_unknowns() -> None:
    tokens = tokens_for()
    slots_of = catalog_slot_lookup(tokens)

    for name in catalog.known_components():
        expected = frozenset(
            slot.name
            for variant in catalog.registration(name).variants
            for slot in catalog.spec_for(name, tokens, variant=variant.name).slots
        )
        assert slots_of(name) == expected
        assert expected, name

    assert slots_of("no_such_component") is None
    assert slots_of("") is None
    assert slots_of("bullets_supporting") == frozenset({"headline", "points", "source"})


def test_library_concept_lookup_resolves_concepts_but_not_bare_filenames() -> None:
    glyph_for = library_concept_lookup()

    assert glyph_for("risk") == resolve_icon("risk").name == "circle-alert"
    for concept in available_concepts():
        assert glyph_for(concept) is not None
    # A literal vendored filename resolves in the library, but is not a *concept*.
    assert resolve_icon("circle-alert").name == "circle-alert"
    assert glyph_for("circle-alert") is None
    assert glyph_for("no_such_concept") is None


# ---------------------------------------------------------------------------
# End to end, real LibreOffice
# ---------------------------------------------------------------------------


@pytest.mark.render
def test_one_real_iteration_renders_true_pngs_and_keeps_facts(tmp_path: Path) -> None:
    """Default rasteriser, Inter test tokens (as `tests/test_renderer.py::tokens_for`), a
    critic proposing `SetTypeScale(spacious)` then scoring 9 -> two PNG sets on disk under
    `work_dir/iter-0/png` and `iter-1/png`, `target_reached`, fingerprint equal."""
    tokens = DesignTokens.load(TOKENS_DIR / "dev.json")  # Inter, as the client's deck would be
    prompt = tmp_path / "aesthetic_critique.md"
    prompt.write_text("You are the aesthetic critic. (test prompt)", encoding="utf-8")
    deck = _deck()
    critic = FakeCritic(reply(5.0, SetTypeScale(slide_id="s1", scale="spacious")), reply(9.0))

    result = run_aesthetic_loop(
        deck,
        tokens=tokens,
        model=critic,
        work_dir=tmp_path / "work",
        prompt_path=prompt,
    )

    assert result.stopped == "target_reached"
    assert result.best_score == 9.0
    assert _type_scale(result.deck) == "spacious"
    for index in (0, 1):
        pngs = sorted((tmp_path / "work" / f"iter-{index}" / "png").glob("*.png"))
        assert len(pngs) == len(deck.slides)
        assert all(png.read_bytes().startswith(b"\x89PNG") for png in pngs)
    assert [len(call) for call in critic.images] == [2, 2]
    assert fact_fingerprint(result.deck) == fact_fingerprint(deck)


# ---------------------------------------------------------------------------
# Scaffold amendment: placement authority and per-action trial render
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")
def test_an_action_that_does_not_render_is_rejected_not_fatal() -> None:
    """A critic proposing [SwapComponent onto a slot the target cannot place, a valid
    SetAccent] → the swap is in `rejected` with a reason starting "does not render:", the
    accent is applied, the loop continues to the next look. Same for a `SetTypeScale` that
    makes a slide overflow (monkeypatch `render_deck` in aesthetic's namespace to raise
    `LayoutOverflowError` for that candidate only). Fingerprint equal."""
    raise NotImplementedError


@pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")
def test_environment_failures_during_a_trial_render_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`FontNotFoundError` raised by the trial render escapes `run_aesthetic_loop`; it is not
    recorded as a rejected action."""
    raise NotImplementedError
