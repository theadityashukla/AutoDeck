"""B53: one bounded repair call, only when the draft lost something."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autodeck.agents.compose import ComposeResult, compose_deck
from autodeck.agents.content import ProposedBlock, ProposedClaim
from autodeck.agents.repair import BlockFix, Declined, RepairDraft
from autodeck.design.components.catalog import COMPONENT_LIB_VERSION
from tests.test_compose import (
    OTHER,
    QUOTE,
    TOKENS,
    Scripted,
    cite,
    claim_block,
    compose_draft,
    context,
    env,
    message,
    run_compose,
    slide,
)


def _compose(tmp_path: Path, model: Any) -> ComposeResult:
    store, pack = env(tmp_path)
    return compose_deck(
        "Make a deck.",
        answers=[],
        pack=pack,
        context=context(),
        store=store,
        tokens=TOKENS,
        model=model,
        run_id="r1",
        client="northwind",
        project="p",
        theme_ref="config/tokens/dev.json",
        component_lib_version=COMPONENT_LIB_VERSION,
    )


def _clean_draft():  # type: ignore[no-untyped-def]
    return compose_draft(
        key_messages=[message("km1", "Quantisation halves memory.", "prompt", QUOTE)],
        slides=[slide("s1", ["km1"], claim_block("b1", "Quantisation halves memory.", QUOTE))],
    )


def _fix(fid: str, block: ProposedBlock) -> RepairDraft:
    return RepairDraft(
        fixes=[BlockFix(failure_id=fid, blocks=[block])],
        declined=[],
        message_fixes=[],
        notes="",
    )


def _failure_id(model: Scripted, block_id: str) -> str:
    """The number the repair prompt gave the failure on `block_id`."""
    prompt = model.calls[1][0]
    for line in prompt.splitlines():
        if line.startswith("### f"):
            fid = line.split()[1]
        if line.startswith(f"block {block_id} "):
            return fid
    raise AssertionError(f"no failure listed for {block_id}")


def test_a_clean_draft_is_one_call(tmp_path: Path) -> None:
    result, model, _store, _pack = run_compose(tmp_path, _clean_draft(), repair=True)
    assert result.provider_calls == 1 and len(model.calls) == 1 and not result.repair_ran


def test_a_dropped_quote_is_repaired_in_one_more_call(tmp_path: Path) -> None:
    replacement = claim_block("b2", "Batching raises throughput.", OTHER, slot="quote")
    model = Scripted(compose_draft())
    # The failure id is only known once the prompt is built; script a lazy answer.
    original = model.complete_structured

    def answer(prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        if response_model is RepairDraft:
            model.calls.append((prompt, response_model, system))
            return _fix(_failure_id(model, "b2"), replacement)
        return original(prompt, response_model, system=system)

    model.complete_structured = answer  # type: ignore[method-assign]
    result = _compose(tmp_path, model)
    assert result.provider_calls == 2 and result.repair_ran
    s1 = next(s for s in result.deck.slides if s.id == "s1")
    assert [b.id for b in s1.blocks] == ["b1", "b2"]
    assert (
        s1.blocks[1].claim is not None
        and s1.blocks[1].claim.text == "Batching raises throughput."
    )
    assert any("b2" in line and "replaced" in line for line in result.repairs)
    assert not any(f.block_id == "b2" for f in result.failures)
    repair_system = model.calls[1][2]
    assert repair_system is not None and repair_system.startswith("# Repair")


def test_a_repair_with_a_bad_quote_is_still_dropped(tmp_path: Path) -> None:
    bad = claim_block("b2", "Still invented.", "Also not in any paper.")
    result, _model, _store, _pack = run_compose(
        tmp_path,
        compose_draft(),
        repair=True,
        then=[
            RepairDraft(
                fixes=[
                    BlockFix(failure_id="f1", blocks=[bad]),
                    BlockFix(failure_id="f2", blocks=[bad]),
                ],
                declined=[],
                message_fixes=[],
                notes="",
            )
        ],
    )
    assert result.provider_calls == 2
    s1 = next(s for s in result.deck.slides if s.id == "s1")
    assert [b.id for b in s1.blocks] == ["b1"]
    assert any(f.block_id == "b2" for f in result.failures)


def test_a_decline_keeps_the_failure_and_says_why(tmp_path: Path) -> None:
    declines = RepairDraft(
        fixes=[],
        declined=[
            Declined(failure_id="f1", reason="nothing in the evidence says this"),
            Declined(failure_id="f2", reason="nothing in the evidence says this"),
        ],
        message_fixes=[],
        notes="",
    )
    result, _model, _store, _pack = run_compose(
        tmp_path, compose_draft(), repair=True, then=[declines]
    )
    assert any("declined" in line for line in result.repairs)
    assert any(f.block_id == "b2" for f in result.failures)


def test_a_failed_repair_call_keeps_the_first_draft(tmp_path: Path) -> None:
    class Boom(Scripted):
        def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
            if response_model is RepairDraft:
                raise RuntimeError("provider down")
            return super().complete_structured(prompt, response_model, system=system)

    result = _compose(tmp_path, Boom(compose_draft()))
    assert result.provider_calls == 2
    assert any("repair call failed" in c for c in result.corrections)
    assert [b.id for b in result.deck.slides[0].blocks] == ["b1"]


def _a2_draft():  # type: ignore[no-untyped-def]
    """Run XLP's shape: a points claim whose number (0.8%) is in no cited span."""
    uncited = ProposedBlock(
        id="b2",
        kind="claim",
        slot="points",
        claim=ProposedClaim(
            text="Memory fell a further 0.8% on the comparator.", citations=[cite(QUOTE)]
        ),
    )
    good = ProposedBlock(
        id="b1",
        kind="claim",
        slot="points",
        claim=ProposedClaim(text="Quantisation halves memory.", citations=[cite(QUOTE)]),
    )
    header = ProposedBlock(
        id="h1", kind="section_header", slot="headline", text="Quantisation halves memory"
    )
    note = ProposedBlock(
        id="n1", kind="framing", slot="notes", text="The review covers 23 of 46 articles."
    )
    return compose_draft(
        key_messages=[message("km1", "Quantisation halves memory.", "prompt", QUOTE)],
        slides=[
            slide("s1", ["km1"], header, good, uncited, component="bullets_supporting")
            .model_copy(update={"speaker_notes": [note]})
        ],
    )


def test_a_block_still_failing_a_draft_check_after_repair_is_dropped(tmp_path: Path) -> None:
    """Run XLP: an uncited 0.8% and a framing note with numbers survived repair into the IR
    and only surfaced at the render gate. What still fails after the repair is dropped."""
    declines = RepairDraft(
        fixes=[],
        declined=[
            Declined(failure_id="f1", reason="no passage gives the figure"),
            Declined(failure_id="f2", reason="no passage gives the figure"),
        ],
        message_fixes=[],
        notes="",
    )
    result, _model, _store, _pack = run_compose(
        tmp_path, _a2_draft(), repair=True, then=[declines]
    )
    s1 = result.deck.slides[0]
    assert [b.id for b in s1.blocks] == ["h1", "b1"]
    assert s1.speaker_notes == []
    assert {f.block_id for f in result.failures} >= {"b2", "n1"}
    assert any("b2" in line and "dropped" in line for line in result.incomplete_slots)


def test_a_failing_block_is_dropped_with_repair_off_too(tmp_path: Path) -> None:
    result, *_ = run_compose(tmp_path, _a2_draft(), repair=False)
    assert [b.id for b in result.deck.slides[0].blocks] == ["h1", "b1"]
