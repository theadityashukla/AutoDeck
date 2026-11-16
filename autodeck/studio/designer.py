"""The designer: one slide brief in, one designed slide (or a failure with its findings)
out (Phase 2-3, L3 Composition and L4 Placement; plan §6.2).

This is the slide bench's trial loop (`bench/slides/run.py`, `Trial._design`) moved into
the product, because it is what produced clean, designed slides: `gpt-5.6-sol` in one or
two attempts on every slide it completed, `gpt-5.6-luna` on 14 of 16 in two to four. A
model is given one slide brief and one tool, `write_slide`; what it returns is validated,
checked against the brief, layout-checked and dry-built, and every problem goes back to
the model as the tool result, until the slide is clean or the attempts run out.

**One attempt** is one model call. Per call, in order:

1. Call `model.model.converse(messages, [WRITE_SLIDE_TOOL], system=<designer prompt>)`.
2. No `write_slide` call: the first time, nudge (`NUDGE_TEXT`, as a user message, or as the
   tool result of any other tool it called) and continue; the second time, stop
   (outcome `no_tool_call`, the slide fails).
3. Validate the first `write_slide` call (`evaluate`): invalid JSON or arguments →
   `validation_error`; else build the slide (`designed_slide`) → a validation error of the
   built slide (a block placed twice, an unknown block) → `validation_error`; then
   `conformance_findings` (the header word for word, the chart data exactly) →
   `conformance`; then layout QA (`render_adapter.check_slide`, through the module
   attribute so tests can observe the tokens) → `qa_findings`; then the dry build
   (`design_render.renderable`) → `render`; else `clean`.
4. Answer every tool call of that model turn (the real result to the first `write_slide`,
   `"Not run: only one write_slide call is read per turn."` to any other `write_slide`,
   `"No such tool <name>."` to anything else), then stop if clean.

The designer keeps no state between calls of `design_slide`; parallelism is
`design_slides` running several `design_slide` calls on a thread pool. A model exception
fails that slide only (outcome recorded as an error), never the others; v2's
`FontNotFoundError` propagates (no honest check is possible without the font).

Results are applied to the deck elsewhere (`compose.py`), through the artifact store, with
the layer `composition` and the designer's model id.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from autodeck.design.fonts import FontNotFoundError
from autodeck.design.theme.tokens import DesignTokens
from autodeck.providers.base import AssistantTurn, Message, ToolCall, ToolSpec
from autodeck.studio import design_render, designer_prompt, render_adapter
from autodeck.studio.bindings import BoundModel
from autodeck.studio.design import DesignSystem
from autodeck.studio.models import MAX_FAILURE_FINDINGS, Slide, SlideBrief, brief_digest
from autodeck.studio.tool_args import DesignerWriteArgs

TOOL_NAME = "write_slide"

WRITE_SLIDE_TOOL = ToolSpec(
    name=TOOL_NAME,
    description=(
        "Write the slide: its blocks (the words, chart or icons) and its free layout (where "
        "each block goes, plus any shapes). Call it again with the whole corrected slide to "
        "change it."
    ),
    args_model=DesignerWriteArgs,
)

NUDGE_TEXT = (
    "You did not call write_slide. Design the slide by calling write_slide with the whole "
    "slide (blocks and layout); do not answer in prose."
)
ACCEPTED_TEXT = "Accepted: the slide is valid and passes the layout checks. Reply DONE."
INVALID_JSON_TEXT = "The arguments were not valid JSON. Call write_slide again."
REJECTED_PREFIX = (
    "write_slide was rejected; nothing was written. Fix these and call write_slide again "
    "with the whole slide:\n"
)
FINDINGS_PREFIX = (
    "The slide is valid but fails the checks. Fix these and call write_slide again with the "
    "whole corrected slide:\n"
)
OTHER_WRITE_TEXT = "Not run: only one write_slide call is read per turn."

DEFAULT_ATTEMPTS = 4
DEFAULT_PARALLEL = 4
MAX_VALIDATION_LINES = 20

Outcome = Literal[
    "clean", "validation_error", "conformance", "qa_findings", "render", "no_tool_call", "error"
]


@dataclass(frozen=True)
class DesignJob:
    """One slide to design."""

    slide_id: str
    brief: SlideBrief
    system: DesignSystem
    tokens: DesignTokens
    """The tokens of `system` (`design.design_tokens(system.palette, base)`)."""


@dataclass(frozen=True)
class Attempt:
    """One model call of a design: its outcome and what was fed back."""

    n: int
    outcome: Outcome
    findings: tuple[str, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class DesignResult:
    """The outcome of one slide.

    `clean` True: `slide` is the designed slide (blocks and layout, id = the job's slide
    id, `intent` = the brief's intent, `brief` = the brief, no `composed`), and it passed
    every check. `clean` False: `slide` is None and `findings` are the last attempt's
    findings (one line each, at most `models.MAX_FAILURE_FINDINGS`), or the one line
    `[no_tool_call] the model did not call write_slide (after one nudge)` /
    `[error] <Type>: <message>` that says what happened. `attempts` counts model calls.
    """

    slide_id: str
    clean: bool
    slide: Slide | None
    attempts: tuple[Attempt, ...]
    findings: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    seconds: float
    model_id: str
    error: str = ""
    system_id: str = ""
    system_version: int = 1
    brief_digest: str = ""

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


def _flat(text: str) -> str:
    return " ".join(text.split())


def designed_slide(args: DesignerWriteArgs, *, slide_id: str, brief: SlideBrief) -> Slide:
    """The `Slide` the designer's call describes: `Slide(id=slide_id, intent=brief.intent,
    brief=brief, blocks=args.slide.blocks, layout=args.slide.layout)` (the model's own `id`,
    `intent` and `speaker_notes` are ignored; marker, serves and notes are the caller's to
    restore). Raises `pydantic.ValidationError` when the layout does not place every block
    exactly once, as `Slide` validates."""
    return Slide(
        id=slide_id,
        intent=brief.intent,
        brief=brief,
        blocks=args.slide.blocks,
        layout=args.slide.layout,
    )


def conformance_findings(slide: Slide, brief: SlideBrief) -> list[str]:
    """What the slide gets wrong against its brief, by code. `[]` when it conforms.

    In order:

    * The header: unless some text block's flat text (whitespace runs, newlines included,
      collapsed to one space; ends stripped) equals the flat header, the finding
      `[brief] the header must appear word for word in one text block: "<header>"`.
    * The chart: with no `brief.content.chart`, each chart block is
      `[brief] chart <block id>: the brief has no chart data; remove the chart`. With one,
      more than one chart block is `[brief] the brief has one chart; draw it once`; a chart
      block whose `categories`, or series (names and values, in order), differ from the
      brief's is `[brief] chart <block id> must use the brief's data exactly: categories
      <list>, series <name: values; ...>`. A brief chart that is not drawn is allowed (the
      designer may leave it out).
    """
    findings: list[str] = []
    flat_header = _flat(brief.header)
    if not any(b.kind == "text" and _flat(b.text or "") == flat_header for b in slide.blocks):
        findings.append(
            f'[brief] the header must appear word for word in one text block: "{brief.header}"'
        )
    charts = [b for b in slide.blocks if b.kind == "chart" and b.chart is not None]
    want = brief.content.chart
    if want is None:
        findings.extend(
            f"[brief] chart {b.id}: the brief has no chart data; remove the chart"
            for b in charts
        )
        return findings
    if len(charts) > 1:
        findings.append("[brief] the brief has one chart; draw it once")
    expected_series = [(x.name, [float(v) for v in x.values]) for x in want.series]
    for block in charts:
        data = block.chart
        assert data is not None
        got_series = [(x.name, [float(v) for v in x.values]) for x in data.series]
        if list(data.categories) != list(want.categories) or got_series != expected_series:
            series_text = "; ".join(
                f"{name}: {', '.join(f'{v:g}' for v in values)}"
                for name, values in expected_series
            )
            findings.append(
                f"[brief] chart {block.id} must use the brief's data exactly: categories "
                f"{list(want.categories)}, series {series_text}"
            )
    return findings


def qa_findings(slide: Slide, tokens: DesignTokens) -> list[str]:
    """Layout QA as finding lines: `render_adapter.check_slide(slide, tokens)` (called
    through the module attribute) formatted `[<check>] <block id or 'slide'>: <message>`;
    when that is empty, the dry build: `design_render.renderable(slide, tokens)` → one line
    `[render] slide: <reason>` when it returns a reason. `[]` when clean. v2's
    `FontNotFoundError` propagates."""
    lines = [
        f"[{f.check}] {f.block_id or 'slide'}: {f.message}"
        for f in render_adapter.check_slide(slide, tokens)
    ]
    if lines:
        return lines
    reason = design_render.renderable(slide, tokens)
    return [f"[render] slide: {reason}"] if reason else []


def evaluate(
    call: ToolCall, *, slide_id: str, brief: SlideBrief, tokens: DesignTokens
) -> tuple[Slide | None, Outcome, list[str], str]:
    """Validate and check one `write_slide` call: `(slide, outcome, findings, result text)`.

    * `"__invalid__"` in the arguments → `(None, "validation_error", ["[validation]
      invalid JSON"], INVALID_JSON_TEXT)`.
    * `DesignerWriteArgs` or `designed_slide` raises `ValidationError` → findings are the
      first `MAX_VALIDATION_LINES` errors as `[validation] <loc joined by '.'>: <msg>`,
      result `REJECTED_PREFIX` + those lines joined by `\\n`; slide None.
    * `conformance_findings` non-empty → outcome `conformance`; else `qa_findings`
      non-empty → outcome `qa_findings` when any line starts with something other than
      `[render]`, else `render`. Result `FINDINGS_PREFIX` + the lines joined by `\\n`; the
      slide is returned (it validated).
    * Otherwise `(slide, "clean", [], ACCEPTED_TEXT)`.
    """
    if "__invalid__" in call.arguments:
        return None, "validation_error", ["[validation] invalid JSON"], INVALID_JSON_TEXT
    try:
        args = DesignerWriteArgs.model_validate(call.arguments)
        slide = designed_slide(args, slide_id=slide_id, brief=brief)
    except ValidationError as exc:
        lines = [
            f"[validation] {'.'.join(str(part) for part in e['loc'])}: {e['msg']}"
            for e in exc.errors()[:MAX_VALIDATION_LINES]
        ]
        return None, "validation_error", lines, REJECTED_PREFIX + "\n".join(lines)
    outcome: Outcome = "conformance"
    lines = conformance_findings(slide, brief)
    if not lines:
        lines = qa_findings(slide, tokens)
        outcome = (
            "qa_findings"
            if any(not line.startswith("[render]") for line in lines)
            else "render"
        )
    if lines:
        return slide, outcome, lines, FINDINGS_PREFIX + "\n".join(lines)
    return slide, "clean", [], ACCEPTED_TEXT


def answer_calls(turn: AssistantTurn, primary: ToolCall | None, result: str) -> list[Message]:
    """One `tool` message per tool call of `turn`, in order: `result` for `primary`;
    `OTHER_WRITE_TEXT` for any other `write_slide` call; `f"No such tool {name!r}. {result}"`
    for a call to any other name (with `primary` None, every call gets that form)."""
    answers: list[Message] = []
    for call in turn.tool_calls:
        if primary is None:
            text = f"No such tool {call.name!r}. {result}"
        elif call is primary:
            text = result
        elif call.name == TOOL_NAME:
            text = OTHER_WRITE_TEXT
        else:
            text = f"No such tool {call.name!r}. {result}"
        answers.append(Message(role="tool", content=text, tool_call_id=call.id))
    return answers


def design_slide(
    model: BoundModel,
    job: DesignJob,
    *,
    system_prompt: str | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
) -> DesignResult:
    """Design one slide, as the module docstring describes.

    The conversation starts with one user message,
    `designer_prompt.brief_user_text(job.slide_id, job.brief, job.system)`; the system
    prompt is `system_prompt` or `designer_prompt.designer_system_prompt(job.tokens,
    job.system)`. Each model reply is appended as an assistant message (text and tool
    calls); the answers from `answer_calls` follow it. At most `attempts` model calls in
    total (the nudge call counts). Tokens are summed from each turn's usage; `seconds` is
    wall time (`time.perf_counter`). The result carries `system_id`, `system_version` and
    `brief_digest` (`models.brief_digest(job.brief)`) for the caller's fingerprint.

    An exception from `converse` ends the design: `clean=False`, outcome `error` on the
    attempt, `error=f"{type(exc).__name__}: {exc}"`, findings `("[error] <that text>",)`.
    `FontNotFoundError` from the checks propagates.
    """
    started = time.perf_counter()
    prompt = system_prompt or designer_prompt.designer_system_prompt(job.tokens, job.system)
    messages: list[Message] = [
        Message(
            role="user",
            content=designer_prompt.brief_user_text(job.slide_id, job.brief, job.system),
        )
    ]
    made: list[Attempt] = []
    slide: Slide | None = None
    findings: tuple[str, ...] = ()
    error = ""
    clean = False
    nudged = False
    for n in range(1, attempts + 1):
        try:
            turn = model.model.converse(messages, [WRITE_SLIDE_TOOL], system=prompt)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            findings = (f"[error] {error}",)
            made.append(Attempt(n, "error", findings))
            break
        tin, tout = turn.usage.input_tokens, turn.usage.output_tokens
        messages.append(
            Message(role="assistant", content=turn.text, tool_calls=turn.tool_calls)
        )
        writes = [c for c in turn.tool_calls if c.name == TOOL_NAME]
        if not writes:
            made.append(Attempt(n, "no_tool_call", (), tin, tout))
            findings = ("[no_tool_call] the model did not call write_slide (after one nudge)",)
            if nudged:
                break
            nudged = True
            if turn.tool_calls:
                messages.extend(answer_calls(turn, None, NUDGE_TEXT))
            else:
                messages.append(Message(role="user", content=NUDGE_TEXT))
            continue
        primary = writes[0]
        built, outcome, lines, result = evaluate(
            primary, slide_id=job.slide_id, brief=job.brief, tokens=job.tokens
        )
        made.append(Attempt(n, outcome, tuple(lines), tin, tout))
        findings = tuple(lines)
        messages.extend(answer_calls(turn, primary, result))
        if outcome == "clean":
            clean, slide = True, built
            break
    return DesignResult(
        slide_id=job.slide_id,
        clean=clean,
        slide=slide,
        attempts=tuple(made),
        findings=() if clean else findings[:MAX_FAILURE_FINDINGS],
        input_tokens=sum(a.input_tokens for a in made),
        output_tokens=sum(a.output_tokens for a in made),
        seconds=time.perf_counter() - started,
        model_id=model.model_id,
        error=error,
        system_id=job.system.id,
        system_version=job.system.version,
        brief_digest=brief_digest(job.brief),
    )


def design_slides(
    model: BoundModel,
    jobs: Sequence[DesignJob],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    max_parallel: int = DEFAULT_PARALLEL,
) -> list[DesignResult]:
    """`design_slide` for every job, at most `max_parallel` at a time
    (`concurrent.futures.ThreadPoolExecutor`), results in **job order**. `[]` for no jobs.
    The system prompt is built once per distinct system (`designer_system_prompt`) and
    shared. A `FontNotFoundError` from any job propagates after the pool shuts down."""
    if not jobs:
        return []
    prompts: dict[tuple[str, int], str] = {}
    for job in jobs:
        key = (job.system.id, job.system.version)
        if key not in prompts:
            prompts[key] = designer_prompt.designer_system_prompt(job.tokens, job.system)

    def run(job: DesignJob) -> DesignResult:
        started = time.perf_counter()
        try:
            return design_slide(
                model,
                job,
                system_prompt=prompts[(job.system.id, job.system.version)],
                attempts=attempts,
            )
        except FontNotFoundError:
            raise
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            return DesignResult(
                slide_id=job.slide_id,
                clean=False,
                slide=None,
                attempts=(Attempt(1, "error", (f"[error] {text}",)),),
                findings=(f"[error] {text}",),
                input_tokens=0,
                output_tokens=0,
                seconds=time.perf_counter() - started,
                model_id=model.model_id,
                error=text,
                system_id=job.system.id,
                system_version=job.system.version,
                brief_digest=brief_digest(job.brief),
            )

    with ThreadPoolExecutor(max_workers=max(1, max_parallel)) as pool:
        futures = [pool.submit(run, job) for job in jobs]
        return [f.result() for f in futures]
