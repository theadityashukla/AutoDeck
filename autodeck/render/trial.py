"""Accept one presentation action only if the deck still renders and still obeys D13.

Both passes that change presentation — the art director (3b.7) and the aesthetic critic
(3b.5) — apply model-proposed actions one at a time and keep each only if it is safe.
"Safe" was first written inline in `render/qa/aesthetic.py`; art direction needs the same
rule, and two copies of an acceptance rule drift (the lesson this project keeps relearning),
so it lives here and both call it.

An action is accepted when, in order:

1. `apply_action` accepts it — types, addresses, pins, and the fact fingerprint
   (`autodeck/ir/actions.py`). `FactMutationError` is never caught anywhere.
2. The resulting deck renders (`render_deck` to a scratch path — pure python-pptx, ~10 ms a
   slide, no LibreOffice). A render failure *caused by the action* is a rejection.
3. It creates no new grammar finding (`autodeck.design.grammar.lint_slide_ir`, D13's
   blocking IR lints; advisories do not count): the count of findings on the touched slide
   does not rise. An `AssignIcons` that completes an icon+chart+diagram pileup, or a mode
   change that pushes a slide over its word budget, is a regression the model cannot see
   from where it stands.

Rejections carry a reason a person can read; they are reported, never retried here.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Final

from autodeck.design import grammar
from autodeck.design.layout_kit import LayoutOverflowError
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.actions import (
    ActionRejected,
    ConceptLookup,
    SlotLookup,
    UnknownAddressError,
    apply_action,
)
from autodeck.ir.models import Deck, LayoutPin
from autodeck.render.renderer import RenderStageError, render_deck


class DoesNotRender(ActionRejected):
    """The action applied cleanly to the IR, but the resulting deck does not render."""


class GrammarRegression(ActionRejected):
    """The action applied and renders, but adds a D13 grammar finding on its slide."""


DOES_NOT_RENDER_PREFIX: Final = "does not render: "
"""`str(DoesNotRender)` starts with this — the reason format `aesthetic.py`'s tests assert."""


def try_action(
    deck: Deck,
    action: object,
    *,
    tokens: DesignTokens,
    scratch: Path,
    pins: tuple[LayoutPin, ...] | list[LayoutPin] = (),
    slots_of: SlotLookup,
    glyph_for: ConceptLookup,
) -> Deck:
    """Return `deck` with `action` applied, or raise `ActionRejected` explaining why not.

    Contract:
      - `action` is any `ArtAction` or `Action` member (typed `object` here only so both
        unions are accepted; narrow it with the same union `apply_action` takes).
      - Step 1 → `apply_action(...)`; its `ActionRejected` propagates unchanged.
      - Step 2 → `render_deck(candidate, tokens=tokens, out_path=scratch)`;
        `RenderStageError` or `LayoutOverflowError` → `DoesNotRender(DOES_NOT_RENDER_PREFIX
        + f"{type(exc).__name__}: {exc}")` chained `from exc`. `FontNotFoundError`,
        `RenderBlocked` and anything else propagate — environment and safety failures, not
        properties of the action.
      - Step 3 → `grammar.lint_slide_ir` on the touched slide (`action.slide_id`) before and
        after; more findings after → `GrammarRegression` naming the new finding(s).
        Equal or fewer is accepted (an action may fix a finding).
      - Never mutates `deck`. `scratch` is overwritten on each call.
    """
    candidate = apply_action(
        deck,
        action,  # type: ignore[arg-type]  # any member of Action | ArtAction, see docstring
        pins=pins,
        slots_of=slots_of,
        glyph_for=glyph_for,
    )

    try:
        render_deck(candidate, tokens=tokens, out_path=scratch)
    except (RenderStageError, LayoutOverflowError) as exc:
        raise DoesNotRender(f"{DOES_NOT_RENDER_PREFIX}{type(exc).__name__}: {exc}") from exc

    slide_id: str = action.slide_id  # type: ignore[attr-defined]
    before = _slide_findings(deck, slide_id)
    after = _slide_findings(candidate, slide_id)
    if len(after) > len(before):
        remaining = Counter(before)
        new = []
        for finding in after:
            if remaining[finding] > 0:
                remaining[finding] -= 1
            else:
                new.append(finding)
        raise GrammarRegression(
            f"adds {len(new)} grammar finding(s) on slide {slide_id!r}: "
            + "; ".join(str(finding) for finding in new)
        )
    return candidate


def _slide_findings(deck: Deck, slide_id: str) -> list[grammar.GrammarFinding]:
    """D13's *blocking* IR lints for one slide. `apply_action` has already vouched the id.

    Advisory findings are not counted: the concept-count advisory is a rough proxy that a
    correctly filled `icon_pillars` slide (title, labels, and an icon per label) can trip
    merely by being complete, and a rule that rejected `AssignIcons` for that would refuse
    the action art direction exists to make. Advisories stay visible in
    `ArtDirectionResult.grammar`; only a finding that would block the build rejects here.
    """
    for slide in deck.slides:
        if slide.id == slide_id:
            return [
                finding
                for finding in grammar.lint_slide_ir(slide, location=f"slide {slide.id}")
                if finding.severity == "blocking"
            ]
    raise UnknownAddressError(f"unknown slide_id {slide_id!r}")  # pragma: no cover
