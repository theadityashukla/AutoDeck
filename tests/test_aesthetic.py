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

import pytest

SCAFFOLD = pytest.mark.xfail(strict=True, reason="scaffold: not implemented yet")


# ---------------------------------------------------------------------------
# A1/A3 — the defining constraint
# ---------------------------------------------------------------------------


@SCAFFOLD
def test_a_critique_that_tries_to_edit_text_is_rejected_and_the_deck_is_unchanged() -> None:
    """PHASE-3B.md 3b.5 "done when". Two layers, both asserted:
    1. `ActionList.model_validate_json` on a reply whose action carries `"text": "..."`
       (and one carrying `"citations": [...]`) raises `ValidationError`.
    2. A `FakeCritic` that raises `StructuredOutputError` (what the provider raises after
       its repair attempts on exactly such a reply) → `stopped == "model_error"`,
       `result.deck == input deck`, fingerprint equal, `detail` names the exception."""
    raise NotImplementedError


@SCAFFOLD
def test_fact_mutation_inside_apply_action_propagates_out_of_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sabotage `autodeck.ir.actions._apply_unchecked` to edit a claim's text; run the loop
    with a critic proposing one valid action; assert `FactMutationError` escapes
    `run_aesthetic_loop` (it is never caught — module docstring)."""
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Stop reasons
# ---------------------------------------------------------------------------


@SCAFFOLD
def test_target_score_on_first_look_returns_the_input_deck_after_one_call() -> None:
    """Critic scores 9.0 with actions it would like applied → `target_reached`, one call,
    no actions applied, `result.deck == input`, `best_score == 9.0`."""
    raise NotImplementedError


@SCAFFOLD
def test_an_empty_action_list_stops_with_no_actions() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_every_action_rejected_stops_with_all_rejected_and_records_each_reason() -> None:
    """Actions addressing an unknown slide, an unknown component, and a pinned component →
    each appears in `iterations[0].rejected` with the `ActionRejected` message;
    `stopped == "all_rejected"`; no second render happened."""
    raise NotImplementedError


@SCAFFOLD
def test_a_rejected_action_does_not_stop_the_valid_ones_after_it() -> None:
    """[unknown slide, valid SetTypeScale] → the SetTypeScale is applied to the candidate;
    one rejected, one applied recorded."""
    raise NotImplementedError


@SCAFFOLD
def test_budget_exhaustion_returns_the_best_scored_deck_not_the_last_candidate() -> None:
    """`max_iterations=3`, scores 5, 7, 6, each with a valid action → three calls,
    `max_iterations`, returned deck is the one scored 7 (after one round of actions), and the
    third round's actions (never scored) are not in it. Also: ties go to the earlier deck."""
    raise NotImplementedError


@SCAFFOLD
def test_a_provider_error_mid_run_returns_the_best_deck_so_far() -> None:
    """Scores 6 then `RateLimitError` → `model_error`, returned deck is the one scored 6,
    `detail` names `RateLimitError`."""
    raise NotImplementedError


@SCAFFOLD
def test_a_candidate_with_more_qa_findings_is_reverted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the module's `run_deterministic_qa` to return 0 findings then 2 → `qa_regression`,
    returned deck is the first, `detail` has both counts. Equal counts must NOT stop the
    loop (second case in the same test)."""
    raise NotImplementedError


@SCAFFOLD
def test_an_input_deck_that_fails_the_audit_never_reaches_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch `post_render_audit` to fail on iteration 0 → `AestheticLoopError`, the critic was
    never called. Failing on iteration 1 instead → `audit_failed`, first deck returned."""
    raise NotImplementedError


@SCAFFOLD
def test_a_missing_prompt_fails_before_any_render_or_model_call(tmp_path: object) -> None:
    raise NotImplementedError


# ---------------------------------------------------------------------------
# What the model is shown
# ---------------------------------------------------------------------------


@SCAFFOLD
def test_the_prompt_lists_addresses_but_never_claim_text_or_citations() -> None:
    """`_critique_prompt` output contains every slide id and face block id, each catalog
    component with its slots, and the concept list; it contains **no** claim text, no
    citation quote, no doc id, and no notes-block id. Same inputs → identical string."""
    raise NotImplementedError


@SCAFFOLD
def test_earlier_rejections_are_fed_back_to_the_model() -> None:
    """The second call's prompt contains the first iteration's rejected action and reason."""
    raise NotImplementedError


@SCAFFOLD
def test_the_model_is_shown_one_image_per_slide_of_the_current_render() -> None:
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


@SCAFFOLD
def test_catalog_slot_lookup_matches_the_registry_and_returns_none_for_unknowns() -> None:
    raise NotImplementedError


@SCAFFOLD
def test_library_concept_lookup_resolves_concepts_but_not_bare_filenames() -> None:
    raise NotImplementedError


# ---------------------------------------------------------------------------
# End to end, real LibreOffice
# ---------------------------------------------------------------------------


@SCAFFOLD
@pytest.mark.render
def test_one_real_iteration_renders_true_pngs_and_keeps_facts(tmp_path: object) -> None:
    """Default rasteriser, Inter test tokens (as `tests/test_renderer.py::tokens_for`), a
    critic proposing `SetTypeScale(spacious)` then scoring 9 → two PNG sets on disk under
    `work_dir/iter-0/png` and `iter-1/png`, `target_reached`, fingerprint equal."""
    raise NotImplementedError
