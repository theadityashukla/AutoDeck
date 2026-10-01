"""The bounded aesthetic critique loop (Phase 3b, task 3b.5).

A vision model looks at **true renders** of the deck (D5 — LibreOffice PNGs of the PPTX the
client will open, never a mock-up) and answers with an `ActionList`: a score and at most
eight actions from the closed set in `autodeck/ir/actions.py`. This module applies the
actions it can, re-renders, and asks again, until the score reaches a target, the model has
nothing left to propose, or the iteration budget runs out.

Read `autodeck/ir/actions.py`'s module docstring first. Everything that makes this loop
safe is there, not here: the model's output **cannot express** an edit to claim text or a
citation, `apply_action` rejects unknown addresses and pinned targets, and every applied
action is fingerprint-checked. This module adds no new safety mechanism and must not need
one — if it ever does, the fix belongs in the action types (PHASE-3B.md, escalation
triggers).

## What this module is responsible for

1. **Orchestration.** Render → audit → rasterise → critique → apply, bounded by
   `LoopConfig.max_iterations`. One vision call per iteration, so a deck costs at most
   `max_iterations` calls to the `aesthetic` role — a number you can see (B25 quota).
2. **Keeping only improvements it can defend.** A candidate deck (the previous one with the
   model's accepted actions applied) is kept only if it renders, passes the post-render
   audit, and has **no more deterministic QA findings** than its predecessor. A vision model
   that likes a slide whose text now overlaps its chart has found a regression, not an
   improvement; the arithmetic checks outrank the model's taste.
3. **Returning the best deck it saw, not the last one.** The deck returned is the
   highest-scoring *scored* deck. The final candidate, produced by the last round of
   actions, has never been looked at by the model when the budget runs out — it is not
   returned on the strength of a score it never received.
4. **Honest reporting.** Every proposed action is recorded as applied or rejected, with the
   rejection's reason. The model's `rationale` is recorded and never applied to anything.

## What this module must never do

- Construct, modify, or copy text into the deck. It calls `apply_action`; that is its only
  way to change a deck.
- Catch `FactMutationError`. That exception means `apply_action` itself is defective; it
  propagates and stops the run.
- Retry a failed model call with a different prompt, or invent a score. A provider failure
  ends the loop (`stopped="model_error"`) and returns the best deck seen so far — which,
  on a first-iteration failure, is the input deck unchanged.

## Stop reasons, exhaustively

`target_reached` — the scored deck met `target_score`. `no_actions` — the model proposed
nothing. `all_rejected` — it proposed actions and `apply_action` rejected every one, so
there is no candidate to render. `max_iterations` — the budget ran out. `qa_regression` — a
candidate had more deterministic findings than its predecessor. `audit_failed` — a candidate
failed the post-render audit (a presentation change that breaks A1/A2 on the rendered page
is a defect to investigate, never a trade-off to accept). `model_error` — the vision call
raised a `ProviderError` (including `StructuredOutputError`: a reply the schema rejects,
such as one that tries to smuggle in a `"text"` field).

## Layering

The catalog and icon library are injected into `apply_action` through
`catalog_slot_lookup` and `library_concept_lookup`, defined here, because `autodeck/ir/`
must not import the design layer. Rasterising is injected (`Rasteriser`) so the loop's
logic is testable in CI without LibreOffice (B10); the default rasteriser is
`autodeck.render.qa.libreoffice.render_pptx`, and a `render`-marked test exercises it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Protocol, get_args

from autodeck.audit.post_render import post_render_audit
from autodeck.design.components.catalog import (
    known_components,
)
from autodeck.design.icons.library import (
    CONCEPT_TO_ICON,
    IconNotFoundError,
    available_concepts,
    resolve_icon,
)
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.actions import (
    Action,
    ActionList,
    ActionRejected,
    ConceptLookup,
    SlotLookup,
    apply_action,
)
from autodeck.ir.models import (
    AccentToken,
    ColumnBalance,
    CommunicationMode,
    Deck,
    LayoutPin,
    TypeScale,
)
from autodeck.providers.base import ImageInput, ProviderError
from autodeck.render.qa.deterministic import QAFinding, run_deterministic_qa
from autodeck.render.qa.libreoffice import render_pptx
from autodeck.render.renderer import render_deck

PROMPT_PATH = Path("prompts/aesthetic_critique.md")
DEFAULT_TOKENS = Path("config/tokens/dev.json")

StopReason = Literal[
    "target_reached",
    "no_actions",
    "all_rejected",
    "max_iterations",
    "qa_regression",
    "audit_failed",
    "model_error",
]


class AestheticModel(Protocol):
    """The slice of `BaseProvider` this loop uses. A provider bound to the `aesthetic` role
    satisfies it; tests pass a fake that returns canned `ActionList`s."""

    def vision(
        self,
        images: list[ImageInput],
        prompt: str,
        response_model: type[ActionList],
        *,
        system: str | None = None,
    ) -> ActionList: ...  # pragma: no cover — protocol shape only


Rasteriser = Callable[[Path, Path], list[Path]]
"""`(pptx, output_dir) -> one PNG per slide, in slide order.` The default wraps
`render_pptx(pptx, output_dir, tokens)` and returns its `images`."""


@dataclass(frozen=True)
class LoopConfig:
    max_iterations: int = 3
    """Vision calls per deck, at most. Three is the plan's §6.9 default: one look, one
    correction, one confirmation."""
    target_score: float = 8.0
    """Stop as soon as a scored deck reaches this. Same 0-10 scale as `ActionList.score`."""


DEFAULT_CONFIG = LoopConfig()


@dataclass(frozen=True)
class RejectedAction:
    action: Action
    reason: str
    """`str(exc)` of the `ActionRejected` that `apply_action` raised."""


@dataclass(frozen=True)
class Iteration:
    """One look by the model at one rendered deck."""

    index: int
    """0-based."""
    score: float
    rationale: str
    """The model's words. Reported, never applied."""
    qa_findings: int
    """Deterministic QA findings on the deck this iteration scored."""
    applied: tuple[Action, ...]
    rejected: tuple[RejectedAction, ...]
    images: tuple[Path, ...]
    """The PNGs the model was shown — kept so the owner can see what it saw."""


@dataclass
class AestheticResult:
    deck: Deck
    """The best-scoring deck the model actually looked at (see module docstring, point 3).
    The input deck if no iteration completed."""
    best_score: float | None
    """`None` if the model never returned a score."""
    stopped: StopReason
    iterations: list[Iteration] = field(default_factory=list)
    detail: str = ""
    """For `qa_regression`, `audit_failed` and `model_error`: what happened, in one line an
    owner can act on (e.g. the exception type and message, or the finding counts)."""


class AestheticLoopError(RuntimeError):
    """The input deck itself cannot enter the loop: it fails the post-render audit before
    any action has been applied. That is an upstream defect (content or renderer), and
    critiquing its looks would be polishing a deck that must not ship."""


# ---------------------------------------------------------------------------
# Lookups injected into `apply_action`
# ---------------------------------------------------------------------------


def catalog_slot_lookup() -> SlotLookup:
    """A `SlotLookup` over the registered components, as the renderer places them.

    Contract: delegates to `autodeck.render.renderer.placeable_slots` — the single authority
    on where a block can go — and maps its `UnknownComponentError` to `None`. Never raises
    for an unknown name. No tokens, no `Canvas`: slot names do not depend on the theme.
    (Amended: the first scaffold read the catalog's `ComponentSlot`s, which describe text
    measurement, not placement — they omit chart/diagram slots and include the computed
    `source`, and building them needs a `Canvas` with installed fonts.)
    """
    raise NotImplementedError("scaffold: Sonnet re-fills this against placeable_slots")


def library_concept_lookup() -> ConceptLookup:
    """A `ConceptLookup` over the vendored icon library.

    Contract: maps a concept to the glyph id `autodeck.design.icons.library.resolve_icon`
    resolves it to, or `None` when it raises `IconNotFoundError`. Only concepts — a literal
    icon filename that is not a concept is `None` here, because `SwapGlyph` addresses ideas,
    not files (library docstring, §9). Use `CONCEPT_TO_ICON` to tell them apart.
    """

    def glyph_for(concept: str) -> str | None:
        if concept not in CONCEPT_TO_ICON:
            return None
        try:
            return resolve_icon(concept).name
        except IconNotFoundError:
            return None

    return glyph_for


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def run_aesthetic_loop(
    deck: Deck,
    *,
    tokens: DesignTokens,
    model: AestheticModel,
    work_dir: Path,
    pins: Sequence[LayoutPin] = (),
    config: LoopConfig = DEFAULT_CONFIG,
    rasterise: Rasteriser | None = None,
    slots_of: SlotLookup | None = None,
    glyph_for: ConceptLookup | None = None,
    prompt_path: Path = PROMPT_PATH,
) -> AestheticResult:
    """Critique and improve `deck`'s presentation within the closed action set.

    Contract, in order:
      - Read `prompt_path` once, up front. Missing → `FileNotFoundError` naming the path and
        saying prompts are versioned files with no inline fallback (same stance as
        `agents/outline.py::_read_prompt`). No model call happens before this check.
      - Defaults: `rasterise` wraps `render_pptx(pptx, out, tokens).images`; `slots_of` is
        `catalog_slot_lookup()`; `glyph_for` is `library_concept_lookup()`.
      - Iteration `i` (0-based) works in `work_dir / f"iter-{i}"`: `render_deck(current,
        tokens=tokens, out_path=<dir>/deck.pptx)`, then `post_render_audit(current, pptx)`,
        then `run_deterministic_qa(pptx, tokens)`, then `rasterise(pptx, <dir>/png)`.
      - Iteration 0's audit failing → `AestheticLoopError` (see its docstring). A later
        iteration's audit failing → revert to the previous deck, `stopped="audit_failed"`.
      - A later iteration with more QA findings than the deck it came from → revert,
        `stopped="qa_regression"`, `detail` giving both counts. Equal is acceptable.
      - Call `model.vision(images, _critique_prompt(...), ActionList, system=<prompt>)` with
        every PNG as an `ImageInput`. `ProviderError` (base class — covers auth, rate limit
        exhaustion, bad replies, `StructuredOutputError`) → `stopped="model_error"`.
        Any other exception propagates.
      - Record the score against the deck just rendered. If `score >= target_score` →
        `target_reached`. If `actions` is empty → `no_actions`.
      - Apply each action in order with `apply_action(candidate, action, pins=pins,
        slots_of=..., glyph_for=...)`, threading the result; an `ActionRejected` is recorded
        and the next action is tried against the unchanged candidate. `FactMutationError`
        propagates (never caught — module docstring). If nothing applied → `all_rejected`.
      - **Trial render per action.** After `apply_action` succeeds, `render_deck` the
        candidate to a scratch path in the iteration's directory (pure python-pptx, ~10 ms a
        slide — no LibreOffice). `RenderStageError` (incl. `UnplacedBlockError`,
        `UnknownComponentError`) or `LayoutOverflowError` → the action is recorded as
        rejected with reason `"does not render: <ExcType>: <msg>"` and the candidate reverts
        to before it. This is how a `spacious` overflow or a swap onto a slot the component
        cannot fill becomes a rejected action (`renderer.TYPE_SCALE_FACTORS`' docstring)
        rather than a crash. `FontNotFoundError`, `RenderBlocked` and anything else
        propagate — they are environment or safety failures, not properties of the action.
        Consequently the next iteration's render of the candidate cannot fail for the
        action's sake; if it raises, that is a defect and propagates.
      - After `max_iterations` scored looks, `max_iterations`. The unscored final candidate
        is discarded.
      - Return the deck with the highest recorded score; ties go to the earlier deck (fewer
        changes for the same judgement). `best_score` is that score.
      - Invariant, asserted by tests on every path: `fact_fingerprint(result.deck) ==
        fact_fingerprint(deck)`.
    """
    system = _read_prompt(prompt_path)

    def default_rasterise(pptx: Path, output_dir: Path) -> list[Path]:
        return render_pptx(pptx, output_dir, tokens).images

    rasterise = rasterise if rasterise is not None else default_rasterise
    slots_of = slots_of if slots_of is not None else catalog_slot_lookup(tokens)
    glyph_for = glyph_for if glyph_for is not None else library_concept_lookup()

    iterations: list[Iteration] = []
    scored: list[tuple[float, Deck]] = []  # (score, the deck the model scored), in order

    def result(stopped: StopReason, detail: str = "") -> AestheticResult:
        best_score: float | None = None
        best_deck = deck
        for score, scored_deck in scored:
            if best_score is None or score > best_score:  # strict: ties keep the earlier deck
                best_score, best_deck = score, scored_deck
        return AestheticResult(
            deck=best_deck,
            best_score=best_score,
            stopped=stopped,
            iterations=iterations,
            detail=detail,
        )

    current = deck
    previous_findings: int | None = None
    for index in range(config.max_iterations):
        iteration_dir = work_dir / f"iter-{index}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        pptx = iteration_dir / "deck.pptx"

        render_deck(current, tokens=tokens, out_path=pptx)

        report = post_render_audit(current, pptx)
        if not report.passes:
            summary = _audit_summary(report.numeric.findings, report.findings)
            if index == 0:
                raise AestheticLoopError(
                    f"the input deck fails the post-render audit before any action was "
                    f"applied ({summary}); that is an upstream defect, so its looks were "
                    "not critiqued"
                )
            return result("audit_failed", f"iteration {index}: {summary}")

        findings = run_deterministic_qa(pptx, tokens)
        if previous_findings is not None and len(findings) > previous_findings:
            return result(
                "qa_regression",
                f"iteration {index}: candidate has {len(findings)} deterministic QA "
                f"finding(s), the deck it came from had {previous_findings}",
            )

        images = rasterise(pptx, iteration_dir / "png")
        image_inputs = [ImageInput(data=image.read_bytes()) for image in images]
        try:
            reply = model.vision(
                image_inputs,
                _critique_prompt(
                    current,
                    qa_findings=findings,
                    iteration=index,
                    previous=iterations,
                    slots_of=slots_of,
                ),
                ActionList,
                system=system,
            )
        except ProviderError as exc:
            return result("model_error", f"iteration {index}: {type(exc).__name__}: {exc}")

        scored.append((reply.score, current))
        previous_findings = len(findings)

        look = Iteration(
            index=index,
            score=reply.score,
            rationale=reply.rationale,
            qa_findings=len(findings),
            applied=(),
            rejected=(),
            images=tuple(images),
        )

        if reply.score >= config.target_score:
            iterations.append(look)
            return result("target_reached")
        if not reply.actions:
            iterations.append(look)
            return result("no_actions")

        candidate = current
        applied: list[Action] = []
        rejected: list[RejectedAction] = []
        for action in reply.actions:
            try:
                candidate = apply_action(
                    candidate, action, pins=pins, slots_of=slots_of, glyph_for=glyph_for
                )
            except ActionRejected as exc:
                rejected.append(RejectedAction(action=action, reason=str(exc)))
            else:
                applied.append(action)
        iterations.append(replace(look, applied=tuple(applied), rejected=tuple(rejected)))
        if not applied:
            return result("all_rejected")
        current = candidate

    # The final candidate was never shown to the model; it is dropped, not returned.
    return result("max_iterations")


def _read_prompt(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"aesthetic critique prompt not found at {path}. Prompts are versioned files "
            "(plan §0.5) and their hashes go into the build manifest — there is no inline "
            "fallback."
        )
    return path.read_text(encoding="utf-8")


def _audit_summary(numeric: Sequence[object], findings: Sequence[object]) -> str:
    parts = [f"{len(numeric)} numeric finding(s)"]
    parts.append(f"{len(findings)} post-render finding(s)")
    if findings:
        first = findings[0]
        parts.append(
            f"first: {getattr(first, 'check', '?')} on slide {getattr(first, 'slide_id', '?')}"
        )
    return "; ".join(parts)


def _critique_prompt(
    deck: Deck,
    *,
    qa_findings: Sequence[QAFinding],
    iteration: int,
    previous: Sequence[Iteration],
    slots_of: SlotLookup,
) -> str:
    """The per-iteration user prompt. The system prompt is `prompts/aesthetic_critique.md`.

    Contract — the model can only act on addresses it is told exist, so list them, and
    nothing else that could be mistaken for editable content:
      - Per slide, in order, with its image index: `slide.id`, `component`,
        `communication_mode`, the current `style` fields, and each **face** block as
        `id  kind  slot` — no block text, no claim text, no citations. The model reads the
        words off the image; giving them to it as strings invites it to hand them back.
      - Components it may swap to: every catalog component with its slot names (via
        `slots_of`), so a `SwapComponent.slot_map` can be written correctly.
      - Icon concepts it may use (`available_concepts()`), and the `AccentToken`,
        `TypeScale`, `ColumnBalance` and `CommunicationMode` vocabularies from the IR.
      - The deterministic QA findings for this render, one line each (`check`, `slide_id`,
        `shapes`, `remedy_detail`) — these are facts about geometry the model should fix,
        not opinions to weigh.
      - From `previous`: each earlier iteration's score and every rejected action with its
        reason, so the model does not propose the same impossible thing twice.
      Deterministic: the same inputs produce the same string (it is part of the cache key).
    """
    lines: list[str] = [
        f"Aesthetic critique, look {iteration + 1}. You are shown one image per slide, in the "
        "order listed below. Reply with a score and at most eight actions.",
        "",
        "SLIDES (addresses you may use; read the words off the images)",
    ]
    for position, slide in enumerate(deck.slides, start=1):
        style = slide.style
        lines.append(f"slide {slide.id} (image {position})")
        lines.append(f"  component: {slide.component}")
        lines.append(f"  communication_mode: {slide.communication_mode or 'unset'}")
        lines.append(
            f"  style: type_scale={style.type_scale} accent={style.accent} "
            f"column_balance={style.column_balance} "
            f"emphasis_block_id={style.emphasis_block_id or 'none'}"
        )
        lines.append("  blocks (id  kind  slot):")
        for block in slide.blocks:
            lines.append(f"    {block.id}  {block.kind}  {block.slot}")

    lines += [
        "",
        "COMPONENTS you may swap to (name: slots; slot_map must cover every slot used)",
    ]
    for name in known_components():
        slots = slots_of(name)
        if slots is not None:
            lines.append(f"  {name}: {', '.join(sorted(slots))}")

    lines += [
        "",
        "ICON CONCEPTS: " + ", ".join(available_concepts()),
        "",
        "VOCABULARIES",
        "  type_scale: " + ", ".join(get_args(TypeScale)),
        "  accent / color_token: " + ", ".join(get_args(AccentToken)),
        "  column_balance: " + ", ".join(get_args(ColumnBalance)),
        "  communication_mode: " + ", ".join(get_args(CommunicationMode)),
        "",
        "DETERMINISTIC QA FINDINGS for this render (geometry facts to fix, not opinions)",
    ]
    if qa_findings:
        for finding in qa_findings:
            lines.append(_finding_line(finding))
    else:
        lines.append("  none")

    if previous:
        lines += ["", "EARLIER LOOKS"]
        for earlier in previous:
            lines.append(f"  look {earlier.index + 1}: score {earlier.score:.1f}")
            for rejection in earlier.rejected:
                lines.append(
                    f"    rejected {rejection.action.model_dump_json()}: {rejection.reason}"
                )
    return "\n".join(lines)


def _finding_line(finding: object) -> str:
    if isinstance(finding, QAFinding):
        return (
            f"  {finding.check} | slide {finding.slide_id} | shapes {', '.join(finding.shapes)}"
            f" | {finding.remedy_detail}"
        )
    return f"  {finding}"
