"""The B53 repair call: one chance to replace what a draft lost, before anyone sees it.

`compose_deck` resolves a draft, runs the draft checks (B56), and — only when something
failed — makes one call with `prompts/repair.md`. This module owns the three pieces that call
needs and nothing else:

- the response schema (`RepairDraft`), flat and fully required (B26);
- the user message: per failing slide, its kept blocks, budgets, and a numbered list of
  failures, each with the block the model wrote, what was wrong in figures, and candidate
  passages from the evidence pack the draft was written from;
- `apply_repair`, which patches the model's **original** draft with the replacements. The
  patched draft then goes back through exactly the same resolution and checks as the first
  one, so a repaired block earns its place by the same rules — A1 has no repair-shaped door.

Candidates are a ranked subset of the pack the model was already shown, never more: the pack
is the evidence a draft-first deck was written from (B45), and a repair must not see wider.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.content import (
    ProposedBlock,
    ProposedCitation,
    render_evidence,
    slide_budgets,
)
from autodeck.agents.evidence_pack import EvidencePack
from autodeck.agents.rejections import Rejection
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import FreeLayout
from autodeck.retrieval.hybrid import tokenize

if TYPE_CHECKING:
    from autodeck.agents.compose import ComposeDraft, ComposedSlide

#: Candidate passages shown per failure. Enough to contain the passage a near-miss quote was
#: aiming at; few enough that the repair prompt stays a fraction of the compose prompt.
CANDIDATES_PER_FAILURE = 8

#: What a repair is told about each kind, in the words `prompts/repair.md` uses.
KIND_LABELS: dict[str, str] = {
    "quote_not_found": "Quote not found",
    "quote_splice": "Quote joined two passages (splice)",
    "doc_not_shown": "Quote not found",
    "uncitable": "Quote not found",
    "no_payload": "Required part empty",
    "ir_invalid": "Could not be built",
    "overflow_item": "Too long for its slot",
    "overflow_stack": "Too long for its slot",
    "overflow_text": "Too long for its slot",
    "unknown_slot": "Not a slot of this layout",
    "computed_slot": "Not a slot of this layout",
    "missing_slot": "Required part empty",
    "framing_fence": "Framing carried a fact",
    "numeral_unmatched": "Number not in a cited source",
    "header_fact_unbacked": "Headline fact not backed on the slide",
    "mode_blocked": "Not allowed in this provenance mode",
    "reworded_keep_words": "Reworded the client's words",
    "overflow_frame": "Too long for its frame",
    "layout_fit": "Layout problem",
}

#: Kinds a repair cannot do anything useful about: the slot does not exist or is code's.
_NOT_REPAIRABLE = frozenset({"unknown_slot", "computed_slot", "layout_fit"})
"""`layout_fit` (B69): an overlap, a contrast or a safe-area problem is in the layout, which
a block replacement cannot move. It is reported, not sent to the repair call."""


# ---------------------------------------------------------------------------
# What the model returns
# ---------------------------------------------------------------------------


class BlockFix(BaseModel):
    """Replacement block(s) for one numbered failure."""

    model_config = ConfigDict(extra="forbid")

    failure_id: str = Field(min_length=1, description="f1, f2, … as listed.")
    blocks: list[ProposedBlock] = Field(
        min_length=1,
        description="Replacements for the same slot; two for a split bullet.",
    )


class Declined(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class MessageFix(BaseModel):
    """New citations for a key message whose citations failed. `[]` is an honest answer."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)
    citations: list[ProposedCitation]


class RepairDraft(BaseModel):
    """The whole repair answer. Every list present, even when empty (B26)."""

    model_config = ConfigDict(extra="forbid")

    fixes: list[BlockFix]
    declined: list[Declined]
    message_fixes: list[MessageFix]
    notes: str = Field(
        description="What could not be repaired, in a sentence or two; '' for none."
    )


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------


@dataclass
class RepairRequest:
    """A numbered set of failures and the prompt that asks for their replacement."""

    numbered: dict[str, Rejection]
    prompt: str
    advisories: list[Rejection] = field(default_factory=list)


#: Kinds that removed a block from the draft.
_DROPS = frozenset(
    {
        "quote_not_found",
        "quote_splice",
        "doc_not_shown",
        "uncitable",
        "no_payload",
        "ir_invalid",
        "overflow_item",
        "overflow_stack",
        "overflow_text",
        "mode_blocked",
    }
)


def repairable(failures: Sequence[Rejection]) -> list[Rejection]:
    """The failures worth spending the repair call on.

    An empty required slot counts only when a drop emptied it: a slot the model never wrote
    is a choice of component, not lost content, and B53 spends the call on what was lost.
    """
    dropped = {(f.slide_id, f.slot) for f in failures if f.kind in _DROPS}
    return [
        f
        for f in failures
        if f.kind not in _NOT_REPAIRABLE
        and (f.kind != "missing_slot" or (f.slide_id, f.slot) in dropped)
    ]


def build_repair_request(
    draft: ComposeDraft,
    *,
    failures: Sequence[Rejection],
    advisories: Sequence[Rejection] = (),
    kept: Mapping[str, Sequence[Any]],
    pack: EvidencePack,
    tokens: DesignTokens,
) -> RepairRequest:
    """Number the failures and write the user message for the repair call.

    `kept` is each slide's surviving face blocks after resolution (IR `Block`s), shown so the
    model knows what the slide already says — the header rule depends on it.
    """
    numbered: dict[str, Rejection] = {}
    by_slide: dict[str, list[tuple[str, Rejection]]] = {}
    messages: list[tuple[str, Rejection]] = []
    for index, failure in enumerate([*failures, *advisories], start=1):
        fid = f"f{index}"
        numbered[fid] = failure
        if failure.where == "message":
            messages.append((fid, failure))
        else:
            by_slide.setdefault(failure.slide_id, []).append((fid, failure))

    slides = {s.id: s for s in draft.slides}
    advisory_ids = {id(a) for a in advisories}
    parts: list[str] = [
        "# Failures to repair\n\nEach is numbered. Return a fix or a decline for every one. "
        "Advisories (marked) are optional: fix them if you can do so honestly."
    ]
    for slide_id, items in by_slide.items():
        slide = slides.get(slide_id)
        header = [f"## Slide {slide_id}"]
        if slide is not None:
            header.append(
                f"component: {slide.component} · role: {slide.narrative_role} · intent: "
                f"{slide.intent}"
            )
            header.append("Blocks the slide kept:")
            for block in kept.get(slide_id, ()):
                header.append(f"  - [{block.id}] {block.slot}: {_block_text(block)}")
            if getattr(slide, "layout", None) is not None:
                header.append(
                    "Creative slide: each block keeps its frame in the layout. A replacement "
                    "must fit the frame named in its failure at the same size; it is never "
                    "shrunk to fit."
                )
            else:
                header.append("Slot budgets:\n" + slide_budgets(slide.component, tokens))
        parts.append("\n".join(header))
        for fid, failure in items:
            parts.append(
                _failure_text(fid, failure, pack, advisory=id(failure) in advisory_ids)
            )
    if messages:
        parts.append("## Key messages")
        for fid, failure in messages:
            parts.append(_failure_text(fid, failure, pack, advisory=False))
    return RepairRequest(
        numbered=numbered, prompt="\n\n---\n\n".join(parts), advisories=list(advisories)
    )


def _failure_text(fid: str, failure: Rejection, pack: EvidencePack, *, advisory: bool) -> str:
    label = KIND_LABELS.get(failure.kind, failure.kind)
    lines = [
        f"### {fid}{' (advisory)' if advisory else ''} — {label}",
        f"block {failure.block_id or '(none)'} · slot {failure.slot or '(none)'} · "
        f"{failure.where}",
        f"What was wrong: {failure.message}",
    ]
    detail = {k: v for k, v in failure.detail.items() if k != "advisory"}
    if detail:
        lines.append("Figures: " + json.dumps(detail, ensure_ascii=False, default=str))
    if failure.proposed is not None and hasattr(failure.proposed, "model_dump_json"):
        lines.append("You wrote:\n" + failure.proposed.model_dump_json(exclude_none=True))
    claims, spans = _candidates(failure, pack)
    if claims or spans:
        lines.append(
            "Candidate passages (copy quotes exactly):\n" + render_evidence(claims, spans)
        )
    else:
        lines.append(
            "Candidate passages: none in the evidence — decline unless you can fix it "
            "without a citation."
        )
    return "\n".join(lines)


def _block_text(block: Any) -> str:
    claim = getattr(block, "claim", None)
    if claim is not None:
        return claim.text
    if getattr(block, "chart", None) is not None:
        return f"(chart: {block.chart.title or 'untitled'})"
    if getattr(block, "diagram", None) is not None:
        return "(diagram)"
    return block.text or ""


def _proposed_text(proposed: Any) -> str:
    if proposed is None:
        return ""
    if hasattr(proposed, "model_dump_json"):
        return proposed.model_dump_json()
    return str(proposed)


def _candidates(failure: Rejection, pack: EvidencePack) -> tuple[list[Any], list[Any]]:
    """The pack entries most like what the failed block was trying to say."""
    query = set(tokenize(" ".join([failure.message, _proposed_text(failure.proposed)])))
    if not query:
        return [], []

    def score(text: str) -> int:
        return len(query & set(tokenize(text)))

    claims = sorted(
        (c for c in pack.claims if score(c.claim + " " + c.quote) > 0),
        key=lambda c: -score(c.claim + " " + c.quote),
    )
    spans = sorted(
        (s for s in pack.spans if s.citable and score(s.text) > 0),
        key=lambda s: -score(s.text),
    )
    budget = CANDIDATES_PER_FAILURE
    chosen_claims = claims[: budget // 2]
    chosen_spans = spans[: budget - len(chosen_claims)]
    return chosen_claims, chosen_spans


# ---------------------------------------------------------------------------
# Applying the answer
# ---------------------------------------------------------------------------


@dataclass
class AppliedRepair:
    draft: ComposeDraft
    replaced: list[str] = field(default_factory=list)
    """One line per fix applied, for `ComposeResult.repairs`."""
    declined: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    """Fixes that could not be applied (unknown failure id, wrong slot)."""


def apply_repair(
    draft: ComposeDraft, answer: RepairDraft, numbered: Mapping[str, Rejection]
) -> AppliedRepair:
    """Patch the model's original draft with the repair's replacement blocks.

    Pure: returns a new draft. A fix replaces the failed block in place (same position, same
    face/notes list); a fix for an emptied slot is appended. Replacement blocks must target the
    failure's slot; one that does not is ignored, since moving content between slots is not a
    repair. Ids are kept unique within the slide.
    """
    patched = draft.model_copy(deep=True)
    slides: dict[str, ComposedSlide] = {s.id: s for s in patched.slides}
    out = AppliedRepair(draft=patched)

    for fix in answer.fixes:
        failure = numbered.get(fix.failure_id)
        if failure is None or failure.where == "message":
            out.ignored.append(f"{fix.failure_id}: no such block failure")
            continue
        slide = slides.get(failure.slide_id)
        if slide is None:
            out.ignored.append(
                f"{fix.failure_id}: slide {failure.slide_id!r} is not in the draft"
            )
            continue
        blocks = [b for b in fix.blocks if not failure.slot or b.slot == failure.slot]
        if not blocks:
            out.ignored.append(
                f"{fix.failure_id}: replacement wrote to another slot than {failure.slot!r}"
            )
            continue
        target = slide.speaker_notes if failure.where == "notes" else slide.blocks
        position = next((i for i, b in enumerate(target) if b.id == failure.block_id), None)
        taken = {b.id for b in [*slide.blocks, *slide.speaker_notes]} - {failure.block_id}
        unique = [_unique(b, taken) for b in blocks]
        if position is None:
            target.extend(unique)
        else:
            target[position : position + 1] = unique
        layout = getattr(slide, "layout", None)
        if layout is not None and failure.where == "face" and position is not None:
            slide.layout = _retarget(layout, failure.block_id, [b.id for b in unique])
        out.replaced.append(
            f"slide {failure.slide_id} block {failure.block_id or failure.slot}: "
            f"{KIND_LABELS.get(failure.kind, failure.kind).lower()} — replaced "
            f"({', '.join(b.id for b in unique)})"
        )

    messages = {m.id: m for m in patched.key_messages}
    for fix in answer.message_fixes:
        message = messages.get(fix.message_id)
        if message is None:
            out.ignored.append(f"message {fix.message_id!r}: not in the draft")
            continue
        message.citations = list(fix.citations)
        out.replaced.append(f"key message {fix.message_id}: citations replaced")

    for decline in answer.declined:
        failure = numbered.get(decline.failure_id)
        where = (
            f"slide {failure.slide_id} block {failure.block_id or failure.slot}"
            if failure is not None
            else decline.failure_id
        )
        out.declined.append(f"{where}: declined — {decline.reason}")
    return out


def _retarget(layout: FreeLayout, old_id: str, new_ids: list[str]) -> FreeLayout:
    """Point a creative slide's layout at a failed block's replacements (B69).

    One replacement takes the failed block's element as it was. A split into several
    stacks them in that element's frame, top to bottom, in equal bands, so every
    replacement is placed and none overlaps; the fit check then judges the result.
    """
    elements: list[Any] = []
    for element in layout.elements:
        if getattr(element, "block_id", None) != old_id:
            elements.append(element)
            continue
        if not new_ids:
            continue
        frame, n = element.frame, len(new_ids)
        for i, new_id in enumerate(new_ids):
            band = frame.model_copy(update={"y": frame.y + i * frame.h / n, "h": frame.h / n})
            elements.append(element.model_copy(update={"block_id": new_id, "frame": band}))
    return layout.model_copy(update={"elements": elements})


def _unique(block: ProposedBlock, taken: set[str]) -> ProposedBlock:
    if block.id not in taken:
        taken.add(block.id)
        return block
    suffix = 2
    while f"{block.id}-r{suffix}" in taken:
        suffix += 1
    new_id = f"{block.id}-r{suffix}"
    taken.add(new_id)
    return block.model_copy(update={"id": new_id})
