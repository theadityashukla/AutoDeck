"""A6/A8 — the audit report: the verdict, the quote, the working, and both sides.

Four tests carry the phase brief's done-whens, and each is written so that a green run is
evidence the report *shows* the thing rather than that the fixture happened to be agreeable:

- `test_every_derived_figure_shows_its_working` — formula, every named input **with that
  input's own citation and quote**, and the result. A derived number whose inputs are not
  individually traceable is asserted, not audited.
- `test_an_input_absent_from_its_span_is_marked_in_the_working` — the same working with
  `check_derivation_inputs`' answer switched to False, so the tick in the test above is
  proved to be reporting something rather than printed unconditionally.
- `test_a_conflict_shows_both_sides_and_does_not_average` — asserts the averaged figure is
  **absent** from the output. A8's failure is not "forgot to mention the conflict", it is
  "silently reconciled it", and only the absence test catches that.
- `test_open_risks_are_resurfaced_with_who_accepted_them` — plan §7: the gap is not allowed
  to disappear.

The rest of the file is mostly about what the report refuses to imply: an unrun linter is
not a count of zero, an empty conflicts section is not agreement, and a missing brief is a
hole rather than a clean bill.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autodeck.audit.framing_linter import lint_framing
from autodeck.audit.numeric_linter import check_derivation_inputs, lint_deck
from autodeck.audit.report import (
    DOES_NOT_ESTABLISH,
    AuditReportError,
    build_audit_report,
    render,
    write_report,
)
from autodeck.audit.verdicts import (
    ValidatorEvidence,
    VerdictJudgement,
    VerdictReport,
    assess_claim,
)
from autodeck.ir.models import (
    Block,
    Citation,
    Claim,
    Deck,
    DeckBrief,
    Derivation,
    DerivationInput,
    DiagramSpec,
    KeyMessage,
    LabelFraming,
    OpenRisk,
    ProcessFlowSpec,
    ProcessStep,
    RetrievedBy,
    Slide,
    Verdict,
)

NEW_STACK = "Throughput on the new stack is 480 requests per second."
OLD_STACK = "The previous stack sustained 300 requests per second."
COST_DOWN = "Migrating the workload cut run cost by 40 percent over the quarter."
COST_UP = "After migration the same workload cost 10 percent more to run."


def citation(
    quote: str,
    *,
    doc_id: str = "bench",
    page: int = 3,
    retrieved_by: RetrievedBy = "writer",
) -> Citation:
    return Citation.for_quote(
        doc_id=doc_id,
        page=page,
        bbox=(72.0, 100.0, 523.0, 200.0),
        quote=quote,
        retrieved_by=retrieved_by,
    )


def derived_claim(*, input_a: float = 480.0) -> Claim:
    """A claim whose figure is computed from two separately cited numbers.

    `input_a` is a parameter so one test can make the value disagree with the span it
    cites — the case `check_derivation_inputs` exists to catch.
    """
    new = citation(NEW_STACK, doc_id="bench", page=3)
    old = citation(OLD_STACK, doc_id="bench", page=2)
    return Claim(
        text="Throughput rose 60 percent after the migration.",
        citations=[new, old],
        derivation=Derivation(
            formula="(a - b) / b * 100",
            inputs={
                "a": DerivationInput(value=input_a, citation=new),
                "b": DerivationInput(value=300.0, citation=old),
            },
            result=60.0,
            unit="percent",
        ),
        verdict="supported",
    )


def contradicted_claim() -> Claim:
    """A claim with a perfectly valid citation that another document refutes."""
    return Claim(
        text="Migration cut run cost by 40 percent.",
        citations=[citation(COST_DOWN, doc_id="vendor-report", page=11)],
        verdict="contradicted",
        verdict_notes="The finance extract reports a cost increase over the same period.",
        contradicting_spans=[
            citation(COST_UP, doc_id="finance-extract", page=4, retrieved_by="validator")
        ],
    )


def claim_block(block_id: str, claim: Claim, *, slot: str = "body") -> Block:
    return Block(id=block_id, kind="claim", slot=slot, claim=claim)


def deck(*slides: Slide, run_id: str = "r1") -> Deck:
    return Deck(
        run_id=run_id,
        project="inference-migration",
        client="acme",
        audience="CTO and platform leads",
        version=2,
        slides=list(slides),
        theme_ref="acme/v1",
        component_lib_version="0.3.0",
    )


def one_slide_deck(*blocks: Block, notes: list[Block] | None = None) -> Deck:
    return deck(
        Slide(
            id="s1",
            narrative_role="evidence",
            component="stat_pair",
            intent="establish that the migration paid for itself",
            blocks=list(blocks),
            speaker_notes=notes or [],
            message_ids=["m1"],
        )
    )


def brief(*, risks: list[OpenRisk] | None = None, run_id: str = "r1") -> DeckBrief:
    return DeckBrief(
        run_id=run_id,
        version=3,
        objective="Decide whether to migrate the remaining workloads.",
        audience="CTO and platform leads",
        key_messages=[
            KeyMessage(
                id="m1",
                text="The migration pays for itself within two quarters.",
                evidence_status="thin" if risks else "supported",
            )
        ],
        open_risks=risks or [],
        approved_by="owner",
    )


# ---------------------------------------------------------------------------
# The claims table — slide, claim, verdict, doc, page, verbatim quote
# ---------------------------------------------------------------------------


def test_the_claims_table_carries_slide_claim_verdict_doc_page_and_quote() -> None:
    """A6's own list. The quote is the point: a reader checks it without opening the IR."""
    report = build_audit_report(
        one_slide_deck(claim_block("b1", derived_claim())), brief=brief()
    )
    text = render(report)

    assert "`s1`" in text
    assert "Throughput rose 60 percent after the migration." in text
    assert "supported" in text
    assert "`bench` p.3" in text
    assert NEW_STACK in text, "the verbatim quote must be printed, not summarised"


def test_the_quote_is_printed_verbatim_rather_than_flattened_into_a_cell() -> None:
    """A quote reformatted to fit a table is no longer the thing A1 asks a reader to check."""
    quote = "Line one of the span.\nLine two carries the figure: 480 requests per second."
    claim = Claim(text="The span says so.", citations=[citation(quote)], verdict="supported")
    text = render(build_audit_report(one_slide_deck(claim_block("b1", claim)), brief=brief()))

    assert "> Line one of the span." in text
    assert "> Line two carries the figure: 480 requests per second." in text


def test_speaker_note_claims_appear_and_are_marked_as_notes() -> None:
    """A1 applies to notes; a reviewer needs to know which sentences the room will not see."""
    note = Claim(
        text="The finance extract is the weaker of the two sources.",
        citations=[citation(COST_DOWN, doc_id="vendor-report", page=11)],
        verdict="partially_supported",
    )
    report = build_audit_report(
        one_slide_deck(claim_block("b1", derived_claim()), notes=[claim_block("n1", note)]),
        brief=brief(),
    )
    text = render(report)

    assert report.summary.claims == 2
    assert "notes" in text
    assert "The finance extract is the weaker of the two sources." in text


def test_a_diagram_node_claim_is_audited_like_any_other() -> None:
    """The diagram engine is not a loophole in A1, so it is not one in the report either."""
    node_claim = Claim(
        text="Cost fell after the cutover.",
        citations=[citation(COST_DOWN, doc_id="vendor-report", page=11)],
        verdict="supported",
    )
    block = Block(
        id="b1",
        kind="diagram",
        slot="body",
        diagram=DiagramSpec(
            relationship="sequence",
            kind="process_flow",
            process_flow=ProcessFlowSpec(
                steps=[
                    ProcessStep(
                        id="n1",
                        label="Cutover",
                        order=1,
                        framing=LabelFraming(reason="stage_name"),
                    ),
                    ProcessStep(id="n2", label="Cost falls", order=2, claim=node_claim),
                ]
            ),
        ),
    )
    report = build_audit_report(one_slide_deck(block), brief=brief())

    assert [row.block_id for row in report.claim_rows()] == ["b1/n2"]
    assert "Cost fell after the cutover." in render(report)


# ---------------------------------------------------------------------------
# The working, shown — the phase brief's done-when
# ---------------------------------------------------------------------------


def test_every_derived_figure_shows_its_working() -> None:
    """Formula, named inputs **with each input's own citation**, and the result.

    The per-input citation is the load-bearing half. A derivation printed as
    `(a - b) / b * 100 = 60` tells the reader nothing they can check; a derived number whose
    inputs are not individually traceable is asserted rather than audited.
    """
    report = build_audit_report(
        one_slide_deck(claim_block("b1", derived_claim())), brief=brief()
    )
    text = render(report)

    assert "(a - b) / b * 100 = 60 percent" in text
    assert "`a` = 480" in text
    assert "`b` = 300" in text
    assert "`bench` p.3" in text and "`bench` p.2" in text
    assert NEW_STACK in text, "input a's own span"
    assert OLD_STACK in text, "input b's own span"
    assert "appears in the span above" in text

    working = report.workings()[0][1]
    assert working.fully_traced
    assert working.arithmetic_agrees
    assert report.summary.derivation_inputs_traced == 2


def test_an_input_absent_from_its_span_is_marked_in_the_working() -> None:
    """The same working with the input value changed to one its span does not contain.

    Without this test the tick in `test_every_derived_figure_shows_its_working` could be
    printed unconditionally and nobody would know.
    """
    claim = derived_claim(input_a=999.0)
    report = build_audit_report(one_slide_deck(claim_block("b1", claim)), brief=brief())
    text = render(report)

    working = report.workings()[0][1]
    assert not working.fully_traced
    assert report.summary.derivation_inputs_traced == 1
    assert "does not appear in the span above" in text


def test_the_working_agrees_with_the_linter_about_what_is_traceable() -> None:
    """One definition of "the value is in the span", read by the linter and by the report.

    If these two ever disagree the report prints a tick under a build A2 has blocked, which
    is the failure the shared `derivation_input_is_traceable` exists to prevent.
    """
    for value in (480.0, 999.0):
        claim = derived_claim(input_a=value)
        assert claim.derivation is not None
        report = build_audit_report(one_slide_deck(claim_block("b1", claim)), brief=brief())
        findings = check_derivation_inputs(claim.derivation)
        assert report.workings()[0][1].fully_traced is (not findings)


def test_a_formula_that_will_not_re_execute_is_shown_as_such() -> None:
    """A derivation nobody can reproduce is indistinguishable from an invented number."""
    new = citation(NEW_STACK)
    claim = Claim(
        text="Throughput rose sharply.",
        citations=[new],
        derivation=Derivation(
            formula="a / 0",
            inputs={"a": DerivationInput(value=480.0, citation=new)},
            result=60.0,
            unit="percent",
        ),
        verdict="supported",
    )
    report = build_audit_report(one_slide_deck(claim_block("b1", claim)), brief=brief())

    working = report.workings()[0][1]
    assert working.recompute_error is not None
    assert not working.arithmetic_agrees
    assert "failed" in render(report)


# ---------------------------------------------------------------------------
# Conflicts (A8) — both sides, attributed, not averaged
# ---------------------------------------------------------------------------


def test_a_conflict_shows_both_sides_and_does_not_average() -> None:
    """A8's failure is not omission, it is silent reconciliation.

    So the assertion that matters is the negative one: 25 — the mean of the two figures the
    sources give — must not appear anywhere in the report.
    """
    report = build_audit_report(
        one_slide_deck(claim_block("b1", contradicted_claim())), brief=brief()
    )
    text = render(report)

    assert report.summary.conflicts == 1
    assert COST_DOWN in text, "the source the deck cites"
    assert COST_UP in text, "the source that disagrees with it"
    assert "`vendor-report` p.11" in text
    assert "`finance-extract` p.4" in text
    assert "disagree" in text
    # Hash prefixes are hex and will contain any two digits eventually; the question is
    # whether the report's own prose ever names a reconciled figure.
    prose = "\n".join(line for line in text.splitlines() if "sha256" not in line)
    assert "25" not in prose, "the report must not reconcile two sources into one figure"


def test_a_contradicted_claim_keeps_the_citation_it_contradicts() -> None:
    """Dropping the half that agreed would erase what the contradiction contradicts."""
    report = build_audit_report(
        one_slide_deck(claim_block("b1", contradicted_claim())), brief=brief()
    )
    conflict = report.conflicts[0]

    assert [c.doc_id for c in conflict.cited] == ["vendor-report"]
    assert [c.doc_id for c in conflict.contradicting] == ["finance-extract"]


def test_an_empty_conflicts_section_does_not_claim_the_sources_agree() -> None:
    """Only contradictions the validator's search actually surfaced can appear here."""
    text = render(
        build_audit_report(one_slide_deck(claim_block("b1", derived_claim())), brief=brief())
    )
    assert "no contradicting span" in text
    assert "not that the corpus agrees with itself" in text


def test_contradicting_spans_from_the_validator_reach_the_conflicts_section() -> None:
    """End to end from `assess_claim`: what A3 recorded is what A8 prints."""
    writer = citation(COST_DOWN, doc_id="vendor-report", page=11)
    validator = citation(COST_UP, doc_id="finance-extract", page=4, retrieved_by="validator")
    claim = Claim(text="Migration cut run cost by 40 percent.", citations=[writer])
    assessment = assess_claim(
        claim,
        evidence=ValidatorEvidence([validator]),
        judgement=VerdictJudgement(
            verdict="contradicted",
            verdict_notes="The finance extract reports the opposite direction.",
            contradicting_quotes=[COST_UP],
        ),
    )
    report = build_audit_report(
        one_slide_deck(claim_block("b1", assessment.apply(claim))), brief=brief()
    )

    assert report.summary.conflicts == 1
    assert COST_UP in render(report)


# ---------------------------------------------------------------------------
# Open risks — the gap that is not allowed to disappear
# ---------------------------------------------------------------------------


def risk(*, mitigation: str | None = "Hedge the payback period in the slide text.") -> OpenRisk:
    return OpenRisk(
        message_id="m1",
        description="No source gives a payback period for a workload of this size.",
        accepted_by="j.okafor",
        mitigation=mitigation,
    )


def test_open_risks_are_resurfaced_with_who_accepted_them() -> None:
    """Plan §7 Phase 2a: the gap *is not allowed to disappear*. This is where it reappears."""
    report = build_audit_report(
        one_slide_deck(claim_block("b1", derived_claim())), brief=brief(risks=[risk()])
    )
    text = render(report)

    assert report.summary.open_risks == 1
    assert "j.okafor" in text
    assert "No source gives a payback period for a workload of this size." in text
    assert "Hedge the payback period in the slide text." in text
    assert "slide `s1`" in text, "which slide now carries the message the gap qualifies"


def test_a_risk_with_no_mitigation_says_so_rather_than_leaving_a_blank() -> None:
    report = build_audit_report(
        one_slide_deck(claim_block("b1", derived_claim())),
        brief=brief(risks=[risk(mitigation=None)]),
    )
    assert "none recorded" in render(report)


def test_a_risk_whose_message_no_slide_serves_is_still_printed() -> None:
    """The risk that has been written out of the deck is the one that must still appear."""
    empty = deck(
        Slide(id="s1", narrative_role="evidence", component="stat_pair", message_ids=["m2"])
    )
    report = build_audit_report(empty, brief=brief(risks=[risk()]))
    text = render(report)

    assert report.risks[0].slides == ()
    assert "no slide serves this message" in text


def test_risks_come_from_the_brief_and_not_from_the_deck() -> None:
    """A report assembled without a brief must say so, not print an empty section."""
    text = render(
        build_audit_report(one_slide_deck(claim_block("b1", derived_claim())), brief=None)
    )

    assert "No brief was supplied" in text
    assert "not a statement that the deck carries no risks" in text


def test_a_brief_from_another_run_is_refused() -> None:
    with pytest.raises(AuditReportError):
        build_audit_report(
            one_slide_deck(claim_block("b1", derived_claim())), brief=brief(run_id="r2")
        )


# ---------------------------------------------------------------------------
# The summary, and what it refuses to imply
# ---------------------------------------------------------------------------


def test_the_summary_counts_claims_by_verdict_including_the_zeroes() -> None:
    """`contradicted 0` is a result; an omitted row reads like a check that never ran."""
    report = build_audit_report(
        one_slide_deck(
            claim_block("b1", derived_claim()), claim_block("b2", contradicted_claim())
        ),
        brief=brief(),
    )
    text = render(report)

    assert report.summary.verdicts["supported"] == 1
    assert report.summary.verdicts["contradicted"] == 1
    assert report.summary.verdicts["unverified"] == 0
    assert "unverified 0" in text
    assert report.summary.blocking_claims == 1
    assert "bars final render" in text


def test_a_linter_that_did_not_run_is_not_reported_as_a_count_of_zero() -> None:
    """The `unverified` vs `unsupported` distinction, applied to the report's own inputs."""
    report = build_audit_report(
        one_slide_deck(claim_block("b1", derived_claim())), brief=brief()
    )
    text = render(report)

    assert report.summary.unmatched_numerals is None
    assert report.summary.demotions is None
    assert "the numeric linter did not run for this report" in text
    assert "the framing linter did not run for this report" in text


def test_linter_reports_are_summarised_when_they_did_run() -> None:
    built = one_slide_deck(claim_block("b1", derived_claim()))
    report = build_audit_report(
        built, brief=brief(), numeric=lint_deck(built), framing=lint_framing(built)
    )
    text = render(report)

    assert report.summary.numerals_checked is not None
    assert report.summary.unmatched_numerals == 0
    assert report.summary.demotions == 0
    assert "## Numeric lint (A2)" in text
    assert "## Framing lint (A5)" in text


def test_an_uncited_numeral_is_counted_and_listed() -> None:
    """A2's pass condition is *zero unmatched numerals* — read off, not derived from a list."""
    claim = Claim(
        text="Throughput rose 60 percent and latency fell to 12 milliseconds.",
        citations=[citation(NEW_STACK)],
        verdict="supported",
    )
    built = one_slide_deck(claim_block("b1", claim))
    report = build_audit_report(built, brief=brief(), numeric=lint_deck(built))
    text = render(report)

    assert report.summary.unmatched_numerals is not None
    assert report.summary.unmatched_numerals >= 1
    assert "uncited numeral" in text


def test_a_framing_demotion_is_shown_on_the_slide_it_sits_on() -> None:
    """The deck still types the block `framing`; only this report says otherwise."""
    block = Block(
        id="f1",
        kind="framing",
        slot="body",
        text="Our approach is clinically shown to cut costs 40%.",
    )
    built = one_slide_deck(claim_block("b1", derived_claim()), block)
    report = build_audit_report(built, brief=brief(), framing=lint_framing(built))
    text = render(report)

    assert report.slides[0].demotions
    assert "demoted to `claim`" in text
    assert "Our approach is clinically shown to cut costs 40%." in text


def test_a_capped_verdict_is_surfaced() -> None:
    """A model that regularly needs capping is one to stop trusting on A3 (B8)."""
    writer = citation(COST_DOWN, doc_id="vendor-report", page=11)
    validator = citation(COST_UP, doc_id="finance-extract", page=4, retrieved_by="validator")
    claim = Claim(text="Migration cut run cost by 40 percent.", citations=[writer])
    assessment = assess_claim(
        claim,
        evidence=ValidatorEvidence([validator]),
        judgement=VerdictJudgement(
            verdict="supported",
            verdict_notes="The vendor report backs this.",
            supporting_quote=COST_UP,
            contradicting_quotes=[COST_UP],
        ),
    )
    verdicts = VerdictReport()
    verdicts.add(assessment)
    report = build_audit_report(
        one_slide_deck(claim_block("b1", assessment.apply(claim))),
        brief=brief(),
        verdicts=verdicts,
    )
    text = render(report)

    assert assessment.capped
    assert report.summary.capped_verdicts == 1
    assert "Verdict ceilings applied (A3)" in text


def test_the_report_states_what_it_does_not_establish() -> None:
    """`gate1.py`'s register: the sentence a tidy table would be the first to lose."""
    text = render(
        build_audit_report(one_slide_deck(claim_block("b1", derived_claim())), brief=brief())
    )
    for paragraph in DOES_NOT_ESTABLISH:
        assert paragraph in text
    assert "does not show that the quote supports the sentence attached to it" in text
    assert "Nothing here is an approval" in text


def test_nothing_in_the_report_returns_a_pass() -> None:
    """A7: no function here approves anything, and no attribute reads like a verdict."""
    report = build_audit_report(
        one_slide_deck(claim_block("b1", derived_claim())), brief=brief()
    )
    names = set(dir(report)) | set(dir(report.summary))
    assert not {n for n in names if n in {"passed", "passes", "approved", "ok"}}


# ---------------------------------------------------------------------------
# Assembly and rendering are separable
# ---------------------------------------------------------------------------


def test_assembly_is_usable_without_rendering() -> None:
    """Phase 4's PDF and Phase 3b's re-run want the structure, not the Markdown."""
    report = build_audit_report(
        one_slide_deck(claim_block("b1", derived_claim())), brief=brief(risks=[risk()])
    )

    assert report.run_id == "r1"
    assert report.brief_version == 3
    assert [s.slide_id for s in report.slides] == ["s1"]
    assert report.workings()[0][1].formula == "(a - b) / b * 100"
    assert report.risks[0].risk.accepted_by == "j.okafor"


def test_render_is_deterministic() -> None:
    built = one_slide_deck(claim_block("b1", derived_claim()))
    report = build_audit_report(built, brief=brief())
    assert render(report) == render(report)


def test_write_report_writes_the_markdown(tmp_path: Path) -> None:
    report = build_audit_report(
        one_slide_deck(claim_block("b1", derived_claim())), brief=brief()
    )
    path = write_report(report, tmp_path / "audit" / "report.md")

    assert path.read_text(encoding="utf-8") == render(report)


def test_an_empty_deck_renders_rather_than_raising() -> None:
    """A report on a deck with nothing in it should say that, not fail mid-gate."""
    text = render(build_audit_report(deck(), brief=brief()))
    assert "This deck has no slides." in text


@pytest.mark.parametrize("verdict", ["unsupported", "contradicted"])
def test_blocking_verdicts_are_marked_in_the_table(verdict: Verdict) -> None:
    claim = Claim(
        text="Migration cut run cost by 40 percent.",
        citations=[citation(COST_DOWN, doc_id="vendor-report", page=11)],
        verdict=verdict,
        contradicting_spans=(
            [citation(COST_UP, doc_id="finance-extract", page=4, retrieved_by="validator")]
            if verdict == "contradicted"
            else []
        ),
    )
    report = build_audit_report(one_slide_deck(claim_block("b1", claim)), brief=brief())

    assert report.claim_rows()[0].blocks_render
    assert f"**{verdict}**" in render(report)
