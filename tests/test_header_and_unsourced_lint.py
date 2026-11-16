"""B54 talking headers, B55 unsourced fence and B56 comparatives in the A2/A5 linters."""

from __future__ import annotations

from autodeck.audit.framing_linter import lint_block, lint_framing, lint_header
from autodeck.audit.numeric_linter import lint_deck
from autodeck.ir.models import Block, Citation, Claim, Deck, Slide

QUOTE = "Oral semaglutide 14 mg reduced HbA1c by 1.3% versus placebo in PIONEER 1."


def _citation(quote: str = QUOTE) -> Citation:
    return Citation.for_quote(
        doc_id="andersen-2021", page=3, bbox=(0, 0, 1, 1), quote=quote, retrieved_by="writer"
    )


def _slide(header: str, *, cited: bool = True, kind: str = "section_header") -> Slide:
    blocks = [Block(id="h", kind=kind, slot="headline", text=header)]
    if cited:
        blocks.append(
            Block(
                id="b1",
                kind="claim",
                slot="points",
                claim=Claim(
                    text="In PIONEER 1, 14 mg reduced HbA1c by 1.3% versus placebo.",
                    citations=[_citation()],
                ),
            )
        )
    return Slide(
        id="s1", narrative_role="evidence", component="bullets_supporting", blocks=blocks
    )


def _deck(*slides: Slide, provenance: str = "strict") -> Deck:
    return Deck(
        run_id="r",
        project="p",
        client="c",
        audience="a",
        version=1,
        slides=list(slides),
        theme_ref="t",
        component_lib_version="1",
        provenance=provenance,  # type: ignore[arg-type]
    )


class TestTalkingHeaders:
    def test_backed_number_in_header_passes_both_linters(self) -> None:
        slide = _slide("Oral semaglutide cut HbA1c by 1.3% more than placebo in PIONEER 1")
        assert lint_header(slide.blocks[0], slide) is None
        assert lint_deck(_deck(slide)).passes

    def test_a_synthesis_header_with_a_comparative_passes(self) -> None:
        slide = _slide("Oral dosing matches injectable glucose control for most patients")
        assert lint_header(slide.blocks[0], slide) is None

    def test_number_not_on_the_slide_is_flagged(self) -> None:
        slide = _slide("Oral semaglutide cut HbA1c by 1.8% in PIONEER 1")
        demotion = lint_header(slide.blocks[0], slide)
        assert demotion is not None
        assert {r.fragment for r in demotion.reasons} == {"1.8%"}
        assert not lint_deck(_deck(slide)).passes

    def test_named_source_not_on_the_slide_is_flagged(self) -> None:
        slide = _slide("Davies et al. report lower HbA1c on oral dosing")
        demotion = lint_header(slide.blocks[0], slide)
        assert demotion is not None
        assert demotion.reasons[0].check == "header fact not on the slide"

    def test_header_on_a_slide_without_citations_keeps_the_full_fence(self) -> None:
        slide = _slide("The fastest route to glucose control", cited=False)
        assert lint_header(slide.blocks[0], slide) is not None

    def test_lint_framing_routes_headers_through_the_header_rule(self) -> None:
        slide = _slide("Oral semaglutide cut HbA1c by 1.3% more than placebo in PIONEER 1")
        assert not lint_framing(_deck(slide)).blocks_build


class TestComparatives:
    def test_live_run_takeaway_is_demoted(self) -> None:
        block = Block(
            id="t",
            kind="framing",
            slot="takeaway",
            text=(
                "Oral semaglutide demonstrates superior glycemic control and weight reduction "
                "compared to active comparators and placebo."
            ),
        )
        demotion = lint_block(block, slide_id="s6")
        assert demotion is not None
        checks = {r.fragment.lower() for r in demotion.reasons}
        assert "demonstrates" in checks
        assert any("compared" in c for c in checks)

    def test_engagement_framing_still_passes(self) -> None:
        block = Block(
            id="f",
            kind="framing",
            slot="takeaway",
            text="The question is where the cost actually sits before deciding what to change",
        )
        assert lint_block(block) is None


class TestUnsourced:
    def _unsourced(self, text: str) -> Slide:
        block = Block(
            id="u", kind="claim", slot="points", claim=Claim(text=text, basis="unsourced")
        )
        return Slide(
            id="s2", narrative_role="context", component="bullets_supporting", blocks=[block]
        )

    def test_qualitative_general_knowledge_passes(self) -> None:
        deck = _deck(
            self._unsourced("Incretin-based drugs act partly by slowing gastric emptying"),
            provenance="normal",
        )
        assert not lint_framing(deck).blocks_build
        assert lint_deck(deck).passes

    def test_appeal_to_unnamed_evidence_is_demoted(self) -> None:
        deck = _deck(
            self._unsourced("Studies show patients prefer tablets to injections"),
            provenance="normal",
        )
        report = lint_framing(deck)
        assert report.blocks_build
        assert "unsourced claim points at evidence" in report.demotions[0].summary()

    def test_numbers_in_unsourced_claims_fail_a2(self) -> None:
        deck = _deck(self._unsourced("Most patients start on a 3 mg dose"), provenance="normal")
        assert not lint_deck(deck).passes


class TestNamesWithDigits:
    """B58: digits inside names are not quantities."""

    def test_fused_digits_are_names(self) -> None:
        block = Block(id="f", kind="framing", slot="takeaway", text="HbA1c and GLP-1 matter")
        assert lint_block(block) is None

    def test_digit_first_words_are_still_quantities(self) -> None:
        block = Block(id="f", kind="framing", slot="takeaway", text="A 3x gain on 13B models")
        assert lint_block(block) is not None

    def test_glossary_terms_are_masked(self) -> None:
        block = Block(id="f", kind="framing", slot="takeaway", text="Treating type 2 diabetes")
        assert lint_block(block) is not None
        assert lint_block(block, terms=["Type 2 diabetes"]) is None

    def test_deck_terms_reach_both_linters(self) -> None:
        title = Block(
            id="t",
            kind="section_header",
            slot="title",
            text="Oral semaglutide in Type 2 diabetes",
        )
        slide = Slide(id="s1", narrative_role="title", component="title", blocks=[title])
        deck = _deck(slide).model_copy(update={"named_terms": ["Type 2 diabetes"]})
        assert not lint_framing(deck).blocks_build
        assert lint_deck(deck).passes
        bare = _deck(slide)
        assert lint_framing(bare).blocks_build and not lint_deck(bare).passes
