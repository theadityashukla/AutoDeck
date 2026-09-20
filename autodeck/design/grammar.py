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

from autodeck.ir.models import Block, CommunicationMode, Slide

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
