"""D13 — grammar lints: word budgets, diagram/pileup composition, and icon adjacency.

`TestIR*` classes build `Deck`/`Slide`/`Block` and never render anything, the way
`test_framing_linter.py` and `test_numeric_linter.py` exercise their modules; a later
`TestIconAdjacency` class builds a real `pptx.Presentation` for the rendered pass. Each
blocking rule gets a "disable the defence, confirm red" test: a weaker, plausible-but-wrong
stand-in for the real check is run over the same fixture the real check catches, and is shown
to let it through — proving the specific thing the real check does is what is doing the work,
not an accident of the fixture.
"""

from __future__ import annotations

from autodeck.design.grammar import (
    EXCLUDED_CONCEPT_SLOTS,
    MAX_CONCEPTS_ADVISORY,
    MAX_DIAGRAMS_PER_SLIDE,
    PILEUP_KINDS,
    WORD_BUDGET_PER_MODE,
    check_concept_count,
    check_diagram_count,
    check_no_icon_chart_diagram_pileup,
    check_word_budget,
    lint_deck,
)
from autodeck.ir.models import (
    Block,
    ChartSeries,
    ChartSpec,
    Citation,
    Claim,
    Deck,
    DiagramSpec,
    IconRef,
    LabelFraming,
    ProcessFlowSpec,
    ProcessStep,
    Slide,
)

QUOTE = "Inference cost per request fell from $0.41 to $0.24 after the cutover."


def citation() -> Citation:
    return Citation.for_quote(
        doc_id="vendor-report",
        page=4,
        bbox=(10.0, 20.0, 300.0, 44.0),
        quote=QUOTE,
        retrieved_by="writer",
    )


def claim(text: str = "Inference cost per request fell by 41%.") -> Claim:
    return Claim(text=text, citations=[citation()])


def words(n: int, *, prefix: str = "w") -> str:
    """`n` distinct one-token words, so `str.split()` always finds exactly `n` of them."""
    return " ".join(f"{prefix}{i}" for i in range(n))


def text_block(block_id: str, n_words: int, *, slot: str = "body") -> Block:
    return Block(id=block_id, kind="framing", slot=slot, text=words(n_words))


def claim_block(block_id: str, n_words: int, *, slot: str = "body") -> Block:
    return Block(id=block_id, kind="claim", slot=slot, claim=claim(words(n_words)))


def diagram_block(
    block_id: str, *, num_steps: int = 2, words_per_label: int = 4, slot: str = "diagram"
) -> Block:
    """A `process_flow` diagram block, `num_steps` steps of `words_per_label` words each.

    `words_per_label` must stay at or under `GEOMETRIES["process_flow"].max_label_words`
    (4) — `DiagramSpec._labels_fit_the_budget` enforces that at construction, independent
    of anything this module checks.
    """
    steps = [
        ProcessStep(
            id=f"{block_id}n{i}",
            label=words(words_per_label, prefix="s"),
            order=i,
            framing=LabelFraming(reason="stage_name"),
        )
        for i in range(1, num_steps + 1)
    ]
    spec = DiagramSpec(
        relationship="sequence", kind="process_flow", process_flow=ProcessFlowSpec(steps=steps)
    )
    return Block(id=block_id, kind="diagram", slot=slot, diagram=spec)


def chart_block(block_id: str, *, slot: str = "chart") -> Block:
    spec = ChartSpec(
        chart_type="bar",
        categories=["Q1", "Q2"],
        series=[ChartSeries(name="cost", values=[1.0, 2.0])],
        source_citations=[citation()],
    )
    return Block(id=block_id, kind="chart", slot=slot, chart=spec)


def icon_block(block_id: str, *, slot: str = "icon") -> Block:
    return Block(
        id=block_id,
        kind="icon",
        slot=slot,
        icon=IconRef(concept="risk", glyph_id="circle-alert", color_token="accent1"),
    )


def slide_with(
    *blocks: Block,
    mode: str | None = None,
    notes: tuple[Block, ...] = (),
    slide_id: str = "s1",
) -> Slide:
    return Slide(
        id=slide_id,
        narrative_role="position",
        component="text_block",
        communication_mode=mode,  # type: ignore[arg-type]
        blocks=list(blocks),
        speaker_notes=list(notes),
    )


def deck_with(*slides: Slide) -> Deck:
    return Deck(
        run_id="r1",
        project="p",
        client="northwind-retail",
        audience="CTO",
        version=1,
        theme_ref="t",
        component_lib_version="1",
        slides=list(slides),
    )


# ---------------------------------------------------------------------------
# Word budgets
# ---------------------------------------------------------------------------


class TestWordBudget:
    def test_a_slide_within_its_modes_budget_passes(self) -> None:
        slide = slide_with(text_block("b1", 40), mode="text_led")
        assert check_word_budget(slide) == []

    def test_a_slide_over_its_modes_budget_blocks(self) -> None:
        slide = slide_with(text_block("b1", 95), mode="text_led")
        findings = check_word_budget(slide)
        assert [f.check for f in findings] == ["word budget"]
        assert findings[0].severity == "blocking"
        assert "95" in findings[0].detail

    def test_every_mode_uses_its_own_named_ceiling(self) -> None:
        assert WORD_BUDGET_PER_MODE == {
            "icon_anchored": 50,
            "diagram_led": 60,
            "text_led": 90,
        }
        for mode, ceiling in WORD_BUDGET_PER_MODE.items():
            assert check_word_budget(slide_with(text_block("b1", ceiling), mode=mode)) == []
            over = check_word_budget(slide_with(text_block("b1", ceiling + 1), mode=mode))
            assert over and over[0].severity == "blocking"

    def test_a_slide_with_no_communication_mode_is_not_checked(self) -> None:
        """Mode assignment is Phase 3b's decision (task 3b.7); a slide built before that
        pass has run has nothing to check its word count against yet."""
        slide = slide_with(text_block("b1", 1000), mode=None)
        assert check_word_budget(slide) == []

    def test_speaker_notes_do_not_count_towards_the_budget(self) -> None:
        """The budget is about what a reader scans on the slide face, not what the
        presenter reads aloud — unlike A5's fence, which follows a fact into the notes."""
        slide = slide_with(
            text_block("b1", 10), mode="text_led", notes=(text_block("n1", 500),)
        )
        assert check_word_budget(slide) == []

    def test_claim_text_counts_and_citations_do_not(self) -> None:
        slide = slide_with(claim_block("b1", 91), mode="text_led")
        findings = check_word_budget(slide)
        assert findings and findings[0].severity == "blocking"

    def test_a_diagrams_node_labels_count_towards_the_budget(self) -> None:
        """The real check, sanity case: a diagram-led slide whose block.text is small but
        whose diagram nodes carry real words is still over budget."""
        slide = slide_with(
            text_block("b1", 5),
            diagram_block("d1", num_steps=15, words_per_label=4),
            mode="diagram_led",
        )
        findings = check_word_budget(slide)
        assert findings and findings[0].severity == "blocking"

    def test_disable_the_defence_a_naive_count_that_ignores_diagram_text_goes_green(
        self,
    ) -> None:
        """Disable the defence, confirm red.

        The real check sums every text-bearing field, diagram node labels included. A
        narrower count that reads only `block.text`/`block.claim.text` — a plausible first
        cut at "word budget" — would report this diagram-led slide as 57 words (under the
        60-word ceiling) and pass it, when the diagram's own labels put it at 73.
        """
        slide = slide_with(
            text_block("b1", 57),
            diagram_block("d1", num_steps=4, words_per_label=4),
            mode="diagram_led",
        )

        def naive_word_count(block: Block) -> int:
            words_found = 0
            if block.text:
                words_found += len(block.text.split())
            if block.claim is not None:
                words_found += len(block.claim.text.split())
            return words_found

        naive_total = sum(naive_word_count(b) for b in slide.blocks)
        assert naive_total <= WORD_BUDGET_PER_MODE["diagram_led"], (
            "the naive count must itself read as passing for this to be a real defence test"
        )

        findings = check_word_budget(slide)
        assert findings and findings[0].severity == "blocking"
        assert naive_total < int(findings[0].detail.split()[0])


# ---------------------------------------------------------------------------
# Diagram count
# ---------------------------------------------------------------------------


class TestDiagramCount:
    def test_one_diagram_passes(self) -> None:
        slide = slide_with(diagram_block("d1"))
        assert check_diagram_count(slide) == []

    def test_two_diagrams_block(self) -> None:
        slide = slide_with(diagram_block("d1"), diagram_block("d2"))
        findings = check_diagram_count(slide)
        assert [f.check for f in findings] == ["diagram count"]
        assert findings[0].severity == "blocking"
        assert MAX_DIAGRAMS_PER_SLIDE == 1

    def test_disable_the_defence_trusting_the_declared_mode_goes_green(self) -> None:
        """Disable the defence, confirm red.

        A plausible-but-wrong stand-in: "this slide has a diagram problem only if its
        `communication_mode` says `diagram_led`". Two diagram blocks on a slide whose mode
        is something else (or unset) would sail through that version. The real check counts
        actual `kind="diagram"` blocks and does not consult the mode at all.
        """
        slide = slide_with(diagram_block("d1"), diagram_block("d2"), mode="text_led")

        def naive_has_diagram_problem(s: Slide) -> bool:
            return s.communication_mode == "diagram_led" and len(s.blocks) > 3

        assert naive_has_diagram_problem(slide) is False

        findings = check_diagram_count(slide)
        assert findings and findings[0].severity == "blocking"


# ---------------------------------------------------------------------------
# icon+chart+diagram pileup
# ---------------------------------------------------------------------------


class TestPileup:
    def test_icon_and_chart_alone_is_not_a_pileup(self) -> None:
        slide = slide_with(icon_block("i1"), chart_block("c1"))
        assert check_no_icon_chart_diagram_pileup(slide) == []

    def test_all_three_kinds_together_blocks(self) -> None:
        slide = slide_with(icon_block("i1"), chart_block("c1"), diagram_block("d1"))
        findings = check_no_icon_chart_diagram_pileup(slide)
        assert [f.check for f in findings] == ["icon+chart+diagram pileup"]
        assert findings[0].severity == "blocking"
        assert frozenset({"icon", "chart", "diagram"}) == PILEUP_KINDS

    def test_disable_the_defence_matching_on_component_name_goes_green(self) -> None:
        """Disable the defence, confirm red.

        A stand-in that infers a pileup from the component's *name* ("does it mention
        icon/chart/diagram?") would miss it on a generically named component that
        nonetheless carries all three block kinds. The real check reads block kinds
        directly and never looks at the component name.
        """
        slide = Slide(
            id="s1",
            narrative_role="position",
            component="custom_layout_7",
            blocks=[icon_block("i1"), chart_block("c1"), diagram_block("d1")],
        )

        def naive_pileup(s: Slide) -> bool:
            name = s.component.lower()
            return sum(k in name for k in ("icon", "chart", "diagram")) >= 2

        assert naive_pileup(slide) is False

        findings = check_no_icon_chart_diagram_pileup(slide)
        assert findings and findings[0].severity == "blocking"


# ---------------------------------------------------------------------------
# Concept count — advisory
# ---------------------------------------------------------------------------


class TestConceptCount:
    def test_within_the_brief_range_passes(self) -> None:
        slide = slide_with(*(text_block(f"b{i}", 3) for i in range(MAX_CONCEPTS_ADVISORY)))
        assert check_concept_count(slide) == []

    def test_over_the_ceiling_is_advisory_never_blocking(self) -> None:
        slide = slide_with(*(text_block(f"b{i}", 3) for i in range(MAX_CONCEPTS_ADVISORY + 3)))
        findings = check_concept_count(slide)
        assert [f.check for f in findings] == ["concept count"]
        assert findings[0].severity == "advisory"

    def test_the_source_slot_is_not_a_concept(self) -> None:
        assert frozenset({"source"}) == EXCLUDED_CONCEPT_SLOTS
        blocks = [text_block(f"b{i}", 3) for i in range(MAX_CONCEPTS_ADVISORY)]
        blocks.append(text_block("src", 3, slot="source"))
        slide = slide_with(*blocks)
        assert check_concept_count(slide) == []


# ---------------------------------------------------------------------------
# lint_deck — the IR-only pass, end to end
# ---------------------------------------------------------------------------


class TestLintDeck:
    def test_a_clean_deck_reports_nothing(self) -> None:
        deck = deck_with(
            slide_with(text_block("b1", 10), mode="text_led", slide_id="s1"),
            slide_with(diagram_block("d1"), mode="diagram_led", slide_id="s2"),
        )
        report = lint_deck(deck)
        assert report.findings == []
        assert report.slides_checked == 2
        assert report.blocks_build is False

    def test_findings_carry_the_slide_id_as_their_location(self) -> None:
        deck = deck_with(
            slide_with(text_block("b1", 200), mode="text_led", slide_id="bad-slide"),
        )
        report = lint_deck(deck)
        assert report.blocking
        assert "bad-slide" in report.blocking[0].location

    def test_advisory_findings_do_not_block_the_build(self) -> None:
        deck = deck_with(
            slide_with(
                *(text_block(f"b{i}", 2) for i in range(MAX_CONCEPTS_ADVISORY + 1)),
                slide_id="s1",
            )
        )
        report = lint_deck(deck)
        assert report.advisory and not report.blocking
        assert report.blocks_build is False
