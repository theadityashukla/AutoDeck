"""The lead loop: one turn of the conversation (plan §5.2, §12 Phase 1).

Unlike v2's deck agent (`agents/session.py`), a turn here ends when the model **replies in
text with no tool call**: that is a normal reply, not a stall, and there is no `finish`
tool. The loop keeps v2's other disciplines:

* **Caps.** A step cap and a cumulative input-token cap per turn (`LoopLimits`). Every
  stop has a reason (`conversation.StopReason`).
* **Compaction.** Older tool results are replaced by their one-line summaries with v2's
  pure `agents.session.compact`, so the same history always compacts to the same request.
* **Tool mechanics.** Calls go through v2's `ToolBox.dispatch`, which never raises for a
  model's mistake. An exception that does escape (a bug, a corrupt store) propagates to
  the session, which ends the turn with `stop_reason="error"`.

The loop owns no deck logic and no storage. It talks to a `TurnSink`, which the session
implements by appending lines to the thread log and publishing events; tests implement it
with a recorder. That keeps the loop testable with the scripted model alone.

Phase 2 routes calls by layer; the loop already takes the model as a `BoundModel` (role,
model id, model) rather than a provider, so routing changes which binding is passed, not
this code.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from autodeck.agents.session import compact
from autodeck.agents.tools.registry import ToolBox, ToolResult
from autodeck.providers.base import Message, ToolCall
from autodeck.studio import diff
from autodeck.studio.bindings import BoundModel
from autodeck.studio.conversation import (
    MAX_DIFF_LINES,
    ArtifactCreated,
    AssistantLine,
    AssistantText,
    ChangeRecorded,
    ChangeReverted,
    NoteLine,
    ProposalCreated,
    SlideComposed,
    StopReason,
    ThreadLine,
    ToolCalled,
    ToolFinished,
    ToolLine,
    TurnEvent,
    UserLine,
)
from autodeck.studio.models import ChangeEntry
from autodeck.studio.prompt import CONTEXT_SEPARATOR
from autodeck.studio.tools import ComposedSlide, TurnLedger

STALL_NUDGE = "You returned neither a reply nor a tool call. Reply to the owner in words."
"""Sent once, unrecorded, when a model call returns no text and no tool call."""

INTERRUPTED_RESULT = "ERROR: this call was interrupted before it ran."
"""The tool result `build_model_messages` supplies for a logged call with no logged result
(a turn that crashed between the call and its result)."""

NOTE_PREFIX = "[Note: "
NOTE_SUFFIX = "]"

MECHANIC_PREFIX = "[mechanic] "
"""Phase 2-3: how the mechanic's part of a turn appears in the lead's conversation."""


def fold_mechanic_lines(lines: Sequence[ThreadLine]) -> str | None:
    """Phase 2-3: a run of the mechanic's lines as one line of assistant text for the lead.

    `lines` are consecutive `AssistantLine`s and `ToolLine`s with `role == "mechanic"`.
    Parts, in order: each `ToolLine`'s `summary` (with `" (error)"` appended when
    `error`), then `"reply: <views.flat(text)>"` for the last `AssistantLine` with
    non-blank text. Returns `MECHANIC_PREFIX + " | ".join(parts)`, or None when there are
    no parts. Pure. Example: `[mechanic] retitled s2: layout passed | reply: Slide 2 is now
    titled 'Quantisation cuts the bill by 38%'.`
    """
    raise NotImplementedError


@dataclass(frozen=True)
class LoopLimits:
    max_steps: int = 24
    """Model calls per turn."""
    max_input_tokens: int = 800_000
    """Cumulative reported input tokens per turn."""
    keep_recent_results: int = 6
    """Tool results kept verbatim; older ones are compacted to their summaries."""


@dataclass(frozen=True)
class LoopOutcome:
    stop_reason: StopReason
    steps: int
    input_tokens: int
    output_tokens: int
    final_text: str
    """The text of the last model call that had non-blank text ("" if none)."""


class TurnSink(Protocol):
    """Where the loop reports what happens. Called synchronously, in order."""

    def assistant(
        self,
        *,
        step: int,
        text: str,
        tool_calls: list[ToolCall],
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """One model call returned (record an `AssistantLine`)."""
        ...

    def tool(self, *, step: int, call: ToolCall, result: ToolResult) -> None:
        """One tool call ran (record a `ToolLine`)."""
        ...

    def event(self, event: TurnEvent) -> None:
        """Publish one streamed event."""
        ...


def build_model_messages(
    lines: Sequence[ThreadLine], *, role: str = "lead"
) -> tuple[list[Message], dict[str, str]]:
    """A thread's log as provider messages, plus the tool summaries for compaction.

    Phase 2-3: `role` is the role the messages are for (the lead). Assistant and tool lines
    written by another role (the mechanic) are not replayed as calls: each maximal run of
    them becomes one `assistant` message with `fold_mechanic_lines`' text (skipped when it
    is None), so the lead sees what the mechanic did without tool calls it does not have.
    Logs with only lead lines are unchanged from Phase 1.

    Walk the lines in order:

    * `UserLine` → a `user` message with its text.
    * `NoteLine` → a `user` message `"[Note: <text>]"`.
    * Consecutive `user` messages (from the two rules above) are merged into one, their
      texts joined with `prompt.CONTEXT_SEPARATOR`. So the opening context and the first
      request become one message, and notes written between turns arrive at the front of
      the next request.
    * `AssistantLine` → an `assistant` message with its text and its tool calls (as v2
      `ToolCall`s, same id, name and arguments); an assistant line with blank text and no
      tool calls is skipped (providers reject empty assistant messages).
    * `ToolLine` → a `tool` message (`content=text`, `tool_call_id`), and
      `summaries[tool_call_id] = summary`.
    * `TurnEndLine` → nothing.

    Before a non-tool line (and at the end), every tool call of the latest assistant
    message that has no `tool` message yet gets one with content `INTERRUPTED_RESULT`
    (summary `"<name>: interrupted"`), in call order. Pure.
    """
    messages: list[Message] = []
    summaries: dict[str, str] = {}
    pending: list[ToolCall] = []

    def flush() -> None:
        for call in pending:
            messages.append(Message("tool", INTERRUPTED_RESULT, tool_call_id=call.id))
            summaries[call.id] = f"{call.name}: interrupted"
        pending.clear()

    def add_user(text: str) -> None:
        if messages and messages[-1].role == "user":
            last = messages[-1]
            messages[-1] = Message("user", last.content + CONTEXT_SEPARATOR + text)
        else:
            messages.append(Message("user", text))

    folded: list[ThreadLine] = []

    def flush_folded() -> None:
        if folded:
            text = fold_mechanic_lines(folded)
            if text is not None:
                messages.append(Message("assistant", text))
            folded.clear()

    for line in lines:
        if isinstance(line, AssistantLine | ToolLine) and line.role != role:
            flush()
            folded.append(line)
            continue
        flush_folded()
        if isinstance(line, ToolLine):
            pending[:] = [c for c in pending if c.id != line.tool_call_id]
            messages.append(Message("tool", line.text, tool_call_id=line.tool_call_id))
            summaries[line.tool_call_id] = line.summary
            continue
        flush()
        if isinstance(line, UserLine):
            add_user(line.text)
        elif isinstance(line, NoteLine):
            add_user(f"{NOTE_PREFIX}{line.text}{NOTE_SUFFIX}")
        elif isinstance(line, AssistantLine):
            if not line.text.strip() and not line.tool_calls:
                continue
            calls = [
                ToolCall(id=c.id, name=c.name, arguments=c.arguments) for c in line.tool_calls
            ]
            messages.append(Message("assistant", line.text, list(calls)))
            pending.extend(calls)
    flush_folded()
    flush()
    return messages, summaries


def run_steps(
    model: BoundModel,
    *,
    system: str,
    messages: list[Message],
    summaries: dict[str, str],
    toolbox: ToolBox,
    ledger: TurnLedger,
    sink: TurnSink,
    thread_id: str,
    turn_id: str,
    limits: LoopLimits = LoopLimits(),  # noqa: B008 - frozen
    stop_when: Callable[[], bool] | None = None,
) -> LoopOutcome:
    """Run model calls until the model replies or a cap stops the turn.

    `messages` (already ending with this turn's user message) and `summaries` are mutated:
    each assistant message and tool result is appended as it happens.

    Each iteration:

    1. If `steps >= limits.max_steps` return `step_cap`; if the input tokens counted so
       far are `>= limits.max_input_tokens` return `token_cap`.
    2. `turn = model.model.converse(compact(messages, summaries,
       limits.keep_recent_results), toolbox.specs, system=system)` (v2's `compact`).
    3. Count the step and tokens. Append `Message("assistant", turn.text,
       list(turn.tool_calls))`; `sink.assistant(...)`; if `turn.text.strip()`:
       `sink.event(AssistantText(thread_id, turn_id, step, text, model.model_id))` and
       remember it as the final text.
    4. No tool calls: with non-blank text, return `replied`. With blank text: the first
       time, append `Message("user", STALL_NUDGE)` (not reported to the sink) and continue;
       the second time in a row, return `stalled`.
    5. Otherwise, for each call in order: `sink.event(ToolCalled(...))`; `mark =
       ledger.mark()`; `result = toolbox.dispatch(call)`; `summaries[call.id] =
       result.summary`; append `Message("tool", result.text, tool_call_id=call.id)`;
       `sink.tool(step=..., call=..., result=...)`; `sink.event(ToolFinished(...,
       summary=result.summary, error=result.error))`; then for each item in
       `ledger.since(mark)`, in order, one event: `change` → `ChangeRecorded` (lines =
       first `MAX_DIFF_LINES` of `diff.describe(entry.diff)`, `truncated` accordingly,
       `instruction`/`layer`/`model_id` from the entry), `undo`/`redo` →
       `ChangeReverted(by="model")`, `created` → `ArtifactCreated`, `proposal` →
       `ProposalCreated`.

    6. Phase 2-3: after all of an iteration's tool calls, if `stop_when` is given and
       returns True (the mechanic called `hand_to_lead`), return `handed_off`.

    Ledger `composed` items become `SlideComposed` events (step 5).

    Exceptions from the model or a tool propagate (after whatever was already reported).
    """
    steps = 0
    input_tokens = 0
    output_tokens = 0
    final_text = ""
    nudged = False

    def outcome(reason: StopReason) -> LoopOutcome:
        return LoopOutcome(reason, steps, input_tokens, output_tokens, final_text)

    while True:
        if steps >= limits.max_steps:
            return outcome("step_cap")
        if input_tokens >= limits.max_input_tokens:
            return outcome("token_cap")
        turn = model.model.converse(
            compact(messages, summaries, limits.keep_recent_results),
            toolbox.specs,
            system=system,
        )
        steps += 1
        input_tokens += turn.usage.input_tokens
        output_tokens += turn.usage.output_tokens
        messages.append(Message("assistant", turn.text, list(turn.tool_calls)))
        sink.assistant(
            step=steps,
            text=turn.text,
            tool_calls=list(turn.tool_calls),
            input_tokens=turn.usage.input_tokens,
            output_tokens=turn.usage.output_tokens,
        )
        if turn.text.strip():
            sink.event(
                AssistantText(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    step=steps,
                    text=turn.text,
                    model_id=model.model_id,
                )
            )
            final_text = turn.text
        if not turn.tool_calls:
            if turn.text.strip():
                return outcome("replied")
            if nudged:
                return outcome("stalled")
            nudged = True
            messages.append(Message("user", STALL_NUDGE))
            continue
        nudged = False
        for call in turn.tool_calls:
            sink.event(
                ToolCalled(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    step=steps,
                    call_id=call.id,
                    name=call.name,
                )
            )
            mark = ledger.mark()
            result = toolbox.dispatch(call)
            summaries[call.id] = result.summary
            messages.append(Message("tool", result.text, tool_call_id=call.id))
            sink.tool(step=steps, call=call, result=result)
            sink.event(
                ToolFinished(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    step=steps,
                    call_id=call.id,
                    name=call.name,
                    summary=result.summary,
                    error=result.error,
                )
            )
            for kind, artifact_id, item in ledger.since(mark):
                event = _ledger_event(kind, artifact_id, item, thread_id, turn_id)
                if event is not None:
                    sink.event(event)
        if stop_when is not None and stop_when():
            return outcome("handed_off")


def _ledger_event(
    kind: str, artifact_id: str, item: object, thread_id: str, turn_id: str
) -> TurnEvent | None:
    if kind == "change":
        assert isinstance(item, ChangeEntry)
        described = diff.describe(item.diff)
        return ChangeRecorded(
            thread_id=thread_id,
            turn_id=turn_id,
            artifact_id=artifact_id,
            entry_id=item.id,
            instruction=item.instruction,
            layer=item.layer,
            model_id=item.model_id,
            lines=described[:MAX_DIFF_LINES],
            truncated=len(described) > MAX_DIFF_LINES,
        )
    if kind in ("undo", "redo"):
        assert isinstance(item, ChangeEntry)
        return ChangeReverted(
            thread_id=thread_id,
            turn_id=turn_id,
            artifact_id=artifact_id,
            entry_id=item.id,
            action="undo" if kind == "undo" else "redo",
            by="model",
        )
    if kind == "created":
        return ArtifactCreated(thread_id=thread_id, turn_id=turn_id, artifact_id=artifact_id)
    if kind == "composed":
        assert isinstance(item, ComposedSlide)
        return SlideComposed(
            thread_id=thread_id,
            turn_id=turn_id,
            artifact_id=artifact_id,
            slide_id=item.slide_id,
            clean=item.clean,
            attempts=item.attempts,
            findings=list(item.findings),
            model_id=item.model_id,
            seconds=round(item.seconds, 2),
        )
    if kind == "proposal":
        return ProposalCreated(
            thread_id=thread_id,
            turn_id=turn_id,
            proposal_id=item.id,  # type: ignore[attr-defined]
            artifact_id=item.artifact_id,  # type: ignore[attr-defined]
            summary=item.summary,  # type: ignore[attr-defined]
            option_ids=[o.id for o in item.options],  # type: ignore[attr-defined]
        )
    return None
