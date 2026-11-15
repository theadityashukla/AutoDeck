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

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pydantic import ValidationError

from autodeck.providers.base import Message, ToolSpec
from autodeck.studio import design, prompt
from autodeck.studio.bindings import BoundModel
from autodeck.studio.design import DesignDirection, DesignDraft, PaletteAttempt
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
MAX_VALIDATION_LINES = 20
MAX_ATTEMPT_FINDINGS = 8
ATTEMPT_FINDING_CLIP = 160
OTHER_CALL_TEXT = "Not run: only one set_palette call is read per turn."


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
    attempt_log: tuple[PaletteAttempt, ...] = ()
    """Every call that reached a verdict, in order: accepted, or refused with its findings
    (a contrast refusal's measured ratios, a rejected call's validation lines, or the
    no-tool-call line). A call that raised is not in it (`findings` has the error). The
    accepted draft carries the same list as `palette_attempts`."""


def _attempt(number: int, accepted: bool, findings: Sequence[str]) -> PaletteAttempt:
    clipped = [
        f if len(f) <= ATTEMPT_FINDING_CLIP else f[: ATTEMPT_FINDING_CLIP - 1] + "…"
        for f in findings[:MAX_ATTEMPT_FINDINGS]
    ]
    return PaletteAttempt(attempt=number, accepted=accepted, findings=clipped)


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
    lines = [
        "# Design direction",
        f"Name: {direction.name}",
        f"Concept: {direction.concept.strip()}",
        "Rules:",
        *(f"- {rule}" for rule in direction.rules),
        "",
        "# What the deck is about",
    ]
    sample = list(briefs)[:MAX_SAMPLE_BRIEFS]
    if sample:
        lines.extend(f"- {brief.header}" for brief in sample)
    else:
        lines.append("(no slides yet)")
    lines.extend(["", "Make this direction concrete and call set_palette."])
    return "\n".join(lines)


def draft_from_args(
    args: SetPaletteArgs, direction: DesignDirection, *, model_id: str
) -> DesignDraft:
    """`DesignDraft(name=direction.name, concept=direction.concept, rules=direction.rules,
    palette=args.palette, roles={slot: role for slot, role in args.roles.items()},
    background=args.background, text_pairs=args.text_pairs, made_by=model_id)`. Raises
    `pydantic.ValidationError` for a structural problem (a missing role, no text colour on
    the background)."""
    return DesignDraft(
        name=direction.name,
        concept=direction.concept,
        rules=direction.rules,
        palette=args.palette,
        roles={slot: role for slot, role in args.roles.items()},
        background=args.background,
        text_pairs=args.text_pairs,
        made_by=model_id,
    )


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
    started = time.perf_counter()
    prompt_text = system_prompt or prompt.role_prompt(prompt.SYSTEM_PROMPT_PATH)
    messages: list[Message] = [
        Message(role="user", content=system_user_text(direction, briefs))
    ]
    input_tokens = output_tokens = calls = 0
    findings: tuple[str, ...] = ()
    draft: DesignDraft | None = None
    log: list[PaletteAttempt] = []
    nudged = False
    no_call = f"[no_tool_call] the model did not call {TOOL_NAME} (after one nudge)"

    def result() -> SystemResult:
        return SystemResult(
            direction=direction,
            draft=draft,
            attempts=calls,
            findings=() if draft is not None else findings,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            seconds=time.perf_counter() - started,
            model_id=model.model_id,
            attempt_log=tuple(log),
        )

    while calls < attempts:
        calls += 1
        try:
            turn = model.model.converse(messages, [SET_PALETTE_TOOL], system=prompt_text)
        except Exception as exc:  # a model failure fails this direction only
            findings = (f"[error] {type(exc).__name__}: {exc}",)
            return result()
        input_tokens += turn.usage.input_tokens
        output_tokens += turn.usage.output_tokens
        messages.append(
            Message(role="assistant", content=turn.text, tool_calls=turn.tool_calls)
        )
        primary = next((c for c in turn.tool_calls if c.name == TOOL_NAME), None)
        if primary is None:
            findings = (no_call,)
            log.append(_attempt(calls, False, findings))
            if nudged:
                return result()
            nudged = True
            if turn.tool_calls:
                messages.extend(
                    Message(
                        role="tool",
                        content=f"No such tool {c.name}. {NUDGE_TEXT}",
                        tool_call_id=c.id,
                    )
                    for c in turn.tool_calls
                )
            else:
                messages.append(Message(role="user", content=NUDGE_TEXT))
            continue

        text = ""
        candidate: DesignDraft | None = None
        if "__invalid__" in primary.arguments:
            findings = ("[validation] invalid JSON",)
            text = REJECTED_PREFIX + "\n".join(findings)
        else:
            try:
                candidate = draft_from_args(
                    SetPaletteArgs.model_validate(primary.arguments),
                    direction,
                    model_id=model.model_id,
                )
            except ValidationError as exc:
                findings = tuple(
                    f"[validation] {'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
                    for err in exc.errors()[:MAX_VALIDATION_LINES]
                )
                text = REJECTED_PREFIX + "\n".join(findings)
        if candidate is not None:
            palette_findings = design.check_draft(candidate)
            if palette_findings:
                body = design.findings_text(palette_findings)
                findings = tuple(body.split("\n"))
                text = REFUSED_PREFIX + body
            else:
                text = ACCEPTED_TEXT
        if candidate is None:
            log.append(_attempt(calls, False, findings))
        elif text == ACCEPTED_TEXT:
            log.append(_attempt(calls, True, ()))
            draft = candidate.model_copy(update={"palette_attempts": list(log)})
        else:
            log.append(_attempt(calls, False, findings))
        for call in turn.tool_calls:
            if call is primary:
                answer = text
            elif call.name == TOOL_NAME:
                answer = OTHER_CALL_TEXT
            else:
                answer = f"No such tool {call.name}."
            messages.append(Message(role="tool", content=answer, tool_call_id=call.id))
        if draft is not None:
            break
    return result()


def make_designs(
    model: BoundModel,
    directions: Sequence[DesignDirection],
    *,
    briefs: Sequence[SlideBrief] = (),
    attempts: int = DEFAULT_ATTEMPTS,
) -> list[SystemResult]:
    """`make_design` for every direction in parallel (one thread each), results in
    direction order."""

    def one(direction: DesignDirection) -> SystemResult:
        try:
            return make_design(model, direction, briefs=briefs, attempts=attempts)
        except Exception as exc:  # never let one direction stop the others
            return SystemResult(
                direction=direction,
                draft=None,
                attempts=0,
                findings=(f"[error] {type(exc).__name__}: {exc}",),
                input_tokens=0,
                output_tokens=0,
                seconds=0.0,
                model_id=model.model_id,
            )

    if not directions:
        return []
    with ThreadPoolExecutor(max_workers=len(directions)) as pool:
        return list(pool.map(one, directions))
