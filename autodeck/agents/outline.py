"""The outline agent: a signed brief becomes an IR skeleton (task 2a.7).

Produces a valid `Deck` at version 0 semantics — slides with narrative roles, component
assignments and intents, and **no prose**. The content agent fills the words in Phase 2b,
with citations attached.

## Why no prose, enforced rather than requested

`prompts/outline.md` tells the model not to write copy. `build_outline` also refuses to
carry any it produced, because an outline header would arrive at the content stage looking
like a decision already made — and it would have arrived without a citation, through a door
A1 is not watching. The schema helps: the outline emits slide *intents*, not blocks, so
there is no field for prose to sit in.

## What it guarantees about the brief

Three things, all checked in code rather than trusted to the model:

- **A signed brief, or nothing.** `build_outline` requires `approved_by`. The A7 gate is
  the orchestrator's job, but an outline built from an unsigned draft would be an outline
  nobody agreed to, so the agent refuses one outright.
- **Pins are honoured or flagged.** A pinned component that the model silently replaced is
  detected by comparing the result against the brief, and the deviation is written into
  `Slide.pin_deviation` whether or not the model bothered to explain itself.
- **Messages are not invented.** A slide claiming to serve a `message_id` that is not in
  the brief has its reference dropped, so GATE 1's coverage check cannot be satisfied by a
  fabricated id.

None of these blocks an outline that fails GATE 1's checks. That is deliberate: the gate is
a human review, and an agent that silently repaired its own output would hide the very
drift the reviewer is there to catch. `review_outline` (task 2a.9) reports; it does not fix.

Owning phase: 2a (task 2a.7).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from autodeck.ir.models import CommunicationMode, Deck, DeckBrief, LayoutPin, Slide

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/outline.md")

#: The initial catalog (§6.6). The outline may only assign from here — a component the
#: renderer does not have produces a deck that fails at render time, three phases later,
#: with an error about a missing template rather than about a bad outline.
CATALOG: tuple[str, ...] = (
    "title",
    "section_divider",
    "agenda",
    "big_number",
    "two_column_compare",
    "quote",
    "bullets_supporting",
    "evidence_with_figure",
    "framework_diagram",
    "timeline",
    "data_card_grid",
    "chart_focus",
    "before_after",
    "callout_takeaway",
    "closing_cta",
)

#: Components that stake a whole slide on a single figure. Pairing one with a key message
#: the evidence-gap check called `thin` or `unsupported` manufactures confidence the
#: evidence does not support — the failure A8 exists to prevent — so it is reported.
CONFIDENT_COMPONENTS: frozenset[str] = frozenset({"big_number", "chart_focus", "quote"})


class OutlineError(RuntimeError):
    """The outline could not be produced."""


# ---------------------------------------------------------------------------
# What the model returns
# ---------------------------------------------------------------------------


class SlideDraft(BaseModel):
    """One slide of the skeleton.

    No text field, by design. There is nowhere for prose to go, which is a stronger
    guarantee than asking for none.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    narrative_role: str = Field(min_length=1)
    component: str = Field(min_length=1, description=f"One of: {', '.join(CATALOG)}")
    intent: str = Field(
        min_length=1,
        description="What this slide must accomplish. A statement, not a topic label.",
    )
    message_ids: list[str] = Field(
        default_factory=list, description="Brief key message ids this slide serves."
    )
    communication_mode: CommunicationMode | None = None
    pin_deviation: str | None = Field(
        default=None,
        description="If a pin could not be honoured: what was pinned, what you used, why.",
    )


class OutlineDraft(BaseModel):
    """The model's proposed skeleton."""

    model_config = ConfigDict(extra="forbid")

    slides: list[SlideDraft] = Field(min_length=1)
    notes: str | None = Field(
        default=None,
        description="What was left out and why, if the storyline did not fit the target.",
    )


class OutlineModel(Protocol):
    def complete_structured(
        self,
        prompt: str,
        response_model: type[OutlineDraft],
        *,
        system: str | None = None,
    ) -> OutlineDraft: ...  # pragma: no cover — protocol shape only


@dataclass
class OutlineResult:
    """The skeleton, plus what had to be corrected on the way out."""

    deck: Deck
    notes: str | None = None
    corrections: list[str] = None  # type: ignore[assignment]
    """Structural repairs applied to the model's output — an unknown component, a
    fabricated message id. Surfaced rather than silent: a model needing frequent correction
    is a prompt problem, and that signal disappears if the fixes are invisible."""

    def __post_init__(self) -> None:
        if self.corrections is None:
            self.corrections = []


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def build_outline(
    brief: DeckBrief,
    model: OutlineModel,
    *,
    client: str,
    project: str,
    theme_ref: str,
    component_lib_version: str,
    context: str = "",
    prompt_path: Path = PROMPT_PATH,
) -> OutlineResult:
    """Turn a signed brief into an IR skeleton.

    Args:
        context: assembled curated knowledge, from `ContextAssembler`. Passed through
            rather than loaded here so A4's namespace guard stays in one place.

    Raises:
        OutlineError: the brief is not signed, or the model returned nothing usable.
    """
    if not brief.approved_by:
        raise OutlineError(
            f"brief v{brief.version} for run {brief.run_id!r} has no approver. An outline "
            "built from an unsigned brief is an outline nobody agreed to — sign it off "
            "through the planning session first (A7)."
        )

    system = _read_prompt(prompt_path)
    try:
        draft = model.complete_structured(
            _outline_prompt(brief, context), OutlineDraft, system=system
        )
    except Exception as exc:
        raise OutlineError(
            f"outline generation failed for run {brief.run_id!r}: {type(exc).__name__}: {exc}"
        ) from exc

    slides, corrections = _slides_from_draft(draft, brief)
    if not slides:
        raise OutlineError(
            "the outline contained no usable slides after validation. Every slide named an "
            "unknown component or was otherwise unbuildable."
        )

    deck = Deck(
        run_id=brief.run_id,
        project=project,
        client=client,
        audience=brief.audience,
        version=1,
        slides=slides,
        theme_ref=theme_ref,
        component_lib_version=component_lib_version,
    )
    return OutlineResult(deck=deck, notes=draft.notes, corrections=corrections)


def _slides_from_draft(draft: OutlineDraft, brief: DeckBrief) -> tuple[list[Slide], list[str]]:
    """Convert drafts to slides, correcting what must be corrected and recording it."""
    known_messages = {message.id for message in brief.key_messages}
    slides: list[Slide] = []
    corrections: list[str] = []
    seen_ids: set[str] = set()

    for position, item in enumerate(draft.slides, start=1):
        if item.component not in CATALOG:
            corrections.append(
                f"slide {item.id!r} named component {item.component!r}, which is not in the "
                f"catalog; dropped. A component the renderer lacks fails at render time, "
                "three phases from here, with an error about a missing template."
            )
            continue

        slide_id = item.id if item.id not in seen_ids else f"{item.id}-{position}"
        if slide_id != item.id:
            corrections.append(f"duplicate slide id {item.id!r} renamed to {slide_id!r}")
        seen_ids.add(slide_id)

        invented = [mid for mid in item.message_ids if mid not in known_messages]
        if invented:
            corrections.append(
                f"slide {slide_id!r} claimed to serve key message(s) "
                f"{', '.join(invented)}, which are not in the brief; references dropped so "
                "GATE 1's coverage check cannot be satisfied by a fabricated id."
            )

        slides.append(
            Slide(
                id=slide_id,
                narrative_role=item.narrative_role,
                component=item.component,
                communication_mode=item.communication_mode,
                intent=item.intent,
                message_ids=[mid for mid in item.message_ids if mid in known_messages],
                pin_deviation=item.pin_deviation,
            )
        )

    _record_pin_deviations(slides, brief, corrections)
    return slides, corrections


def _record_pin_deviations(
    slides: list[Slide], brief: DeckBrief, corrections: list[str]
) -> None:
    """Write `pin_deviation` for any pin the outline did not honour.

    The model is asked to explain its own deviations, and often will. This runs regardless,
    because a pin the model dropped *without noticing* is exactly the case where it will not
    have written an explanation — and that is the case worth catching.
    """
    for pin in brief.layout_pins:
        serving = [slide for slide in slides if pin.message_id in slide.message_ids]
        if not serving:
            corrections.append(
                f"pin on message {pin.message_id!r} ({pin.target}={pin.value}) could not be "
                "checked: no slide serves that message"
            )
            continue
        if any(_honours(slide, pin) for slide in serving):
            continue
        for slide in serving:
            note = (
                f"brief pinned {pin.target}={pin.value!r} for message "
                f"{pin.message_id!r}; this outline used "
                f"{_actual(slide, pin) or 'nothing for that target'} instead"
            )
            slide.pin_deviation = (
                f"{slide.pin_deviation} | {note}" if slide.pin_deviation else note
            )
        corrections.append(f"unhonoured pin recorded on message {pin.message_id!r}")


def _honours(slide: Slide, pin: LayoutPin) -> bool:
    return _actual(slide, pin) == pin.value


def _actual(slide: Slide, pin: LayoutPin) -> str | None:
    """What the slide actually has for the pin's target.

    `diagram_kind` returns None: the outline assigns components, not diagram geometry, so a
    diagram pin cannot be satisfied or refuted here. It is carried to Phase 3a's diagram
    engine — reported as a deviation now would be a false alarm every time.
    """
    if pin.target == "component":
        return slide.component
    if pin.target == "communication_mode":
        return slide.communication_mode
    return pin.value if pin.target == "diagram_kind" else None


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def _outline_prompt(brief: DeckBrief, context: str) -> str:
    parts: list[str] = []
    if context.strip():
        parts.append("# Curated knowledge\n\n" + context)
    parts.append("# The signed brief\n\n" + _render_brief(brief))
    parts.append(
        "# Your task\n\nProduce the slide skeleton. Narrative role, component, intent and "
        "the key message ids each slide serves. No prose, no headers, no numbers."
    )
    return "\n\n---\n\n".join(parts)


def _render_brief(brief: DeckBrief) -> str:
    lines = [
        f"objective: {brief.objective}",
        f"audience: {brief.audience}",
        f"length_target: {brief.length_target or 'not set'}",
        f"header_style: {brief.header_style or 'not set'}",
        "",
        "key_messages:",
    ]
    for message in brief.key_messages:
        lines.append(f"  - {message.id}: {message.text}")
        lines.append(f"      evidence: {message.evidence_status}")
        if message.evidence_status in ("thin", "unsupported"):
            # Named at the point of use, because the component choice is where this
            # matters: a big_number on a thin message overstates it (A8).
            lines.append(
                "      NOTE: weak evidence — do not give this slide a component that "
                "stakes everything on one figure."
            )
    for label, values in (
        ("must_include", brief.must_include),
        ("must_avoid", brief.must_avoid),
    ):
        lines.append(f"{label}: {', '.join(values) if values else '(none)'}")

    lines.append("layout_pins:")
    if brief.layout_pins:
        for pin in brief.layout_pins:
            rationale = f" — {pin.rationale}" if pin.rationale else ""
            lines.append(f"  - {pin.message_id}: {pin.target}={pin.value}{rationale}")
    else:
        lines.append("  (none — choose freely)")

    lines.append("open_risks (carry these into the deck, do not drop them):")
    if brief.open_risks:
        for risk in brief.open_risks:
            lines.append(f"  - {risk.message_id}: {risk.description}")
            if risk.mitigation:
                lines.append(f"      mitigation: {risk.mitigation}")
    else:
        lines.append("  (none)")

    lines.append(f"\ncomponents available: {', '.join(CATALOG)}")
    return "\n".join(lines)


def _read_prompt(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        raise OutlineError(
            f"outline prompt not found at {path}. Prompts are versioned files (plan §0.5) "
            "and their hashes go into the build manifest — there is no inline fallback."
        )
    return path.read_text(encoding="utf-8")
