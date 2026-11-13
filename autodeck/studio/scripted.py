"""A scripted stand-in model: plays back a prepared sequence of model turns (Phase 1).

There are no provider keys in the build environment, and the loop must be testable end to
end anyway. `ScriptedModel` implements the same `converse` signature as v2's providers and
returns, call by call, the steps of a script: each step is the text and tool calls one
model call would have produced. It ignores what it is sent, except to record it, so a test
can assert exactly what the model was given (for example, that a returning thread's
context contains nothing from an earlier thread's messages).

The server can be started on a script (`python -m autodeck.studio --script PATH`, or the
`AUTODECK_STUDIO_SCRIPT` environment variable), so the real interface can be driven in a
browser without a key. One script serves the whole process: its steps are consumed in
order across every thread, so a script is written for one walk-through.

A script is JSON:

```json
{
  "model_id": "scripted/two-threads",
  "description": "What the walk-through does.",
  "steps": [
    {"label": "thread 1, turn 1: read the sources",
     "text": "",
     "tool_calls": [{"name": "list_sources", "arguments": {}}]},
    {"label": "thread 1, turn 1: reply", "text": "I have drafted three slides."}
  ]
}
```

A step must have text or at least one tool call. A step with tool calls continues the
turn; a step with text and no tool calls ends it (the loop's normal end of a turn).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autodeck.providers.base import AssistantTurn, Message, ToolCall, ToolSpec, Usage
from autodeck.studio.bindings import BoundModel

SCRIPT_ENV_VAR = "AUTODECK_STUDIO_SCRIPT"
"""Names a script file; when set (or `--script` is given) the server uses `ScriptedModel`."""

EXHAUSTED_TEXT = (
    "The script for this scripted session has no more steps. Restart the server with a "
    "script to continue."
)
"""What the model replies once every step has been played. Counted in `overrun`."""

DEFAULT_MODEL_ID = "scripted"


class _ScriptModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScriptToolCall(_ScriptModel):
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    id: str | None = Field(default=None, description="Defaults to call-<step>-<index>.")


class ScriptStep(_ScriptModel):
    label: str = ""
    text: str = ""
    tool_calls: list[ScriptToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def _does_something(self) -> ScriptStep:
        if not self.text.strip() and not self.tool_calls:
            raise ValueError(f"step {self.label!r} has neither text nor a tool call")
        return self


class Script(_ScriptModel):
    model_id: str = Field(default=DEFAULT_MODEL_ID, min_length=1)
    description: str = ""
    steps: list[ScriptStep] = Field(min_length=1)


def load_script(path: Path) -> Script:
    """Parse and validate a script file (UTF-8 JSON).

    Raises:
        FileNotFoundError: no such file.
        pydantic.ValidationError: not JSON, or not a valid `Script`.
    """
    return Script.model_validate_json(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ScriptedCall:
    """What one `converse` call was given, copied so later mutation cannot change it."""

    messages: list[Message]
    tool_names: list[str]
    system: str | None

    def text(self) -> str:
        """Every message's content and every tool call's arguments, joined by newlines:
        everything the model was sent apart from the system prompt and tool schemas."""
        parts: list[str] = []
        for message in self.messages:
            parts.append(message.content)
            parts.extend(
                json.dumps(c.arguments, ensure_ascii=False) for c in message.tool_calls
            )
        return "\n".join(parts)


@dataclass
class ScriptedModel:
    """Plays a `Script` back, one step per `converse` call. Thread-safe."""

    script: Script
    calls: list[ScriptedCall] = field(default_factory=list)
    """Every call received, in order."""
    overrun: int = 0
    """Calls made after the script ran out (each answered with `EXHAUSTED_TEXT`)."""
    _next: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_steps(
        cls, steps: list[dict[str, Any]], *, model_id: str = DEFAULT_MODEL_ID
    ) -> ScriptedModel:
        """Build from step dicts (the `steps` list of a script), for tests."""
        return cls(Script.model_validate({"model_id": model_id, "steps": steps}))

    @classmethod
    def from_file(cls, path: Path) -> ScriptedModel:
        return cls(load_script(path))

    @property
    def model_id(self) -> str:
        return self.script.model_id

    @property
    def remaining(self) -> int:
        """Steps not yet played."""
        with self._lock:
            return len(self.script.steps) - self._next

    def converse(
        self, messages: list[Message], tools: list[ToolSpec], *, system: str | None = None
    ) -> AssistantTurn:
        """Record the call and return the next step as an `AssistantTurn`.

        Tool call ids are the step's own, or `call-<step number, 3 digits>-<index>`
        (step numbers count from 1 across the whole script). Usage is deterministic: input
        tokens are the total characters of every message's content divided by 4, output
        tokens the step's text length divided by 4.
        """
        if not messages:
            raise ValueError("converse() needs at least one message")
        with self._lock:
            self.calls.append(ScriptedCall(list(messages), [t.name for t in tools], system))
            sent = sum(len(m.content) for m in messages) // 4
            if self._next >= len(self.script.steps):
                self.overrun += 1
                return AssistantTurn(
                    text=EXHAUSTED_TEXT, usage=Usage(sent, len(EXHAUSTED_TEXT) // 4)
                )
            index = self._next
            step = self.script.steps[index]
            self._next += 1
        calls = [
            ToolCall(
                id=c.id or f"call-{index + 1:03d}-{i}", name=c.name, arguments=dict(c.arguments)
            )
            for i, c in enumerate(step.tool_calls)
        ]
        return AssistantTurn(
            text=step.text, tool_calls=calls, usage=Usage(sent, len(step.text) // 4)
        )


def scripted_binding(model: ScriptedModel) -> BoundModel:
    """The `BoundModel` for a scripted session: role `lead`, the script's `model_id`,
    environment `"scripted"`."""
    return BoundModel(role="lead", model_id=model.model_id, model=model, env="scripted")
