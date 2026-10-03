"""Draft-first composition (B43 to B48): the output contracts its model calls are held to.

A draft-first run replaces the planner → outline → per-slide content chain with three model
calls on the `composer` role — **clarify**, **compose**, **revise** — around the same
deterministic machinery the gate-first chain already relies on. This module holds the
**output contracts** those calls are held to. The schemas are the point: the owner's framing
was that a citation is "more of an output contract thing", and here it literally is one.

## What a model may say, and what code decides

- A model names evidence by `(doc_id, verbatim quote)` — `content.ProposedCitation`, reused,
  not redefined — and code resolves it through `content.resolve_blocks` against the
  evidence pack it was shown (A1). Page, bbox and hash never come from a model.
- A key message's evidence status is **never** a field here. It is computed from which of
  the message's own citations resolved, with `evidence_gap._cap`'s rule (one non-curated
  span is `thin`; none is `unsupported`), exactly as the planner's probe would have set it —
  without the probe's per-message call (B45).
- Coverage — what the draft did with everything the person asked for — is reported by the
  model (`coverage`) **and** recomputed by code from the resolved draft; a code finding is
  never overridden by a model claim that something was covered (B48).

## B26, again

Every list field is required and non-nullable. Gemini silently omits optional nested arrays
on some fraction of calls, and a slide whose `blocks` arrive missing reads perfectly in the
model's prose fields while the structure that becomes the deck is empty. An empty list is a
legitimate answer (`citations: []` for a message nothing supports); an absent one is not.

## Agreed messages are kept (B48)

`ComposedMessage.origin` records whether the person asked for a message (in the prompt, an
answer or the chat) or the composer proposed it. A message the person agreed to is never
dropped for weak evidence: if it is `thin` it stays on its slides, hedged; if it is
`unsupported` it stays in the brief as a named gap and no uncited sentence is written for
it. Code enforces the first half (an agreed message with no slide is a coverage finding);
`prompts/compose.md` asks for the second.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.content import (
    ProposedBlock,
    ProposedCitation,
    ProposedClaim,
    check_budgets,
    resolve_blocks,
    slide_budgets,
)
from autodeck.agents.evidence_gap import EvidenceSpan, _cap
from autodeck.agents.evidence_pack import EvidencePack
from autodeck.agents.outline import CATALOG
from autodeck.agents.planner import Draft
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ingest.deck_source import DOC_ID_PREFIX
from autodeck.ingest.document_store import DocumentStore
from autodeck.ingest.redesign_settings import settings_text
from autodeck.ir.models import Block, Deck, KeyMessage, Slide
from autodeck.knowledge.context_assembler import AssembledContext

# ---------------------------------------------------------------------------
# Clarify: the checkpoint before the draft (B47, B48)
# ---------------------------------------------------------------------------

AssumptionTopic = Literal["audience", "decision", "length", "evidence", "scope", "voice"]


class Assumption(BaseModel):
    """Something the draft will take as given unless the person corrects it."""

    model_config = ConfigDict(extra="forbid")

    topic: AssumptionTopic
    statement: str = Field(
        min_length=1,
        description="One plain sentence: 'Five slides, for clinicians on the P&T committee.'",
    )


class ClarifyingQuestion(BaseModel):
    """A question whose answer would change the deck — never one asked to fill the step."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="q1, q2, q3.")
    question: str = Field(min_length=1)
    why: str = Field(
        min_length=1,
        description="What changes in the deck depending on the answer, in one sentence.",
    )
    suggested_answer: str = Field(
        min_length=1, description="What the draft will do if the person just accepts."
    )
    options: list[str] = Field(
        description="Two to four short alternatives, or [] for a free-text question."
    )


class ClarifyResult(BaseModel):
    """The checkpoint: assumptions always, questions only when they matter (B48)."""

    model_config = ConfigDict(extra="forbid")

    assumptions: list[Assumption] = Field(min_length=1)
    questions: list[ClarifyingQuestion] = Field(max_length=3)


# ---------------------------------------------------------------------------
# Compose: brief + outline + slides in one call (B45)
# ---------------------------------------------------------------------------

MessageOrigin = Literal["prompt", "answer", "chat", "proposed"]


class ComposedMessage(BaseModel):
    """A key message, with the evidence the composer says supports it.

    `citations` may be empty — that is how a message nothing supports is stated honestly —
    but it may not be absent (B26). Its evidence status is computed from what resolves.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="km1, km2, …")
    text: str = Field(min_length=1)
    origin: MessageOrigin
    citations: list[ProposedCitation]


class ComposedSlide(BaseModel):
    """One slide: its place in the argument (the outline) and its blocks (the content)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="s1, s2, … in deck order.")
    narrative_role: str = Field(min_length=1)
    component: str = Field(min_length=1, description="A catalog component name.")
    intent: str = Field(min_length=1, description="What this slide must accomplish.")
    message_ids: list[str] = Field(description="Key messages this slide serves; [] for none.")
    blocks: list[ProposedBlock] = Field(min_length=1)
    speaker_notes: list[ProposedBlock]


CoverageStatus = Literal["covered", "hedged", "gap", "left_out"]


class CoverageNote(BaseModel):
    """What the draft did with one thing the person asked for (B48)."""

    model_config = ConfigDict(extra="forbid")

    item: str = Field(min_length=1, description="What was asked for, in the person's terms.")
    status: CoverageStatus
    detail: str = Field(
        min_length=1,
        description=(
            "covered: where. hedged: on which slide and why the evidence is thin. gap: what "
            "is missing from the evidence. left_out: why it is not in the draft."
        ),
    )


class ComposeDraft(BaseModel):
    """The whole first draft: brief, outline and every slide, in one response."""

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, description="The decision the deck should produce.")
    audience: str = Field(min_length=1)
    length_target: int = Field(ge=1)
    key_messages: list[ComposedMessage] = Field(min_length=1)
    must_include: list[str]
    must_avoid: list[str]
    slides: list[ComposedSlide] = Field(min_length=1)
    coverage: list[CoverageNote]
    notes: str = Field(description="Anything the person should know first; '' for none.")


# ---------------------------------------------------------------------------
# Redesign: the client's deck is the source (B41, Phase 3d)
# ---------------------------------------------------------------------------


class LayoutChange(BaseModel):
    """Where one redesigned slide came from, and why its layout changed (or did not)."""

    model_config = ConfigDict(extra="forbid")

    slide_id: str = Field(min_length=1, description="The new slide's id.")
    original_slides: list[int] = Field(
        min_length=1, description="The original slide number(s) it was built from."
    )
    why: str = Field(min_length=1, description="One sentence on the layout change, or 'kept'.")


class RedesignDraft(ComposeDraft):
    """A first draft rebuilt from the client's own deck (`prompts/redesign.md`).

    The same contract as `ComposeDraft` — every citation a verbatim quote, here from a
    `client-deck--` document whose pages are the original slides — plus `changes`, one per new
    slide, which the review screen shows beside the original.
    """

    changes: list[LayoutChange] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Revise: one instruction, only what it touches (3c.9)
# ---------------------------------------------------------------------------


class ReviseDraft(BaseModel):
    """A scoped change to an existing draft.

    The brief comes back whole (it is small, and returning it whole is the only way a
    change to it is unambiguous); slides come back only when they are new or rewritten.
    Every other slide is kept by code **exactly** as it was — same resolved blocks, same
    verdicts — which is what lets validation reuse their verdicts and lets the outline and
    claims approvals survive a change that does not touch them (B43, B44).
    """

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    length_target: int = Field(ge=1)
    key_messages: list[ComposedMessage] = Field(min_length=1)
    must_include: list[str]
    must_avoid: list[str]
    changed_slides: list[ComposedSlide] = Field(
        description="New or rewritten slides only; [] when the change is brief-only."
    )
    removed_slide_ids: list[str]
    order: list[str] = Field(min_length=1, description="Every slide id, in the new order.")
    coverage: list[CoverageNote]
    reply: str = Field(
        min_length=1, description="One or two sentences to the person: what changed and why."
    )


# ===========================================================================
# The agent: three structured calls, and everything code decides around them
# ===========================================================================
#
# A model's answer here is a proposal. Code resolves every citation (A1, through
# `content.resolve_blocks` — there is no third path), computes every key message's evidence
# status from what resolved, enforces slot budgets, and recomputes coverage from the draft it
# actually built. Nothing below calls a model more than once per function.

CLARIFY_PROMPT = Path("prompts/clarify.md")
COMPOSE_PROMPT = Path("prompts/compose.md")
REVISE_PROMPT = Path("prompts/revise.md")
REDESIGN_PROMPT = Path("prompts/redesign.md")
CONTENT_PROMPT = Path("prompts/content.md")

PROMPT_SEPARATOR = "\n\n---\n\n"
"""Compose and revise are the same writer as `content`: its rules follow their own."""

MAX_OUTPUT_TOKENS = 32768
"""A whole deck is far longer than the provider default (8192) and truncates mid-JSON."""

AGREED_ORIGINS = frozenset({"prompt", "answer", "chat"})
"""Messages the person asked for. They are never dropped for weak evidence (B48)."""


class ComposeError(RuntimeError):
    """A compose-family call could not be made or produced nothing usable."""


class ComposeModel(Protocol):
    def complete_structured(
        self, prompt: str, response_model: type[Any], *, system: str | None = None
    ) -> Any: ...  # pragma: no cover — protocol shape only


@dataclass
class ComposeResult:
    """A first draft, resolved: the IR deck, the draft brief, and what was reported on it."""

    deck: Deck
    draft_brief: Draft
    coverage: list[dict[str, str]]
    rejections: list[str]
    """Every dropped block (unresolved citation, overflow), key-message citations included."""
    notes: str
    """The composer's own note to the person, or ''."""
    provider_calls: int = 1
    corrections: list[str] = field(default_factory=list)
    """Structural repairs: an unknown component, a duplicate id, an invented message id."""
    incomplete_slots: list[str] = field(default_factory=list)
    origins: dict[str, str] = field(default_factory=dict)
    """key message id -> origin; revise needs them to keep agreed messages agreed."""
    changes: list[dict[str, Any]] = field(default_factory=list)
    """Redesign only: per new slide, the original slide(s) it came from and why its layout
    changed (`LayoutChange` as dicts). Empty for a first draft from papers."""


@dataclass
class ReviseResult:
    """A revised draft: untouched slides identical, changed slides re-resolved."""

    deck: Deck
    draft_brief: Draft
    coverage: list[dict[str, str]]
    rejections: list[str]
    reply: str
    notes: list[str] = field(default_factory=list)
    """Code-side remarks: an unusable order, a removal of an unknown slide."""
    provider_calls: int = 1
    corrections: list[str] = field(default_factory=list)
    incomplete_slots: list[str] = field(default_factory=list)
    changed_slide_ids: list[str] = field(default_factory=list)
    origins: dict[str, str] = field(default_factory=dict)


# -- prompts ------------------------------------------------------------------


def _read_prompt(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        raise ComposeError(
            f"prompt not found at {path}. Prompts are versioned files (plan §0.5) and their "
            "hashes go into the build manifest — there is no inline fallback."
        )
    return path.read_text(encoding="utf-8")


def _writer_system(path: Path, content_path: Path) -> str:
    return _read_prompt(path) + PROMPT_SEPARATOR + _read_prompt(content_path)


def _call(model: ComposeModel, prompt: str, schema: type[Any], system: str, what: str) -> Any:
    try:
        return model.complete_structured(prompt, schema, system=system)
    except Exception as exc:
        raise ComposeError(f"{what} failed: {type(exc).__name__}: {exc}") from exc


# -- clarify ------------------------------------------------------------------


def clarify(
    prompt: str,
    *,
    pack: EvidencePack,
    context: AssembledContext,
    model: ComposeModel,
    prompt_path: Path = CLARIFY_PROMPT,
    redesign: Mapping[str, Any] | None = None,
) -> ClarifyResult:
    """One short call: what the draft assumes, and the few questions that would change it.

    With `redesign` (the run's settings) the request is a redesign of the client's deck and
    the evidence pack is that deck; the question list stays "only what changes the deck".
    """
    system = _read_prompt(prompt_path)
    request = f"# The request\n\n{prompt.strip()}"
    evidence = "# Evidence pack\n\n" + pack.text
    if redesign is not None:
        request += (
            "\n\nThis is a redesign of a deck the client already has, not a new deck. The "
            "evidence below is that whole deck, slide by slide. The person's settings:\n"
            + settings_text(redesign)
            + "\n\nThe redesign is one slide in, one slide out. Merging or splitting slides "
            "happens only on the person's request (B49): you may ask whether to, where the "
            "deck plainly needs it, but never assume it."
        )
        evidence = "# The client's deck\n\n" + pack.text
    user = PROMPT_SEPARATOR.join(
        [request, "# Client context\n\n" + context.to_prompt_context(), evidence]
    )
    result = _call(model, user, ClarifyResult, system, "clarify")
    return result


# -- user messages --------------------------------------------------------------


def _catalog_text(tokens: DesignTokens) -> str:
    return "\n\n".join(f"## {name}\n{slide_budgets(name, tokens)}" for name in CATALOG)


def _answers_text(answers: Sequence[tuple[str, str] | str]) -> str:
    """Answers as Q/A pairs; a bare string is a correction to an assumption."""
    if not answers:
        return "(no questions were asked, and nothing was corrected)"
    lines: list[str] = []
    for entry in answers:
        if isinstance(entry, str):
            lines.append(f"- Correction to an assumption: {entry}")
        else:
            question, answer = entry
            lines.append(f"- Q: {question}\n  A: {answer}")
    return "\n".join(lines)


def _brief_text(draft: Draft) -> str:
    lines = [
        f"objective: {draft.objective}",
        f"audience: {draft.audience}",
        f"length_target: {draft.length_target or 'not set'}",
        "key_messages:",
    ]
    for message in draft.key_messages:
        lines.append(f"  - {message.id}: {message.text}")
    lines.append(f"must_include: {', '.join(draft.must_include) or '(none)'}")
    lines.append(f"must_avoid: {', '.join(draft.must_avoid) or '(none)'}")
    return "\n".join(lines)


def _compose_prompt(
    prompt: str,
    *,
    answers: Sequence[tuple[str, str] | str],
    pack: EvidencePack,
    context: AssembledContext,
    tokens: DesignTokens,
    chat_brief: Draft | None,
    redesign: Mapping[str, Any] | None = None,
) -> str:
    parts = [f"# The request\n\n{prompt.strip()}"]
    if redesign is not None:
        parts.append(
            "# Redesign settings\n\nRebuild the client's deck, shown below slide by slide. "
            "Every citation names the deck's document id and quotes the original slide "
            "verbatim.\n" + settings_text(redesign)
        )
    if chat_brief is not None:
        parts.append(
            "# The brief, already agreed\n\nThe person shaped this brief in conversation. Keep "
            "its objective, audience and key messages verbatim; set their origin to chat. "
            "Write the outline and the slides to it; do not write a brief of your own.\n\n"
            + _brief_text(chat_brief)
        )
    parts.append("# The person's answers\n\n" + _answers_text(answers))
    parts.append("# Client context\n\n" + context.to_prompt_context())
    parts.append(
        "# Components and their slot budgets (hard constraints)\n\n" + _catalog_text(tokens)
    )
    heading = "The client's deck" if redesign is not None else "Evidence pack"
    parts.append(f"# {heading} — everything you may cite\n\n" + pack.text)
    return PROMPT_SEPARATOR.join(parts)


def _block_lines(block: Block) -> list[str]:
    head = f"    [{block.id}] {block.kind} · slot {block.slot}"
    if block.claim is not None:
        claim = block.claim
        lines = [f"{head} · verdict: {claim.verdict}", f"      {claim.text}"]
        if claim.verdict_notes:
            lines.append(f"      verdict notes: {claim.verdict_notes}")
        for citation in claim.citations:
            lines.append(f"      cites {citation.doc_id} p.{citation.page}: {citation.quote!r}")
        return lines
    if block.text is not None:
        return [head, f"      {block.text}"]
    return [head + " (not text)"]


def _draft_text(deck: Deck, brief: Draft, origins: Mapping[str, str]) -> str:
    lines = [_brief_text(brief).split("key_messages:")[0].rstrip(), "key_messages:"]
    for message in brief.key_messages:
        origin = origins.get(message.id, "prompt")
        lines.append(f"  - {message.id} [{origin}] [{message.evidence_status}]: {message.text}")
        if message.probe_notes:
            lines.append(f"      evidence: {message.probe_notes}")
    lines.append(f"must_include: {', '.join(brief.must_include) or '(none)'}")
    lines.append(f"must_avoid: {', '.join(brief.must_avoid) or '(none)'}")
    lines.append("")
    for number, slide in enumerate(deck.slides, start=1):
        served = ", ".join(slide.message_ids) or "-"
        lines.append(
            f"slide {slide.id} (#{number}) · {slide.component} · {slide.narrative_role} "
            f"· serves {served}"
        )
        lines.append(f"  intent: {slide.intent or '(none)'}")
        lines.append("  face:")
        for block in slide.blocks:
            lines.extend(_block_lines(block))
        if slide.speaker_notes:
            lines.append("  notes:")
            for block in slide.speaker_notes:
                lines.extend(_block_lines(block))
    return "\n".join(lines)


def _revise_prompt(
    instruction: str,
    *,
    deck: Deck,
    brief: Draft,
    origins: Mapping[str, str],
    pack: EvidencePack,
    context: AssembledContext,
    tokens: DesignTokens,
) -> str:
    return PROMPT_SEPARATOR.join(
        [
            f"# The instruction\n\n{instruction.strip()}",
            "# The current draft\n\n" + _draft_text(deck, brief, origins),
            "# Client context\n\n" + context.to_prompt_context(),
            "# Components and their slot budgets (hard constraints)\n\n"
            + _catalog_text(tokens),
            "# Evidence pack — everything you may cite\n\n" + pack.text,
        ]
    )


# -- resolution -----------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _resolve_slides(
    composed: Sequence[ComposedSlide],
    *,
    pack: EvidencePack,
    store: DocumentStore,
    tokens: DesignTokens,
    known_messages: set[str],
    message_map: Mapping[str, str],
    rejections: list[str],
    corrections: list[str],
    incomplete: list[str],
) -> list[Slide | None]:
    """Resolve each composed slide into an IR `Slide`; `None` where it cannot be built.

    Citations go through `content.resolve_blocks` against the pack the model was shown, and
    budgets through `content.check_budgets`, exactly as a single-slide write does.
    """
    out: list[Slide | None] = []
    seen: set[str] = set()
    for position, item in enumerate(composed, start=1):
        if item.component not in CATALOG:
            corrections.append(
                f"slide {item.id!r} named component {item.component!r}, which is not in the "
                "catalog; dropped. A component the renderer lacks fails at render time."
            )
            out.append(None)
            continue

        slide_id = item.id if item.id not in seen else f"{item.id}-{position}"
        if slide_id != item.id:
            corrections.append(f"duplicate slide id {item.id!r} renamed to {slide_id!r}")
        seen.add(slide_id)

        mapped = [message_map.get(mid, mid) for mid in item.message_ids]
        invented = [mid for mid in mapped if mid not in known_messages]
        if invented:
            corrections.append(
                f"slide {slide_id!r} claimed to serve key message(s) {', '.join(invented)}, "
                "which are not in the brief; references dropped."
            )

        local: list[str] = []
        face = resolve_blocks(
            item.blocks,
            store=store,
            claims=pack.claims,
            spans=pack.spans,
            location=f"slide {slide_id} face",
            rejections=local,
            snapped=corrections,
        )
        notes = resolve_blocks(
            item.speaker_notes,
            store=store,
            claims=pack.claims,
            spans=pack.spans,
            location=f"slide {slide_id} notes",
            rejections=local,
            snapped=corrections,
        )
        kept, overflow, missing, _checked = check_budgets(
            face, component=item.component, tokens=tokens
        )
        rejections.extend(local)
        rejections.extend(f"slide {slide_id}: {reason}" for reason in overflow)
        incomplete.extend(f"slide {slide_id}: {finding}" for finding in missing)
        if not kept:
            rejections.append(
                f"slide {slide_id}: no block survived resolution; the slide is empty"
            )

        out.append(
            Slide(
                id=slide_id,
                narrative_role=item.narrative_role,
                component=item.component,
                intent=item.intent,
                message_ids=[mid for mid in mapped if mid in known_messages],
                blocks=kept,
                speaker_notes=notes,
            )
        )
    return out


def _grade(
    message: ComposedMessage,
    *,
    pack: EvidencePack,
    store: DocumentStore,
    rejections: list[str],
    snapped: list[str] | None = None,
) -> KeyMessage:
    """Evidence status from what the message's own citations resolved to (B45).

    Each citation is resolved on its own through `content.resolve_blocks`, wrapped in a
    throwaway claim block, so a message's citation takes the same path a slide's does. The
    status then follows `evidence_gap._cap`: nothing resolved is `unsupported`; a single
    non-curated passage is `thin`; anything more is `supported` — except on a redesign,
    where citations to the client's own deck alone are `supported` (B50).
    """
    evidence: list[EvidenceSpan] = []
    seen: set[tuple[str, int, str]] = set()
    for index, proposed in enumerate(message.citations):
        probe = ProposedBlock(
            id=f"{message.id}-c{index}",
            kind="claim",
            slot="evidence",
            claim=ProposedClaim(text=message.text, citations=[proposed]),
        )
        resolved = resolve_blocks(
            [probe],
            store=store,
            claims=pack.claims,
            spans=pack.spans,
            location=f"key message {message.id}",
            rejections=rejections,
            snapped=snapped,
        )
        for block in resolved:
            assert block.claim is not None
            citation = block.claim.citations[0]
            if citation.identity() in seen:
                continue
            seen.add(citation.identity())
            curated = any(
                c.doc_id == proposed.doc_id and c.quote == proposed.quote for c in pack.claims
            )
            evidence.append(
                EvidenceSpan(
                    doc_id=citation.doc_id,
                    page=citation.page,
                    text=citation.quote,
                    source="claims.md" if curated else "corpus",
                )
            )

    proposed_count = len(message.citations)
    if not evidence:
        status = "unsupported"
        note = "no passage in the evidence pack supports this"
        if proposed_count:
            note += f" ({proposed_count} citation(s) proposed, none resolved)"
    elif all(e.doc_id.startswith(DOC_ID_PREFIX) for e in evidence):
        # A redesign (B41, B50): the claim is faithfulness to the client's own deck, so one
        # slide that states the message supports it. `_cap`'s one-source rule is about
        # research evidence, where a single passage is weak; here it would make the person
        # accept a "risk" for every message their own deck makes once.
        status = "supported"
        note = "stated in the client's deck: " + "; ".join(f"slide {e.page}" for e in evidence)
    else:
        status, _capped = _cap("supported", evidence)
        if status == "thin":
            only = evidence[0]
            note = f"one passage only: {only.doc_id} p.{only.page}"
        else:
            note = f"{len(evidence)} passages: " + "; ".join(
                f"{e.doc_id} p.{e.page}" for e in evidence
            )
        if len(evidence) < proposed_count:
            note += f" ({proposed_count - len(evidence)} proposed citation(s) did not resolve)"

    doc_ids = list(dict.fromkeys(e.doc_id for e in evidence))
    return KeyMessage(
        id=message.id,
        text=message.text,
        evidence_status=status,  # type: ignore[arg-type]
        supporting_claims=doc_ids,
        probe_notes=note,
    )


# -- coverage -------------------------------------------------------------------


def _slide_names(ids: Sequence[str]) -> str:
    return ("slide " if len(ids) == 1 else "slides ") + ", ".join(ids)


_STOPWORDS = frozenset(
    {"the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "has", "its"}
)


def _words(text: str) -> list[str]:
    return [w for w in _norm(text).split() if len(w) >= 3 and w not in _STOPWORDS]


def _face_text(slide: Slide) -> str:
    parts: list[str] = []
    for block in slide.blocks:
        if block.claim is not None:
            parts.append(block.claim.text)
        elif block.text:
            parts.append(block.text)
    return _norm(" ".join(parts))


def _matches(entry_item: str, text: str, ident: str = "") -> bool:
    entry, target = _norm(entry_item), _norm(text)
    if not entry or not target:
        return False
    if entry == target or (ident and entry.split()[0] == ident.lower()):
        return True
    return (len(entry) >= 4 and entry in target) or (len(target) >= 4 and target in entry)


def _coverage(
    model_notes: Sequence[CoverageNote],
    *,
    messages: Sequence[KeyMessage],
    origins: Mapping[str, str],
    slides: Sequence[Slide],
    must_include: Sequence[str],
) -> list[dict[str, str]]:
    """The model's coverage report, corrected by what the built draft actually shows (B48).

    Every message the person agreed to and every `must_include` gets a code finding. Where
    the model said something different about the same item, the code finding replaces it, so
    a claim of "covered" for a message no slide serves cannot stand. Where they agree, the
    model's wording is kept (it is usually the more specific one).
    """
    entries = [{"item": n.item, "status": n.status, "detail": n.detail} for n in model_notes]

    def apply(finding: dict[str, str], matches: Any) -> None:
        indexes = [i for i, e in enumerate(entries) if matches(e["item"])]
        if not indexes:
            entries.append(finding)
            return
        keep = next((i for i in indexes if entries[i]["status"] == finding["status"]), None)
        if keep is not None:
            entries[:] = [e for i, e in enumerate(entries) if i == keep or i not in indexes]
            return
        first = indexes[0]
        entries[first] = finding
        entries[:] = [e for i, e in enumerate(entries) if i == first or i not in indexes]

    for message in messages:
        if origins.get(message.id, "prompt") not in AGREED_ORIGINS:
            continue
        serving = [s.id for s in slides if message.id in s.message_ids]
        note = message.probe_notes or message.evidence_status
        if message.evidence_status == "unsupported":
            status = "gap"
            detail = f"{note}; kept in the brief, no uncited sentence written for it"
            if serving:
                detail += f" ({_slide_names(serving)} serve it)"
        elif not serving:
            status = "left_out"
            detail = f"no slide serves this message (its evidence is {message.evidence_status})"
        elif message.evidence_status == "thin":
            status = "hedged"
            detail = f"on {_slide_names(serving)}: evidence is thin — {note}"
        else:
            status = "covered"
            detail = f"on {_slide_names(serving)}"
        apply(
            {"item": message.text, "status": status, "detail": detail},
            lambda item, m=message: _matches(item, m.text, m.id),
        )

    face = {slide.id: set(_face_text(slide).split()) for slide in slides}
    for required in must_include:
        wanted = set(_words(required))
        found = [sid for sid, words in face.items() if wanted <= words]
        if found or not wanted:
            status, detail = (
                "covered",
                f"on {_slide_names(found)}" if found else "(no key words)",
            )
        else:
            status, detail = "left_out", "its words appear on no slide"
        apply(
            {"item": required, "status": status, "detail": detail},
            lambda item, r=required: _matches(item, r),
        )
    return entries


#: A line of the client's deck shorter than this is a label ("Recommendation", a table's
#: header row), not a statement worth reporting as left out.
_MIN_STATEMENT_WORDS = 4


def _redesign_left_out(slides: Sequence[Slide], pack: EvidencePack) -> list[dict[str, str]]:
    """Every statement of the client's deck that the redesign does not carry (B48, Phase 3d).

    Checked in code, not taken from the model's coverage notes: a line is carried when a
    claim on any slide (face or notes) cites a quote from it, or when its text appears in a
    block's text. Anything else is reported `left_out` with the slide it came from, so a
    bullet the redesign quietly dropped is called out rather than covered by a model's
    "original slide 5: covered".
    """
    cited: list[tuple[str, int, str]] = []
    texts: list[str] = []
    for slide in slides:
        for block in [*slide.blocks, *slide.speaker_notes]:
            if block.text:
                texts.append(_norm(block.text))
        for site in slide.claim_sites():
            texts.append(_norm(site.claim.text))
            for citation in site.claim.citations:
                cited.append((citation.doc_id, citation.page, _norm(citation.quote)))
    carried_text = " \n ".join(texts)

    findings: list[dict[str, str]] = []
    seen: set[tuple[int, str]] = set()
    for span in pack.spans:
        if not (span.citable and span.doc_id.startswith(DOC_ID_PREFIX)):
            continue
        line = _norm(span.text)
        if len(line.split()) < _MIN_STATEMENT_WORDS or (span.page, line) in seen:
            continue
        seen.add((span.page, line))
        quoted = any(
            doc == span.doc_id
            and page == span.page
            and quote
            and (quote in line or line in quote)
            for doc, page, quote in cited
        )
        if quoted or line in carried_text:
            continue
        excerpt = " ".join(span.text.split())
        if len(excerpt) > 90:
            excerpt = excerpt[:87].rsplit(" ", 1)[0] + "…"
        findings.append(
            {
                "item": f"Original slide {span.page}: “{excerpt}”",
                "status": "left_out",
                "detail": "not on the redesigned deck — neither cited nor carried over",
            }
        )
    return findings


# -- compose --------------------------------------------------------------------


def _chat_merge(
    messages: list[ComposedMessage], chat_brief: Draft
) -> tuple[list[ComposedMessage], dict[str, str], list[KeyMessage]]:
    """Keep the chat brief's messages verbatim (B47, B48), borrowing the composer's citations.

    Returns the merged message list, the model-id -> final-id map for slides, and the chat
    messages the composer did not mention at all (kept as the planner left them).
    """
    id_map: dict[str, str] = {}
    by_text = {_norm(m.text): m for m in messages}
    by_id = {m.id: m for m in messages}
    taken = {m.id for m in chat_brief.key_messages}
    merged: list[ComposedMessage] = []
    untouched: list[KeyMessage] = []
    used: set[int] = set()
    for chat in chat_brief.key_messages:
        match = by_text.get(_norm(chat.text)) or by_id.get(chat.id)
        if match is None or id(match) in used:
            untouched.append(chat)
            continue
        used.add(id(match))
        id_map[match.id] = chat.id
        merged.append(
            ComposedMessage(
                id=chat.id, text=chat.text, origin="chat", citations=list(match.citations)
            )
        )
    for message in messages:
        if id(message) in used:
            continue
        new_id = message.id
        while new_id in taken:
            new_id = f"{new_id}x"
        taken.add(new_id)
        id_map[message.id] = new_id
        merged.append(message.model_copy(update={"id": new_id}))
    return merged, id_map, untouched


def compose_deck(
    prompt: str,
    *,
    answers: Sequence[tuple[str, str] | str],
    pack: EvidencePack,
    context: AssembledContext,
    store: DocumentStore,
    tokens: DesignTokens,
    model: ComposeModel,
    run_id: str,
    client: str,
    project: str,
    theme_ref: str,
    component_lib_version: str,
    chat_brief: Draft | None = None,
    prompt_path: Path | None = None,
    content_prompt_path: Path = CONTENT_PROMPT,
    mode: Literal["compose", "redesign"] = "compose",
    settings: Mapping[str, Any] | None = None,
) -> ComposeResult:
    """One call writes brief, outline and every slide; code resolves and audits the answer.

    `mode="redesign"` (Phase 3d, B41) rebuilds the client's own deck: the system prompt is
    `prompts/redesign.md` followed by `content.md`, the response model is `RedesignDraft`,
    and the user message states `settings` and shows the deck. Everything after the call —
    resolution against the pack (A1), budgets, evidence status, coverage — is the same code
    as a first draft; the model's `changes` are kept, minus any naming a slide that did not
    survive, in `ComposeResult.changes`.

    Raises:
        ComposeError: the prompt is missing, the call failed, or no slide could be built.
    """
    redesign = mode == "redesign"
    if redesign and settings is None:
        raise ComposeError("a redesign needs the run's settings (wording, layouts, papers).")
    system = _writer_system(
        prompt_path or (REDESIGN_PROMPT if redesign else COMPOSE_PROMPT), content_prompt_path
    )
    user = _compose_prompt(
        prompt,
        answers=answers,
        pack=pack,
        context=context,
        tokens=tokens,
        chat_brief=chat_brief,
        redesign=settings if redesign else None,
    )
    draft: ComposeDraft = _call(
        model, user, RedesignDraft if redesign else ComposeDraft, system, "compose"
    )

    rejections: list[str] = []
    corrections: list[str] = []
    incomplete: list[str] = []

    messages = list(draft.key_messages)
    objective, audience, length_target = draft.objective, draft.audience, draft.length_target
    must_include, must_avoid = list(draft.must_include), list(draft.must_avoid)
    message_map: dict[str, str] = {}
    untouched: list[KeyMessage] = []
    header_style = None
    layout_pins: list[Any] = []
    open_risks: list[Any] = []
    if chat_brief is not None:
        messages, message_map, untouched = _chat_merge(messages, chat_brief)
        objective = chat_brief.objective or objective
        audience = chat_brief.audience or audience
        length_target = chat_brief.length_target or length_target
        must_include = [
            *chat_brief.must_include,
            *(m for m in must_include if m not in chat_brief.must_include),
        ]
        must_avoid = [
            *chat_brief.must_avoid,
            *(m for m in must_avoid if m not in chat_brief.must_avoid),
        ]
        header_style = chat_brief.header_style
        layout_pins = list(chat_brief.layout_pins)
        open_risks = list(chat_brief.open_risks)

    graded = [
        _grade(m, pack=pack, store=store, rejections=rejections, snapped=corrections)
        for m in messages
    ]
    origins = {m.id: m.origin for m in messages}
    for kept_message in untouched:
        graded.append(kept_message)
        origins[kept_message.id] = "chat"
    known = {m.id for m in graded}

    resolved = _resolve_slides(
        draft.slides,
        pack=pack,
        store=store,
        tokens=tokens,
        known_messages=known,
        message_map=message_map,
        rejections=rejections,
        corrections=corrections,
        incomplete=incomplete,
    )
    slides = [s for s in resolved if s is not None]
    if not slides:
        raise ComposeError(
            "the draft contained no usable slides after validation: every slide named an "
            "unknown component."
        )

    deck = Deck(
        run_id=run_id,
        project=project,
        client=client,
        audience=audience,
        version=1,
        slides=slides,
        theme_ref=theme_ref,
        component_lib_version=component_lib_version,
    )
    brief = Draft(
        objective=objective,
        audience=audience,
        key_messages=graded,
        must_include=must_include,
        must_avoid=must_avoid,
        length_target=length_target,
        header_style=header_style,
        layout_pins=layout_pins,
        open_risks=open_risks,
    )
    coverage = _coverage(
        draft.coverage,
        messages=graded,
        origins=origins,
        slides=slides,
        must_include=must_include,
    )
    if redesign:
        coverage.extend(_redesign_left_out(slides, pack))
    changes: list[dict[str, Any]] = []
    if isinstance(draft, RedesignDraft):
        built_ids = {s.id for s in slides}
        for change in draft.changes:
            if change.slide_id in built_ids:
                changes.append(change.model_dump(mode="json"))
            else:
                corrections.append(
                    f"layout note for {change.slide_id!r} dropped: no such slide was built"
                )
    return ComposeResult(
        deck=deck,
        draft_brief=brief,
        coverage=coverage,
        rejections=rejections,
        notes=draft.notes,
        provider_calls=1,
        corrections=corrections,
        incomplete_slots=incomplete,
        origins=origins,
        changes=changes,
    )


# -- revise ---------------------------------------------------------------------


def revise_deck(
    instruction: str,
    *,
    deck: Deck,
    draft_brief: Draft,
    pack: EvidencePack,
    context: AssembledContext,
    store: DocumentStore,
    tokens: DesignTokens,
    model: ComposeModel,
    origins: Mapping[str, str] | None = None,
    prompt_path: Path = REVISE_PROMPT,
    content_prompt_path: Path = CONTENT_PROMPT,
) -> ReviseResult:
    """One call applies one instruction; slides it does not return are kept exactly.

    `origins` maps key message id -> origin from the draft being revised (`ComposeResult
    .origins`); an id it does not know is shown to the model as `prompt`, the safe reading,
    because an agreed message is never dropped for weak evidence (B48).

    Unchanged key messages (same id and text, and no citations offered) keep their evidence
    status and notes; a changed or new message, or one the model offers citations for, is
    graded again.
    """
    origins = dict(origins or {})
    system = _writer_system(prompt_path, content_prompt_path)
    user = _revise_prompt(
        instruction,
        deck=deck,
        brief=draft_brief,
        origins=origins,
        pack=pack,
        context=context,
        tokens=tokens,
    )
    draft: ReviseDraft = _call(model, user, ReviseDraft, system, "revise")

    rejections: list[str] = []
    corrections: list[str] = []
    incomplete: list[str] = []
    notes: list[str] = []

    # Key messages: keep what did not change, grade what did.
    old = {m.id: m for m in draft_brief.key_messages}
    graded: list[KeyMessage] = []
    new_origins: dict[str, str] = {}
    for message in draft.key_messages:
        previous = old.get(message.id)
        new_origins[message.id] = message.origin
        if previous is not None and previous.text == message.text and not message.citations:
            graded.append(previous)
        else:
            graded.append(
                _grade(
                    message, pack=pack, store=store, rejections=rejections, snapped=corrections
                )
            )
    known = {m.id for m in graded}

    # Slides: changed ones are resolved; the rest are the very same objects.
    existing = {s.id: s for s in deck.slides}
    resolved = _resolve_slides(
        draft.changed_slides,
        pack=pack,
        store=store,
        tokens=tokens,
        known_messages=known,
        message_map={},
        rejections=rejections,
        corrections=corrections,
        incomplete=incomplete,
    )
    rebuilt: dict[str, Slide] = {}
    for item, slide in zip(draft.changed_slides, resolved, strict=True):
        if slide is None:
            if item.id in existing:
                notes.append(
                    f"the rewrite of slide {item.id!r} was unusable; it is kept as it was"
                )
            continue
        rebuilt[slide.id] = slide

    removed = set()
    for slide_id in draft.removed_slide_ids:
        if slide_id in existing:
            removed.add(slide_id)
        else:
            notes.append(f"asked to remove slide {slide_id!r}, which is not in the draft")

    by_id = {**existing, **rebuilt}
    remaining = [
        sid
        for sid in [*existing, *(r for r in rebuilt if r not in existing)]
        if sid not in removed
    ]
    wanted = list(draft.order)
    if sorted(wanted) == sorted(remaining) and len(set(wanted)) == len(wanted):
        order = wanted
    else:
        order = remaining
        if wanted != remaining:
            notes.append(
                "the proposed slide order did not list every remaining slide exactly once; "
                "the previous order was kept and any new slides were added at the end"
            )
    slides = [by_id[sid] for sid in order]
    if not slides:
        raise ComposeError(
            "the revision would leave the deck with no slides; nothing was changed."
        )

    for slide in slides:
        stale = [mid for mid in slide.message_ids if mid not in known]
        if stale and slide.id not in rebuilt:
            corrections.append(
                f"slide {slide.id!r} still serves key message(s) {', '.join(stale)}, which "
                "are no longer in the brief"
            )

    new_deck = deck.model_copy(
        update={"version": deck.version + 1, "slides": slides, "audience": draft.audience}
    )
    surviving = {m.id for m in graded}
    brief = Draft(
        objective=draft.objective,
        audience=draft.audience,
        key_messages=graded,
        must_include=list(draft.must_include),
        must_avoid=list(draft.must_avoid),
        length_target=draft.length_target,
        header_style=draft_brief.header_style,
        layout_pins=[p for p in draft_brief.layout_pins if p.message_id in surviving],
        open_risks=[r for r in draft_brief.open_risks if r.message_id in surviving],
    )
    coverage = _coverage(
        draft.coverage,
        messages=graded,
        origins=new_origins,
        slides=slides,
        must_include=brief.must_include,
    )
    return ReviseResult(
        deck=new_deck,
        draft_brief=brief,
        coverage=coverage,
        rejections=rejections,
        reply=draft.reply,
        notes=notes,
        provider_calls=1,
        corrections=corrections,
        incomplete_slots=incomplete,
        changed_slide_ids=list(rebuilt),
        origins=new_origins,
    )
