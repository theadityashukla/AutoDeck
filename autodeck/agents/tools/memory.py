"""Memory tools (B77): the agent reads and writes engagement and owner memory."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from autodeck.agents.tools.registry import Tool, ToolError, ToolResult
from autodeck.knowledge.memory import (
    ENGAGEMENT_SECTIONS,
    OWNER_SECTIONS,
    MemoryStore,
    MemoryWriteError,
)

Scope = Literal["engagement", "owner"]
Section = Literal[
    "Terms",
    "People",
    "Open actions",
    "Decisions",
    "Deck preferences",
    "Note style",
    "Deck habits",
]


class RememberArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Scope = Field(
        description="engagement: this client and project. owner: how the person you work "
        "for likes to work, across every client (never a client fact)."
    )
    section: Section = Field(
        description=f"engagement: {', '.join(ENGAGEMENT_SECTIONS)}. "
        f"owner: {', '.join(OWNER_SECTIONS)}."
    )
    text: str = Field(
        min_length=1,
        description="One short line, e.g. 'APLD — anonymised patient-level data; heard as "
        "\"aplb\"' or 'Shikha — runs the FIA walkthrough'.",
    )
    replaces: str = Field(
        description="An existing item this corrects or updates (quote it), or '' to add."
    )


class ForgetArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Scope
    section: Section
    item: str = Field(min_length=1, description="The item to drop, quoted.")


class ReadMemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Scope


class ReviseMemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Scope
    content: str = Field(
        min_length=1,
        description="The whole file, shorter: '## Section' headings and '- item' bullets.",
    )


def memory_tools(store: MemoryStore) -> list[Tool]:
    def _guarded(action) -> ToolResult:  # type: ignore[no-untyped-def]
        try:
            text = action()
        except MemoryWriteError as exc:
            raise ToolError(str(exc)) from exc
        return ToolResult(text, text[:100])

    def remember(args: RememberArgs) -> ToolResult:
        if args.replaces.strip():
            return _guarded(
                lambda: store.replace(args.scope, args.section, args.replaces, args.text)
            )
        return _guarded(lambda: store.add(args.scope, args.section, args.text))

    def forget(args: ForgetArgs) -> ToolResult:
        return _guarded(lambda: store.remove(args.scope, args.section, args.item))

    def read_memory(args: ReadMemoryArgs) -> ToolResult:
        text = store.read(args.scope)
        return ToolResult(text, f"read {args.scope} memory ({len(text)} chars)")

    def revise_memory(args: ReviseMemoryArgs) -> ToolResult:
        return _guarded(lambda: store.rewrite(args.scope, args.content))

    return [
        Tool(
            "remember",
            "Remember one durable thing for future runs: a term, a person and their role, an "
            "open action, a decision, a deck preference (engagement), or how the person you "
            "work for likes to work (owner). Memory is context, never a source to cite.",
            RememberArgs,
            remember,
        ),
        Tool("forget", "Drop a memory item that is wrong or settled.", ForgetArgs, forget),
        Tool(
            "read_memory", "Read a memory file as it stands now.", ReadMemoryArgs, read_memory
        ),
        Tool(
            "revise_memory",
            "Rewrite a whole memory file shorter when it is full: merge, drop what is settled.",
            ReviseMemoryArgs,
            revise_memory,
        ),
    ]
