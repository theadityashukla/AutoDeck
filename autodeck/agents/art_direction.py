"""The art-direction pass (Phase 3b, task 3b.7): deck-level presentation decisions.

Runs after validation and before render. Everything it changes, it changes through the
closed action set (`autodeck/ir/actions.py`) and the shared acceptance rule
(`autodeck/render/trial.py`) — so, like the aesthetic loop, it is structurally unable to
alter a fact, and an action that breaks the render or D13's grammar is rejected, not kept.
Read B36 in DECISIONS.md for the design calls below.

## Two kinds of decision, deliberately made two ways

**Communication mode is a rule, not an opinion** (`derive_mode`). Plan §6.11.2 says the
mode is "chosen from the shape of the content (process → diagram-led; capability pillars →
icon-anchored; nuanced argument → text-led)", and §6.11.2's lints say "taste is encoded as
checkable rules wherever possible". The shape of the content is in the IR: a slide that
draws a diagram is diagram-led; a slide that draws icons is icon-anchored; anything else is
text-led. A rule gives the same answer on every run and every model (A6), and every slide
gets an explicit mode with a recorded source (`ModeDecision`), as D13 requires.
A brief `communication_mode` pin always wins over the rule — that is the human override.

**Taste is the model's** (`ArtDirectionPlan`): which slide to promote to `big_number`,
which slide's density to vary, which accent gives the deck rhythm, and which icon concepts
a pillar slide should carry (`AssignIcons` — the only way icon blocks come to exist; see
B35). Its output vocabulary is `ArtAction`: no text field anywhere, no mode-setting action
(the rule owns that), no glyph restyling (the aesthetic critic owns that).

## Bound to the `outline` role

Art direction is not one of plan §6.2's six roles. It is a structural judgement over the
whole deck, the same competence the outline agent exercises, and it is text-only, so it
runs on the `outline` role's binding (B36) rather than adding a seventh role every
environment config would have to bind.

## What it does not do

- **Insert section dividers.** The plan lists them, but a divider is a slide with a title,
  and there is no fact-safe source for that title text: the model may not write text, and
  composing one from a key message would put owner-signed wording on a slide nobody
  approved as slide copy. B36 records this; the model may recommend dividers in its
  rationale, for a human.
- **Fail the build on a model error.** Art direction is polish on a validated deck. If the
  call fails, no proposed action is applied, the rule-derived modes are still assigned (they
  need no model), and the result says `stopped="model_error"` with the reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, get_args

from pydantic import Field

from autodeck.design import grammar
from autodeck.design.components.catalog import known_components, registration
from autodeck.design.grammar import GrammarFinding
from autodeck.design.icons.library import available_concepts
from autodeck.design.layout_kit import LayoutOverflowError
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.actions import (
    ActionRejected,
    ArtAction,
    ConceptLookup,
    SetCommunicationMode,
    SlotLookup,
    apply_action,
)
from autodeck.ir.models import (
    AccentToken,
    Block,
    CommunicationMode,
    Deck,
    DeckBrief,
    IRModel,
    Slide,
    TypeScale,
)
from autodeck.providers.base import ProviderError
from autodeck.render import trial
from autodeck.render.qa.aesthetic import catalog_slot_lookup, library_concept_lookup
from autodeck.render.renderer import RenderStageError, render_deck

PROMPT_PATH = Path("prompts/art_direction.md")

#: Deck-level, so wider than the aesthetic critic's eight; still bounded, so one confused
#: reply cannot propose a hundred swaps.
MAX_ACTIONS = 24


class ArtDirectionPlan(IRModel):
    """What the art-direction model returns."""

    rationale: str = Field(description="Why. Reporting only — never applied to the deck.")
    actions: list[ArtAction] = Field(default_factory=list, max_length=MAX_ACTIONS)


class ArtDirectionModel(Protocol):
    """The slice of `BaseProvider` this pass uses — the `outline` role's binding (B36)."""

    def complete_structured(
        self,
        prompt: str,
        response_model: type[ArtDirectionPlan],
        *,
        system: str | None = None,
    ) -> ArtDirectionPlan: ...  # pragma: no cover — protocol shape only


ModeSource = Literal["pin", "rule"]


@dataclass(frozen=True)
class ModeDecision:
    mode: CommunicationMode
    source: ModeSource
    note: str = ""
    """For a pin: e.g. a pinned `icon_anchored` on a slide that draws no icon — honoured, and
    said out loud, because the pin outranks the rule but the mismatch is worth seeing."""


@dataclass(frozen=True)
class RejectedArtAction:
    action: ArtAction
    reason: str


@dataclass
class ArtDirectionResult:
    deck: Deck
    modes: dict[str, ModeDecision]
    """Every slide id → its mode and why. Complete: no slide is left without one."""
    applied: list[ArtAction] = field(default_factory=list)
    rejected: list[RejectedArtAction] = field(default_factory=list)
    rationale: str = ""
    grammar: list[GrammarFinding] = field(default_factory=list)
    """`grammar.lint_deck(result.deck)` findings — mode budgets now apply to every slide.
    Reported here; the render stage (3b.10) decides what blocks."""
    stopped: Literal["ok", "model_error"] = "ok"
    detail: str = ""
    render_error: str = ""
    """Non-empty if the final deck does not render (e.g. an `icon_pillars` slide the model
    gave no icons). The deck is still returned; the render stage refuses it loudly."""


def derive_mode(slide: Slide) -> CommunicationMode:
    """D13's mode from the content's shape, by rule (module docstring).

    Contract, first match wins, face blocks only: any `kind == "diagram"` →
    `"diagram_led"`; any `kind == "icon"` → `"icon_anchored"`; otherwise `"text_led"`.
    Pure. Speaker notes never decide a mode — they are not drawn.
    """
    kinds = {block.kind for block in slide.blocks}
    if "diagram" in kinds:
        return "diagram_led"
    if "icon" in kinds:
        return "icon_anchored"
    return "text_led"


def run_art_direction(
    deck: Deck,
    *,
    brief: DeckBrief,
    tokens: DesignTokens,
    model: ArtDirectionModel,
    work_dir: Path,
    slots_of: SlotLookup | None = None,
    glyph_for: ConceptLookup | None = None,
    prompt_path: Path = PROMPT_PATH,
) -> ArtDirectionResult:
    """Apply the model's taste, then the mode rule, to `deck`.

    Contract, in order:
      - Read `prompt_path` first; missing → `FileNotFoundError` (same stance as
        `agents/outline.py::_read_prompt`), before any model call.
      - Defaults: `slots_of` / `glyph_for` from `autodeck.render.qa.aesthetic`'s
        `catalog_slot_lookup()` / `library_concept_lookup()` — reuse, do not re-implement.
      - One call: `model.complete_structured(_art_direction_prompt(...), ArtDirectionPlan,
        system=<prompt>)`. `ProviderError` → no plan, `stopped="model_error"`, `detail` =
        `"<ExcType>: <msg>"`; continue with the rule. Any other exception propagates.
      - Apply each plan action in order with `trial.try_action(current, action,
        tokens=tokens, scratch=work_dir / "trial.pptx", pins=brief.layout_pins, ...)`;
        `ActionRejected` (incl. `DoesNotRender`, `GrammarRegression`) → `RejectedArtAction`
        with `str(exc)`, continue against the unchanged deck. `FactMutationError` and
        environment errors propagate.
      - Then, for every slide in order: a `communication_mode` pin on any message the slide
        serves → that value, source `"pin"` (note a mismatch with `derive_mode`); else
        `derive_mode(slide)`, source `"rule"`. Set it with `apply_action(SetCommunicationMode
        ...)` — through the action channel, so the fingerprint check covers it — and *not*
        through `try_action`: a mode is assigned even if it makes a budget finding; that
        finding is reported in `grammar`, not hidden by refusing the mode.
      - `grammar = grammar.lint_deck(final).findings`.
      - Final `render_deck(final, tokens=tokens, out_path=work_dir / "art_directed.pptx")`;
        `RenderStageError`/`LayoutOverflowError` → `render_error` set, deck still returned.
      - Invariant on every path (tests assert it): `fact_fingerprint(result.deck) ==
        fact_fingerprint(deck)` — icon blocks are not facts (B36), so `AssignIcons` keeps it.
    """
    system = _read_prompt(prompt_path)
    slots_of = slots_of if slots_of is not None else catalog_slot_lookup()
    glyph_for = glyph_for if glyph_for is not None else library_concept_lookup()
    work_dir.mkdir(parents=True, exist_ok=True)

    plan: ArtDirectionPlan | None = None
    stopped: Literal["ok", "model_error"] = "ok"
    detail = ""
    try:
        plan = model.complete_structured(
            _art_direction_prompt(deck, brief, slots_of=slots_of),
            ArtDirectionPlan,
            system=system,
        )
    except ProviderError as exc:
        stopped, detail = "model_error", f"{type(exc).__name__}: {exc}"

    current = deck
    applied: list[ArtAction] = []
    rejected: list[RejectedArtAction] = []
    for action in plan.actions if plan is not None else ():
        try:
            current = trial.try_action(
                current,
                action,
                tokens=tokens,
                scratch=work_dir / "trial.pptx",
                pins=brief.layout_pins,
                slots_of=slots_of,
                glyph_for=glyph_for,
            )
        except ActionRejected as exc:  # incl. DoesNotRender, GrammarRegression
            rejected.append(RejectedArtAction(action=action, reason=str(exc)))
        else:
            applied.append(action)

    modes: dict[str, ModeDecision] = {}
    for slide in current.slides:
        decision = _decide_mode(slide, brief)
        modes[slide.id] = decision
        # `pins=()` on purpose: a pinned mode is what the pin asks for, so applying it is
        # honouring the pin, not overriding it; `apply_action` would otherwise refuse the very
        # value the pin names. The fingerprint check still runs.
        current = apply_action(
            current,
            SetCommunicationMode(slide_id=slide.id, mode=decision.mode),
            pins=(),
            slots_of=slots_of,
            glyph_for=glyph_for,
        )

    render_error = ""
    try:
        render_deck(current, tokens=tokens, out_path=work_dir / "art_directed.pptx")
    except (RenderStageError, LayoutOverflowError) as exc:
        render_error = f"{type(exc).__name__}: {exc}"

    return ArtDirectionResult(
        deck=current,
        modes=modes,
        applied=applied,
        rejected=rejected,
        rationale=plan.rationale if plan is not None else "",
        grammar=grammar.lint_deck(current).findings,
        stopped=stopped,
        detail=detail,
        render_error=render_error,
    )


_MODES: tuple[str, ...] = get_args(CommunicationMode)


def _decide_mode(slide: Slide, brief: DeckBrief) -> ModeDecision:
    """A `communication_mode` pin on any message the slide serves, else the rule."""
    rule = derive_mode(slide)
    pins = [
        pin
        for pin in brief.layout_pins
        if pin.target == "communication_mode" and pin.message_id in slide.message_ids
    ]
    if not pins:
        return ModeDecision(mode=rule, source="rule")

    pin = pins[0]
    if pin.value not in _MODES:
        return ModeDecision(
            mode=rule,
            source="rule",
            note=(
                f"the pin on message {pin.message_id!r} names {pin.value!r}, which is not a "
                f"communication mode ({', '.join(_MODES)}); the rule's answer was used"
            ),
        )
    notes: list[str] = []
    if pin.value != rule:
        notes.append(f"pinned {pin.value!r} but the slide's content reads as {rule!r}")
    conflicting = sorted({other.value for other in pins[1:] if other.value != pin.value})
    if conflicting:
        notes.append(
            f"other pins on this slide name {', '.join(map(repr, conflicting))}; "
            f"the first ({pin.message_id!r}) was honoured"
        )
    return ModeDecision(
        mode=pin.value,  # type: ignore[arg-type]  # checked against _MODES above
        source="pin",
        note="; ".join(notes),
    )


def _read_prompt(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"art direction prompt not found at {path}. Prompts are versioned files "
            "(plan §0.5) and their hashes go into the build manifest — there is no inline "
            "fallback."
        )
    return path.read_text(encoding="utf-8")


def _art_direction_prompt(deck: Deck, brief: DeckBrief, *, slots_of: SlotLookup) -> str:
    """The per-deck user prompt. System prompt: `prompts/art_direction.md`.

    Contract — unlike the aesthetic critic, this model needs the words: choosing an icon for
    a pillar or the number worth a `big_number` slide is a judgement about meaning. Its
    *output* cannot carry text, so showing it text is safe. List, deterministically:
      - The brief's objective and key messages (id, text) in order, and its layout pins.
      - Per slide in order: id, narrative_role, intent, message_ids, component, current
        style, and each face block as `id  kind  slot  <text>` where text is
        `claim.text` / `block.text` / a chart's title / a diagram's kind and node labels;
        icon blocks as their concept.
      - Every catalog component: name, narrative roles, `slots_of(name)`.
      - The icon concepts (`available_concepts()`) and the accent / type-scale vocabularies.
      Same inputs → identical string.
    """
    lines: list[str] = [
        "Art direction for one deck. Propose presentation actions only; you cannot write or "
        "change any text. Communication mode is derived from content, not proposed.",
        "",
        "BRIEF",
        f"  objective: {_one_line(brief.objective)}",
        "  key messages (id: text):",
    ]
    for message in brief.key_messages:
        lines.append(f"    {message.id}: {_one_line(message.text)}")
    lines.append("  layout pins (message  target  value):")
    if brief.layout_pins:
        for pin in brief.layout_pins:
            lines.append(f"    {pin.message_id}  {pin.target}  {pin.value}")
    else:
        lines.append("    none")

    lines += ["", "SLIDES (in order)"]
    for slide in deck.slides:
        style = slide.style
        lines.append(f"slide {slide.id}")
        lines.append(f"  narrative_role: {_one_line(slide.narrative_role)}")
        lines.append(f"  intent: {_one_line(slide.intent) if slide.intent else 'none'}")
        lines.append(f"  message_ids: {', '.join(slide.message_ids) or 'none'}")
        lines.append(f"  component: {slide.component}")
        lines.append(
            f"  style: type_scale={style.type_scale} accent={style.accent} "
            f"column_balance={style.column_balance} "
            f"emphasis_block_id={style.emphasis_block_id or 'none'}"
        )
        lines.append("  blocks (id  kind  slot  content):")
        for block in slide.blocks:
            content = _block_content(block)
            lines.append(
                f"    {block.id}  {block.kind}  {block.slot}"
                + (f"  {content}" if content else "")
            )

    lines += ["", "COMPONENTS (name | narrative roles | slots)"]
    for name in known_components():
        slots = slots_of(name)
        if slots is None:
            continue
        roles = "; ".join(registration(name).narrative_roles)
        lines.append(f"  {name} | {roles} | {', '.join(sorted(slots))}")

    lines += [
        "",
        "ICON CONCEPTS: " + ", ".join(available_concepts()),
        "",
        "VOCABULARIES",
        "  type_scale: " + ", ".join(get_args(TypeScale)),
        "  accent / color_token: " + ", ".join(get_args(AccentToken)),
    ]
    return "\n".join(lines)


def _one_line(text: str) -> str:
    """Collapse whitespace so one block is one line of the prompt."""
    return " ".join(text.split())


def _block_content(block: Block) -> str:
    """What the art director may read of a block: words for judging meaning, never edited."""
    if block.claim is not None:
        return _one_line(block.claim.text)
    if block.text is not None:
        return _one_line(block.text)
    if block.chart is not None:
        title = _one_line(block.chart.title) if block.chart.title else "untitled"
        return f"chart: {title}"
    if block.diagram is not None:
        labels = "; ".join(_one_line(node.label) for node in block.diagram.nodes)
        return f"diagram ({block.diagram.kind}): {labels}"
    if block.icon is not None:
        return f"icon: {block.icon.concept}"
    if block.figure is not None:
        caption = _one_line(block.figure.caption) if block.figure.caption else "no caption"
        return f"figure {block.figure.asset_id}: {caption}"
    return ""  # pragma: no cover - Block's validator guarantees one payload
