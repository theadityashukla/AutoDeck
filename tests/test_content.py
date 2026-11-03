"""The content agent: citations resolved through the store, never composed by the model.

The load-bearing property is `test_a_model_supplied_page_and_hash_are_discarded` — a model
that names a real quote gets back the document store's own page/bbox/hash, never whatever
it typed. Everything else here is the failure modes that property has to survive: a
fabricated doc_id, an edited quote, a figure description offered as evidence, an
over-budget block, and a provider that falls over mid-slide.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.agents.content import (
    ContentDraft,
    ContentError,
    ProposedBlock,
    ProposedChart,
    ProposedChartSeries,
    ProposedCitation,
    ProposedClaim,
    ProposedDerivation,
    ProposedDerivationInput,
    resolve_blocks,
    write_slide,
)
from autodeck.design.fonts import is_available
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ingest.document_store import Document, DocumentElement, DocumentStore
from autodeck.ir.models import DeckBrief, KeyMessage, OpenRisk, Slide
from autodeck.knowledge.context_assembler import AssembledContext
from autodeck.knowledge.loader import CachedClaim
from autodeck.retrieval.hybrid import build_index

PROMPT = Path("prompts/content.md")
TOKENS_DIR = Path(__file__).resolve().parents[1] / "config" / "tokens"
TEST_FAMILY = "Liberation Sans"

requires_test_font = pytest.mark.skipif(
    not is_available(TEST_FAMILY), reason=f"{TEST_FAMILY} not installed"
)


def tokens_for() -> DesignTokens:
    base = DesignTokens.load(TOKENS_DIR / "dev.json")
    return base.model_copy(
        update={
            "typography": base.typography.model_copy(
                update={"major": TEST_FAMILY, "minor": TEST_FAMILY}
            )
        }
    )


class Scripted:
    """A fake `content` model that returns a fixed draft and records every prompt it saw."""

    def __init__(self, draft: ContentDraft) -> None:
        self.draft = draft
        self.prompts: list[str] = []
        self.systems: list[str | None] = []

    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        self.systems.append(system)
        return self.draft


class Broken:
    def complete_structured(self, prompt, response_model, *, system=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider down")


def element(
    element_id: str,
    text: str,
    *,
    doc_id: str = "paper-1",
    page: int = 1,
    kind: str = "text",
    description: str | None = None,
) -> DocumentElement:
    return DocumentElement(
        element_id=element_id,
        doc_id=doc_id,
        kind=kind,  # type: ignore[arg-type]
        page=page,
        bbox=(72.0, 100.0, 523.0, 200.0),
        reading_order=0,
        text=text,
        description=description,
    )


def store_with(tmp_path: Path, *elements: DocumentElement) -> DocumentStore:
    doc_id = elements[0].doc_id if elements else "paper-1"
    document = Document(
        doc_id=doc_id, source_path=f"{doc_id}.pdf", page_count=6, elements=list(elements)
    )
    store = DocumentStore(tmp_path)
    store.add(document)
    return store


def context() -> AssembledContext:
    return AssembledContext(
        client="northwind",
        project="llm-inference-efficiency",
        project_md="# Project\n\nServing cost for a 13B model.",
        client_md="# Northwind\n\nA mid-market retailer.",
        value_prop_md="Serve better before you buy more.",
    )


def brief(**overrides) -> DeckBrief:  # type: ignore[no-untyped-def]
    payload: dict[str, object] = {
        "run_id": "northwind-2026-08",
        "objective": "Decide whether to serve better or buy more GPUs.",
        "audience": "CTO",
        "key_messages": [
            KeyMessage(
                id="km1", text="Quantisation halves memory.", evidence_status="supported"
            ),
        ],
        "approved_by": "aditya",
    }
    payload.update(overrides)
    return DeckBrief(**payload)  # type: ignore[arg-type]


#: A component genuinely registered in the catalog (`closing_cta`, task 3a's component
#: fan-out, `6f2c3ae`) but never the one these fixtures write to: every block below fills
#: `slot="headline"`, so its other required slot (`cta`) is always left empty. That used to
#: matter here — before `is_missing_slot_finding` split `check_overflow`'s two finding kinds,
#: a missing required slot landed in `ContentResult.rejections` indistinguishably from a real
#: citation failure, which is exactly what broke every citation test below when
#: `closing_cta` was registered.
#: It is deliberately still exercised here, unchanged, rather than swapped for an
#: unregistered placeholder: these tests are about citation resolution, and a component that
#: is registered but genuinely incomplete for what the fixture writes is the more honest
#: case to pin than one that dodges the catalog entirely.
UNFILLED_COMPONENT = "closing_cta"

#: Genuinely absent from the catalog — used only by the one test that means to exercise that
#: gap. `agenda` served this role until task 3a's fan-out (`6f2c3ae`) registered it too.
UNREGISTERED_COMPONENT = "process_flow"


def slide(**overrides) -> Slide:  # type: ignore[no-untyped-def]
    payload: dict[str, object] = {
        "id": "s1",
        "narrative_role": "evidence",
        "component": UNFILLED_COMPONENT,
        "intent": "Establish that quantisation is the cheap first move.",
        "message_ids": ["km1"],
    }
    payload.update(overrides)
    return Slide(**payload)  # type: ignore[arg-type]


QUOTE = "LLM.int8() can cut the memory needed for inference by half."


def draft_with(
    *blocks: ProposedBlock, notes: list[ProposedBlock] | None = None
) -> ContentDraft:
    return ContentDraft(blocks=list(blocks), speaker_notes=notes or [])


def claim_block(
    block_id: str = "b1",
    *,
    slot: str = "headline",
    text: str = "Quantisation cuts the memory needed for inference by half.",
    doc_id: str = "paper-1",
    quote: str = QUOTE,
) -> ProposedBlock:
    return ProposedBlock(
        id=block_id,
        kind="claim",
        slot=slot,
        claim=ProposedClaim(
            text=text, citations=[ProposedCitation(doc_id=doc_id, quote=quote)]
        ),
    )


# ---------------------------------------------------------------------------
# Citations are resolved, never composed
# ---------------------------------------------------------------------------


def test_a_model_supplied_page_and_hash_are_discarded(tmp_path: Path) -> None:
    """The block that comes back carries the STORE's page and hash, not anything the model
    could have typed — the model schema does not even have a page or hash field."""
    store = store_with(tmp_path, element("e1", QUOTE, page=7))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(draft_with(claim_block()))

    result = write_slide(
        slide(),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert not result.rejections
    [block] = result.blocks
    assert block.claim is not None
    [citation] = block.claim.citations
    assert citation.page == 7
    assert citation.retrieved_by == "writer"
    assert citation.quote == QUOTE
    # The hash is computed from the resolved quote, not received from the model at all —
    # there is no field on `ProposedCitation` it could have arrived through.
    from autodeck.ir.models import quote_digest

    assert citation.quote_sha256 == quote_digest(QUOTE)


def test_a_fabricated_doc_id_drops_the_block_and_is_reported(tmp_path: Path) -> None:
    store = store_with(tmp_path, element("e1", QUOTE))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(draft_with(claim_block(doc_id="not-a-real-paper")))

    result = write_slide(
        slide(),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert result.blocks == []
    assert len(result.rejections) == 1
    assert "not-a-real-paper" in result.rejections[0]
    assert "not among the evidence shown" in result.rejections[0]


def test_an_edited_quote_does_not_resolve(tmp_path: Path) -> None:
    """Tidying a quote is exactly what A1 forbids — an edited quote must fail to resolve,
    not resolve against a nearby real one."""
    store = store_with(tmp_path, element("e1", QUOTE))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(draft_with(claim_block(quote="LLM.int8() halves memory usage.")))

    result = write_slide(
        slide(),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert result.blocks == []
    assert len(result.rejections) == 1


def test_a_curated_claim_resolves_through_cached_claim_to_citation(tmp_path: Path) -> None:
    store = store_with(tmp_path, element("e1", QUOTE, page=4))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    cached = CachedClaim(
        claim="Quantisation halves memory.", doc_id="paper-1", page=4, quote=QUOTE
    )
    model = Scripted(draft_with(claim_block()))

    result = write_slide(
        slide(message_ids=["km1"]),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[cached],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert not result.rejections
    [block] = result.blocks
    assert block.claim is not None
    assert block.claim.citations[0].page == 4


def test_a_figure_description_cannot_be_cited(tmp_path: Path) -> None:
    """§6.3, enforced in the resolver: a VLM description is retrievable, never citable, and
    the failure must be reported clearly rather than swallowed into a generic 'not found'."""
    figure = element(
        "fig1", text="", kind="figure", description="A bar chart showing memory halving."
    )
    store = store_with(tmp_path, figure)
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(draft_with(claim_block(quote="A bar chart showing memory halving.")))

    result = write_slide(
        slide(intent="A bar chart showing memory halving."),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert result.blocks == []
    assert len(result.rejections) == 1
    assert "not citable" in result.rejections[0]


def test_a_chart_blocks_source_citations_resolve_the_same_way(tmp_path: Path) -> None:
    store = store_with(tmp_path, element("e1", QUOTE, page=5))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    block = ProposedBlock(
        id="b1",
        kind="chart",
        slot="chart",
        chart=ProposedChart(
            chart_type="bar",
            categories=["FP16", "INT8"],
            series=[ProposedChartSeries(name="Memory (GB)", values=[26.0, 13.0])],
            source_citations=[ProposedCitation(doc_id="paper-1", quote=QUOTE)],
        ),
    )
    model = Scripted(draft_with(block))

    result = write_slide(
        slide(component="chart_focus"),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert not result.rejections
    [resolved] = result.blocks
    assert resolved.chart is not None
    assert resolved.chart.source_citations[0].page == 5


def test_a_derivation_input_citation_is_folded_into_the_claims_own_citations(
    tmp_path: Path,
) -> None:
    weights = "Weights use 65% of memory on a 13B model."
    kv_cache = "The KV cache uses close to 30% of memory."
    store = store_with(
        tmp_path,
        element("e1", weights, page=2),
        element("e2", kv_cache, page=3),
    )
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")

    block = ProposedBlock(
        id="b1",
        kind="claim",
        slot="headline",
        claim=ProposedClaim(
            text="Weights and the KV cache together are 95% of memory.",
            citations=[ProposedCitation(doc_id="paper-1", quote=weights)],
            derivation=ProposedDerivation(
                formula="weights + kv_cache",
                inputs={
                    "weights": ProposedDerivationInput(
                        value=65, citation=ProposedCitation(doc_id="paper-1", quote=weights)
                    ),
                    "kv_cache": ProposedDerivationInput(
                        value=30, citation=ProposedCitation(doc_id="paper-1", quote=kv_cache)
                    ),
                },
                result=95,
                unit="%",
            ),
        ),
    )
    model = Scripted(draft_with(block))

    result = write_slide(
        slide(),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert not result.rejections
    [resolved] = result.blocks
    # The kv_cache citation was never in the claim's own `citations` list — it arrived only
    # through the derivation input — and must still end up on the claim (A2's own rule:
    # `Claim._derivation_inputs_are_cited`).
    assert resolved.claim is not None
    quotes = {c.quote for c in resolved.claim.citations}
    assert quotes == {weights, kv_cache}


# ---------------------------------------------------------------------------
# Speaker notes get the same treatment
# ---------------------------------------------------------------------------


def test_speaker_notes_are_resolved_exactly_like_face_blocks(tmp_path: Path) -> None:
    store = store_with(tmp_path, element("e1", QUOTE, page=9))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(
        draft_with(claim_block("face"), notes=[claim_block("note1", slot="notes")])
    )

    result = write_slide(
        slide(),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert len(result.speaker_notes) == 1
    note = result.speaker_notes[0]
    assert note.claim is not None
    assert note.claim.citations[0].page == 9


def test_an_uncited_speaker_note_is_dropped_like_any_other_block(tmp_path: Path) -> None:
    store = store_with(tmp_path, element("e1", QUOTE))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(
        draft_with(
            claim_block("face"),
            notes=[claim_block("note1", slot="notes", doc_id="ghost-paper")],
        )
    )

    result = write_slide(
        slide(),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert result.speaker_notes == []
    assert any("note1" in r for r in result.rejections)


# ---------------------------------------------------------------------------
# A8 context reaches the prompt
# ---------------------------------------------------------------------------


def test_a_thin_message_and_its_open_risk_reach_the_prompt(tmp_path: Path) -> None:
    store = store_with(tmp_path, element("e1", QUOTE))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    the_brief = brief(
        key_messages=[
            KeyMessage(
                id="km1",
                text="Quantisation halves memory.",
                evidence_status="thin",
                probe_notes="single source",
            ),
        ],
        open_risks=[
            OpenRisk(
                message_id="km1",
                description="Only one paper measures this.",
                accepted_by="aditya",
            ),
        ],
    )
    model = Scripted(draft_with(claim_block()))

    write_slide(
        slide(),
        the_brief,
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    [prompt] = model.prompts
    assert "thin" in prompt
    assert "single source" in prompt
    assert "Only one paper measures this." in prompt
    assert "aditya" in prompt


# ---------------------------------------------------------------------------
# The header style profile reaches the writer (3a.8, D12)
# ---------------------------------------------------------------------------


def test_the_client_header_profile_reaches_the_prompt(tmp_path: Path) -> None:
    """`AssembledContext.header_profile` is loaded today and rendered nowhere — this pins
    that it now lands in the slide prompt the model actually reads, not just on the
    context object."""
    store = store_with(tmp_path, element("e1", QUOTE))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(draft_with(claim_block()))

    write_slide(
        slide(),
        brief(),
        AssembledContext(
            client="northwind",
            project="llm-inference-efficiency",
            project_md="# Project",
            client_md="# Northwind",
            value_prop_md="Serve better before you buy more.",
            header_profile={
                "style": "assertion",
                "max_words": 12,
                "avoid": ["revolutionary"],
            },
        ),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    [prompt] = model.prompts
    assert "Header style profile" in prompt
    assert "style: assertion" in prompt
    assert "max words: 12" in prompt
    assert "revolutionary" in prompt
    # The invariant the profile can never waive, restated in the writer's own prompt.
    assert "never lowers what needs support" in prompt


def test_a_header_style_override_changes_the_voice_not_the_clients_other_rules(
    tmp_path: Path,
) -> None:
    """`DeckBrief.header_style` is the one-flag switch: it swaps `style` only, and every
    other rule the client's `headers.yaml` set (here, the word budget) survives."""
    store = store_with(tmp_path, element("e1", QUOTE))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(draft_with(claim_block()))

    write_slide(
        slide(),
        brief(header_style="question_led"),
        AssembledContext(
            client="northwind",
            project="llm-inference-efficiency",
            project_md="# Project",
            client_md="# Northwind",
            value_prop_md="Serve better before you buy more.",
            header_profile={"style": "assertion", "max_words": 9},
        ),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    [prompt] = model.prompts
    assert "style: question_led" in prompt
    assert "question" in prompt.lower()
    assert "max words: 9" in prompt  # kept from the client's own profile


# ---------------------------------------------------------------------------
# Budgets checked before blocks are returned
# ---------------------------------------------------------------------------


@requires_test_font
def test_an_overbudget_block_is_rejected_before_render(tmp_path: Path) -> None:
    """The block's citation must actually resolve here, or the overflow check this test
    means to exercise never runs — a dropped-for-citation block leaves its slot empty, which
    `check_overflow` then reports as a *missing* slot, not an overflowing one, and the two
    used to be indistinguishable in `rejections` (a repeat of the fan-out bug this file's
    other tests hit, just via a quote whose vocabulary happened to share nothing with the
    slide's `intent` and so was never retrieved). A quote sharing `intent`'s vocabulary,
    repeated past the slot's budget, keeps this test pinned on overflow specifically."""
    long_quote = ("Quantisation cuts the memory needed for inference. " * 60).strip()
    store = store_with(tmp_path, element("e1", long_quote))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(
        draft_with(
            ProposedBlock(
                id="b1",
                kind="claim",
                slot="figure_label",
                claim=ProposedClaim(
                    text=long_quote,
                    citations=[ProposedCitation(doc_id="paper-1", quote=long_quote)],
                ),
            )
        )
    )

    result = write_slide(
        slide(component="big_number"),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert result.blocks == []
    assert result.budgets_checked is True
    [rejection] = result.rejections
    assert "overflow" in rejection
    assert "big_number.figure_label" in rejection
    assert "does not fit" in rejection
    # `headline`/`figure` were never filled by this fixture either, but leaving them blank
    # is a different event from figure_label overflowing — it belongs in incomplete_slots,
    # not folded into the same rejection count (see ContentResult.incomplete_slots).
    # `figure_label` is listed too: it is required, and its only block was just dropped, so
    # the slot really is empty afterwards (incomplete slots are read after the drops).
    assert {s.split(":", 1)[0] for s in result.incomplete_slots} == {
        "big_number.headline",
        "big_number.figure",
        "big_number.figure_label",
    }


@requires_test_font
def test_a_component_with_no_catalog_entry_skips_budgets_and_says_so(tmp_path: Path) -> None:
    store = store_with(tmp_path, element("e1", QUOTE))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")
    model = Scripted(draft_with(claim_block()))

    result = write_slide(
        slide(component=UNREGISTERED_COMPONENT),
        brief(),
        context(),
        store=store,
        index=index,
        claims=[],
        tokens=tokens_for(),
        model=model,
        prompt_path=PROMPT,
    )

    assert result.budgets_checked is False
    assert len(result.blocks) == 1


# ---------------------------------------------------------------------------
# Provider failure and other guards
# ---------------------------------------------------------------------------


def test_a_provider_failure_raises_rather_than_returning_an_empty_slide(tmp_path: Path) -> None:
    store = store_with(tmp_path, element("e1", QUOTE))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")

    with pytest.raises(ContentError):
        write_slide(
            slide(),
            brief(),
            context(),
            store=store,
            index=index,
            claims=[],
            tokens=tokens_for(),
            model=Broken(),
            prompt_path=PROMPT,
        )


def test_missing_prompt_file_raises(tmp_path: Path) -> None:
    store = store_with(tmp_path, element("e1", QUOTE))
    index = build_index([store.get("paper-1")], project="llm-inference-efficiency")

    with pytest.raises(ContentError):
        write_slide(
            slide(),
            brief(),
            context(),
            store=store,
            index=index,
            claims=[],
            tokens=tokens_for(),
            model=Scripted(draft_with(claim_block())),
            prompt_path=tmp_path / "no-such-prompt.md",
        )


# ---------------------------------------------------------------------------
# Budgets drop only the block at fault; structured rejections
# ---------------------------------------------------------------------------


def _framing(block_id: str, slot: str, text: str):  # type: ignore[no-untyped-def]
    from autodeck.ir.models import Block

    return Block(id=block_id, kind="framing", slot=slot, text=text)


@requires_test_font
def test_an_overflowing_item_drops_only_its_own_block() -> None:
    from autodeck.agents.content import check_budgets
    from autodeck.agents.rejections import Rejection

    blocks = [
        _framing("h", "headline", "A headline"),
        _framing("p0", "points", "x" * 60),
        _framing("p1", "points", "y" * 140),
        _framing("p2", "points", "z" * 70),
    ]
    records: list[Rejection] = []
    kept, rejections, incomplete, checked = check_budgets(
        blocks, component="bullets_supporting", tokens=tokens_for(), records=records,
        slide_id="s5",
    )
    assert checked is True and incomplete == []
    assert [b.id for b in kept] == ["h", "p0", "p2"]
    [rejection] = rejections
    assert "p1" in rejection and "140 characters" in rejection
    [record] = records
    assert (record.kind, record.block_id, record.item_index, record.slide_id) == (
        "overflow_item", "p1", 1, "s5"
    )
    assert record.detail["chars"] == 140 and record.detail["max_chars"] > 0


@requires_test_font
def test_a_stack_that_is_too_tall_sheds_blocks_from_the_end() -> None:
    from autodeck.agents.content import check_budgets
    from autodeck.agents.rejections import Rejection

    blocks = [_framing("h", "headline", "A headline")]
    blocks += [_framing(f"p{i}", "points", f"point {i}") for i in range(10)]
    records: list[Rejection] = []
    kept, rejections, _incomplete, _ = check_budgets(
        blocks, component="bullets_supporting", tokens=tokens_for(), records=records
    )
    # How many fit depends on the theme's type scale; what matters is that the stack keeps
    # its first items in order and sheds from the end.
    fitted = len(kept) - 1
    assert 3 <= fitted < 10
    assert [b.id for b in kept] == ["h", *(f"p{i}" for i in range(fitted))]
    assert [r.block_id for r in records] == [f"p{i}" for i in range(9, fitted - 1, -1)]
    assert {r.kind for r in records} == {"overflow_stack"}
    assert len(rejections) == 10 - fitted


@requires_test_font
def test_a_single_text_slot_that_overflows_is_overflow_text() -> None:
    from autodeck.agents.content import check_budgets
    from autodeck.agents.rejections import Rejection

    records: list[Rejection] = []
    kept, _rej, incomplete, _ = check_budgets(
        [_framing("h", "headline", "word " * 400), _framing("p0", "points", "fine")],
        component="bullets_supporting",
        tokens=tokens_for(),
        records=records,
    )
    assert [b.id for b in kept] == ["p0"]
    assert [r.kind for r in records if r.block_id == "h"] == ["overflow_text"]
    assert any("headline" in f for f in incomplete)
    assert any(r.kind == "missing_slot" and r.slot == "headline" for r in records)


@requires_test_font
def test_a_second_block_in_a_single_slot_is_rejected() -> None:
    """Run XLP3: two `takeaway` blocks on a callout reached the preview, which drew the
    whole slide as a placeholder. The first stays; the second is rejected for repair."""
    from autodeck.agents.content import check_budgets
    from autodeck.agents.rejections import Rejection

    records: list[Rejection] = []
    kept, rejections, _incomplete, _ = check_budgets(
        [
            _framing("l", "label", "Key takeaways"),
            _framing("t1", "takeaway", "The first takeaway"),
            _framing("t2", "takeaway", "A second takeaway"),
        ],
        component="callout_takeaway",
        tokens=tokens_for(),
        records=records,
    )
    assert [b.id for b in kept] == ["l", "t1"]
    [record] = records
    assert (record.block_id, record.kind) == ("t2", "overflow_text")
    assert record.detail["reason"] == "second_block_in_single_slot"
    assert "holds one block" in rejections[0]


@requires_test_font
def test_slots_that_fit_alone_but_not_together_drop_the_optional_part_first() -> None:
    """Design gallery: a big_number whose label and support each fit their own budget did not
    fit the figure block together, and the renderer crashed. The trial layout now drops the
    optional support first, and says why."""
    from autodeck.agents.content import check_budgets
    from autodeck.agents.rejections import Rejection

    words = "weight fell more on the tablet than on the comparator across the trial period "
    records: list[Rejection] = []
    kept, rejections, _incomplete, _ = check_budgets(
        [
            _framing("h", "headline", "Weight fell more on the tablet"),
            _framing("f", "figure", "Fell"),
            _framing("l", "figure_label", (words * 4)[:280].strip()),
            _framing("s", "support", (words * 8)[:520].strip()),
        ],
        component="big_number",
        tokens=tokens_for(),
        records=records,
    )
    assert [b.id for b in kept] == ["h", "f", "l"]
    [record] = records
    assert record.block_id == "s" and record.detail["reason"] == "slide_does_not_fit_as_a_whole"
    assert "does not fit as a whole" in rejections[0]


@requires_test_font
def test_list_slots_still_take_many_blocks() -> None:
    from autodeck.agents.content import check_budgets

    kept, rejections, _incomplete, _ = check_budgets(
        [_framing("h", "headline", "A headline")]
        + [_framing(f"p{i}", "points", f"point {i}") for i in range(4)],
        component="bullets_supporting",
        tokens=tokens_for(),
    )
    assert len(kept) == 5 and rejections == []


@requires_test_font
def test_a_block_in_no_slot_of_the_layout_is_unknown_slot() -> None:
    from autodeck.agents.content import check_budgets
    from autodeck.agents.rejections import Rejection

    records: list[Rejection] = []
    kept, rejections, _inc, _ = check_budgets(
        [_framing("h", "headline", "A headline"), _framing("x", "sidebar", "stray")],
        component="bullets_supporting",
        tokens=tokens_for(),
        records=records,
    )
    assert [b.id for b in kept] == ["h"]
    [record] = [r for r in records if r.block_id == "x"]
    assert record.kind == "unknown_slot" and "sidebar" in record.message
    assert any("'x'" in r for r in rejections)


@requires_test_font
def test_a_block_written_to_the_computed_source_slot_is_computed_slot() -> None:
    from autodeck.agents.content import check_budgets
    from autodeck.agents.rejections import Rejection

    records: list[Rejection] = []
    kept, _rej, _inc, _ = check_budgets(
        [_framing("h", "headline", "A headline"), _framing("src", "source", "Source: me")],
        component="bullets_supporting",
        tokens=tokens_for(),
        records=records,
    )
    assert [b.id for b in kept] == ["h"]
    assert [r.kind for r in records if r.block_id == "src"] == ["computed_slot"]


def test_a_rejection_is_json_serialisable_with_its_proposed_block() -> None:
    import json

    from autodeck.agents.rejections import Rejection

    proposed = claim_block("b9")
    record = Rejection(
        kind="quote_splice",
        where="face",
        slide_id="s3",
        block_id="b9",
        slot="chart",
        message="quote joined two passages",
        detail={"parts": [{"passage": 0, "coverage": 0.5}], "best_coverage": 0.5},
        proposed=proposed,
    )
    data = json.loads(json.dumps(record.to_dict()))
    assert data["kind"] == "quote_splice" and data["proposed"]["id"] == "b9"
    assert data["item_index"] is None


def test_a_quote_that_is_not_in_the_source_is_recorded_with_its_kind(tmp_path: Path) -> None:
    from autodeck.agents.rejections import Rejection
    from autodeck.retrieval.hybrid import RetrievedSpan

    store = store_with(tmp_path, element("e1", QUOTE, page=3))
    span = RetrievedSpan(
        doc_id="paper-1", element_id="e1", page=3, text=QUOTE, score=1.0, citable=True
    )
    records: list[Rejection] = []
    resolve_blocks(
        [claim_block(quote="Patients overwhelmingly preferred the tablet to injections.")],
        store=store, claims=[], spans=[span], location="slide s1 face", rejections=[],
        records=records, slide_id="s1",
    )
    [record] = records
    assert record.kind == "quote_not_found" and record.detail["doc_id"] == "paper-1"
    assert record.proposed is not None and record.slide_id == "s1"

    records.clear()
    resolve_blocks(
        [claim_block(doc_id="ghost")], store=store, claims=[], spans=[span],
        location="slide s1 face", rejections=[], records=records,
    )
    assert [r.kind for r in records] == ["doc_not_shown"]
