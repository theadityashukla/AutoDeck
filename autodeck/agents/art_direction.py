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
from typing import Literal, Protocol

from pydantic import Field

from autodeck.design.grammar import GrammarFinding
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.actions import ArtAction, ConceptLookup, SlotLookup
from autodeck.ir.models import CommunicationMode, Deck, DeckBrief, IRModel, Slide

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
    raise NotImplementedError("scaffold: Sonnet fills this in")


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
    raise NotImplementedError("scaffold: Sonnet fills this in")


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
    raise NotImplementedError("scaffold: Sonnet fills this in")
