"""The toolbox: validates a model's tool call, runs it, and turns every failure into feedback.

A small model calls tools badly — invalid JSON, a wrong field, the same call five times in a
row. None of that may crash a session or silently loop. `ToolBox.dispatch` therefore never
raises for a model's mistake: it returns an error *result* the model can read and correct.
Only a bug in a tool (an unexpected exception) propagates.

The repeat guard keys on the call plus `state_key()` (the workspace revision). The same check
after an edit is a new call; the same call with nothing changed in between is a loop.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from autodeck.agents.compose import ComposeError
from autodeck.agents.workspace import WorkspaceError
from autodeck.providers.base import ToolCall, ToolSpec


@dataclass(frozen=True)
class ToolResult:
    text: str
    """What the model sees."""
    summary: str
    """One line for the UI timeline and for compaction. Never passage text beyond ~100 chars."""
    finished: bool = False
    error: bool = False


class ToolError(ValueError):
    """A tool refused: the message goes back to the model as an error result."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[Any], ToolResult]
    """Receives the validated args model instance."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name, description=self.description, args_model=self.args_model
        )


def error_result(text: str, summary: str) -> ToolResult:
    return ToolResult(text=f"ERROR: {text}", summary=summary, error=True)


def _validation_text(exc: ValidationError) -> str:
    lines = []
    for item in exc.errors()[:8]:
        loc = ".".join(str(p) for p in item["loc"]) or "(arguments)"
        lines.append(f"{loc}: {item['msg']}")
    return "; ".join(lines)


class ToolBox:
    def __init__(
        self,
        tools: Sequence[Tool],
        *,
        state_key: Callable[[], object] = lambda: None,
        max_repeats: int = 2,
    ) -> None:
        names = [t.name for t in tools]
        if len(set(names)) != len(names):
            raise ValueError(
                f"duplicate tool names: {sorted({n for n in names if names.count(n) > 1})}"
            )
        self._tools = {t.name: t for t in tools}
        self.specs: list[ToolSpec] = [t.spec for t in tools]
        self._state_key = state_key
        self._max_repeats = max_repeats
        self._seen: dict[tuple[str, str, object], int] = {}

    def dispatch(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return error_result(
                f"there is no tool {call.name!r}. Available: {', '.join(self._tools)}.",
                f"{call.name}: unknown tool",
            )
        if "__invalid__" in call.arguments:
            raw = str(call.arguments["__invalid__"])[:200]
            return error_result(
                f"your arguments were not valid JSON: {raw}", f"{call.name}: invalid arguments"
            )
        try:
            args = tool.args_model.model_validate(call.arguments)
        except ValidationError as exc:
            return error_result(
                f"the arguments for {call.name} are invalid: {_validation_text(exc)}",
                f"{call.name}: invalid arguments",
            )
        key = (
            call.name,
            json.dumps(call.arguments, sort_keys=True, default=str),
            self._state_key(),
        )
        count = self._seen.get(key, 0)
        if count >= self._max_repeats:
            return error_result(
                f"you already ran {call.name} with these exact arguments and nothing has "
                "changed since. Do something different.",
                f"{call.name}: repeated call refused",
            )
        self._seen[key] = count + 1
        try:
            return tool.run(args)
        except (ToolError, WorkspaceError, ComposeError) as exc:
            return error_result(str(exc), f"{call.name}: refused")
