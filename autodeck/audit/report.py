"""The audit report (A6, A8): slide → claim → verdict → doc/page → verbatim quote.

This is the artifact the owner reads at GATE 2, and it is the only place the whole accuracy
subsystem becomes visible at once. A1 lives in the IR, A2 in the numeric linter, A3 in
`verdicts.py`, A5 in the framing linter — each of them holds a piece and none of them shows
a human the deck. This module assembles the pieces into a document somebody can check a
figure against without opening the IR.

## The four things it has to get right

**The quote, in full.** A claims table that shows a verdict and a document name has moved
the reader's work rather than done it: to check the claim they still have to open the IR,
or the paper. So every claim's citations are printed verbatim, with `doc_id`, page and the
hash prefix, exactly as `spotcheck.py` prints them for GATE 1a.

**The working, for every derived figure** (the phase brief's done-when). A `Derivation`
renders as its formula, each named input *with that input's own citation*, and the result.
A derived number whose inputs are not individually traceable is not audited, it is asserted
— so each input line also says whether its value really appears in the span it cites. That
answer is `numeric_linter.derivation_input_is_traceable`, the same function whose False is
a blocking A2 finding, called rather than re-implemented: a report that decided
traceability for itself could print a tick under a build the linter had blocked.

**A conflicts section that does not average.** A8 names the failure precisely — *"never
average, round, or silently pick one"* — so where the validator recorded a contradicting
span, this report prints both sides, each attributed to its own document and page, and says
in words that they disagree. It offers no reconciliation, because there is no honest
reconciliation to offer and a reader who sees one figure will assume the question is
settled.

**The open risks, resurfaced.** `OpenRisk` is a gap the owner accepted at planning time
with their name on it, and plan §7 Phase 2a says the gap *"is not allowed to disappear"*.
They are taken from the brief, never reconstructed from the deck: a risk that has been
written out of the slides is exactly the one that must still appear here. Where no brief is
supplied the report says so loudly rather than printing an empty section, because a missing
section reads as "no risks".

## Assembly and rendering are separate

`build_audit_report` produces a structured `AuditReport`; `render` turns one into Markdown.
Phase 4 adds a PDF renderer and Phase 3b re-runs the audit over the rendered deck, and both
want the assembly without the Markdown. Nothing in the structure knows about `#` or `|`.

## What it does not do

**It does not check anything.** Every verdict, finding and demotion here was decided by
another module; this one arranges them. The one exception is deliberate and cosmetic: the
formula is re-executed so the working can print what it computes, using the linter's own
`evaluate_formula` and tolerance. The blocking judgement remains the linter's.

**It does not decide.** No function returns "approved" and nothing writes a gate approval —
that is the owner's, through `Orchestrator.approve` (A7). `gate1.py`'s posture exactly.

**A clean report is not a sound deck, and it says so in its own text.** It shows that every
claim has a verdict and a traceable quote. It does not show that the quotes support the
sentences they are attached to, nor that the sentences together make an argument the
sources bear. That sentence is in the rendered output, near the top, for the same reason
`gate1.py` puts the equivalent one in front of its reviewer: a tidy table is persuasive out
of all proportion to what it proves.

Owning phase: 2b (task 2b.9). Opus tier — `autodeck/audit/` is a path guardrail in
docs/MODEL_ROUTING.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from autodeck.audit.framing_linter import Demotion, FramingReport
from autodeck.audit.numeric_linter import (
    DERIVATION_REL_TOL,
    FormulaError,
    NumericFinding,
    NumericReport,
    derivation_input_is_traceable,
    evaluate_formula,
)
from autodeck.audit.verdicts import VerdictReport
from autodeck.ir.models import Citation, Claim, Deck, DeckBrief, OpenRisk, Slide, Verdict

#: Worst first. A reader skimming one summary line should meet what stops the build before
#: what does not, and every verdict is printed even at zero — "contradicted 0" is a result,
#: whereas an omitted row is indistinguishable from a check that never ran.
VERDICT_ORDER: tuple[Verdict, ...] = (
    "contradicted",
    "unsupported",
    "unverified",
    "partially_supported",
    "supported",
)

#: The A2 finding raised for a numeral that traces to no cited span and no derivation.
#: Counted separately in the summary because "zero unmatched numerals" is A2's own pass
#: condition and the owner should not have to derive it from a list of findings.
UNCITED_NUMERAL_CHECK = "uncited numeral"


class AuditReportError(ValueError):
    """The report was asked to describe two different builds at once."""


# ---------------------------------------------------------------------------
# The working, shown
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DerivationInputRow:
    """One named input to a derived figure, with the span it was copied from.

    `value_in_span` is the whole reason this row exists separately from the formula. A
    derivation with real citations, correct arithmetic and an invented input value passes
    every other check in the system — its result traces to itself — so the report has to
    show, per input, that the number is really in the sentence underneath it.
    """

    name: str
    value: float
    citation: Citation
    value_in_span: bool


@dataclass(frozen=True)
class Working:
    """A derived figure with its formula, its cited inputs and its result.

    `recomputed` is what `evaluate_formula` makes of the formula now, printed so the reader
    can see the arithmetic rather than be told it was checked. `recompute_error` is set
    instead when the formula will not evaluate at all, which the numeric linter has already
    raised as blocking.
    """

    formula: str
    inputs: tuple[DerivationInputRow, ...]
    result: float
    unit: str
    recomputed: float | None = None
    recompute_error: str | None = None

    @property
    def inputs_traced(self) -> int:
        return sum(1 for row in self.inputs if row.value_in_span)

    @property
    def fully_traced(self) -> bool:
        """Whether every input's value appears in the span that input cites."""
        return all(row.value_in_span for row in self.inputs)

    @property
    def arithmetic_agrees(self) -> bool:
        """Whether re-executing the formula reproduces the stated result.

        Uses the numeric linter's own tolerance. False also covers a formula that would not
        evaluate — there is no result to agree with.
        """
        if self.recomputed is None:
            return False
        return math.isclose(
            self.recomputed, self.result, rel_tol=DERIVATION_REL_TOL, abs_tol=1e-12
        )


# ---------------------------------------------------------------------------
# Claims, slides, conflicts, risks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimRow:
    """One claim, located, with everything needed to check it on the page.

    `in_speaker_notes` is carried because A1 applies to notes exactly as it applies to the
    slide face, and a reviewer told only "block b7" cannot tell whether the sentence is one
    the room will see.
    """

    slide_id: str
    block_id: str
    claim_text: str
    verdict: Verdict
    notes: str
    citations: tuple[Citation, ...]
    contradicting_spans: tuple[Citation, ...] = ()
    working: Working | None = None
    in_speaker_notes: bool = False

    @property
    def blocks_render(self) -> bool:
        """Whether A3 forbids this claim from reaching final render.

        Asks the IR rather than restating the rule, for the reason `verdicts.py` gives: a
        second copy of "which verdicts block" is one `or` away from disagreeing with the
        model the renderer and the render guard both read.
        """
        from autodeck.audit.verdicts import verdict_blocks_render

        return verdict_blocks_render(self.verdict)


@dataclass(frozen=True)
class SlideSection:
    """One slide's claims, plus any framing block A5 demoted on it.

    The demotions sit here rather than only in their own section because a demoted block is
    still typed `framing` in the deck and therefore invisible in the claims table — the one
    place a reviewer would look for it is the slide it is on.
    """

    slide_id: str
    narrative_role: str
    component: str
    intent: str | None
    claims: tuple[ClaimRow, ...]
    demotions: tuple[Demotion, ...] = ()


@dataclass(frozen=True)
class Conflict:
    """One claim the corpus disagrees with itself about (A8).

    Both sides are kept, attributed. The writer's citations are not deleted when a
    contradiction is found — `VerdictAssessment.apply` leaves them alone deliberately —
    because removing the half that agreed would erase what the contradiction contradicts,
    and a report showing only one side has picked a winner, which is the A8 failure.
    """

    slide_id: str
    block_id: str
    claim_text: str
    verdict: Verdict
    cited: tuple[Citation, ...]
    contradicting: tuple[Citation, ...]


@dataclass(frozen=True)
class RiskRow:
    """An accepted evidence gap from the brief, with where it landed in the deck."""

    risk: OpenRisk
    message_text: str | None
    slides: tuple[str, ...]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Summary:
    """The counts that matter, with `None` reserved for "that check did not run".

    The distinction is the same one `unverified` draws against `unsupported`: zero unmatched
    numerals because the linter found none is a result, and zero because nobody ran it is
    not. Collapsing the two would let a report assembled without its linters read exactly
    like a clean one.
    """

    claims: int
    verdicts: dict[Verdict, int]
    derivations: int
    derivation_inputs: int
    derivation_inputs_traced: int
    derivations_recomputing: int
    conflicts: int
    open_risks: int | None
    numerals_checked: int | None = None
    unmatched_numerals: int | None = None
    numeric_blocking: int | None = None
    numeric_advisory: int | None = None
    framing_blocks_checked: int | None = None
    demotions: int | None = None
    capped_verdicts: int | None = None

    @property
    def blocking_claims(self) -> int:
        return self.verdicts.get("contradicted", 0) + self.verdicts.get("unsupported", 0)


@dataclass(frozen=True)
class AuditReport:
    """Everything the GATE 2 reviewer reads, assembled and not yet rendered."""

    run_id: str
    project: str
    client: str
    audience: str
    deck_version: int
    brief_version: int | None
    slides: tuple[SlideSection, ...]
    conflicts: tuple[Conflict, ...]
    risks: tuple[RiskRow, ...]
    summary: Summary
    has_brief: bool
    numeric: NumericReport | None = None
    framing: FramingReport | None = None
    verdicts: VerdictReport | None = None

    def claim_rows(self) -> list[ClaimRow]:
        return [row for section in self.slides for row in section.claims]

    def workings(self) -> list[tuple[ClaimRow, Working]]:
        return [(row, row.working) for row in self.claim_rows() if row.working is not None]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_audit_report(
    deck: Deck,
    *,
    brief: DeckBrief | None,
    numeric: NumericReport | None = None,
    framing: FramingReport | None = None,
    verdicts: VerdictReport | None = None,
) -> AuditReport:
    """Assemble the audit report from the deck and whatever checked it.

    Args:
        deck: the validated IR. Verdicts, notes and contradicting spans are read from the
            claims themselves, which is where `VerdictAssessment.apply` put them.
        brief: the signed-off brief, for `open_risks`. Explicitly required rather than
            defaulted, and `None` is rendered as a stated hole in the report: risks are
            carried *from planning*, and a report that quietly omitted the section would
            look identical to one whose deck had no accepted gaps.
        numeric: `numeric_linter.lint_deck`'s report, or None if A2 did not run.
        framing: `framing_linter.lint_framing`'s report, or None if A5 did not run.
        verdicts: `validate_deck`'s `VerdictReport`, or None. Only needed for the caps A3
            applied to the model's own answers; the verdicts themselves are on the claims.

    Raises:
        AuditReportError: the deck and brief belong to different runs. An audit report
            pairing one deck's claims with another run's accepted risks would be confident
            and wrong, which is worse than missing.
    """
    if brief is not None and brief.run_id != deck.run_id:
        raise AuditReportError(
            f"deck is for run {deck.run_id!r} but brief is for {brief.run_id!r}; an audit "
            "report pairs one deck with the brief its risks were accepted against"
        )

    sections = tuple(_slide_section(slide, framing) for slide in deck.slides)
    rows = [row for section in sections for row in section.claims]
    conflicts = tuple(
        Conflict(
            slide_id=row.slide_id,
            block_id=row.block_id,
            claim_text=row.claim_text,
            verdict=row.verdict,
            cited=row.citations,
            contradicting=row.contradicting_spans,
        )
        for row in rows
        if row.contradicting_spans
    )
    risks = tuple(_risk_rows(deck, brief)) if brief is not None else ()

    return AuditReport(
        run_id=deck.run_id,
        project=deck.project,
        client=deck.client,
        audience=deck.audience,
        deck_version=deck.version,
        brief_version=brief.version if brief is not None else None,
        slides=sections,
        conflicts=conflicts,
        risks=risks,
        summary=_summary(rows, conflicts, risks, brief, numeric, framing, verdicts),
        has_brief=brief is not None,
        numeric=numeric,
        framing=framing,
        verdicts=verdicts,
    )


def _slide_section(slide: Slide, framing: FramingReport | None) -> SlideSection:
    # Through `Slide.claim_sites()` rather than walking blocks and diagram nodes here. This
    # function had the diagram branch and `Block.blocks_render()` did not, which is how the
    # claims table came to print a claim as `contradicted` on the same GATE 2 screen as
    # "[PASS] zero blocks verdict unsupported/contradicted". One walk, so they cannot
    # disagree again — including about a claim site neither has heard of yet.
    rows = [
        _claim_row(
            site.slide_id,
            f"{site.block_id}/{site.node_id}" if site.node_id else site.block_id,
            site.claim,
            in_notes=site.in_speaker_notes,
        )
        for site in slide.claim_sites()
    ]
    demotions = (
        tuple(d for d in framing.demotions if d.slide_id == slide.id)
        if framing is not None
        else ()
    )
    return SlideSection(
        slide_id=slide.id,
        narrative_role=slide.narrative_role,
        component=slide.component,
        intent=slide.intent,
        claims=tuple(rows),
        demotions=demotions,
    )


def _claim_row(slide_id: str, block_id: str, claim: Claim, *, in_notes: bool) -> ClaimRow:
    return ClaimRow(
        slide_id=slide_id,
        block_id=block_id,
        claim_text=claim.text,
        verdict=claim.verdict,
        notes=claim.verdict_notes or "",
        citations=tuple(claim.citations),
        contradicting_spans=tuple(claim.contradicting_spans),
        working=_working(claim) if claim.derivation is not None else None,
        in_speaker_notes=in_notes,
    )


def _working(claim: Claim) -> Working:
    """Render one derivation into the shape the report prints.

    The formula is re-executed here so the working can show what it computes. That is a
    display concern, not a second opinion: it calls the linter's `evaluate_formula`, and
    whether a mismatch blocks the build is `re_execute_derivation`'s answer, not this one's.
    """
    derivation = claim.derivation
    assert derivation is not None
    inputs = tuple(
        DerivationInputRow(
            name=name,
            value=item.value,
            citation=item.citation,
            value_in_span=derivation_input_is_traceable(item),
        )
        for name, item in sorted(derivation.inputs.items())
    )
    try:
        recomputed = evaluate_formula(
            derivation.formula, {name: item.value for name, item in derivation.inputs.items()}
        )
        error = None
    except FormulaError as exc:
        recomputed = None
        error = str(exc)
    return Working(
        formula=derivation.formula,
        inputs=inputs,
        result=derivation.result,
        unit=derivation.unit,
        recomputed=recomputed,
        recompute_error=error,
    )


def _risk_rows(deck: Deck, brief: DeckBrief) -> list[RiskRow]:
    """Every accepted gap, with the slides that now carry the message it qualifies."""
    rows: list[RiskRow] = []
    for risk in brief.open_risks:
        message = brief.message(risk.message_id)
        rows.append(
            RiskRow(
                risk=risk,
                message_text=message.text if message is not None else None,
                slides=tuple(
                    slide.id for slide in deck.slides if risk.message_id in slide.message_ids
                ),
            )
        )
    return rows


def _summary(
    rows: list[ClaimRow],
    conflicts: tuple[Conflict, ...],
    risks: tuple[RiskRow, ...],
    brief: DeckBrief | None,
    numeric: NumericReport | None,
    framing: FramingReport | None,
    verdicts: VerdictReport | None,
) -> Summary:
    counts: dict[Verdict, int] = {verdict: 0 for verdict in VERDICT_ORDER}
    for row in rows:
        counts[row.verdict] = counts.get(row.verdict, 0) + 1
    workings = [row.working for row in rows if row.working is not None]
    return Summary(
        claims=len(rows),
        verdicts=counts,
        derivations=len(workings),
        derivation_inputs=sum(len(w.inputs) for w in workings),
        derivation_inputs_traced=sum(w.inputs_traced for w in workings),
        derivations_recomputing=sum(1 for w in workings if w.arithmetic_agrees),
        conflicts=len(conflicts),
        open_risks=len(risks) if brief is not None else None,
        numerals_checked=numeric.numerals_checked if numeric is not None else None,
        unmatched_numerals=(
            sum(1 for f in numeric.findings if f.check == UNCITED_NUMERAL_CHECK)
            if numeric is not None
            else None
        ),
        numeric_blocking=len(numeric.blocking) if numeric is not None else None,
        numeric_advisory=len(numeric.advisory) if numeric is not None else None,
        framing_blocks_checked=(
            framing.framing_blocks_checked if framing is not None else None
        ),
        demotions=len(framing.demotions) if framing is not None else None,
        capped_verdicts=len(verdicts.capped) if verdicts is not None else None,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

#: The paragraph `gate1.py` and `spotcheck.py` both carry in their own words: what a clean
#: run does *not* license. Kept as a constant so a test can assert the report still says it
#: — this is the sentence a report under pressure to look finished would lose first.
DOES_NOT_ESTABLISH = (
    "**What this report does not establish.** It shows that every claim carries a verdict "
    "and a quote a reader can trace to a document and a page. It does not show that the "
    "quote supports the sentence attached to it, and it does not show that the sentences "
    "together make an argument the sources bear — a deck can be clean here and wrong in "
    "the room.",
    "A verdict is a model's judgement bounded by the spans retrieval actually found (A3, "
    "and B8 makes it model-sensitive). An empty conflicts section means the validator's "
    "independent search found no contradicting span, not that the corpus agrees with "
    "itself. A traced numeral means the figure appears in a cited sentence, not that the "
    "sentence is about this claim.",
    "Nothing here is an approval. GATE 2 is the owner's, recorded by `autodeck approve` "
    "(A7), and no function in this module returns a pass.",
)


def render(report: AuditReport) -> str:
    """Render an assembled report as Markdown (A6: *"Markdown first; PDF is Phase 4"*).

    Separate from assembly on purpose: Phase 4's PDF and Phase 3b's post-render re-run want
    the `AuditReport`, not this string.
    """
    lines: list[str] = [
        f"# Audit report — {report.project}",
        "",
        f"Run `{report.run_id}` · deck v{report.deck_version} · client "
        f"{report.client} · audience {report.audience}",
        "",
    ]
    lines.extend(_summary_lines(report))
    lines.extend(["", "---", ""])
    for paragraph in DOES_NOT_ESTABLISH:
        lines.extend([paragraph, ""])
    lines.extend(["---", ""])
    lines.extend(_slides_lines(report))
    lines.extend(_conflicts_lines(report))
    lines.extend(_risks_lines(report))
    lines.extend(_lint_lines(report))
    return "\n".join(lines).rstrip() + "\n"


def write_report(report: AuditReport, path: Path) -> Path:
    """Render and write the report. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(report), encoding="utf-8")
    return path


# -- summary ----------------------------------------------------------------


def _summary_lines(report: AuditReport) -> list[str]:
    summary = report.summary
    verdicts = " · ".join(
        f"{verdict} {summary.verdicts.get(verdict, 0)}" for verdict in VERDICT_ORDER
    )
    lines = [
        "## Summary",
        "",
        f"- **Claims:** {summary.claims} — {verdicts}",
    ]

    if summary.derivations:
        traced = f"{summary.derivation_inputs_traced}/{summary.derivation_inputs}"
        lines.append(
            f"- **Derived figures:** {summary.derivations} — "
            f"{summary.derivations_recomputing}/{summary.derivations} re-execute to their "
            f"stated result · {traced} inputs found in the span they cite"
        )
    else:
        lines.append("- **Derived figures:** none in this deck")

    lines.append(
        "- **Numerals (A2):** "
        + (
            f"{summary.numerals_checked} checked · {summary.unmatched_numerals} unmatched "
            f"(A2 passes at zero) · {summary.numeric_blocking} blocking, "
            f"{summary.numeric_advisory} advisory finding(s)"
            if summary.numerals_checked is not None
            else "**the numeric linter did not run for this report** — this is not a count "
            "of zero"
        )
    )
    lines.append(
        "- **Framing (A5):** "
        + (
            f"{summary.framing_blocks_checked} block(s) checked · {summary.demotions} "
            "demoted to `claim`"
            if summary.framing_blocks_checked is not None
            else "**the framing linter did not run for this report** — this is not a count "
            "of zero"
        )
    )
    lines.append(
        f"- **Conflicts (A8):** {summary.conflicts} claim(s) with a contradicting span"
    )
    lines.append(
        "- **Open risks carried from the brief:** "
        + (
            f"{summary.open_risks}"
            if summary.open_risks is not None
            else "**no brief was supplied** — accepted evidence gaps could not be "
            "resurfaced here"
        )
    )
    if summary.capped_verdicts:
        lines.append(
            f"- **Verdict ceilings applied (A3):** {summary.capped_verdicts} — the model's "
            "own answer was lowered or redirected by the evidence it was shown"
        )
    if summary.blocking_claims:
        lines.extend(
            [
                "",
                f"> **{summary.blocking_claims} claim(s) carry a verdict that bars final "
                "render (A3).** They are listed below with the spans behind them. The deck "
                "cannot ship in this state; the fix is to cite the sentence differently, "
                "rewrite it, or cut it.",
            ]
        )
    return lines


# -- slides -----------------------------------------------------------------


def _slides_lines(report: AuditReport) -> list[str]:
    lines = ["## Claims, slide by slide", ""]
    if not report.slides:
        lines.extend(["This deck has no slides.", ""])
        return lines

    for section in report.slides:
        lines.append(
            f"### Slide `{section.slide_id}` — {section.narrative_role} · "
            f"component `{section.component}`"
        )
        lines.append("")
        if section.intent:
            lines.append(f"*Intent:* {section.intent}")
            lines.append("")
        if not section.claims and not section.demotions:
            lines.extend(["No claims on this slide.", ""])
            continue

        if section.claims:
            lines.extend(_claims_table(section))
            lines.append("")
            for row in section.claims:
                lines.extend(_claim_detail(row))
        for demotion in section.demotions:
            lines.extend(_demotion_lines(demotion))
    return lines


def _claims_table(section: SlideSection) -> list[str]:
    """The index. Full quotes are printed beneath it, never squeezed into a cell.

    A verbatim quote in a table cell has to have its newlines flattened and its pipes
    escaped, and a quote that has been reformatted to fit is no longer the thing A1 asks the
    reader to check. So the table carries the claim, the verdict and a pointer to each span,
    and the spans themselves are quoted in full below.
    """
    lines = [
        "| Block | Claim | Verdict | Evidence |",
        "|---|---|---|---|",
    ]
    for row in section.claims:
        where = f"`{row.block_id}`" + (" *(notes)*" if row.in_speaker_notes else "")
        evidence = " · ".join(_ref(c) for c in row.citations) or "—"
        if row.contradicting_spans:
            evidence += " · **contradicted by** " + " · ".join(
                _ref(c) for c in row.contradicting_spans
            )
        verdict = f"**{row.verdict}**" if row.blocks_render else row.verdict
        lines.append(f"| {where} | {_cell(row.claim_text)} | {verdict} | {evidence} |")
    return lines


def _claim_detail(row: ClaimRow) -> list[str]:
    """One claim's evidence in full: the quotes, the working, the contradictions."""
    heading = f"**`{row.block_id}` — {row.verdict}**"
    if row.in_speaker_notes:
        heading += " · speaker notes"
    lines = [heading, "", row.claim_text, ""]

    for citation in row.citations:
        lines.extend(_citation_lines(citation))
    if row.working is not None:
        lines.extend(_working_lines(row.working))
    for span in row.contradicting_spans:
        lines.append("Contradicting span found by the validator's independent search:")
        lines.append("")
        lines.extend(_citation_lines(span))
    if row.notes:
        lines.extend([f"*Validator notes:* {row.notes}", ""])
    return lines


def _citation_lines(citation: Citation) -> list[str]:
    """A quote, verbatim, with the attribution a reader needs to go and look.

    Rendered as a blockquote rather than a table cell so the text is printed exactly as it
    is stored, line breaks included. The hash prefix is shown the way `spotcheck.py` shows
    it: enough to match against the document store, not so much that it crowds the quote.

    **The attribution sits outside the quote marks**, and the blank line that puts it there
    is load-bearing rather than cosmetic: Markdown's lazy continuation would otherwise fold
    the following line into the blockquote, and a reader would be looking at a span of
    "source text" whose last sentence this repository wrote.
    """
    lines = [f"> {line}" for line in citation.quote.strip().splitlines()]
    lines.append("")
    lines.append(
        f"— `{citation.doc_id}` p.{citation.page} · retrieved by "
        f"{citation.retrieved_by} · sha256 `{citation.quote_sha256[:16]}…`"
    )
    lines.append("")
    return lines


def _working_lines(working: Working) -> list[str]:
    """The working for one derived figure: formula, named inputs, result.

    Each input prints its own citation. A derived number whose inputs are not individually
    traceable is asserted rather than audited, so an input whose value is not in the span it
    cites is called out on its own line rather than left for the reader to notice.
    """
    unit = f" {working.unit}" if working.unit else ""
    lines = [
        "*Working (A2 — derived figure):*",
        "",
        "```",
        f"{working.formula} = {_number(working.result)}{unit}",
        "```",
        "",
    ]
    for row in working.inputs:
        lines.append(f"- `{row.name}` = {_number(row.value)} — {_ref(row.citation)}")
        lines.append("")
        lines.extend(f"  > {line}" for line in row.citation.quote.strip().splitlines())
        # Blank line first, for the reason `_citation_lines` gives: without it the verdict
        # on the input would be folded into the quote and read as part of the source.
        lines.append("")
        if row.value_in_span:
            lines.append(
                f"  ✓ {_number(row.value)} appears in the span above "
                "(`check_derivation_inputs`)."
            )
        else:
            lines.append(
                f"  **✗ {_number(row.value)} does not appear in the span above.** The input "
                "was not copied from its citation, so this figure rests on a number with no "
                "source (A2, blocking)."
            )
        lines.append("")

    if working.recompute_error is not None:
        lines.append(
            f"Re-executing `{working.formula}` failed: {working.recompute_error}. A "
            "derivation nobody can reproduce is indistinguishable from an invented number."
        )
    elif working.arithmetic_agrees:
        lines.append(
            f"Re-executed: the formula over the inputs above computes "
            f"{_number(working.recomputed or 0.0)}, which is the stated result."
        )
    else:
        lines.append(
            f"**Re-executed: the formula over the inputs above computes "
            f"{_number(working.recomputed or 0.0)}, not the stated "
            f"{_number(working.result)}.** See the A2 findings below; the stated result may "
            "be the computed one rounded, which the linter reports separately."
        )
    lines.append("")
    return lines


def _demotion_lines(demotion: Demotion) -> list[str]:
    """A framing block A5 reclassified, printed on the slide it sits on.

    Worth spelling out in the report because the deck itself does not show it: the block is
    still typed `framing` in the IR — the demoted object is one the IR cannot hold — so a
    reviewer reading the slide sees a sentence that looks exempt from A1 and is not.
    """
    lines = [
        f"**`{demotion.block_id}` — framing demoted to `claim` (A5)**",
        "",
        f"> {demotion.text}",
        "",
    ]
    lines.extend(f"- {reason}" for reason in demotion.reasons)
    lines.extend(
        [
            "",
            "This block is now a claim with no citation, which A1 forbids and A3 marks "
            f"`{demotion.verdict}`. It bars final render until the sentence is cited or "
            "rewritten as a statement about the engagement rather than about the world.",
            "",
        ]
    )
    return lines


# -- conflicts --------------------------------------------------------------


def _conflicts_lines(report: AuditReport) -> list[str]:
    lines = ["## Conflicts — where the sources disagree (A8)", ""]
    if not report.conflicts:
        lines.extend(
            [
                "The validator's independent search recorded no contradicting span. That "
                "means nothing was found, not that the corpus agrees with itself: a "
                "disagreement the contradiction search never surfaced does not appear "
                "here. See A3's own limits above.",
                "",
            ]
        )
        return lines

    lines.extend(
        [
            f"{len(report.conflicts)} claim(s) have a cited source and a contradicting "
            "source. Both are printed below, each attributed to its own document and page.",
            "",
            "**Neither side is reconciled here, and neither should be in the deck.** A8: "
            "*never average, round, or silently pick one.* A single figure standing where "
            "two sources disagree tells the reader the question is settled. The deck's job "
            "is to hedge in the slide text or the notes and say which source says what.",
            "",
        ]
    )
    for conflict in report.conflicts:
        lines.append(f"### `{conflict.slide_id}` / `{conflict.block_id}` — {conflict.verdict}")
        lines.extend(["", conflict.claim_text, ""])
        lines.append("**The source the deck cites:**")
        lines.append("")
        for citation in conflict.cited:
            lines.extend(_citation_lines(citation))
        lines.append("**The source that disagrees with it:**")
        lines.append("")
        for citation in conflict.contradicting:
            lines.extend(_citation_lines(citation))
        lines.append(
            "These two say different things. Both are in the corpus and this report takes "
            "no view on which is right."
        )
        lines.append("")
    return lines


# -- open risks -------------------------------------------------------------


def _risks_lines(report: AuditReport) -> list[str]:
    lines = ["## Open risks carried from the brief", ""]
    if not report.has_brief:
        lines.extend(
            [
                "**No brief was supplied to this report, so the accepted evidence gaps "
                "could not be resurfaced.** This is a hole in the report, not a statement "
                "that the deck carries no risks — `DeckBrief.open_risks` is the only place "
                "they exist, and plan §7 is explicit that a gap accepted at planning time "
                "is not allowed to disappear. Re-run the report with the brief.",
                "",
            ]
        )
        return lines

    if not report.risks:
        lines.extend(
            [
                f"Brief v{report.brief_version} records no open risks: no key message went "
                "into this deck on weak or absent evidence.",
                "",
            ]
        )
        return lines

    lines.extend(
        [
            f"Brief v{report.brief_version} records {len(report.risks)} evidence gap(s) "
            "accepted at planning time. They appear here because the gap is not allowed to "
            "disappear between the brief and the deck (plan §7 Phase 2a) — carrying one is "
            "allowed, carrying it silently is not.",
            "",
        ]
    )
    for row in report.risks:
        lines.append(
            f"### Message `{row.risk.message_id}` — accepted by {row.risk.accepted_by}"
        )
        lines.append("")
        if row.message_text:
            lines.extend([f"*The message:* {row.message_text}", ""])
        lines.extend([f"*What is missing:* {row.risk.description}", ""])
        if row.risk.mitigation:
            lines.extend([f"*Mitigation recorded:* {row.risk.mitigation}", ""])
        else:
            lines.extend(
                [
                    "*Mitigation:* **none recorded.** The gap was accepted without a stated "
                    "hedge, so nothing in the deck is committed to softening it.",
                    "",
                ]
            )
        if row.slides:
            lines.extend(
                [
                    "*Carried by:* " + ", ".join(f"slide `{s}`" for s in row.slides),
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "*Carried by:* **no slide serves this message.** The risk was accepted "
                    "for a message the deck no longer makes — check whether the message was "
                    "dropped deliberately.",
                    "",
                ]
            )
    return lines


# -- linter detail ----------------------------------------------------------


def _lint_lines(report: AuditReport) -> list[str]:
    lines: list[str] = []
    if report.numeric is not None:
        lines.extend(["## Numeric lint (A2)", ""])
        if not report.numeric.findings:
            lines.extend(
                [
                    f"{report.numeric.numerals_checked} numeral(s) and "
                    f"{report.numeric.derivations_checked} derivation(s) checked. Every "
                    "numeral traces to a cited span or to a re-executed derivation.",
                    "",
                ]
            )
        else:
            lines.extend(_findings_lines(report.numeric.blocking + report.numeric.advisory))

    if report.framing is not None:
        lines.extend(["## Framing lint (A5)", ""])
        if not report.framing.demotions:
            lines.extend(
                [
                    f"{report.framing.framing_blocks_checked} framing block(s) checked, none "
                    "demoted. A framing block passing the fence asserts nothing checkable "
                    "about the world — it is not evidence that what it says is true.",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    f"{len(report.framing.demotions)} framing block(s) were demoted to "
                    "`claim`; each is shown on its slide above.",
                    "",
                ]
            )

    if report.verdicts is not None and report.verdicts.capped:
        lines.extend(["## Verdict ceilings applied (A3)", ""])
        lines.extend(
            [
                "On these claims the model's own answer was lowered or redirected by the "
                "evidence it was shown. Surfaced rather than swallowed: a model that "
                "regularly needs capping is one to stop trusting on A3 (B8).",
                "",
            ]
        )
        lines.extend(_capped_lines(report.verdicts))
    return lines


def _findings_lines(findings: list[NumericFinding]) -> list[str]:
    lines = [f"- {finding}" for finding in findings]
    lines.append("")
    return lines


def _capped_lines(verdicts: VerdictReport) -> list[str]:
    lines: list[str] = []
    for assessment in verdicts.capped:
        lines.append(f"- **{assessment.verdict}** — {_cell(assessment.claim_text)}")
        lines.extend(f"  - {reason}" for reason in assessment.cap_reasons)
        lines.extend(
            f"  - quote the model named that was not in its evidence: {quote!r}"
            for quote in assessment.dropped_quotes
        )
    lines.append("")
    return lines


# -- small helpers ----------------------------------------------------------


def _ref(citation: Citation) -> str:
    return f"`{citation.doc_id}` p.{citation.page}"


def _cell(text: str) -> str:
    """Flatten text for a Markdown table cell.

    Only ever applied to claim text and finding details — never to a verbatim quote, which
    is printed outside the table for exactly this reason.
    """
    return " ".join(text.split()).replace("|", "\\|")


def _number(value: float) -> str:
    """Print a float without inventing precision or losing it.

    An integral value prints as an integer: `result: 63` arrives from JSON as `63.0`, and
    `63.0 percent` in the working reads as a measurement made to one decimal place.
    """
    if math.isfinite(value) and value == int(value):
        return str(int(value))
    return repr(value)


__all__ = [
    "AuditReport",
    "AuditReportError",
    "ClaimRow",
    "Conflict",
    "DerivationInputRow",
    "RiskRow",
    "SlideSection",
    "Summary",
    "Working",
    "build_audit_report",
    "render",
    "write_report",
]
