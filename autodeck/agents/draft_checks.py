"""Deterministic checks on a draft, run before the person sees it (B56).

The A2 and A5 linters used to run only on the gate-first path and at render, so a draft could
show the person a framing line claiming "superior … compared to active comparators" (live run
Xls, slide s6) that nothing had looked at. This module runs the same linters — the audit
subsystem's own functions, nothing re-implemented here — on every draft, and reports what
they find as `Rejection`s, so the B53 repair call can be told exactly what to fix.

Two kinds of output:

- **failures** — an invariant broke (A2, A5, B54's header rule) or the client's words were
  reworded under "keep my words". These trigger the repair call. A block that still fails
  after it is *kept and reported*, not dropped: the linters block a final render anyway, and
  a person reviewing a draft is better served by the flagged sentence than by a hole.
- **advisories** — quality findings (a topic-label headline). Shown in the UI and passed to a
  repair only when one is already running; they never spend a model call on their own.

Section dividers are handled here too, because removing one is safe (a divider carries no
fact, B36) and a six-slide deck with a "1. Glycemic control" divider is the kind of output
the owner wants gone regardless of model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from autodeck.agents.rejections import Rejection, RejectionKind
from autodeck.audit.framing_linter import (
    Demotion,
    lint_block,
    lint_diagram,
    lint_header,
    lint_unsourced,
)
from autodeck.audit.numeric_linter import HEADER_SLOTS, NumericFinding, lint_deck
from autodeck.ir.models import CLIENT_DECK_DOC_PREFIX, Deck, Slide

#: A deck shorter than this gets no section dividers (B56; prompts/compose.md says the same).
MIN_SLIDES_FOR_DIVIDERS = 8

#: A divider must open a section of at least this many slides.
MIN_SECTION_SLIDES = 2

#: Headline wording that names a topic instead of stating a point (plan §6.11.1's banned list
#: plus what the live run produced).
_LABEL_WORDS = re.compile(
    r"^(?:overview|background|introduction|summary|key takeaways?|takeaways?|conclusions?|"
    r"next steps|agenda|limitations|appendix)\b",
    re.I,
)

_NUMERIC_LOCATION = re.compile(
    r"^slide (?P<slide>\S+) / (?P<where>slide|notes) block (?P<block>\S+)"
)


@dataclass
class DraftCheckResult:
    """What the checks found, and the slides after safe structural fixes."""

    slides: list[Slide]
    failures: list[Rejection] = field(default_factory=list)
    advisories: list[Rejection] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)


def run_draft_checks(
    deck: Deck,
    *,
    proposed: Mapping[tuple[str, str], Any] | None = None,
    keep_words: bool = False,
    dividers_requested: bool = False,
) -> DraftCheckResult:
    """Lint `deck`'s slides as a draft. Pure: returns new slide lists, never mutates `deck`.

    Args:
        deck: the resolved draft.
        proposed: the model's original block for each `(slide_id, block_id)`, so a failure can
            show the repair call what was written.
        keep_words: a redesign in "keep my words" mode (B49): a claim citing the client's deck
            may only delete words from the slide text it cites.
        dividers_requested: the person asked for sections, so dividers are left alone.
    """
    lookup = proposed or {}
    result = DraftCheckResult(slides=list(deck.slides))
    if not dividers_requested:
        result.slides, removed = _drop_dividers(result.slides)
        result.corrections.extend(removed)

    seen: set[tuple[str, str]] = set()
    terms = deck.named_terms

    def add(
        kind: RejectionKind,
        slide: Slide,
        block_id: str,
        slot: str,
        message: str,
        where: str = "face",
        detail: dict[str, Any] | None = None,
    ) -> None:
        key = (slide.id, block_id)
        if key in seen:
            return
        seen.add(key)
        result.failures.append(
            Rejection(
                kind=kind,
                where=where,  # type: ignore[arg-type]
                slide_id=slide.id,
                block_id=block_id,
                slot=slot,
                message=message,
                detail=detail or {},
                proposed=lookup.get((slide.id, block_id)),
            )
        )

    for slide in result.slides:
        face_ids = {b.id for b in slide.blocks}
        for block in slide.all_blocks():
            where = "face" if block.id in face_ids else "notes"
            demotion: Demotion | None
            if block.diagram is not None:
                demotion = lint_diagram(block, slide_id=slide.id, terms=terms)
            elif block.claim is not None:
                demotion = lint_unsourced(block, slide_id=slide.id)
            elif block.slot in HEADER_SLOTS and where == "face":
                demotion = lint_header(
                    block, slide, terms=terms, rounding=deck.provenance == "normal"
                )
            else:
                demotion = lint_block(block, slide_id=slide.id, terms=terms)
            if demotion is not None:
                header = any(
                    r.check == "header fact not on the slide" for r in demotion.reasons
                )
                add(
                    "header_fact_unbacked" if header else "framing_fence",
                    slide,
                    block.id,
                    block.slot,
                    demotion.summary(),
                    where,
                    {"fragments": sorted({r.fragment for r in demotion.reasons if r.fragment})},
                )
            if keep_words and block.claim is not None:
                reworded = _reworded(
                    block.claim.text,
                    [
                        c.quote
                        for c in block.claim.citations
                        if c.doc_id.startswith(CLIENT_DECK_DOC_PREFIX)
                    ],
                )
                if reworded:
                    add(
                        "reworded_keep_words",
                        slide,
                        block.id,
                        block.slot,
                        f"slide {slide.id} block {block.id}: with 'keep my words' a sentence "
                        "may "
                        f"only lose words, but it adds {', '.join(reworded[:5])}",
                        where,
                    )

        for block_id, slot, column in _subjectless_points(slide):
            result.advisories.append(
                Rejection(
                    kind="subjectless_point",
                    where="face",
                    slide_id=slide.id,
                    block_id=block_id,
                    slot=slot,
                    message=(
                        f"slide {slide.id} block {block_id}: this {slot} point does not name "
                        f"its column's subject ({column!r}). The point is checked, quoted and "
                        "read on its own, without the column title, so it must say what it "
                        "is about: 'Oral: fasting dose required', not 'Requires fasting'."
                    ),
                    detail={"advisory": "subjectless_point", "column": column},
                    proposed=lookup.get((slide.id, block_id)),
                )
            )

        label = _topic_label(slide)
        if label is not None:
            result.advisories.append(
                Rejection(
                    kind="header_fact_unbacked",
                    where="face",
                    slide_id=slide.id,
                    block_id=label[0],
                    slot="headline",
                    message=(
                        f"slide {slide.id}: the headline {label[1]!r} names a topic; a "
                        "talking header states the slide's point as a sentence (B54)"
                    ),
                    detail={"advisory": "topic_label"},
                    proposed=lookup.get((slide.id, label[0])),
                )
            )

    checked = deck.model_copy(update={"slides": result.slides})
    for finding in _blocking(lint_deck(checked).findings):
        match = _NUMERIC_LOCATION.match(finding.location)
        if match is None:
            continue
        slide = next(s for s in result.slides if s.id == match["slide"])
        block = next((b for b in slide.all_blocks() if b.id == match["block"]), None)
        add(
            "numeral_unmatched",
            slide,
            match["block"],
            block.slot if block is not None else "",
            f"slide {slide.id} block {match['block']}: {finding.detail}",
            "face" if match["where"] == "slide" else "notes",
        )
    return result


def _blocking(findings: Sequence[NumericFinding]) -> list[NumericFinding]:
    return [f for f in findings if f.severity == "blocking"]


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def _reworded(text: str, quotes: Sequence[str]) -> list[str]:
    """Words of `text` that break "only delete words" against every cited client quote.

    Empty when `text`'s words appear, in order, within one quote's words — or when the claim
    cites no client-deck text at all (nothing to compare with).
    """
    if not quotes:
        return []
    wanted = _words(text)
    candidates = [_extra_words(wanted, _words(quote)) for quote in quotes]
    return min(candidates, key=len)


def _extra_words(wanted: list[str], source: list[str]) -> list[str]:
    extra: list[str] = []
    position = 0
    for word in wanted:
        try:
            position = source.index(word, position) + 1
        except ValueError:
            extra.append(word)
    return extra


_SUBJECT_LABEL = re.compile(r"^\s*[^:]{1,16}:\s")
"""A short label and a colon opening a point: "s.c.: ", "Oral: ", "Arm B: "."""

_COLUMNS = {
    "left_points": "left_title",
    "left_point": "left_title",
    "right_points": "right_title",
    "right_point": "right_title",
}


def _subjectless_points(slide: Slide) -> list[tuple[str, str, str]]:
    """`(block_id, slot, column title)` of each comparison claim that never names its side.

    A `two_column_compare` point is drawn under its column title, but A3 judges its claim
    alone and the audit report quotes it alone. Live run XLP5-agent put "No fasting
    requirement" under "Subcutaneous Semaglutide"; read alone it says the oral drug needs no
    fasting, and validation marked it contradicted. A point names its side when it uses a
    word that is distinctive in its column's title (one the other title lacks), or when it
    opens with a short label and a colon ("s.c.: no fasting rule"), which is how a 37-character
    point can carry an abbreviated subject. Advisory: the heuristic can miss a synonym.
    """
    sides = ("left_title", "right_title")
    titles = {b.slot: b.text or "" for b in slide.blocks if b.slot in sides}
    if len(titles) < 2:
        return []
    words = {slot: set(_words(text)) for slot, text in titles.items()}
    out: list[tuple[str, str, str]] = []
    for block in slide.blocks:
        column = _COLUMNS.get(block.slot)
        if column is None or block.claim is None or column not in titles:
            continue
        other = "right_title" if column == "left_title" else "left_title"
        distinctive = words[column] - words[other]
        text = block.claim.text
        if not distinctive or distinctive & set(_words(text)) or _SUBJECT_LABEL.match(text):
            continue
        out.append((block.id, block.slot, titles[column]))
    return out


def _topic_label(slide: Slide) -> tuple[str, str] | None:
    """`(block_id, text)` of a content headline that reads as a topic label, or None."""
    if slide.component in ("title", "section_divider", "agenda", "closing_cta"):
        return None
    for block in slide.blocks:
        if block.slot not in HEADER_SLOTS or not block.text:
            continue
        text = block.text.strip()
        words = text.split()
        titled = sum(1 for w in words if w[:1].isupper()) >= max(3, int(0.7 * len(words)))
        if len(words) < 6 or titled or _LABEL_WORDS.match(text):
            return block.id, text
    return None


def _drop_dividers(slides: list[Slide]) -> tuple[list[Slide], list[str]]:
    """Remove section dividers the deck is too short for, or that open no real section."""
    content = [s for s in slides if s.component != "section_divider"]
    if not any(s.component == "section_divider" for s in slides):
        return slides, []
    notes: list[str] = []
    if len(slides) < MIN_SLIDES_FOR_DIVIDERS:
        notes.extend(
            f"section divider {s.id!r} removed: a deck of {len(slides)} slides needs no "
            f"dividers (fewer than {MIN_SLIDES_FOR_DIVIDERS}; B56)"
            for s in slides
            if s.component == "section_divider"
        )
        return content, notes
    kept: list[Slide] = []
    for index, slide in enumerate(slides):
        if slide.component != "section_divider":
            kept.append(slide)
            continue
        following = 0
        for later in slides[index + 1 :]:
            if later.component == "section_divider":
                break
            following += 1
        if following < MIN_SECTION_SLIDES:
            notes.append(
                f"section divider {slide.id!r} removed: it opens {following} slide(s), and a "
                f"section needs at least {MIN_SECTION_SLIDES} (B56)"
            )
            continue
        kept.append(slide)
    return kept, notes


#: The failures `run_draft_checks` reports. A block with one of these still in the final draft
#: is removed by `drop_failed_blocks`; resolution-stage failures (quotes, budgets) never reach
#: the deck in the first place.
CHECK_KINDS: frozenset[str] = frozenset(
    {"framing_fence", "header_fact_unbacked", "numeral_unmatched", "reworded_keep_words"}
)


def drop_failed_blocks(
    slides: Sequence[Slide], failures: Sequence[Rejection], *, only: set[str] | None = None
) -> tuple[list[Slide], list[str]]:
    """Remove every block a draft check still fails (B53: what fails after repair is dropped).

    `run_draft_checks` only *reports*; until this ran, a block it failed stayed in the IR and
    surfaced at the render gate instead (run XLP: an uncited `0.8%` and a demoted note). A
    removed headline leaves its slide headless on purpose — the preview shows the gap, as for
    any required slot nothing honest filled.

    Args:
        slides: the draft's slides.
        failures: all failures; only `CHECK_KINDS` on face or notes blocks are acted on.
        only: restrict to these slide ids (a revision drops only from slides it rewrote).

    Returns:
        The slides with failing blocks removed, and one line per removal.
    """
    doomed: dict[str, dict[str, Rejection]] = {}
    for failure in failures:
        if failure.kind not in CHECK_KINDS or failure.where == "message":
            continue
        if only is not None and failure.slide_id not in only:
            continue
        doomed.setdefault(failure.slide_id, {})[failure.block_id] = failure
    if not doomed:
        return list(slides), []
    kept_slides: list[Slide] = []
    notes: list[str] = []
    for slide in slides:
        ids = doomed.get(slide.id)
        if not ids:
            kept_slides.append(slide)
            continue
        for block in slide.all_blocks():
            if block.id in ids:
                notes.append(
                    f"slide {slide.id}: block {block.id} ({block.slot}) dropped — still "
                    f"failing {ids[block.id].kind} after the draft checks"
                )
        kept_slides.append(slide.without_blocks(set(ids)))
    return kept_slides, notes
