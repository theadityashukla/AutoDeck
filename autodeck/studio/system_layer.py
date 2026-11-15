"""The system layer: a design direction in words → a checked palette and roles (Phase 2-3,
L2 System; plan §6.1, §7.2).

The lead writes a `DesignDirection` (a name, a concept, three to five rules). The system
layer's model, given `prompts/studio/system.md` and the direction, calls its one tool,
`set_palette`, with a palette, the role of every slot, the background slot and the text
pairs the roles allow. Code checks every pair (`design.check_palette`); a failing palette
is refused with the measured ratios (`design.findings_text`) and the model corrects it, up
to `attempts` calls. The result is a `DesignDraft` that passes the check, or a failure with
the last findings. Nothing is stored here: `compose.py` adds a draft to the engagement's
`DesignSystemStore` when a design is adopted, or records it on a proposal option.

The loop has the designer's shape (`designer.design_slide`): one tool, nudge once when the
model answers in prose, every problem fed back as the tool result.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from autodeck.providers.base import ToolSpec
from autodeck.studio.bindings import BoundModel
from autodeck.studio.design import DesignDirection, DesignDraft
from autodeck.studio.models import SlideBrief
from autodeck.studio.tool_args import SetPaletteArgs

TOOL_NAME = "set_palette"

SET_PALETTE_TOOL = ToolSpec(
    name=TOOL_NAME,
    description=(
        "Set the design system's palette: a hex colour per slot, the role of every slot, the "
        "background slot, and every text pair the roles allow. Checked for contrast."
    ),
    args_model=SetPaletteArgs,
)

NUDGE_TEXT = (
    "You did not call set_palette. Call it with the whole palette; do not answer in prose."
)
ACCEPTED_TEXT = "Accepted: every declared text pair passes the contrast check. Reply DONE."
REFUSED_PREFIX = (
    "The palette fails the contrast check. Change the colours (or the pairs the roles "
    "allow) and call set_palette again with the whole palette:\n"
)
REJECTED_PREFIX = "set_palette was rejected. Fix these and call it again:\n"

DEFAULT_ATTEMPTS = 3
MAX_SAMPLE_BRIEFS = 3


@dataclass(frozen=True)
class SystemResult:
    """`draft` is set exactly when the palette passed. `findings` are the last attempt's
    problems (palette findings as `design.findings_text` lines, or validation lines
    `[validation] <loc>: <msg>`, or the one line `[no_tool_call] the model did not call
    set_palette (after one nudge)` / `[error] <Type>: <msg>`)."""

    direction: DesignDirection
    draft: DesignDraft | None
    attempts: int
    findings: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    seconds: float
    model_id: str


def system_user_text(direction: DesignDirection, briefs: Sequence[SlideBrief]) -> str:
    """The system layer's user message. Lines joined by `\\n`, exactly:

    ```
    # Design direction
    Name: <name>
    Concept: <concept stripped>
    Rules:
    - <rule>
    ...

    # What the deck is about
    ```

    then, for each of the first `MAX_SAMPLE_BRIEFS` briefs, `- <header>` (so the palette can
    suit the content), or `(no slides yet)` when there are none; then a blank line and
    `Make this direction concrete and call set_palette.`
    """
    raise NotImplementedError


def draft_from_args(
    args: SetPaletteArgs, direction: DesignDirection, *, model_id: str
) -> DesignDraft:
    """`DesignDraft(name=direction.name, concept=direction.concept, rules=direction.rules,
    palette=args.palette, roles={slot: role for slot, role in args.roles.items()},
    background=args.background, text_pairs=args.text_pairs, made_by=model_id)`. Raises
    `pydantic.ValidationError` for a structural problem (a missing role, no text colour on
    the background)."""
    raise NotImplementedError


def make_design(
    model: BoundModel,
    direction: DesignDirection,
    *,
    briefs: Sequence[SlideBrief] = (),
    attempts: int = DEFAULT_ATTEMPTS,
    system_prompt: str | None = None,
) -> SystemResult:
    """Turn `direction` into a checked `DesignDraft`.

    Messages start with `system_user_text(direction, briefs)`; the system prompt is
    `system_prompt` or `prompt.role_prompt(prompt.SYSTEM_PROMPT_PATH)`; the only tool is
    `SET_PALETTE_TOOL`. Per call: no `set_palette` call → nudge once (`NUDGE_TEXT`), then
    fail with `[no_tool_call]`; invalid arguments (`"__invalid__"`, `SetPaletteArgs` or
    `draft_from_args` raising `ValidationError`) → `REJECTED_PREFIX` + validation lines;
    `design.check_draft` findings → `REFUSED_PREFIX` + `design.findings_text`; else
    `ACCEPTED_TEXT` and stop with the draft. Every tool call of a turn is answered (other
    names: `"No such tool <name>."`). At most `attempts` calls. A model exception fails the
    result with `[error] <Type>: <msg>`. `made_by` is `model.model_id`.
    """
    raise NotImplementedError


def make_designs(
    model: BoundModel,
    directions: Sequence[DesignDirection],
    *,
    briefs: Sequence[SlideBrief] = (),
    attempts: int = DEFAULT_ATTEMPTS,
) -> list[SystemResult]:
    """`make_design` for every direction in parallel (one thread each), results in
    direction order."""
    raise NotImplementedError
