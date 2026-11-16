"""Compose and revise (3c.5, 3c.9): the model proposes, code resolves and audits.

Fake models only. The load-bearing tests: a key message's evidence status comes from what
its citations resolved to (never from the model), a code coverage finding overrides a model
claim of "covered", and a revision keeps every slide it was not asked to touch *identical*.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from autodeck.agents.compose import (
    ComposedMessage,
    ComposeDraft,
    ComposedSlide,
    ComposeError,
    CoverageNote,
    ReviseDraft,
    clarify,
    compose_deck,
    revise_deck,
)
from autodeck.agents.content import ProposedBlock, ProposedCitation, ProposedClaim
from autodeck.agents.evidence_pack import build_evidence_pack
from autodeck.agents.planner import Draft
from autodeck.design.components.catalog import COMPONENT_LIB_VERSION
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import KeyMessage
from autodeck.knowledge.loader import CachedClaim
from autodeck.retrieval.hybrid import build_index
from tests.test_content import context, element, store_with

QUOTE = "Quantisation reduces the memory required for inference by half on a 13B model."
OTHER = "Batching requests raises throughput under a fixed latency budget substantially."
PROMPT = "quantisation memory batching throughput"
TOKENS = DesignTokens.load(Path("config/tokens/dev.json"))


class Scripted:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, type, str | None]] = []

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.calls.append((prompt, response_model, system))
        return self.answers.pop(0)


def env(tmp_path: Path):  # type: ignore[no-untyped-def]
    store = store_with(tmp_path, element("e1", QUOTE, page=4), element("e2", OTHER, page=5))
    index = build_index([store.get("paper-1")], project="p")
    claims = [
        CachedClaim(claim="Quantisation halves memory.", doc_id="paper-1", page=4, quote=QUOTE)
    ]
    pack = build_evidence_pack(PROMPT, project_md="", claims=claims, index=index)
    return store, pack


def cite(quote: str) -> ProposedCitation:
    return ProposedCitation(doc_id="paper-1", quote=quote)


def claim_block(block_id: str, text: str, quote: str, slot: str = "headline") -> ProposedBlock:
    return ProposedBlock(
        id=block_id,
        kind="claim",
        slot=slot,
        claim=ProposedClaim(text=text, citations=[cite(quote)]),
    )


def slide(sid: str, message_ids: list[str], *blocks: ProposedBlock, component="quote"):  # type: ignore[no-untyped-def]
    return ComposedSlide(
        id=sid,
        narrative_role="evidence",
        component=component,
        intent=f"Make the point of {sid}.",
        message_ids=message_ids,
        blocks=list(blocks),
        speaker_notes=[],
    )


def message(mid: str, text: str, origin: str, *quotes: str) -> ComposedMessage:
    return ComposedMessage(
        id=mid, text=text, origin=origin, citations=[cite(q) for q in quotes]
    )  # type: ignore[arg-type]


def compose_draft(**overrides: Any) -> ComposeDraft:
    payload: dict[str, Any] = {
        "objective": "Decide whether to serve better.",
        "audience": "CTO",
        "length_target": 3,
        "key_messages": [
            message("km1", "Quantisation halves memory.", "prompt", QUOTE),
            message("km2", "Batching raises throughput.", "answer", OTHER),
            message("km3", "Cost falls by a third.", "prompt"),
            message("km4", "Both help together.", "proposed", QUOTE, OTHER),
        ],
        "must_include": [],
        "must_avoid": [],
        "slides": [
            slide(
                "s1",
                ["km1"],
                claim_block("b1", "Quantisation halves memory.", QUOTE),
                claim_block(
                    "b2",
                    "Invented sentence.",
                    "This quote is not in any paper at all.",
                    slot="quote",
                ),
            ),
            slide("s2", ["km2"], claim_block("b1", "Batching raises throughput.", OTHER)),
        ],
        "coverage": [],
        "notes": "",
    }
    payload.update(overrides)
    return ComposeDraft(**payload)


def run_compose(tmp_path: Path, draft: ComposeDraft, **kwargs: Any):  # type: ignore[no-untyped-def]
    store, pack = env(tmp_path)
    model = Scripted(draft, *kwargs.pop("then", ()))
    # These tests pin what one compose call resolves; the B53 repair call has its own tests,
    # which pass `repair=True` and script the repair answer with `then=`.
    kwargs.setdefault("repair", False)
    result = compose_deck(
        "Make a deck.",
        answers=kwargs.pop("answers", [("Audience?", "CTO")]),
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
        **kwargs,
    )
    return result, model, store, pack


def status_of(result, mid: str) -> str:  # type: ignore[no-untyped-def]
    return result.draft_brief.message(mid).evidence_status


def coverage_of(result, text: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return next(c for c in result.coverage if text in c["item"])


# -- compose --------------------------------------------------------------------------------


def test_compose_is_one_call_with_the_composer_prompt_and_catalog(tmp_path: Path) -> None:
    result, model, _store, pack = run_compose(tmp_path, compose_draft())
    assert result.provider_calls == 1 and len(model.calls) == 1
    prompt, schema, system = model.calls[0]
    assert schema is ComposeDraft
    assert system.startswith("# Compose") and "\n\n---\n\n" in system and "# Skills" in system
    assert "# Content" not in system
    assert pack.text in prompt
    assert "Audience?" in prompt and "bullets_supporting" in prompt


def test_unresolvable_block_is_dropped_with_a_rejection(tmp_path: Path) -> None:
    result, *_ = run_compose(tmp_path, compose_draft())
    s1 = result.deck.slides[0]
    assert [b.id for b in s1.blocks] == ["b1"]
    assert any("slide s1" in r and "b2" in r for r in result.rejections)
    # The kept claim carries a real, resolved citation.
    assert s1.blocks[0].claim.citations[0].page == 4


def test_key_message_evidence_is_computed_from_resolution(tmp_path: Path) -> None:
    result, *_ = run_compose(tmp_path, compose_draft())
    assert status_of(result, "km1") == "supported"  # one curated passage stays supported
    assert status_of(result, "km2") == "thin"  # one corpus passage
    assert status_of(result, "km3") == "unsupported"
    assert status_of(result, "km4") == "supported"
    km2, km3 = result.draft_brief.message("km2"), result.draft_brief.message("km3")
    assert km2.probe_notes == "one passage only: paper-1 p.5"
    assert km2.supporting_claims == ["paper-1"]
    assert "no passage in the evidence pack supports this" in km3.probe_notes
    assert km3.supporting_claims == []
    assert result.draft_brief.open_risks == []


def test_a_fabricated_message_citation_does_not_count(tmp_path: Path) -> None:
    draft = compose_draft(
        key_messages=[message("km1", "Made up.", "prompt", "A sentence nobody wrote.")]
    )
    result, *_ = run_compose(tmp_path, draft)
    assert status_of(result, "km1") == "unsupported"
    assert any("key message km1" in r for r in result.rejections)


def test_coverage_code_finding_overrides_a_model_covered(tmp_path: Path) -> None:
    draft = compose_draft(
        key_messages=[
            message("km1", "Quantisation halves memory.", "prompt", QUOTE),
            message("km2", "Batching raises throughput.", "answer", OTHER),
            message("km5", "Latency stays flat.", "prompt", QUOTE),
        ],
        coverage=[
            CoverageNote(item="Latency stays flat.", status="covered", detail="slide s9"),
            CoverageNote(item="Batching raises throughput.", status="covered", detail="s2"),
        ],
    )
    result, *_ = run_compose(tmp_path, draft)
    assert coverage_of(result, "Latency")["status"] == "left_out"
    thin = coverage_of(result, "Batching")
    assert thin["status"] == "hedged" and "slide s2" in thin["detail"]
    # The thin agreed message stays on its slide.
    assert "km2" in result.deck.slides[1].message_ids
    assert coverage_of(result, "Quantisation")["status"] == "covered"
    # One entry per item: the model's covered entries were replaced, not duplicated.
    assert sum("Latency" in c["item"] for c in result.coverage) == 1


def test_unsupported_agreed_message_is_a_gap_and_proposed_ones_are_not_reported(
    tmp_path: Path,
) -> None:
    result, *_ = run_compose(tmp_path, compose_draft())
    assert coverage_of(result, "Cost falls")["status"] == "gap"
    assert not any("Both help" in c["item"] for c in result.coverage)


def test_must_include_words_on_no_slide_is_left_out(tmp_path: Path) -> None:
    draft = compose_draft(must_include=["quantisation memory", "regulatory approval"])
    result, *_ = run_compose(tmp_path, draft)
    assert coverage_of(result, "regulatory")["status"] == "left_out"
    assert coverage_of(result, "quantisation memory")["status"] == "covered"


def test_unknown_component_is_dropped_and_recorded(tmp_path: Path) -> None:
    draft = compose_draft(
        slides=[
            slide("s1", ["km1"], claim_block("b1", "Quantisation halves memory.", QUOTE)),
            slide("s2", ["km2"], claim_block("b1", "x", OTHER), component="hologram"),
        ]
    )
    result, *_ = run_compose(tmp_path, draft)
    assert [s.id for s in result.deck.slides] == ["s1"]
    assert any("hologram" in c for c in result.corrections)


def test_chat_brief_messages_are_kept_verbatim_with_origin_chat(tmp_path: Path) -> None:
    chat = Draft(
        objective="Chat objective.",
        audience="The board",
        key_messages=[KeyMessage(id="km1", text="Quantisation halves memory.")],
        must_include=["memory"],
    )
    draft = compose_draft(
        objective="Composer's own objective.",
        key_messages=[
            message("m9", "Quantisation halves memory.  ", "proposed", QUOTE),
            message("m10", "Batching raises throughput.", "proposed", OTHER),
        ],
        slides=[
            slide("s1", ["m9"], claim_block("b1", "Quantisation halves memory.", QUOTE)),
            slide("s2", ["m10"], claim_block("b1", "Batching raises throughput.", OTHER)),
        ],
    )
    result, model, *_ = run_compose(tmp_path, draft, chat_brief=chat)
    assert "already agreed" in model.calls[0][0]
    brief = result.draft_brief
    assert brief.objective == "Chat objective." and brief.audience == "The board"
    kept = brief.message("km1")
    assert kept.text == "Quantisation halves memory."
    assert result.origins["km1"] == "chat"
    assert result.deck.slides[0].message_ids == ["km1"]
    assert "memory" in brief.must_include
    assert brief.message("m10") is not None  # the composer's own addition is still there


def test_a_provider_failure_is_a_compose_error_with_the_cause(tmp_path: Path) -> None:
    class Down:
        def complete_structured(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("provider down")

    store, pack = env(tmp_path)
    with pytest.raises(ComposeError) as caught:
        compose_deck(
            "x",
            answers=[],
            pack=pack,
            context=context(),
            store=store,
            tokens=TOKENS,
            model=Down(),
            run_id="r1",
            client="c",
            project="p",
            theme_ref="t",
            component_lib_version="1",
        )
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_a_missing_prompt_is_an_error_not_a_fallback(tmp_path: Path) -> None:
    store, pack = env(tmp_path)
    with pytest.raises(ComposeError, match="prompt not found"):
        compose_deck(
            "x",
            answers=[],
            pack=pack,
            context=context(),
            store=store,
            tokens=TOKENS,
            model=Scripted(),
            run_id="r1",
            client="c",
            project="p",
            theme_ref="t",
            component_lib_version="1",
            prompt_path=tmp_path / "nope.md",
        )


def test_clarify_is_one_call_over_prompt_context_and_pack(tmp_path: Path) -> None:
    from autodeck.agents.compose import Assumption, ClarifyResult

    _store, pack = env(tmp_path)
    model = Scripted(
        ClarifyResult(
            assumptions=[Assumption(topic="audience", statement="CTO.")], questions=[]
        )
    )
    out = clarify("Make a deck about memory.", pack=pack, context=context(), model=model)
    assert out.assumptions[0].topic == "audience"
    [(prompt, schema, system)] = model.calls
    assert schema is ClarifyResult and system.startswith("# Clarify")
    assert "Make a deck about memory." in prompt and pack.text in prompt


# -- revise ---------------------------------------------------------------------------------


def revise_draft(**overrides: Any) -> ReviseDraft:
    payload: dict[str, Any] = {
        "objective": "Decide whether to serve better.",
        "audience": "CTO",
        "length_target": 3,
        "key_messages": [
            message("km1", "Quantisation halves memory.", "prompt"),
            message("km2", "Batching raises throughput substantially.", "answer", OTHER, QUOTE),
        ],
        "must_include": [],
        "must_avoid": [],
        "changed_slides": [
            slide("s2", ["km2"], claim_block("b9", "Batching raises throughput.", OTHER))
        ],
        "removed_slide_ids": [],
        "order": ["s1", "s2"],
        "coverage": [],
        "reply": "Reworded slide two.",
    }
    payload.update(overrides)
    return ReviseDraft(**payload)


def revise(tmp_path: Path, result, draft: ReviseDraft):  # type: ignore[no-untyped-def]
    store, pack = env(tmp_path)
    return revise_deck(
        "Reword slide two.",
        deck=result.deck,
        draft_brief=result.draft_brief,
        origins=result.origins,
        pack=pack,
        context=context(),
        store=store,
        tokens=TOKENS,
        model=Scripted(draft),
    )


def test_revise_keeps_unchanged_slides_identical_and_bumps_the_version(tmp_path: Path) -> None:
    first, *_ = run_compose(tmp_path, compose_draft())
    kept = first.deck.slides[0]
    kept.blocks[0].claim.verdict = "supported"

    result = revise(tmp_path, first, revise_draft())

    assert result.deck.version == first.deck.version + 1
    assert result.deck.slides[0] is kept  # the very object: blocks and verdicts untouched
    assert result.deck.slides[0].blocks[0].claim.verdict == "supported"
    assert [b.id for b in result.deck.slides[1].blocks] == ["b9"]
    assert result.changed_slide_ids == ["s2"]
    assert result.reply == "Reworded slide two." and result.provider_calls == 1


def test_revise_keeps_unchanged_message_status_and_regrades_changed_ones(
    tmp_path: Path,
) -> None:
    first, *_ = run_compose(tmp_path, compose_draft())
    assert status_of(first, "km2") == "thin"
    result = revise(tmp_path, first, revise_draft())
    # km1 came back with no citations and the same text: it keeps its earlier status.
    assert result.draft_brief.message("km1") is first.draft_brief.message("km1")
    # km2's text changed and it now cites two passages: graded again.
    assert result.draft_brief.message("km2").evidence_status == "supported"


def test_revise_removes_and_validates_order(tmp_path: Path) -> None:
    first, *_ = run_compose(tmp_path, compose_draft())
    removed = revise(
        tmp_path, first, revise_draft(changed_slides=[], removed_slide_ids=["s2"], order=["s1"])
    )
    assert [s.id for s in removed.deck.slides] == ["s1"]

    bad = revise(tmp_path, first, revise_draft(order=["s2"]))
    assert [s.id for s in bad.deck.slides] == ["s1", "s2"]  # old order kept
    assert any("order" in n for n in bad.notes)

    new = revise(
        tmp_path,
        first,
        revise_draft(
            changed_slides=[slide("s3", ["km1"], claim_block("b1", "Quantisation.", QUOTE))],
            order=["s3", "s1", "s2"],
        ),
    )
    assert [s.id for s in new.deck.slides] == ["s3", "s1", "s2"]


def test_revise_recomputes_coverage(tmp_path: Path) -> None:
    first, *_ = run_compose(tmp_path, compose_draft())
    result = revise(
        tmp_path,
        first,
        revise_draft(
            coverage=[CoverageNote(item="Batching raises", status="covered", detail="s2")]
        ),
    )
    assert any(c["status"] == "covered" for c in result.coverage)
    # km1 (agreed) is served by s1, supported -> covered by code.
    assert coverage_of(result, "Quantisation")["status"] == "covered"


# -- structured failures, id clashes, unbuildable slides ----------------------------------


def test_failures_carry_the_structured_rejection_for_each_drop(tmp_path: Path) -> None:
    result, *_ = run_compose(tmp_path, compose_draft())
    [failure] = [f for f in result.failures if f.slide_id == "s1" and f.block_id == "b2"]
    assert failure.kind == "quote_not_found" and failure.where == "face"
    assert failure.block_id == "b2" and failure.slot == "quote"
    assert failure.proposed is not None and failure.proposed.id == "b2"
    assert failure.message in result.rejections
    # JSON-safe, including the model's own block.
    import json

    assert json.loads(json.dumps(failure.to_dict()))["proposed"]["id"] == "b2"


def test_a_speaker_note_id_clashing_with_a_face_block_is_renamed(tmp_path: Path) -> None:
    clash = ComposedSlide(
        id="s1",
        narrative_role="evidence",
        component="quote",
        intent="Make the point.",
        message_ids=["km1"],
        blocks=[claim_block("b1", "Quantisation halves memory.", QUOTE)],
        speaker_notes=[claim_block("b1", "Say it slowly.", QUOTE)],
    )
    result, *_ = run_compose(tmp_path, compose_draft(slides=[clash]))
    [built] = result.deck.slides
    assert [b.id for b in built.blocks] == ["b1"]
    assert [b.id for b in built.speaker_notes] == ["b1-n"]
    assert any("'b1-n'" in c for c in result.corrections)


def test_an_unbuildable_slide_is_dropped_with_ir_invalid_not_a_failed_stage(
    tmp_path: Path,
) -> None:
    # Two face blocks with one id: the IR refuses the slide, the stage must not.
    twin = slide(
        "s2",
        ["km2"],
        claim_block("b1", "Batching raises throughput.", OTHER),
        ProposedBlock(
            id="b1",
            kind="framing",
            slot="attribution",
            text="Twin id.",
        ),
    )
    good = slide("s1", ["km1"], claim_block("b1", "Quantisation halves memory.", QUOTE))
    result, *_ = run_compose(tmp_path, compose_draft(slides=[good, twin]))
    assert [s.id for s in result.deck.slides] == ["s1"]
    [failure] = [f for f in result.failures if f.kind == "ir_invalid"]
    assert failure.slide_id == "s2" and "could not be built" in failure.message
    assert any("could not be built" in r for r in result.rejections)


def test_revise_runs_the_draft_checks_on_rewritten_slides_and_drops_failures(
    tmp_path: Path,
) -> None:
    """A revision used to skip the B56 checks entirely: an uncited number in a rewritten slide
    reached the IR. Only rewritten slides are checked; untouched ones keep their verdicts."""
    first, *_ = run_compose(tmp_path, compose_draft())
    bad = claim_block("b9", "Batching raises throughput by 0.8%.", OTHER, slot="points")
    good = claim_block("b8", "Batching raises throughput.", OTHER, slot="points")
    draft = revise_draft(
        changed_slides=[slide("s2", ["km2"], good, bad, component="bullets_supporting")]
    )
    result = revise(tmp_path, first, draft)
    s2 = next(s for s in result.deck.slides if s.id == "s2")
    assert [b.id for b in s2.blocks] == ["b8"]
    assert any(f.block_id == "b9" and f.kind == "numeral_unmatched" for f in result.failures)
    assert result.deck.slides[0] is first.deck.slides[0]
