"""Horizontal-flow QA (3a.8): read every header in slide order, and only that.

The brief's own test for a deck's headers, stated in consulting terms: strip every slide
down to its most prominent line and read those lines top to bottom. If the argument still
holds without anything else on the page, the headers are carrying it. If it does not, no
amount of good body copy fixes that slide.

## What this module checks, and what it deliberately does not

Word budgets, casing punctuation, the client's `avoid` list and verbatim repeats are
mechanical — the same kind of check `autodeck/audit/numeric_linter.py` and
`autodeck/audit/framing_linter.py` already make elsewhere in this codebase, so they are
made the same way here: closed rules, no model call, the same answer in every environment.

**Whether the sequence "carries the argument" is not mechanical, and this module does not
pretend otherwise.** `framing_linter.py`'s own docstring makes the case for why a model
should never be asked "does this sentence assert a fact" in a build pipeline — a different
answer per environment is the one thing a lint may never give. Asking a model "does this
sequence of ten headers make a coherent argument" is the same failure with a harder
question, so `HeaderFlowReport.render()` hands the sequence to a human instead, the way
`autodeck/audit/gate1.py`'s review report already does for "does the outline make the
argument" (see task 2a.9's design). This module's job stops at making that judgement cheap
to make: one ordered list, with the mechanical noise already flagged separately from it.

## Which slot is "the header"

There is no field named `header` on `Block` or `ComponentSlot` — a slide's most prominent
text is whichever slot the component registered with the `title` type-scale role
(`autodeck.design.components.catalog.ComponentSlot.role`), which is also the role every
renderer already draws at the theme's title size. Reading that role back out, rather than
hardcoding a slot name like `headline`, is what keeps this module correct as more of the
15-component catalog is registered: `quote` already has two `title`-role slots (`headline`
and the pull-quote text itself) and `callout_takeaway`'s one prominent line is named
`takeaway`, not `headline` — a name-based lookup would have missed both.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autodeck.design.components.catalog import UnknownComponentError, spec_for
from autodeck.design.headers.profile import HeaderStyleProfile
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import Block, Deck, Slide

_HEADER_ROLE = "title"


@dataclass(frozen=True)
class HeaderLine:
    """One slide's most prominent text, as a reader would see it."""

    slide_id: str
    component: str
    kind: str
    """The block's IR `kind` — `section_header`, `claim`, or `(no header slot)` /
    `(empty)` when this slide has nothing to show. A fact-bearing header that was written
    correctly shows up here as `claim`, which is the point: this report is also where you
    can see, at a glance, whether headers are actually landing as claims (D12) rather than
    section_header decoration."""
    text: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True)
class FlowFinding:
    """One mechanical thing about a single header worth a human's attention.

    Always advisory: this report never blocks a build. The invariant that blocks a build —
    a fact with no citation — is A5's job (`autodeck/audit/framing_linter.py`), enforced on
    the IR regardless of style. This report is a *readability* pass on top of that, and
    conflating the two would let a phrasing nitpick look as serious as an uncited claim.
    """

    slide_id: str
    detail: str


@dataclass
class HeaderFlowReport:
    lines: list[HeaderLine] = field(default_factory=list)
    findings: list[FlowFinding] = field(default_factory=list)

    def render(self) -> str:
        out = [
            "Header flow — read top to bottom; does the argument hold without the rest of "
            "the slide?",
            "",
        ]
        if not self.lines:
            out.append("(no slides)")
        for index, line in enumerate(self.lines, start=1):
            shown = line.text if line.text.strip() else "(empty)"
            out.append(
                f"{index}. [{line.slide_id}] {shown!r} ({line.kind}, {line.word_count} word(s))"
            )
        out.append("")
        if self.findings:
            out.append("Mechanical checks (advisory — never blocks a build):")
            out.extend(f"  {finding.slide_id}: {finding.detail}" for finding in self.findings)
        else:
            out.append("Mechanical checks: nothing to flag.")
        out.append("")
        out.append(
            "This pass does not judge whether the sequence carries the argument — a human "
            "does. Read the numbered list above top to bottom, covering the rest of each "
            "slide, and ask whether it would still make the deck's case."
        )
        return "\n".join(out)


def _header_slot_name(component: str, tokens: DesignTokens) -> str | None:
    """The name of `component`'s slot with the `title` type-scale role, if it has one.

    Reads the same `ComponentSpec` the renderer and the budget check build, rather than
    guessing a slot name — see the module docstring for why a name-based lookup would be
    wrong for `quote` and `callout_takeaway` alike.
    """
    try:
        spec = spec_for(component, tokens)
    except UnknownComponentError:
        return None
    for slot in spec.slots:
        if slot.role == _HEADER_ROLE:
            return slot.name
    return None


def _header_block(slide: Slide, slot_name: str | None) -> Block | None:
    if slot_name is None:
        return None
    return next((block for block in slide.blocks if block.slot == slot_name), None)


def _header_text(block: Block | None) -> tuple[str, str]:
    """`(kind, text)` for the header a reader would actually see.

    A `claim` block's readable text is `claim.text`, not `block.text` — `Block` forbids a
    `claim` block from also carrying a foreign `text` payload (see
    `Block._payload_matches_kind`), so `block.text` is always empty on one and reading it
    would report every fact-bearing header as blank.
    """
    if block is None:
        return "(no header slot)", ""
    if block.kind == "claim" and block.claim is not None:
        return "claim", block.claim.text
    return block.kind, block.text or ""


def flow_report(
    deck: Deck, tokens: DesignTokens, profile: HeaderStyleProfile
) -> HeaderFlowReport:
    """Assemble the header sequence and its mechanical compliance, in slide order.

    `tokens` must be the same `DesignTokens` the deck was written against — slot geometry
    (and therefore which slot carries the `title` role) is resolved per theme, the same as
    every other read of `autodeck.design.components.catalog`.
    """
    report = HeaderFlowReport()
    seen: dict[str, str] = {}

    for slide in deck.slides:
        slot_name = _header_slot_name(slide.component, tokens)
        block = _header_block(slide, slot_name)
        kind, text = _header_text(block)
        report.lines.append(
            HeaderLine(slide_id=slide.id, component=slide.component, kind=kind, text=text)
        )

        if slot_name is None:
            continue
        if block is None:
            report.findings.append(
                FlowFinding(slide.id, f"no block fills the header slot {slot_name!r}")
            )
            continue
        if not text.strip():
            report.findings.append(FlowFinding(slide.id, "header text is empty"))
            continue

        words = text.split()
        if len(words) > profile.max_words:
            report.findings.append(
                FlowFinding(
                    slide.id,
                    f"{len(words)} word(s) over the {profile.max_words}-word style "
                    f"budget: {text!r}",
                )
            )
        if not profile.terminal_punctuation and text.rstrip().endswith((".", "!")):
            report.findings.append(
                FlowFinding(slide.id, f"ends in punctuation the style disallows: {text!r}")
            )
        hit = [word for word in profile.avoid if word.lower() in text.lower()]
        if hit:
            report.findings.append(
                FlowFinding(slide.id, f"uses avoided wording {hit}: {text!r}")
            )

        normalised = " ".join(text.lower().split())
        earlier = seen.get(normalised)
        if earlier is not None:
            report.findings.append(
                FlowFinding(slide.id, f"repeats slide {earlier}'s header verbatim: {text!r}")
            )
        seen[normalised] = slide.id

    return report
