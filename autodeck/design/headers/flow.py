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

import string
from dataclasses import dataclass, field

from autodeck.design.components.catalog import UnknownComponentError, spec_for
from autodeck.design.headers.profile import HeaderStyleProfile
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import Block, Deck, DeckBrief, Slide

_HEADER_ROLE = "title"

#: Repeated syntax (3b.9): a header "opening" is its first `OPENING_WORDS` words, lowercased,
#: with surrounding punctuation stripped. When `REPEATED_OPENING_THRESHOLD` or more headers
#: share one, the deck reads as a template being filled in ("Inference costs fall…",
#: "Inference costs dominate…", "Inference costs vary…"). Two is a parallel pair, often
#: deliberate; three is a pattern. Two words, not one: a one-word opening fires on every
#: deck whose headers start "The" or "Our".
OPENING_WORDS = 2
REPEATED_OPENING_THRESHOLD = 3

#: Characters stripped from each end of an opening word: ASCII punctuation, typographic
#: quotes and the ellipsis character.
_OPENING_STRIP = string.punctuation + "\u2018\u2019\u201c\u201d\u2026"


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

    A `claim` block's readable text is `claim.text`, not `block.text` — since B36 `Block`
    refuses `text` on any non-text kind by construction (see `Block._payload_matches_kind`),
    so `block.text` is always empty on a `claim` block and reading it would report every
    fact-bearing header as blank.
    """
    if block is None:
        return "(no header slot)", ""
    if block.kind == "claim" and block.claim is not None:
        return "claim", block.claim.text
    return block.kind, block.text or ""


def flow_report(
    deck: Deck,
    tokens: DesignTokens,
    profile: HeaderStyleProfile,
    *,
    brief: DeckBrief | None = None,
) -> HeaderFlowReport:
    """Assemble the header sequence and its mechanical compliance, in slide order.

    `tokens` must be the same `DesignTokens` the deck was written against — slot geometry
    (and therefore which slot carries the `title` role) is resolved per theme, the same as
    every other read of `autodeck.design.components.catalog`.

    3b.9 additions, appended after the existing per-slide checks:
      - repeated-opening findings (`_repeated_opening_findings`) are always added.
      - storyline findings (`_storyline_findings`) are added when `brief` is given; without
        a brief there is no order to check against, and nothing is reported for it.
    Run this on the **final** deck — after art direction and the aesthetic loop — not only
    after content: a `SwapComponent` can move a block out of the title-role slot, so the
    header a reader sees is a property of the deck as rendered, not as written. The render
    stage (3b.10) calls it; `autodeck content` keeps calling it as an early read.
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

    report.findings.extend(_repeated_opening_findings(report.lines))
    if brief is not None:
        report.findings.extend(_storyline_findings(deck, brief))

    return report


def _opening(text: str) -> str:
    """The first `OPENING_WORDS` words of `text`, lowercased, each stripped of surrounding
    punctuation (`string.punctuation` plus typographic quotes and the ellipsis character),
    joined by one space. Empty
    words after stripping are dropped before counting."""
    words = (word.strip(_OPENING_STRIP).lower() for word in text.split())
    return " ".join([word for word in words if word][:OPENING_WORDS])


def _repeated_opening_findings(lines: list[HeaderLine]) -> list[FlowFinding]:
    """One advisory `FlowFinding` per opening shared by `REPEATED_OPENING_THRESHOLD` or more
    non-empty headers.

    Contract: attributed to the slide where the count first reaches the threshold; `detail`
    names the opening and every slide id sharing it, in deck order, and says it reads as a
    template. Headers with fewer than `OPENING_WORDS` words are skipped (a one-word header
    has no syntax to repeat). Exact repeats are counted too — they are also repeated syntax,
    and the existing verbatim finding says something different. Deterministic order:
    findings in order of the attributed slide.
    """
    groups: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        opening = _opening(line.text)
        if len(opening.split()) < OPENING_WORDS:
            continue
        groups.setdefault(opening, []).append(index)

    flagged = sorted(
        (members[REPEATED_OPENING_THRESHOLD - 1], opening, members)
        for opening, members in groups.items()
        if len(members) >= REPEATED_OPENING_THRESHOLD
    )
    return [
        FlowFinding(
            lines[attributed].slide_id,
            f"{len(members)} headers open with {opening!r} "
            f"(slides {', '.join(lines[i].slide_id for i in members)}) - "
            "this reads as a template being filled in",
        )
        for attributed, opening, members in flagged
    ]


def _storyline_findings(deck: Deck, brief: DeckBrief) -> list[FlowFinding]:
    """Advisory findings where the header sequence walks backwards through the brief.

    The mechanical proxy for a storyline break. Whether the headers *argue* well stays a
    human judgement (module docstring); whether they visit the signed brief's key messages
    in the order the owner agreed is checkable, and a deck that returns to message 1 after
    message 3 is either a break or a deliberate recap — worth a human's glance either way.

    Contract:
      - A slide's rank is the lowest index in `brief.key_messages` among its `message_ids`.
        Slides with no `message_ids` (title, agenda, dividers) are skipped entirely — they
        neither advance nor break the order.
      - A `message_id` not in the brief → one finding on that slide naming the id (the IR
        refers to a message the signed brief does not have).
      - Walking in deck order with `furthest` = the highest rank seen so far: a slide whose
        rank < `furthest` → one finding naming both messages by id and their 1-based
        positions, phrased as a question ("a storyline break, or a deliberate recap?").
        `furthest` is not lowered by a backwards step.
      - Coverage (a key message no slide serves) is **not** checked here: GATE 1's report
        already checks it (`autodeck/audit/gate1.py`), and two descriptions of one rule is
        the defect this project keeps finding.
    """
    position = {message.id: index for index, message in enumerate(brief.key_messages)}
    findings: list[FlowFinding] = []
    furthest: int | None = None

    for slide in deck.slides:
        known: list[int] = []
        for message_id in slide.message_ids:
            if message_id in position:
                known.append(position[message_id])
            else:
                findings.append(
                    FlowFinding(
                        slide.id,
                        f"serves message {message_id!r}, which the signed brief does not have",
                    )
                )
        if not known:
            continue

        rank = min(known)
        if furthest is not None and rank < furthest:
            here = brief.key_messages[rank].id
            ahead = brief.key_messages[furthest].id
            findings.append(
                FlowFinding(
                    slide.id,
                    f"serves message {here!r} (position {rank + 1}) after message "
                    f"{ahead!r} (position {furthest + 1}) - a storyline break, or a "
                    "deliberate recap?",
                )
            )
        else:
            furthest = rank

    return findings
