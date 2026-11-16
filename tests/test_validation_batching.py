"""Token-budgeted batching and verdict reuse in the validation agent (B44)."""

from __future__ import annotations

from pathlib import Path

from autodeck.agents.validation import (
    BATCH_SIZE,
    MAX_BATCH_CLAIMS,
    validate_deck,
)
from autodeck.audit.verdicts import VerdictJudgement
from autodeck.ir.models import Claim, Slide
from tests.test_validation import (
    SUPPORT_QUOTE,
    Scripted,
    claim_block,
    deck_with,
    element,
    store_and_index,
    writer_citation,
)

OTHER_QUOTE = "latency is dominated by memory bandwidth rather than compute"


def _slide(store, texts: dict[str, str], quote: str = SUPPORT_QUOTE) -> Slide:  # type: ignore[no-untyped-def]
    blocks = [
        claim_block(bid, Claim(text=text, citations=[writer_citation(store, quote)]))
        for bid, text in texts.items()
    ]
    return Slide(id="s1", narrative_role="evidence", component="big_number", blocks=blocks)


def _supported(quote: str = SUPPORT_QUOTE) -> VerdictJudgement:
    return VerdictJudgement(verdict="supported", verdict_notes="ok", supporting_quote=quote)


def _env(tmp_path: Path):  # type: ignore[no-untyped-def]
    return store_and_index(tmp_path, element("e1", SUPPORT_QUOTE), element("e2", OTHER_QUOTE))


def test_fifteen_claims_are_one_call(tmp_path: Path) -> None:
    store, index = _env(tmp_path)
    texts = {f"b{i}": f"Claim number {i} about quantisation." for i in range(15)}
    model = Scripted({f"s1:{b}": _supported() for b in texts})
    result = validate_deck(
        deck_with(_slide(store, texts)), index=index, store=store, model=model
    )
    assert result.provider_calls == 1 and model.calls == 1
    assert len(result.claims_table) == 15
    assert all(c.verdict == "supported" for c in result.claims_table)


def test_a_tiny_budget_forces_more_batches(tmp_path: Path) -> None:
    store, index = _env(tmp_path)
    texts = {f"b{i}": f"Claim number {i} about quantisation." for i in range(4)}
    model = Scripted({f"s1:{b}": _supported() for b in texts})
    result = validate_deck(
        deck_with(_slide(store, texts)),
        index=index,
        store=store,
        model=model,
        batch_budget_tokens=1,
    )
    assert result.provider_calls == 4  # one oversized claim still gets its own batch
    assert len(result.claims_table) == 4


def test_a_budget_fitting_two_claims_makes_two_batches(tmp_path: Path) -> None:
    store, index = _env(tmp_path)
    texts = {f"b{i}": f"Claim number {i} about quantisation." for i in range(4)}
    probe = Scripted({})
    validate_deck(
        deck_with(_slide(store, {"b0": texts["b0"]})),
        index=index,
        store=store,
        model=probe,
    )
    one_claim_tokens = len(probe.prompts[0]) // 4
    model = Scripted({f"s1:{b}": _supported() for b in texts})
    result = validate_deck(
        deck_with(_slide(store, texts)),
        index=index,
        store=store,
        model=model,
        batch_budget_tokens=one_claim_tokens * 2,
    )
    assert result.provider_calls == 2


def test_max_batch_claims_is_respected(tmp_path: Path) -> None:
    store, index = _env(tmp_path)
    n = MAX_BATCH_CLAIMS + 5
    texts = {f"b{i}": f"Claim number {i} about quantisation." for i in range(n)}
    model = Scripted({f"s1:{b}": _supported() for b in texts})
    result = validate_deck(
        deck_with(_slide(store, texts)), index=index, store=store, model=model
    )
    assert BATCH_SIZE == MAX_BATCH_CLAIMS
    assert result.provider_calls == 2
    assert len(result.claims_table) == n


def _validated(tmp_path: Path, texts: dict[str, str]):  # type: ignore[no-untyped-def]
    store, index = _env(tmp_path)
    model = Scripted({f"s1:{b}": _supported() for b in texts})
    result = validate_deck(
        deck_with(_slide(store, texts)), index=index, store=store, model=model
    )
    return store, index, result.deck


def test_unchanged_deck_makes_zero_calls(tmp_path: Path) -> None:
    texts = {f"b{i}": f"Claim number {i} about quantisation." for i in range(3)}
    store, index, previous = _validated(tmp_path, texts)
    model = Scripted({})
    result = validate_deck(
        deck_with(_slide(store, texts)),
        index=index,
        store=store,
        model=model,
        previous=previous,
    )
    assert model.calls == 0 and result.provider_calls == 0
    assert result.reused == 3
    assert [c.verdict for c in result.claims_table] == ["supported"] * 3


def test_only_the_changed_claim_is_judged_and_the_rest_are_copied(tmp_path: Path) -> None:
    texts = {"b0": "Claim zero about quantisation.", "b1": "Claim one about quantisation."}
    store, index, previous = _validated(tmp_path, texts)
    prev_b0 = previous.slides[0].blocks[0].claim
    assert prev_b0 is not None

    changed = {"b0": texts["b0"], "b1": "Claim one, reworded entirely."}
    model = Scripted({"s1:b1": _supported()})
    result = validate_deck(
        deck_with(_slide(store, changed)),
        index=index,
        store=store,
        model=model,
        previous=previous,
    )
    assert result.provider_calls == 1 and result.reused == 1
    assert "Claim one, reworded entirely." in model.prompts[0]
    assert "s1:b0" not in model.prompts[0] and "Claim zero" not in model.prompts[0]
    new_b0 = result.deck.slides[0].blocks[0].claim
    assert new_b0 is not None
    assert (new_b0.verdict, new_b0.verdict_notes, new_b0.contradicting_spans) == (
        prev_b0.verdict,
        prev_b0.verdict_notes,
        prev_b0.contradicting_spans,
    )
    assert [c.block_id for c in result.claims_table] == ["b0", "b1"]


def test_a_changed_citation_is_not_reused(tmp_path: Path) -> None:
    texts = {"b0": "Claim zero about quantisation."}
    store, index, previous = _validated(tmp_path, texts)
    model = Scripted({"s1:b0": _supported()})
    result = validate_deck(
        deck_with(_slide(store, texts, quote=OTHER_QUOTE)),
        index=index,
        store=store,
        model=model,
        previous=previous,
    )
    assert result.reused == 0 and result.provider_calls == 1


def test_an_unverified_previous_claim_is_judged_again(tmp_path: Path) -> None:
    texts = {"b0": "Claim zero about quantisation."}
    store, index = _env(tmp_path)
    previous = deck_with(_slide(store, texts))  # never validated: verdict "unverified"
    model = Scripted({"s1:b0": _supported()})
    result = validate_deck(
        deck_with(_slide(store, texts)),
        index=index,
        store=store,
        model=model,
        previous=previous,
    )
    assert result.reused == 0 and result.provider_calls == 1
