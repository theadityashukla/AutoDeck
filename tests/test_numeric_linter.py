"""A2 — the numeric linter, and the four ways a number gets onto a slide without a source.

The tests are grouped by the failure each one catches, because that is the only useful
index into a linter:

- **the normalisation table**, tested directly rather than through a lint run. INVARIANTS
  names it as where A2 leaks, and a table tested only end to end is a table whose broken
  entry is hidden by whichever other entry happened to match.
- **matching**, including the asymmetry that a derivation's result may be rounded and a
  cited number may not.
- **derivation re-execution**, including the test that disables the defence and confirms
  the deck goes green without it — proving the check is load-bearing, not decorative.
- **formula safety**, because `Derivation.formula` is model-generated text arriving from a
  provider and evaluating it would hand a content agent arbitrary Python.
- **speaker notes**, which are blocks and to which A1/A2 apply identically.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from autodeck.audit.numeric_linter import (
    ALLOWLIST,
    DATE_TABLE,
    MAX_FORMULA_NODES,
    SCALE_TABLE,
    SEPARATOR_RULES,
    UNIT_TABLE,
    AllowedNumeral,
    FormulaError,
    LintScope,
    check_derivation_inputs,
    evaluate_formula,
    extract_numerals,
    lint_deck,
    lint_rendered_slides,
    lint_scope,
    match_numerals,
    re_execute_derivation,
    suffix_allows_a_space,
)
from autodeck.ir.models import (
    Block,
    Citation,
    Claim,
    Deck,
    Derivation,
    DerivationInput,
    Slide,
)


def cite(quote: str, *, doc_id: str = "kwon2023", page: int = 4) -> Citation:
    return Citation.for_quote(
        doc_id=doc_id,
        page=page,
        bbox=(10.0, 20.0, 300.0, 40.0),
        quote=quote,
        retrieved_by="writer",
    )


def forms(text: str) -> set[tuple[Decimal, str]]:
    """Every normal key for the single numeral in `text`."""
    numerals = extract_numerals(text)
    assert len(numerals) == 1, f"{text!r} produced {len(numerals)} numerals, expected one"
    return set(numerals[0].forms | numerals[0].ambiguous_forms)


def normalises_onto(left: str, right: str) -> bool:
    """Whether the two texts carry the same numerals, compared numeral by numeral.

    Position-wise rather than as a union, so `2-4x` against `2-4\u00d7` is only a match when
    both endpoints match — a union would pass on the `4` alone.
    """
    left_numerals, right_numerals = extract_numerals(left), extract_numerals(right)
    if len(left_numerals) != len(right_numerals):
        return False
    return all(
        (a.forms | a.ambiguous_forms) & (b.forms | b.ambiguous_forms)
        for a, b in zip(left_numerals, right_numerals, strict=True)
    )


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
                narrative_role="evidence",
                component="text_block",
                blocks=list(blocks),
                speaker_notes=list(notes),
            )
        ],
    )


def claim_block(text: str, *citations: Citation, derivation: Derivation | None = None) -> Block:
    return Block(
        id="b1",
        kind="claim",
        slot="body",
        claim=Claim(text=text, citations=list(citations), derivation=derivation),
    )


# ---------------------------------------------------------------------------
# The normalisation table, tested on its own
# ---------------------------------------------------------------------------


class TestNormalisationTable:
    """Catches: a table entry that is wrong in a way no end-to-end lint would reveal.

    A lint run passes as long as *some* key matches, so a broken surface form hides behind
    a working one. These assert each form on its own.
    """

    def test_the_spec_headline_case_3_2M_matches_3_200_000(self) -> None:
        """Catches: a scale suffix that never expands, blocking every correct deck."""
        assert forms("3.2M") & forms("3,200,000")
        assert normalises_onto("3.2M", "3,200,000")

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("40%", "40 percent"),
            ("40%", "40 pct"),
            ("29ms", "29 ms"),
            ("29ms", "29 milliseconds"),
            ("2-4x", "2-4×"),
            ("12k", "12,000"),
            ("$3.2M", "3.2 million dollars"),
            ("13B", "13,000,000,000"),
            ("8GB", "8 gigabytes"),
            ("1,234.5", "1.234,5"),
            ("2023-11-14", "14 November 2023"),
            ("2023-11-14", "November 14, 2023"),
        ],
    )
    def test_format_variants_are_one_numeral(self, left: str, right: str) -> None:
        """Catches: a format the corpus uses and the slide does not, or the reverse.

        Every pair here is a real reformatting between a paper and a slide. If any of them
        stops matching, A2 blocks a deck whose numbers are all correctly copied — and the
        cheapest way out of that for a hurried builder is to weaken the invariant.
        """
        assert normalises_onto(left, right), f"{left!r} does not normalise onto {right!r}"

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("5 percent", "5 pp"),
            ("8GB", "8B"),
            ("30ms", "29ms"),
            ("2x", "2%"),
            ("2023-11-14", "2023-11-04"),
        ],
    )
    def test_different_numbers_do_not_normalise_together(self, left: str, right: str) -> None:
        """Catches: a table so eager that a wrong number matches a right one.

        `5 percent` against `5 percentage points` is the dangerous one — they read alike and
        mean different things, so folding them would let a writer substitute one for the
        other and still pass A2.
        """
        assert not normalises_onto(left, right), f"{left!r} wrongly normalises onto {right!r}"

    def test_every_scale_surface_multiplies(self) -> None:
        """Catches: a surface listed in the table that the scanner never reads.

        Walks `SCALE_TABLE` rather than sampling it, so an entry added later is tested by
        having been added.
        """
        for rule in SCALE_TABLE:
            for surface in rule.surfaces:
                text = f"7{surface}" if not suffix_allows_a_space(surface) else f"7 {surface}"
                assert (Decimal(7) * rule.multiplier, "") in forms(text), (
                    f"scale surface {surface!r} of {rule.name} did not multiply"
                )

    def test_every_unit_surface_reaches_its_canonical_form(self) -> None:
        """Catches: a unit alias in the table that matching never sees."""
        for rule in UNIT_TABLE:
            for surface in rule.surfaces:
                if surface in ("$", "us$", "£", "€", "usd", "eur", "gbp"):
                    text = f"{surface}7"
                else:
                    text = (
                        f"7{surface}" if not suffix_allows_a_space(surface) else f"7 {surface}"
                    )
                assert (Decimal(7), rule.canonical) in forms(text), (
                    f"unit surface {surface!r} did not reach {rule.canonical!r}"
                )

    def test_every_rule_carries_its_justification(self) -> None:
        """Catches: an entry added to the table without saying what leak it closes.

        The brief's rule for the allowlist — explicit, named, justified — applies to the
        normalisation table for the same reason: an unexplained entry is one nobody can
        argue with later.
        """
        for rule in (*SCALE_TABLE, *UNIT_TABLE, *DATE_TABLE, *SEPARATOR_RULES):
            assert rule.why.strip(), f"{rule} has no justification"

    def test_a_three_digit_tail_keeps_both_locale_readings(self) -> None:
        """Catches: a linter that silently picks a locale.

        `1,234` is 1234 in English and 1.234 in German. Both readings are kept and the
        minority one is marked, so a match that needs it is reported rather than accepted.
        """
        numeral = extract_numerals("1,234")[0]
        assert numeral.forms == {(Decimal(1234), "")}
        assert numeral.ambiguous_forms == {(Decimal("1.234"), "")}

    def test_a_non_three_digit_tail_is_unambiguously_decimal(self) -> None:
        """Catches: reading `1,5` as fifteen. No locale groups two digits."""
        assert forms("1,5") == {(Decimal("1.5"), "")}
        assert not extract_numerals("1,5")[0].ambiguous_forms

    def test_a_decimal_is_not_split_by_the_grouping_branch(self) -> None:
        """Catches: tokenising `1.2345` as `1.234` plus a stray `5`.

        A mis-tokenisation here invents a numeral that is in no source, so the linter would
        block a correct deck and point at a number the writer never wrote.
        """
        numerals = extract_numerals("1.2345")
        assert [n.text for n in numerals] == ["1.2345"]
        assert forms("1.2345") == {(Decimal("1.2345"), "")}

    def test_a_single_letter_scale_suffix_needs_no_space(self) -> None:
        """Catches: reading `5 m` as five million.

        The rule exists because `m` after a space is metres, minutes or the start of the
        next word far more often than it is a scale suffix, and guessing inflates a numeral
        by a million.
        """
        assert (Decimal(5_000_000), "") in forms("5m")
        assert (Decimal(5_000_000), "") not in forms("5 m")


# ---------------------------------------------------------------------------
# Extraction — recall, not judgement
# ---------------------------------------------------------------------------


class TestExtraction:
    """Catches: an extractor that has quietly learned to ignore things."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Runs on A100 hardware", ["100"]),
            ("quantised to int8", ["8"]),
            ("GPT-4 and GPT-4o", ["4", "4"]),
            ("2-4× throughput", ["2", "4×"]),
            ("a 65% share", ["65%"]),
            ("$3.2M of spend", ["$3.2M"]),
        ],
    )
    def test_numerals_embedded_in_words_are_still_numerals(
        self, text: str, expected: list[str]
    ) -> None:
        """Catches: an extractor taught that model names are 'obviously fine'.

        The day `A100` stops being extracted, so does the fabricated `A100` that was never
        measured. Whether a numeral is claim-bearing is the matcher's decision, not the
        extractor's.
        """
        assert [n.text for n in extract_numerals(text)] == expected

    def test_a_numeral_reports_the_word_it_sits_in(self) -> None:
        """Catches: a finding that says '100 does not trace' with no way to find it."""
        assert extract_numerals("Runs on A100 hardware")[0].context == "A100"

    def test_a_date_is_one_numeral_not_three(self) -> None:
        """Catches: `2023-11-14` blocking because its source wrote `14 November 2023`.

        Split into 2023, 11 and 14, a reformatted date supplies only two of the three parts
        and A2 blocks a correctly cited date.
        """
        assert [n.text for n in extract_numerals("published 2023-11-14")] == ["2023-11-14"]

    def test_a_decade_is_not_read_as_seconds(self) -> None:
        """Catches: `the 1980s` reported as 1980 seconds by the unit scanner."""
        numeral = extract_numerals("in the 1980s")[0]
        assert numeral.text == "1980s"
        assert (Decimal(1980), "") in numeral.forms

    def test_an_ambiguous_slashed_date_keeps_both_orders(self) -> None:
        """Catches: guessing that 03/04/2024 is 3 April rather than 4 March."""
        numeral = extract_numerals("dated 03/04/2024")[0]
        assert numeral.forms and numeral.ambiguous_forms


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestMatching:
    """Catches: a number reaching a slide without a source."""

    def test_a_numeral_with_no_cited_source_blocks(self) -> None:
        """Adversarial test (a): the plain fabrication.

        The citation is real and supports the sentence; the figure is not in it. This is
        what an invented number looks like in practice — everything around it checks out.
        """
        report = lint_scope(
            LintScope(
                location="slide s1",
                text="Serving costs fall by 42% under continuous batching.",
                citations=(cite("vLLM improves serving throughput by 2-4x."),),
            )
        )
        assert not report.passes
        assert [f.check for f in report.blocking] == ["uncited numeral"]
        assert "'42%'" in report.blocking[0].detail

    def test_a_format_variant_still_matches(self) -> None:
        """Adversarial test (c): `3.2M` in the text, `3,200,000` in the quote.

        The failure this guards against is the one that gets an invariant weakened: A2
        blocking a deck whose numbers are all correctly copied, just typed differently.
        """
        report = lint_scope(
            LintScope(
                location="slide s1",
                text="The estimate is 3.2M tokens per day.",
                citations=(cite("The workload processes 3,200,000 tokens per day."),),
            )
        )
        assert report.passes, report.render()

    def test_a_rounded_figure_does_not_match_a_cited_span(self) -> None:
        """Catches: `about 30ms` accepted against a span saying `29ms`.

        `prompts/content.md` is explicit that hedging never changes a digit. If rounding
        were tolerated on the citation path that instruction would be unenforceable, and
        the rounding-tolerant derivation path would be the only honest way to round.
        """
        report = lint_scope(
            LintScope(
                location="slide s1",
                text="Latency is about 30ms.",
                citations=(cite("Median latency was 29ms."),),
            )
        )
        assert not report.passes

    def test_a_derivation_result_may_be_the_rounded_computation(self) -> None:
        """Catches: blocking a writer who rounded their own arithmetic for a slide.

        The asymmetry with the test above is deliberate. A derived figure is computed here
        and the audit report shows the unrounded working; a copied figure has a source that
        either contains it or does not.
        """
        quote = cite("Spend rose from 412 to 671 units.")
        derivation = Derivation(
            formula="(after - before) / before * 100",
            inputs={
                "before": DerivationInput(value=412.0, citation=quote),
                "after": DerivationInput(value=671.0, citation=quote),
            },
            result=62.9,
            unit="%",
        )
        report = lint_scope(
            LintScope(
                location="slide s1",
                text="Spend rose 62.9%.",
                citations=(quote,),
                derivations=(derivation,),
            )
        )
        assert report.passes, report.render()
        assert [f.check for f in report.advisory] == ["derivation rounding"]

    def test_a_derivation_input_value_traces(self) -> None:
        """Catches: the working shown on the slide being treated as fabricated."""
        quote = cite("Weights take 65% of memory and the KV cache close to 30%.")
        derivation = Derivation(
            formula="weights + kv_cache",
            inputs={
                "weights": DerivationInput(value=65.0, citation=quote),
                "kv_cache": DerivationInput(value=30.0, citation=quote),
            },
            result=95.0,
            unit="%",
        )
        report = lint_scope(
            LintScope(
                location="slide s1",
                text="Weights (65%) and the KV cache (30%) are 95% of memory.",
                citations=(quote,),
                derivations=(derivation,),
            )
        )
        assert report.passes, report.render()

    def test_a_numeral_in_two_spans_is_reported_not_resolved(self) -> None:
        """Catches: a silent choice between two sources for one figure.

        The phase brief makes this an escalation trigger. A2 holds either way — the number
        was copied — but the audit report cannot say from where, so a human decides.
        """
        report = lint_scope(
            LintScope(
                location="slide s1",
                text="Throughput improves 2x.",
                citations=(
                    cite("vLLM improves throughput by 2x.", doc_id="kwon2023"),
                    cite("We measure a 2x gain.", doc_id="dettmers2022"),
                ),
            )
        )
        assert report.passes
        assert any(f.check == "numeral matches several spans" for f in report.advisory)

    def test_a_locale_ambiguous_match_is_reported(self) -> None:
        """Catches: `1.234` in a slide quietly matching `1,234` in a source."""
        report = lint_scope(
            LintScope(
                location="slide s1",
                text="It processed 1.234 requests.",
                citations=(cite("It processed 1,234 requests."),),
            )
        )
        assert report.passes
        assert any(f.check == "locale-ambiguous numeral" for f in report.advisory)

    def test_the_allowlist_is_empty_and_exact(self) -> None:
        """Catches: an allowlist growing a heuristic.

        The empty default is asserted so that adding an entry is a deliberate change with a
        test attached, and the mechanism is exercised so it still works when one is needed.
        """
        assert ALLOWLIST == ()
        scope = LintScope(location="slide s1", text="Slide 7 of 20")
        assert not lint_scope(scope).passes
        allowed = (
            AllowedNumeral("7", "page chrome in a Phase 3b render fixture"),
            AllowedNumeral("20", "page chrome in a Phase 3b render fixture"),
        )
        assert lint_scope(scope, allow=allowed).passes


# ---------------------------------------------------------------------------
# Derivation re-execution
# ---------------------------------------------------------------------------


def miscomputed_derivation() -> tuple[Citation, Derivation]:
    """Citations, inputs and units all correct; only the stated result is wrong."""
    quote = cite("Weights take 65% of memory and the KV cache close to 30%.")
    return quote, Derivation(
        formula="weights + kv_cache",
        inputs={
            "weights": DerivationInput(value=65.0, citation=quote),
            "kv_cache": DerivationInput(value=30.0, citation=quote),
        },
        result=115.0,
        unit="%",
    )


class TestDerivationReExecution:
    """Catches: arithmetic that nobody checked because every number in it was cited."""

    def test_a_miscomputed_derivation_blocks(self) -> None:
        """Adversarial test (b): the stated result is not what the formula computes."""
        quote, derivation = miscomputed_derivation()
        report = lint_scope(
            LintScope(
                location="slide s1",
                text="Weights and the KV cache are 115% of memory.",
                citations=(quote,),
                derivations=(derivation,),
            )
        )
        assert not report.passes
        assert [f.check for f in report.blocking] == ["derivation arithmetic"]
        assert "95.0" in report.blocking[0].detail

    def test_a_miscomputed_derivation_passes_without_re_execution(self) -> None:
        """Adversarial test (f): disable the defence and confirm the deck goes green.

        Matching alone accepts the figure, because the writer wrote 115 in the text and 115
        in the `result` field and the two agree. Every citation resolves, every input is
        cited, every numeral traces. Only re-running the arithmetic finds it — which is why
        `match_numerals` and `re_execute_derivation` are separate functions and why A2 is
        stated as "re-execute every derivation formula" rather than "check derivations".
        """
        quote, derivation = miscomputed_derivation()
        numerals = extract_numerals("Weights and the KV cache are 115% of memory.")
        matches, unmatched = match_numerals(
            numerals, citations=(quote,), derivations=(derivation,)
        )
        assert not unmatched
        assert [m.source for m in matches] == ["derivation_result"]

        # ...and with the check restored, the same derivation is blocking.
        assert re_execute_derivation(derivation)

    def test_a_gross_mismatch_is_not_excused_as_rounding(self) -> None:
        """Catches: the rounding tolerance swallowing a wrong number.

        `round(0.4, 0)` is `0.0`, so a rounding check on its own would accept a stated
        result of 0 for a computed 0.4. The relative-distance limit is what stops that.
        """
        quote = cite("Spend was 0.4 units.")
        derivation = Derivation(
            formula="a",
            inputs={"a": DerivationInput(value=0.4, citation=quote)},
            result=0.0,
            unit="",
        )
        findings = re_execute_derivation(derivation)
        assert [f.severity for f in findings] == ["blocking"]

    def test_an_integral_result_is_rounded_to_whole_numbers(self) -> None:
        """Catches: `result: 63` blocked for failing to equal 62.9.

        JSON gives `63` as the float `63.0`, whose repr suggests one decimal place. Reading
        the precision off the repr would demand 62.9 — a number nobody wrote.
        """
        quote = cite("Spend rose from 412 to 671 units.")
        derivation = Derivation(
            formula="(after - before) / before * 100",
            inputs={
                "before": DerivationInput(value=412.0, citation=quote),
                "after": DerivationInput(value=671.0, citation=quote),
            },
            result=63.0,
            unit="%",
        )
        findings = re_execute_derivation(derivation)
        assert [f.severity for f in findings] == ["advisory"]

    def test_an_input_value_absent_from_its_own_span_blocks(self) -> None:
        """Catches: a derivation laundering invented numbers through real citations.

        Everything about this derivation checks out separately. The citation resolves, it is
        among the claim's citations (the IR insists), the arithmetic is right, and the result
        matches the text. The only thing wrong is that 88 is not in the sentence it cites —
        so the figure traces to itself and to nothing else.
        """
        quote = cite("Weights take 65% of memory and the KV cache close to 30%.")
        derivation = Derivation(
            formula="weights + kv_cache",
            inputs={
                "weights": DerivationInput(value=88.0, citation=quote),
                "kv_cache": DerivationInput(value=30.0, citation=quote),
            },
            result=118.0,
            unit="%",
        )
        assert re_execute_derivation(derivation) == []
        findings = check_derivation_inputs(derivation)
        assert [f.check for f in findings] == ["derivation input"]
        assert "'weights'" in findings[0].detail

    def test_a_silent_unit_conversion_in_an_input_is_a_finding(self) -> None:
        """Catches: arithmetic done in the gap between a quote and a value.

        A span reading `0.65` and an input of `65` is a conversion, and A2's answer to
        arithmetic is that it is declared as a derivation with the working shown — not
        performed invisibly on the way into one.
        """
        quote = cite("The weights account for 0.65 of resident memory.")
        derivation = Derivation(
            formula="weights * 100",
            inputs={"weights": DerivationInput(value=65.0, citation=quote)},
            result=6500.0,
            unit="%",
        )
        assert [f.check for f in check_derivation_inputs(derivation)] == ["derivation input"]

    def test_division_by_zero_is_a_finding_not_a_crash(self) -> None:
        """Catches: one bad derivation taking the whole build down.

        A linter that raises where it should report stops being a linter at exactly the
        moment it is needed, and the pressure is then to skip it.
        """
        quote = cite("Baseline throughput was 0 tokens per second.")
        derivation = Derivation(
            formula="after / before",
            inputs={
                "before": DerivationInput(value=0.0, citation=quote),
                "after": DerivationInput(value=10.0, citation=quote),
            },
            result=99.0,
            unit="x",
        )
        findings = re_execute_derivation(derivation)
        assert [f.check for f in findings] == ["derivation formula"]
        assert "zero" in findings[0].detail


# ---------------------------------------------------------------------------
# Formula safety
# ---------------------------------------------------------------------------


class TestFormulaSafety:
    """Catches: a content agent executing Python inside the build.

    `Derivation.formula` is model-generated text arriving from a provider. Everything in
    this class is a string a compromised or confused provider could return, and every one of
    them must be reported rather than run.
    """

    @pytest.mark.parametrize(
        "formula",
        [
            "__import__('os').system('id')",
            "open('/etc/passwd').read()",
            "a.__class__.__mro__",
            "[x for x in range(10)]",
            "(lambda: 1)()",
            "a if a else 0",
            "a < 1",
            "f'{a}'",
            "a; b",
            "a and 1",
        ],
    )
    def test_anything_that_is_not_arithmetic_raises(self, formula: str) -> None:
        """Adversarial test (d): a formula containing something that is not arithmetic.

        The walker admits nodes rather than denying them, so a construct nobody thought of
        fails by not being on the list — the opposite of a denylist, which fails by omission.
        """
        with pytest.raises(FormulaError):
            evaluate_formula(formula, {"a": 2.0, "b": 3.0})

    def test_an_undeclared_name_raises_rather_than_resolving(self) -> None:
        """Catches: a formula reaching a builtin because nothing was in scope to stop it.

        `open` fails because it is not a declared input, not because a denylist happened to
        mention it. There is no namespace to forget to empty.
        """
        with pytest.raises(FormulaError, match="not a declared input"):
            evaluate_formula("open", {"a": 1.0})

    def test_an_exponent_bomb_raises_quickly(self) -> None:
        """Catches: `9**9**9` allocating until the process dies.

        Python integers are arbitrary precision, so on ints this is a denial of service in
        four tokens. Coercing every literal to float turns it into an OverflowError.
        """
        with pytest.raises(FormulaError):
            evaluate_formula("9 ** 9 ** 9", {})

    def test_an_oversized_expression_is_refused(self) -> None:
        """Catches: a pathological expression that is arithmetic all the way down."""
        with pytest.raises(FormulaError):
            evaluate_formula(" + ".join(["1"] * MAX_FORMULA_NODES), {})

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ("(a - b) / b * 100", 50.0),
            ("-a", -3.0),
            ("a ** 2", 9.0),
            ("(a + b) * (a - b)", 5.0),
            ("1.5 * a", 4.5),
        ],
    )
    def test_real_arithmetic_still_evaluates(self, formula: str, expected: float) -> None:
        """Catches: a walker so strict that legitimate derivations cannot be expressed."""
        assert evaluate_formula(formula, {"a": 3.0, "b": 2.0}) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


class TestEntryPoints:
    """Catches: A2 applying to slide faces and not to everything else on the slide."""

    def test_a_number_only_in_a_speaker_note_is_caught(self) -> None:
        """Adversarial test (e): notes are blocks and A1/A2 apply to them identically.

        INVARIANTS says notes are the most common place for an uncited number to hide, and
        a linter iterating `slide.blocks` rather than `slide.all_blocks()` would be blind to
        exactly that. The face here is clean; the note is not.
        """
        quote = cite("vLLM improves serving throughput by 2-4x.")
        face = claim_block("Throughput improves 2-4x.", quote)
        note = Block(
            id="n1",
            kind="claim",
            slot="notes",
            claim=Claim(text="Internally we measured 7.5x.", citations=[quote]),
        )
        report = lint_deck(deck_with(face, notes=(note,)))
        assert not report.passes
        assert [f.location for f in report.blocking] == ["slide s1 / notes block n1"]

    def test_framing_text_is_linted_too(self) -> None:
        """Catches: a numeral smuggled into a citation-exempt block.

        A `framing` block carries no citations, so any numeral in it is unmatched by
        construction. A5's linter demotes the block; A2 independently reports the number,
        and neither depends on the other having run.
        """
        block = Block(id="b1", kind="framing", slot="body", text="Cut costs by 40%.")
        report = lint_deck(deck_with(block))
        assert not report.passes

    def test_the_rendered_entry_point_catches_a_number_the_ir_never_had(self) -> None:
        """Catches: a figure that appears only after rendering.

        A2 runs twice on purpose. A component that formats a number, a template with one
        baked in, or a renderer-invented label never passed through the content agent and
        was never validated, so the IR pass cannot see it.
        """
        quote = cite("vLLM improves serving throughput by 2-4x.")
        deck = deck_with(claim_block("Throughput improves 2-4x.", quote))
        clean = lint_rendered_slides(deck, {"s1": "Throughput improves 2-4x."})
        assert clean.passes, clean.render()
        dirty = lint_rendered_slides(deck, {"s1": "Throughput improves 2-4x. Saving 38%."})
        assert not dirty.passes
        assert dirty.blocking[0].location == "slide s1 (rendered)"

    def test_rendered_text_for_an_unknown_slide_raises(self) -> None:
        """Catches: linting a render against the wrong deck and reporting it as clean."""
        deck = deck_with(Block(id="b1", kind="framing", slot="body", text="Serve better."))
        with pytest.raises(KeyError):
            lint_rendered_slides(deck, {"s99": "anything"})

    def test_a_diagram_node_label_is_not_a_hole_in_a2(self) -> None:
        """Catches: a number reaching a slide as a diagram label.

        A node label carries no citation unless it carries a `Claim`, and the IR now makes
        the alternative explicit rather than implicit: a label with no claim must declare
        itself framing. That closes the *accidental* hole — nobody can simply omit the
        evidence — and leaves this one, which is the deliberate version: "95% of memory"
        declared a category name. A2 is what catches it, and it still does. The IR says the
        diagram engine is not a loophole in A1; this is the same sentence about A2, and the
        declaration is a signature on a statement, not a proof of it.
        """
        from autodeck.ir.models import (
            DiagramSpec,
            LabelFraming,
            LayeredStackSpec,
            StackLayer,
        )

        def layer(node_id: str, label: str, level: int) -> StackLayer:
            return StackLayer(
                id=node_id,
                label=label,
                level=level,
                framing=LabelFraming(reason="category_name"),
            )

        deck = deck_with(
            Block(
                id="d1",
                kind="diagram",
                slot="diagram",
                diagram=DiagramSpec(
                    relationship="hierarchy_foundation",
                    kind="layered_stack",
                    layered_stack=LayeredStackSpec(
                        support="rests_on",
                        layers=[layer("n1", "Weights", 1), layer("n2", "95% of memory", 2)],
                    ),
                ),
            )
        )
        report = lint_deck(deck)
        assert not report.passes
        assert report.blocking[0].location.endswith("diagram node n2")

    def test_a_figure_caption_is_linted_against_the_figures_own_citation(self) -> None:
        """Catches: a numeral in a caption, where nobody thinks to look for one."""
        from autodeck.ir.models import FigureRef

        quote = cite("Figure 3 shows a 2-4x throughput gain.")
        block = Block(
            id="fig1",
            kind="figure",
            slot="figure",
            figure=FigureRef(asset_id="a1", caption="Throughput gain of 9x.", citation=quote),
        )
        assert not lint_deck(deck_with(block)).passes

    def test_a_chart_is_not_a_hole_in_a2(self) -> None:
        """Catches: numbers escaping A2 by being data rather than prose.

        D10 makes a chart a dense set of factual assertions, so its series values go through
        the same scope as a sentence, against the chart's own `source_citations`.
        """
        from autodeck.ir.models import ChartSeries, ChartSpec

        chart = Block(
            id="c1",
            kind="chart",
            slot="chart",
            chart=ChartSpec(
                chart_type="bar",
                categories=["baseline", "vLLM"],
                series=[ChartSeries(name="throughput", values=[1.0, 7.0])],
                source_citations=[cite("Baseline throughput is 1.0 and vLLM reaches 4.0.")],
            ),
        )
        report = lint_deck(deck_with(chart))
        assert not report.passes
