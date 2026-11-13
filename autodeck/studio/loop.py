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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from autodeck.agents.tools.registry import ToolBox, ToolResult
from autodeck.providers.base import Message, ToolCall
from autodeck.studio.bindings import BoundModel
from autodeck.studio.conversation import StopReason, ThreadLine, TurnEvent
from autodeck.studio.tools import TurnLedger

STALL_NUDGE = "You returned neither a reply nor a tool call. Reply to the owner in words."
"""Sent once, unrecorded, when a model call returns no text and no tool call."""

INTERRUPTED_RESULT = "ERROR: this call was interrupted before it ran."
"""The tool result `build_model_messages` supplies for a logged call with no logged result
(a turn that crashed between the call and its result)."""

NOTE_PREFIX = "[Note: "
NOTE_SUFFIX = "]"


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


def build_model_messages(lines: Sequence[ThreadLine]) -> tuple[list[Message], dict[str, str]]:
    """A thread's log as provider messages, plus the tool summaries for compaction.

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
    raise NotImplementedError


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

    Exceptions from the model or a tool propagate (after whatever was already reported).
    """
    raise NotImplementedError
