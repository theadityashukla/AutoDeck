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
  "model_ids": {"designer": "scripted/designer"},
  "description": "What the walk-through does.",
  "steps": [
    {"label": "thread 1, turn 1: read the sources",
     "text": "",
     "tool_calls": [{"name": "list_sources", "arguments": {}}]},
    {"label": "designer: slide s2", "role": "designer", "match": "Slide id: s2",
     "tool_calls": [{"name": "write_slide", "arguments": {"slide": {}}}]},
    {"label": "thread 1, turn 1: reply", "text": "I have drafted three slides."}
  ]
}
```

A step must have text or at least one tool call. A step with tool calls continues the
turn; a step with text and no tool calls ends it (the loop's normal end of a turn).

**Roles (Phase 2-3).** A step may name the `role` that plays it (`lead`, the default;
`system`, `designer`, `mechanic`, `router`). Each role has its own queue: a call made
through `for_role(r)` is answered with the first not-yet-played step whose role is `r` and
whose `match` (when set) is a substring of what the call was sent (the system prompt and
every message's content, joined by newlines). So the steps of different roles may be
interleaved in the file in reading order, and the designer's parallel calls are answered
deterministically by matching each on its slide (`"match": "Slide id: s2"`) or its
direction (`"match": "Name: Shelf price"`). A role with no step left is answered with
`EXHAUSTED_TEXT` and counted in `overrun` and `overrun_by_role`. Each role reports the
model id `model_ids[role]` when given, else the script's `model_id` for `lead` and
`"<model_id>-<role>"` for the others.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from autodeck.providers.base import AssistantTurn, Message, ToolCall, ToolSpec, Usage
from autodeck.studio.bindings import STUDIO_ROLES, BoundModel, StudioBindings

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


ScriptRole = Literal["lead", "system", "designer", "mechanic", "router"]


class ScriptStep(_ScriptModel):
    label: str = ""
    role: ScriptRole = "lead"
    match: str | None = Field(
        default=None,
        min_length=1,
        description="Play this step only for a call whose input contains this text.",
    )
    text: str = ""
    tool_calls: list[ScriptToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def _does_something(self) -> ScriptStep:
        if not self.text.strip() and not self.tool_calls:
            raise ValueError(f"step {self.label!r} has neither text nor a tool call")
        return self


class Script(_ScriptModel):
    model_id: str = Field(default=DEFAULT_MODEL_ID, min_length=1)
    model_ids: dict[ScriptRole, str] = Field(default_factory=dict)
    description: str = ""
    steps: list[ScriptStep] = Field(min_length=1)

    def model_id_for(self, role: str) -> str:
        """`model_ids[role]` when given; else `model_id` for `lead` and
        `"<model_id>-<role>"` for any other role."""
        if role in self.model_ids:
            return self.model_ids[role]  # type: ignore[index]
        return self.model_id if role == "lead" else f"{self.model_id}-{role}"


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
    role: str = "lead"
    """The role the call was made as (Phase 2-3)."""
    step_label: str | None = None
    """The label of the step that answered it, or None when the role had run out."""

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
    """Plays a `Script` back, one step per `converse` call, by role. Thread-safe."""

    script: Script
    calls: list[ScriptedCall] = field(default_factory=list)
    """Every call received, in order, whatever its role."""
    overrun: int = 0
    """Calls made after their role's steps ran out (each answered with `EXHAUSTED_TEXT`)."""
    overrun_by_role: dict[str, int] = field(default_factory=dict)
    _played: set[int] = field(default_factory=set, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_steps(
        cls,
        steps: list[dict[str, Any]],
        *,
        model_id: str = DEFAULT_MODEL_ID,
        model_ids: dict[str, str] | None = None,
    ) -> ScriptedModel:
        """Build from step dicts (the `steps` list of a script), for tests."""
        return cls(
            Script.model_validate(
                {"model_id": model_id, "model_ids": model_ids or {}, "steps": steps}
            )
        )

    @classmethod
    def from_file(cls, path: Path) -> ScriptedModel:
        return cls(load_script(path))

    @property
    def model_id(self) -> str:
        """The lead's model id."""
        return self.script.model_id

    @property
    def remaining(self) -> int:
        """Steps not yet played, all roles."""
        with self._lock:
            return len(self.script.steps) - len(self._played)

    def remaining_for(self, role: str) -> int:
        """Steps of `role` not yet played."""
        with self._lock:
            return sum(
                1
                for i, step in enumerate(self.script.steps)
                if step.role == role and i not in self._played
            )

    def calls_for(self, role: str) -> list[ScriptedCall]:
        """The calls made as `role`, in order."""
        with self._lock:
            return [c for c in self.calls if c.role == role]

    def for_role(self, role: str) -> ScriptedRoleModel:
        """A `ConverseModel` view that answers as `role` from this script."""
        return ScriptedRoleModel(self, role)

    def converse(
        self, messages: list[Message], tools: list[ToolSpec], *, system: str | None = None
    ) -> AssistantTurn:
        """As the lead: `converse_as("lead", ...)`."""
        return self.converse_as("lead", messages, tools, system=system)

    def converse_as(
        self,
        role: str,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: str | None = None,
    ) -> AssistantTurn:
        """Record the call and return the role's next matching step as an `AssistantTurn`.

        Tool call ids are the step's own, or `call-<step number, 3 digits>-<index>` (step
        numbers count from 1 across the whole script, whatever the role). Usage is
        deterministic: input tokens are the total characters of every message's content
        divided by 4, output tokens the step's text length divided by 4.
        """
        if not messages:
            raise ValueError("converse() needs at least one message")
        haystack = "\n".join([system or "", *(m.content for m in messages)])
        sent = sum(len(m.content) for m in messages) // 4
        with self._lock:
            index = next(
                (
                    i
                    for i, step in enumerate(self.script.steps)
                    if i not in self._played
                    and step.role == role
                    and (step.match is None or step.match in haystack)
                ),
                None,
            )
            label = None if index is None else self.script.steps[index].label
            self.calls.append(
                ScriptedCall(list(messages), [t.name for t in tools], system, role, label)
            )
            if index is None:
                self.overrun += 1
                self.overrun_by_role[role] = self.overrun_by_role.get(role, 0) + 1
                return AssistantTurn(
                    text=EXHAUSTED_TEXT, usage=Usage(sent, len(EXHAUSTED_TEXT) // 4)
                )
            self._played.add(index)
            step = self.script.steps[index]
        calls = [
            ToolCall(
                id=c.id or f"call-{index + 1:03d}-{i}", name=c.name, arguments=dict(c.arguments)
            )
            for i, c in enumerate(step.tool_calls)
        ]
        return AssistantTurn(
            text=step.text, tool_calls=calls, usage=Usage(sent, len(step.text) // 4)
        )


@dataclass(frozen=True)
class ScriptedRoleModel:
    """One role's view of a `ScriptedModel`."""

    script_model: ScriptedModel
    role: str

    def converse(
        self, messages: list[Message], tools: list[ToolSpec], *, system: str | None = None
    ) -> AssistantTurn:
        return self.script_model.converse_as(self.role, messages, tools, system=system)


def scripted_binding(model: ScriptedModel) -> BoundModel:
    """The `BoundModel` for a scripted session's lead: role `lead`, the script's
    `model_id`, environment `"scripted"`, and the `ScriptedModel` itself as the model."""
    return BoundModel(role="lead", model_id=model.model_id, model=model, env="scripted")


def scripted_bindings(model: ScriptedModel) -> StudioBindings:
    """Every role bound to the script (Phase 2-3): the lead as `scripted_binding`, each
    other role as `BoundModel(role, script.model_id_for(role), model.for_role(role),
    "scripted")`."""
    bound = {
        role: BoundModel(
            role=role,
            model_id=model.script.model_id_for(role),
            model=model.for_role(role),
            env="scripted",
        )
        for role in STUDIO_ROLES
        if role != "lead"
    }
    return StudioBindings(lead=scripted_binding(model), **bound)
