"""A5 — the framing exemption, and what stops it widening.

`framing` is the only hole in A1, so these tests pull in both directions at once. Half of
them assert that real value-proposition language passes **untouched** — because a lint that
fires on "Serve better before you buy more" is one that gets switched off — and half assert
that a fact wearing framing's clothes is demoted and stops the build.

The load-bearing test is `test_the_invariants_adversarial_case_end_to_end`, which is
INVARIANTS' own wording: a framing block containing "clinically shown to cut costs 40%"
must be demoted to `claim` and then fail A1 for lack of citation. It asserts the whole
chain, including the part that matters most — that the demoted block is one the IR refuses
to construct, so the demotion cannot be quietly downgraded to a log line.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autodeck.audit.framing_linter import (
    COMPARATIVE_PATTERNS,
    FACTUAL_SUPERLATIVE_PATTERNS,
    NAMED_SOURCE_PATTERNS,
    Demotion,
    lint_block,
    lint_framing,
    lint_framing_text,
)
from autodeck.audit.numeric_linter import LintScope, lint_scope
from autodeck.ir.models import Block, Citation, Claim, Deck, Slide

#: Real framing from `knowledge/clients/northwind-retail/value_prop.md` and the register
#: `prompts/content.md` holds up as the model of an honest framing sentence. Every one of
#: these is a sentence about the engagement rather than about the world.
LEGITIMATE_FRAMING = [
    "Serve better before you buy more.",
    "Latency and throughput are separable for them.",
    "Sequence the techniques.",
    "The clearest way to think about this is as a serving-cost audit.",
    "The question is where the money actually goes before deciding what to fix.",
    "We read the primary literature and cite it.",
    "They are not short of GPUs. They are short of throughput per GPU.",
    "We separate what is measured from what is inferred, and say which is which.",
    "This needs an experiment on your data.",
]


def framing_block(text: str, *, block_id: str = "f1") -> Block:
    return Block(id=block_id, kind="framing", slot="body", text=text)


def deck_with(*blocks: Block, notes: tuple[Block, ...] = ()) -> Deck:
    return Deck(
        run_id="r1",
        project="p",
        client="northwind-retail",
        audience="CTO",
        version=1,
        theme_ref="t",
        component_lib_version="1",
        slides=[
            Slide(
                id="s1",
                narrative_role="position",
                component="text_block",
                blocks=list(blocks),
                speaker_notes=list(notes),
            )
        ],
    )


# ---------------------------------------------------------------------------
# The fence holds open
# ---------------------------------------------------------------------------


class TestLegitimateFramingPasses:
    """Catches: a lint so eager that real value-proposition language cannot be written.

    This is the failure that ends with A5 disabled. The exemption exists because these
    sentences are the argument of the deck and there is no paper to cite for any of them.
    """

    @pytest.mark.parametrize("text", LEGITIMATE_FRAMING)
    def test_real_framing_passes_untouched(self, text: str) -> None:
        """Catches: a false positive on the sentences A5 exists to permit."""
        assert lint_framing_text(text) == []

    def test_a_clean_framing_block_is_not_demoted(self) -> None:
        """Catches: a demotion that fires on a block with nothing wrong with it."""
        assert (
            lint_block(framing_block("Serve better before you buy more."), slide_id="s1")
            is None
        )

    def test_an_opinion_superlative_passes(self) -> None:
        """Catches: a grammatical '-est' detector replacing the closed list.

        "The clearest way to think about this" is a superlative and nothing could measure
        it. A detector that fired on the grammar would have to be argued down case by case
        until it caught nothing, which is why the table lists *factual* superlatives.
        """
        assert lint_framing_text("The clearest way to think about this") == []
        assert lint_framing_text("The fastest way to serve a model")


# ---------------------------------------------------------------------------
# The fence holds shut
# ---------------------------------------------------------------------------


class TestFabricatedFactsAreCaught:
    """Catches: a fact smuggled onto a slide by typing it as framing."""

    @pytest.mark.parametrize(
        ("text", "expected_check"),
        [
            ("Cuts serving cost by 40%.", "numeral in framing"),
            ("Three techniques, one outcome: 2x throughput.", "numeral in framing"),
            ("Dettmers et al. reached the same conclusion.", "named study or source"),
            ("The 2023 Stanford study agrees.", "named study or source"),
            ("According to Nature, the technique generalises.", "named study or source"),
            ("Research shows this approach wins.", "named study or source"),
            ("Peer-reviewed and ready for production.", "named study or source"),
            ("The fastest inference stack available.", "factual superlative"),
            ("Industry-leading throughput.", "factual superlative"),
            ("A proven approach.", "factual superlative"),
            ("Twice as efficient as their current stack.", "factual comparative"),
            ("Cheaper than what they run today.", "factual comparative"),
            ("It outperforms the incumbent.", "factual comparative"),
        ],
    )
    def test_each_kind_of_fabricated_fact_is_detected(
        self, text: str, expected_check: str
    ) -> None:
        """Catches: a whole category of fabricated fact silently going unchecked.

        Each row is one of the three things A5 names — a numeral, a named study, a
        comparative or superlative with factual content — so a table going missing shows up
        as its own row rather than as a slightly smaller pass rate.
        """
        checks = {finding.check for finding in lint_framing_text(text)}
        assert expected_check in checks, f"{text!r} produced {checks}"

    def test_a_finding_quotes_the_phrase_that_caused_it(self) -> None:
        """Catches: a finding that sends the writer hunting through a sentence.

        The fix for a demotion is to rewrite one phrase, so the finding names the phrase.
        """
        findings = lint_framing_text("Industry-leading throughput, clinically shown.")
        assert {f.fragment for f in findings} >= {"Industry-leading", "clinically shown"}

    def test_every_pattern_carries_its_justification(self) -> None:
        """Catches: a pattern added with nobody able to say why it is there.

        An unjustifiable pattern is one that loses the argument the first time it fires on
        a sentence that was fine, and the way that argument ends is with the check removed.
        """
        for entry in (
            *NAMED_SOURCE_PATTERNS,
            *FACTUAL_SUPERLATIVE_PATTERNS,
            *COMPARATIVE_PATTERNS,
        ):
            assert entry.why.strip(), f"{entry.name} has no justification"

    def test_a_cited_claims_own_text_is_not_linted(self) -> None:
        """Catches: A5 demoting correctly cited claims for saying 'faster than'.

        A5 fences uncited language. A claim making the same comparison has a span behind
        it, which is the whole difference, and running these patterns over `claim.text`
        would demote most of a good deck. Note what is being asserted: the block carries no
        free `text` of its own, only a cited `Claim`.
        """
        claim = Block(
            id="c1",
            kind="claim",
            slot="body",
            claim=Claim(
                text="It is 2-4x faster than the incumbent.", citations=[cited_comparison()]
            ),
        )
        assert lint_block(claim, slide_id="s1") is None


# ---------------------------------------------------------------------------
# The fence reads free text, not a kind
# ---------------------------------------------------------------------------


def cited_comparison() -> Citation:
    return Citation.for_quote(
        doc_id="kwon2023",
        page=4,
        bbox=(1.0, 1.0, 2.0, 2.0),
        quote="vLLM is 2-4x faster than the state-of-the-art systems.",
        retrieved_by="writer",
    )


FABRICATED = "The fastest stack available, proven to outperform every competitor."


class TestTheFenceAppliesToAnyBlocksFreeText:
    """The defect: `lint_block` returned at a `block.kind != "framing"` guard, so the whole
    A5 fence — superlatives, named studies, "proven to" — was bypassed for every other
    kind. `text` is not one of the payload fields `Block._payload_matches_kind` polices, so
    a `claim` block carrying both a cited `Claim` and that sentence constructs fine."""

    def claim_block_with_free_text(self, text: str = FABRICATED) -> Block:
        return Block(
            id="b1",
            kind="claim",
            slot="body",
            text=text,
            claim=Claim(text="It is faster.", citations=[cited_comparison()]),
        )

    def test_the_block_that_used_to_slip_through_still_constructs(self) -> None:
        """Not fixed by forbidding the shape — so the lint has to catch it."""
        block = self.claim_block_with_free_text()

        assert block.kind == "claim"
        assert block.text == FABRICATED

    def test_a_superlative_in_a_claim_blocks_text_is_demoted(self) -> None:
        demotion = lint_block(self.claim_block_with_free_text(), slide_id="s1")

        assert demotion is not None
        assert demotion.from_kind == "claim"
        assert {f.fragment for f in demotion.reasons} >= {
            "The fastest",
            "proven",
            "outperform",
        }
        assert demotion.blocks_render()
        assert demotion.verdict == "unsupported"

    def test_the_summary_does_not_call_a_claim_block_framing(self) -> None:
        """ "framing demoted to claim" is the wrong sentence about a `claim` block, and a
        reviewer who cannot find the framing block goes looking for a linter bug."""
        demotion = lint_block(self.claim_block_with_free_text(), slide_id="s1")

        assert demotion is not None
        assert "free text on a claim block is an uncited claim" in demotion.summary()

    def test_a_section_header_is_fenced_too(self) -> None:
        """The reason the fence is not a construction ban: `section_header` is a text kind,
        so forbidding `text` on non-`framing` blocks would have had to permit it."""
        header = Block(id="h1", kind="section_header", slot="title", text=FABRICATED)

        demotion = lint_block(header, slide_id="s1")

        assert demotion is not None
        assert demotion.from_kind == "section_header"

    def test_an_honest_heading_still_passes(self) -> None:
        """The fence tests language. A heading that asserts nothing about the world is
        untouched, exactly as a legitimate framing line is."""
        header = Block(
            id="h1", kind="section_header", slot="title", text="Where the money goes"
        )

        assert lint_block(header, slide_id="s1") is None

    def test_it_blocks_the_render_through_the_report(self) -> None:
        """End to end: the demotion reaches `blocks_build`, which is what the render guard
        and GATE 2 both read."""
        deck = deck_with(self.claim_block_with_free_text())

        report = lint_framing(deck)

        assert report.blocks_build
        assert [d.block_id for d in report.demotions] == ["b1"]
        assert report.framing_blocks_checked == 0, "there is no framing block on this deck"
        assert report.text_blocks_checked == 1

    def test_the_demoted_claim_block_still_cannot_be_constructed(self) -> None:
        """A1 refuses it in the IR's own validator, as for any other demotion."""
        demotion = lint_block(self.claim_block_with_free_text(), slide_id="s1")

        assert demotion is not None
        with pytest.raises(ValidationError):
            demotion.materialise()

    def test_restoring_the_kind_guard_lets_it_through(self) -> None:
        """Defence off, confirm red."""
        block = self.claim_block_with_free_text()
        assert lint_block(block, slide_id="s1") is not None

        def only_framing(b: Block, *, slide_id: str = "") -> Demotion | None:
            return None if b.kind != "framing" else lint_block(b, slide_id=slide_id)

        assert only_framing(block, slide_id="s1") is None


# ---------------------------------------------------------------------------
# Demotion is a state change
# ---------------------------------------------------------------------------


class TestDemotionIsRealStateChange:
    """Catches: demotion degenerating into a logged warning.

    INVARIANTS' "watch for" on A5 is exactly this. A warning leaves the sentence on the
    slide and puts one line in a log next to the forty lines that were fine.
    """

    def test_the_invariants_adversarial_case_end_to_end(self) -> None:
        """INVARIANTS, verbatim: demoted to `claim`, then failing A1 for lack of citation.

        Every link in the chain is asserted, because each one is a place the demotion could
        be quietly downgraded: the block is detected, the demotion says its new kind is
        `claim`, constructing that block against the real IR raises, the A3 verdict is
        `unsupported`, and the report blocks the build.
        """
        deck = deck_with(framing_block("Clinically shown to cut costs 40%."))
        report = lint_framing(deck)

        assert report.blocks_build
        demotion = report.demotion_for("f1")
        assert demotion is not None
        assert demotion.kind == "claim"
        assert demotion.verdict == "unsupported"
        assert demotion.blocks_render()

        with pytest.raises(ValidationError) as raised:
            demotion.materialise()
        assert "citations" in str(raised.value)
        assert "citations" in demotion.a1_error()

    def test_the_deck_alone_does_not_reveal_the_demotion(self) -> None:
        """Catches: a render guard that consults only the deck.

        The demoted block is one the IR cannot hold, so it is still sitting in the deck
        typed as `framing` and validating perfectly. `Deck.blocking_blocks()` is empty. A
        guard that asked the deck alone would render a slide asserting a clinical finding
        with no source — which is why `FramingReport.blocks_build` exists and why its
        docstring says it must be consulted *alongside* the deck, not instead of it.
        """
        deck = deck_with(framing_block("Clinically shown to cut costs 40%."))
        assert deck.blocking_blocks() == []
        assert lint_framing(deck).blocks_build

    def test_a1_error_raises_if_a1_has_been_weakened(self) -> None:
        """Catches: `Claim.citations` being relaxed and every demotion becoming a no-op.

        The tripwire. If a citation-free claim ever becomes constructible, `materialise()`
        succeeds, the demotion stops meaning anything, and the report would still cheerfully
        say `blocks_build`. `a1_error` raises instead, here, rather than downstream.
        """
        demotion = Demotion(
            slide_id="s1", block_id="f1", slot="body", text="anything", reasons=()
        )
        assert "citations" in demotion.a1_error()
        with pytest.raises(ValidationError):
            Claim(text="anything", citations=[])

    def test_a_demoted_block_then_fails_a2_on_its_numeral(self) -> None:
        """Catches: the two linters disagreeing about the same sentence.

        Once demoted, the block is a claim with no citations, so A2 sees a numeral with
        nothing to trace to. Both invariants land on the same sentence independently, and
        neither depends on the other having run — which is what makes the demotion robust
        to being skipped.
        """
        demotion = lint_framing(
            deck_with(framing_block("Clinically shown to cut costs 40%."))
        ).demotions[0]
        numeric = lint_scope(LintScope(location="demoted f1", text=demotion.text))
        assert not numeric.passes
        assert [f.check for f in numeric.blocking] == ["uncited numeral"]

    def test_framing_in_speaker_notes_is_fenced_too(self) -> None:
        """Catches: a linter iterating `slide.blocks` and missing the notes.

        "Nobody reads notes in the room" cuts both ways: an unsourced superlative is worse
        in the place the presenter is reading aloud from.
        """
        deck = deck_with(
            framing_block("Serve better before you buy more."),
            notes=(framing_block("It is twice as efficient.", block_id="n1"),),
        )
        report = lint_framing(deck)
        assert [d.block_id for d in report.demotions] == ["n1"]
        assert report.framing_blocks_checked == 2

    def test_a_clean_deck_reports_clean_and_blocks_nothing(self) -> None:
        """Catches: a report that cannot say 'nothing to see here'."""
        report = lint_framing(deck_with(framing_block("Serve better before you buy more.")))
        assert not report.blocks_build
        assert report.findings == []
        assert "right side of the fence" in report.render()

    def test_the_report_names_the_block_and_the_phrase(self) -> None:
        """Catches: a report a reviewer cannot act on."""
        rendered = lint_framing(
            deck_with(framing_block("Clinically shown to cut costs 40%."))
        ).render()
        assert "f1" in rendered
        assert "40%" in rendered
        assert "state change" in rendered
