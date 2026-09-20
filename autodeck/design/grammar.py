"""Grammar lints (D13): text/icon/diagram balance, enforced deterministically.

D13's own wording is *"text/icon/diagram balance enforced by deterministic grammar lints,
not model taste."* `framing_linter.py` is the register this module matches: findings, not
decisions (an orchestrator blocks); severities named and justified per rule; and — the two
lessons that phase carries forward —

* **Closed lists fail on ordinary phrasing outside the list.** That risk is A5's, not this
  module's: nothing here classifies natural language. Every rule below counts something
  mechanical — words via `str.split()` (the same operationalisation
  `DiagramSpec._labels_fit_the_budget` already uses), block kinds, or rendered geometry.
  The analogous risk here is different and is named per rule: a mechanical count standing in
  for a judgement ("5-7 concepts", "adjacent") a human would sometimes make differently.
* **A check that compares a prediction to itself proves nothing.** Every threshold below is
  an independent number — one of D13's own figures, or a constant derived from the deck's
  own theme tokens (`Spacing.gutter`) rather than from anything this module itself computed
  — compared against an actual count taken from the IR or the rendered slide. None of these
  rules recomputes its own input as its own check.

## The one thing harder than it looks: icon adjacency

D13 says *"every icon adjacent to a text label"*. 3a.7 did not add a structural
icon-plus-label pairing to `layout_kit` (`Stack.icon_row(...)` would be the honest fix — see
its own carried finding), so an icon's `IconRef` block carries no reference to a label
block, and `place_icon` writes only a name (`icon:<family>:<name>`) onto the shapes it
creates. **Adjacency is therefore a geometric judgement made after render, not a structural
fact read off the IR** — see `check_icon_adjacency` for the threshold and what it does not
catch. This module does not build `Stack.icon_row`; that stays 3a.7's deliberate gap, to be
closed by whoever next needs icon+label pairing to be a constructible thing rather than an
inferred one.

## Two seams, not one

Word budgets, diagram count and the icon/chart/diagram pileup rule read only the IR
(`Deck`/`Slide`/`Block`) and need no render — `lint_deck` runs them before a slide is ever
drawn, the same way A2/A5 run on IR text. Icon adjacency needs real shape geometry and can
only run on a rendered `Presentation` — `check_icon_adjacency` is the second, later seam,
mirroring `numeric_linter.py`'s own `lint_deck`/`lint_rendered_slides` split for the same
reason: the two inputs are not interchangeable, so the checks that need each one are kept
apart rather than one function pretending to accept both.

Owning phase: 3a (task 3a.9), D13. Routed to Sonnet per B28: `autodeck/design/` is not a
guardrail path in `docs/MODEL_ROUTING.md`, so the path — not the phase brief's Opus tag —
sets the tier (B28's own rule, "guardrail paths keep their tier; the rest de-escalate").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from autodeck.ir.models import Block, BlockKind, CommunicationMode, Deck, Slide

Severity = Literal["blocking", "advisory"]


@dataclass(frozen=True)
class GrammarFinding:
    """One thing D13 has to say about one slide. Same shape as `gate1.Finding` and
    `FramingFinding`: this module reports, an orchestrator blocks."""

    check: str
    severity: Severity
    detail: str
    location: str = ""

    def __str__(self) -> str:
        marker = "BLOCKING" if self.severity == "blocking" else "advisory"
        where = f" · {self.location}" if self.location else ""
        return f"[{marker}] {self.check}{where}: {self.detail}"


@dataclass
class GrammarReport:
    """What D13's grammar lints found, across the IR pass, the render pass, or both."""

    findings: list[GrammarFinding] = field(default_factory=list)
    slides_checked: int = 0

    @property
    def blocking(self) -> list[GrammarFinding]:
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def advisory(self) -> list[GrammarFinding]:
        return [f for f in self.findings if f.severity == "advisory"]

    @property
    def blocks_build(self) -> bool:
        return bool(self.blocking)

    def extend(self, other: GrammarReport) -> None:
        self.findings.extend(other.findings)
        self.slides_checked += other.slides_checked

    def render(self) -> str:
        lines = [
            "D13 — grammar lint",
            f"{self.slides_checked} slide(s) checked · {len(self.blocking)} blocking · "
            f"{len(self.advisory)} advisory",
            "",
        ]
        if not self.findings:
            lines.append("Every slide holds D13's text/icon/diagram balance.")
        else:
            lines.extend(str(f) for f in self.blocking + self.advisory)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Word budgets per communication mode
# ---------------------------------------------------------------------------

#: D13's own figures (PHASE-3A.md task 3a.9; plan §6.11.2). A slide with no
#: `communication_mode` assigned yet has no budget to check against — see
#: `check_word_budget`.
WORD_BUDGET_PER_MODE: dict[CommunicationMode, int] = {
    "icon_anchored": 50,
    "diagram_led": 60,
    "text_led": 90,
}


def _block_word_count(block: Block) -> int:
    """Words this block puts in front of a reader, across every field that carries text.

    `str.split()` is the definition of "a word" already used one level down, in
    `DiagramNode.word_count()` and `DiagramSpec._labels_fit_the_budget` — reusing it here
    rather than inventing a second tokeniser is the same "one definition, several readers"
    discipline `numeric_linter.py`'s `derivation_input_is_traceable` argues for.

    Counted: `block.text` (framing/section_header prose); `block.claim.text` (the
    assertion, not its citations); every diagram node's label
    (`DiagramNode.word_count()` — the diagram geometry's own count, not re-derived here);
    a diagram's title and structural text (axis poles, transition labels, via
    `DiagramGeometry.structural_texts()`); a chart's headline (`ChartSpec.title`); a
    figure's caption.

    **Not counted, on purpose:** a chart's category and series names, and a citation's
    quoted text. A six-category bar chart legitimately carries six or more short labels
    that read, to a viewer, as one glance at a chart rather than six more things to read —
    counting them would make every chart-bearing slide fail a "reading load" budget for
    data density, which is a different problem D13 does not name. This is the rule's own
    stated gap: a slide that pads a chart's `title` with a paragraph, or pairs a chart with
    enough OTHER text to look like a wall of words, still trips this check on that text.
    """
    words = 0
    if block.text:
        words += len(block.text.split())
    if block.claim is not None:
        words += len(block.claim.text.split())
    if block.figure is not None and block.figure.caption:
        words += len(block.figure.caption.split())
    if block.chart is not None and block.chart.title:
        words += len(block.chart.title.split())
    if block.diagram is not None:
        diagram = block.diagram
        words += sum(node.word_count() for node in diagram.nodes)
        if diagram.title:
            words += len(diagram.title.split())
        words += sum(len(site.text.split()) for site in diagram.payload.structural_texts())
    return words


def check_word_budget(slide: Slide, *, location: str = "") -> list[GrammarFinding]:
    """Blocking: catches a slide whose face carries more reading than D13's mode ceiling.

    Face blocks only (`slide.blocks`), not speaker notes — the budget is about what a
    reader scans on the slide, and a spoken note is not read off it, unlike A5's fence,
    which follows a fact wherever it is written.

    Does not catch: a slide with `communication_mode` unset. Mode assignment is Phase 3b's
    decision (task 3b.7, the art-direction pass), so a slide built before that pass has run
    has nothing to check its word count against yet — silently skipping it, rather than
    blocking on an absent field this phase does not set, is the same posture
    `check_overflow` takes toward a component the catalog has not registered.

    Does not catch: a slide within budget that is still a wall of words for its mode
    because the 50/60/90 ceilings are themselves the brief's own compromise, not a per-slide
    measurement of legibility — D13 sets the ceiling, this function only checks it.
    """
    if slide.communication_mode is None:
        return []
    budget = WORD_BUDGET_PER_MODE[slide.communication_mode]
    total = sum(_block_word_count(block) for block in slide.blocks)
    if total <= budget:
        return []
    return [
        GrammarFinding(
            check="word budget",
            severity="blocking",
            detail=(
                f"{total} word(s) on a {slide.communication_mode!r} slide, over D13's "
                f"{budget}-word ceiling for that mode (icon_anchored ≤ 50, "
                "diagram_led ≤ 60, text_led ≤ 90). Cut prose or split the slide; "
                "shrinking the type to fit more words defeats the budget rather than "
                "meeting it."
            ),
            location=location,
        )
    ]


# ---------------------------------------------------------------------------
# Diagram count and the icon/chart/diagram pileup
# ---------------------------------------------------------------------------

#: D13: "≤1 diagram/slide". A `DiagramSpec` is already a composed geometry of several
#: nodes and edges; two of them sharing a slide is two competing geometries, not one
#: richer one, and the slide-geometry skill's own load-bearing test (would a plain list
#: lose information?) is never asked twice on the same slide by construction here.
MAX_DIAGRAMS_PER_SLIDE = 1

#: D13: "no icon+chart+diagram pileup" — three distinct kinds of non-prose visual
#: furniture. Deliberately the three named in the brief and nothing wider: an icon next to
#: a chart alone, or two charts, is a layout choice this rule has no opinion about. See
#: `check_no_icon_chart_diagram_pileup` for what that narrowness gives up.
PILEUP_KINDS: frozenset[BlockKind] = frozenset({"icon", "chart", "diagram"})


def check_diagram_count(slide: Slide, *, location: str = "") -> list[GrammarFinding]:
    """Blocking: catches more than one `kind="diagram"` block on one slide's face.

    Exact and closed: a diagram block either exists on the slide or it does not, so there
    is no judgement call here to get wrong on an ordinary slide the way a word-count
    ceiling or a concept count can. Face blocks only — a diagram cannot render twice from
    one slide's speaker notes, which carry no geometry at all.

    Does not catch: two diagrams that are visually small and genuinely uncluttered, or one
    diagram that is itself overloaded (`DiagramSpec._labels_fit_the_budget` already blocks
    an over-budget label; there is no "too many nodes" check here or anywhere else in this
    module, and it would need its own calibration if the phase after this one wants it).
    """
    diagrams = [b for b in slide.blocks if b.kind == "diagram"]
    if len(diagrams) <= MAX_DIAGRAMS_PER_SLIDE:
        return []
    return [
        GrammarFinding(
            check="diagram count",
            severity="blocking",
            detail=(
                f"{len(diagrams)} diagram blocks on one slide "
                f"({', '.join(b.id for b in diagrams)}); D13 allows at most "
                f"{MAX_DIAGRAMS_PER_SLIDE}. Two geometries competing for one slide is two "
                "arguments, not one — split the slide."
            ),
            location=location,
        )
    ]


def check_no_icon_chart_diagram_pileup(
    slide: Slide, *, location: str = ""
) -> list[GrammarFinding]:
    """Blocking: catches a slide whose face carries an icon block AND a chart block AND a
    diagram block all at once — D13's named pileup, read straight off block kinds.

    Exact and closed, for the same reason `check_diagram_count` is: kind membership is a
    fact, not an estimate. It fires only on the three-way combination the brief names.

    Does not catch: two of the three together without the third (an icon-heavy slide next
    to a chart, with no diagram, can still be busy); more than one of any single kind
    contributing to the same pileup feeling; or a genuinely cluttered slide built from
    kinds outside this set entirely (several `claim` blocks, say). Widening the set to "any
    two distinct visual kinds" was considered and rejected — a headline `claim` next to a
    `chart` is most of this catalog's components working as designed, and a rule that fired
    on that would be the closed-list failure `framing_linter.py` warns about, just on
    kinds instead of words.
    """
    present = {block.kind for block in slide.blocks} & PILEUP_KINDS
    if present != PILEUP_KINDS:
        return []
    return [
        GrammarFinding(
            check="icon+chart+diagram pileup",
            severity="blocking",
            detail=(
                "This slide carries an icon block, a chart block and a diagram block "
                "together — D13's named pileup. Three different kinds of non-prose visual "
                "furniture compete for the same attention; drop one or split the slide."
            ),
            location=location,
        )
    ]


# ---------------------------------------------------------------------------
# Concept count — advisory
# ---------------------------------------------------------------------------

#: D13's own figure is a range ("5-7"), not a single number. 7, the top of that range, is
#: used as the ceiling: anything at or under 7 is unambiguously within what the brief calls
#: fine, and firing at the range's low end would flag slides D13 itself does not object to.
MAX_CONCEPTS_ADVISORY = 7

#: Slot names that are metadata rather than a "concept" a reader is being asked to hold —
#: the citation strip every component with a `source` slot carries. Kept as an explicit,
#: named exclusion (rather than inferring it from the slot's role) because a metadata slot
#: is the one place counting every block would double-count the same information already
#: sitting behind the claims it labels.
EXCLUDED_CONCEPT_SLOTS = frozenset({"source"})


def check_concept_count(slide: Slide, *, location: str = "") -> list[GrammarFinding]:
    """Advisory: flags a slide whose face carries an unusually large number of IR blocks.

    **Why advisory, not blocking.** "Concept" is a judgement about distinct ideas; this
    function counts `Block`s, which is the only unit the IR actually offers and a real but
    imperfect proxy for it — a one-word data-card label and a fully argued bullet point
    both count as one "concept" here, and a component's own structural chrome (two column
    titles, say) counts exactly like a load-bearing point does. A correctly filled
    `two_column_compare` (two titles plus three points a side) or `data_card_grid` (six
    cards) can legitimately clear 7 blocks while reading as clean, intentional layouts — the
    false-positive risk the spec asks this module to weigh against blocking. Per D13's own
    "prefer advisory where you are unsure" instruction, this stays a name-and-report rather
    than a build-stopper.

    Does not catch: a slide with few, dense blocks that is conceptually overloaded anyway
    (one `claim` block whose text argues five unrelated points), or a slide that pads its
    block count with metadata this function already excludes in some other way it did not
    anticipate.
    """
    concepts = [block for block in slide.blocks if block.slot not in EXCLUDED_CONCEPT_SLOTS]
    if len(concepts) <= MAX_CONCEPTS_ADVISORY:
        return []
    return [
        GrammarFinding(
            check="concept count",
            severity="advisory",
            detail=(
                f"{len(concepts)} content blocks on one slide, over the "
                f"{MAX_CONCEPTS_ADVISORY}-block proxy for D13's 5-7 'concepts' guidance. "
                "Block count is a rough stand-in for distinct ideas, not a measurement of "
                "them (see this function's docstring) — a human should look at whether the "
                "slide actually reads as crowded before splitting it."
            ),
            location=location,
        )
    ]


# ---------------------------------------------------------------------------
# The IR-only pass
# ---------------------------------------------------------------------------


def lint_slide_ir(slide: Slide, *, location: str = "") -> list[GrammarFinding]:
    """Every IR-only grammar check for one slide: word budget, diagram count, the
    icon/chart/diagram pileup, and the advisory concept count. No render required."""
    findings: list[GrammarFinding] = []
    findings.extend(check_word_budget(slide, location=location))
    findings.extend(check_diagram_count(slide, location=location))
    findings.extend(check_no_icon_chart_diagram_pileup(slide, location=location))
    findings.extend(check_concept_count(slide, location=location))
    return findings


def lint_deck(deck: Deck) -> GrammarReport:
    """Run every IR-only grammar check over a whole deck.

    Icon adjacency is not in this report — it needs rendered geometry `Deck` does not
    carry. See `check_icon_adjacency` and combine the two reports at the call site once a
    render exists (`GrammarReport.extend`).
    """
    report = GrammarReport()
    for slide in deck.slides:
        report.slides_checked += 1
        report.findings.extend(lint_slide_ir(slide, location=f"slide {slide.id}"))
    return report
