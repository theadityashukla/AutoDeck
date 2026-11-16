"""The deck agent's loop (B71): the model calls tools until it calls `finish` or a cap hits.

The loop owns no deck logic. It sends the conversation to a tool-calling model, runs each
requested tool through the `ToolBox`, and appends the results. What keeps it affordable and
resumable:

* **Compaction is a pure function of the messages.** Older tool results are replaced by their
  one-line summaries. Because the same history always compacts to the same text, a resumed
  session sends byte-identical requests and the provider's response cache serves every turn
  it already paid for.
* **The transcript is append-only JSONL.** Each message is written as it happens, with its
  summary and token counts; wall-clock timestamps live only in `meta`, never in anything sent
  to the model. `TranscriptLog.load` rebuilds the state exactly.
* **Every stop has a reason.** Step cap, token cap, a model that will not call tools
  ("stalled"), or `finish`. The caller decides what each means; the loop never loops forever.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from autodeck.agents.tools.registry import ToolBox
from autodeck.providers.base import AssistantTurn, Message, ToolCall, ToolSpec

NUDGE = (
    "You replied without calling a tool. Work only through the tools. "
    "When the deck is done, call finish."
)

StopReason = Literal["finished", "step_cap", "token_cap", "stalled"]


class ConverseModel(Protocol):
    def converse(
        self, messages: list[Message], tools: list[ToolSpec], *, system: str | None = None
    ) -> AssistantTurn: ...


@dataclass(frozen=True)
class SessionLimits:
    max_steps: int = 40
    """Model turns per `run_session` call."""
    max_input_tokens: int = 1_500_000
    """Cumulative reported input tokens per call."""
    keep_recent_results: int = 8
    """Tool results kept verbatim; older ones are compacted."""


@dataclass
class SessionState:
    messages: list[Message]
    summaries: dict[str, str] = field(default_factory=dict)
    """tool_call_id -> one-line summary."""
    steps: int = 0
    """Total model turns across all runs."""
    provider_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: StopReason | None = None


def compact(
    messages: Sequence[Message], summaries: Mapping[str, str], keep_recent: int
) -> list[Message]:
    """Shorten all but the last `keep_recent` tool results to their summaries. Pure."""
    tool_at = [i for i, m in enumerate(messages) if m.role == "tool"]
    old = set(tool_at[: max(0, len(tool_at) - max(0, keep_recent))])
    out: list[Message] = []
    for i, message in enumerate(messages):
        if i in old:
            summary = summaries.get(message.tool_call_id or "", "(no summary)")
            out.append(replace(message, content="[earlier result, shortened] " + summary))
        else:
            out.append(message)
    return out


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


def _message_json(message: Message) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "tool_calls": [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in message.tool_calls
        ],
        "tool_call_id": message.tool_call_id,
    }


def _message_from_json(data: Mapping[str, Any]) -> Message:
    return Message(
        role=data["role"],
        content=data["content"],
        tool_calls=[
            ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"])
            for c in data["tool_calls"]
        ],
        tool_call_id=data["tool_call_id"],
    )


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TranscriptLog:
    """Append-only JSONL: one record per message."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(
        self,
        message: Message,
        *,
        summary: str | None = None,
        step: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: bool = False,
    ) -> None:
        record = {
            "message": _message_json(message),
            "summary": summary,
            "step": step,
            "meta": {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "error": error,
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def load(path: Path) -> SessionState:
        state = SessionState(messages=[])
        for record in _records(path):
            message = _message_from_json(record["message"])
            state.messages.append(message)
            if (
                message.role == "tool"
                and message.tool_call_id
                and record["summary"] is not None
            ):
                state.summaries[message.tool_call_id] = record["summary"]
            state.steps = max(state.steps, int(record["step"]))
            if message.role == "assistant":
                state.provider_calls += 1
            state.input_tokens += int(record["meta"]["input_tokens"])
            state.output_tokens += int(record["meta"]["output_tokens"])
        return state


def timeline(path: Path) -> list[dict[str, Any]]:
    """The transcript as UI rows: step, role, tool, summary, error."""
    names: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for record in _records(path):
        message = _message_from_json(record["message"])
        for call in message.tool_calls:
            names[call.id] = call.name
        rows.append(
            {
                "step": record["step"],
                "role": message.role,
                "tool": _tool_label(message, names),
                "summary": record["summary"] or _assistant_summary(message),
                "error": bool(record["meta"].get("error"))
                or (message.role == "tool" and message.content.startswith("ERROR: ")),
            }
        )
    return rows


def _tool_label(message: Message, names: Mapping[str, str]) -> str | None:
    if message.role == "tool":
        return names.get(message.tool_call_id or "")
    if message.tool_calls:
        return message.tool_calls[0].name
    return None


def _assistant_summary(message: Message) -> str:
    if message.tool_calls:
        return "calls " + ", ".join(c.name for c in message.tool_calls)
    return " ".join(message.content.split())[:100]


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def run_session(
    model: ConverseModel,
    *,
    system: str,
    state: SessionState,
    toolbox: ToolBox,
    limits: SessionLimits = SessionLimits(),  # noqa: B008 - frozen
    log: TranscriptLog | None = None,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> SessionState:
    """Run model turns until it finishes or a cap stops it. Mutates and returns `state`."""
    state.stop_reason = None
    steps_this_run = 0
    input_this_run = 0
    nudged = False
    names: dict[str, str] = {}

    def record(
        message: Message,
        summary: str | None,
        *,
        error: bool = False,
        usage: tuple[int, int] = (0, 0),
    ) -> None:
        state.messages.append(message)
        if log is not None:
            log.append(
                message,
                summary=summary,
                step=state.steps,
                input_tokens=usage[0],
                output_tokens=usage[1],
                error=error,
            )
        if on_step is not None:
            on_step(
                {
                    "step": state.steps,
                    "role": message.role,
                    "tool": _tool_label(message, names),
                    "summary": summary or _assistant_summary(message),
                    "error": error,
                    "input_tokens": usage[0],
                    "output_tokens": usage[1],
                }
            )

    while True:
        if steps_this_run >= limits.max_steps:
            state.stop_reason = "step_cap"
            return state
        if input_this_run >= limits.max_input_tokens:
            state.stop_reason = "token_cap"
            return state
        turn = model.converse(
            compact(state.messages, state.summaries, limits.keep_recent_results),
            toolbox.specs,
            system=system,
        )
        steps_this_run += 1
        state.steps += 1
        state.provider_calls += 1
        used = (turn.usage.input_tokens, turn.usage.output_tokens)
        input_this_run += used[0]
        state.input_tokens += used[0]
        state.output_tokens += used[1]
        for call in turn.tool_calls:
            names[call.id] = call.name
        record(
            Message(role="assistant", content=turn.text, tool_calls=list(turn.tool_calls)),
            None,
            usage=used,
        )
        if not turn.tool_calls:
            if nudged:
                state.stop_reason = "stalled"
                return state
            nudged = True
            record(Message(role="user", content=NUDGE), "nudge: call a tool")
            continue
        nudged = False
        finished = False
        for call in turn.tool_calls:
            result = toolbox.dispatch(call)
            state.summaries[call.id] = result.summary
            record(
                Message(role="tool", content=result.text, tool_call_id=call.id),
                result.summary,
                error=result.error,
            )
            finished = finished or result.finished
        if finished:
            state.stop_reason = "finished"
            return state
