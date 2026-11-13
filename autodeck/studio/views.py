"""Pure views of studio state: the compact text the model reads, and the JSON the
interface reads (Phase 1).

Two audiences, one module, so the deck the model is told about and the deck the owner
sees are described from the same functions:

* **Text for the model.** `deck_outline` is the compact view of a deck used both in a
  thread's opening context (`context.render_context`) and by the `view_deck` tool.
  `change_line` is one change-log entry on one line. Their formats are exact, because the
  context builder is tested byte for byte.
* **JSON for the interface.** The `*_view` functions turn records into plain dicts (only
  `str`, `int`, `float`, `bool`, `None`, lists and dicts), the shapes documented in the
  API section of docs/phases/V3-PHASE-1.md.

Everything here is a pure function of its arguments: no file is read, nothing is mutated.

Shared text rules: `flat(s)` collapses every run of whitespace (newlines included) to one
space and strips the ends; `clip(s, n)` returns `s` when `len(s) <= n`, else
`s[: n - 1] + "…"`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from autodeck.studio.conversation import (
    ProposalRecord,
    RenderManifest,
    ThreadLine,
    ThreadRecord,
)
from autodeck.studio.models import (
    ChangeEntry,
    ChangeLog,
    DeckArtifact,
    EngagementRecord,
    OptionId,
)

MAX_BLOCK_TEXT = 80
"""`deck_outline` clips each text block to this many characters."""

PREVIEW_CHARS = 80
"""`thread_summary.preview` clips the first owner message to this many characters."""


def flat(text: str) -> str:
    """Every run of whitespace collapsed to one space; ends stripped."""
    raise NotImplementedError


def clip(text: str, limit: int) -> str:
    """`text` if it has at most `limit` characters, else its first `limit - 1` characters
    followed by `…` (U+2026). `limit` is at least 1."""
    raise NotImplementedError


def deck_outline(deck: DeckArtifact, *, max_text: int = MAX_BLOCK_TEXT) -> str:
    """The compact view of a deck, lines joined by `\\n`, no trailing newline.

    Exactly these lines, in this order (`<m>` is a marker; every free text is `flat`):

    1. ``Deck `<id>`: <title, or (untitled) when blank> (<n> slide|slides)`` (singular
       only for n == 1).
    2. `Brief: none`, or `Brief [<m>]: audience: <a> | goal: <g> | notes: <n>` where an
       empty field shows as `-`.
    3. `Storyline [<m>]: none` when it has no points; otherwise `Storyline [<m>]:` followed
       by one line per point: `  <point id>. <text>`.
    4. `Design concept: none`, or `Design concept [<m>]: <text>`.
    5. `Design system: none`, or `Design system [<m>]: <id> v<version>`.
    6. `Slides: none` when there are none; otherwise `Slides:` followed, per slide i
       (1-based), by two lines:
       `  <i>. <slide id> [<m>] serves <ids joined by ", ", or -> | <placed|no layout> |
       intent: <intent, or ->` (one line), and
       `     <block summaries joined by " / ">`, or `     (no blocks)`.

    A block summary is: a text block, its `clip(flat(text), max_text)` as a JSON string
    (`json.dumps(..., ensure_ascii=False)`, so it is quoted); a chart,
    `chart: <chart_type>, <k> categories, <s> series` (with `1 category` when k == 1;
    `series` is the same word in both numbers); a figure, `figure: <asset_id>`; an icon,
    `icon: <concept>`.
    """
    raise NotImplementedError


def slide_detail(deck: DeckArtifact, slide_id: str) -> str:
    """One slide in full, for `view_slide`: the first line
    `Slide <slide id> (<i> of <n>) in deck <deck id>`, a blank line, then
    `json.dumps(slide.model_dump(mode="json"), indent=2, ensure_ascii=False)`.

    Raises:
        KeyError: no such slide (from `DeckArtifact.slide`).
    """
    raise NotImplementedError


def change_line(entry: ChangeEntry) -> str:
    """One entry on one line, exactly:
    `<id> <live|undone> | <layer> | <model_id> | <thread_id> | <flat(instruction)>`."""
    raise NotImplementedError


def change_view(entry: ChangeEntry, log: ChangeLog) -> dict[str, Any]:
    """An entry for the Changes tab:

    `{"id", "parent_id", "live": not undone, "layer", "model_id", "thread_id",
    "instruction", "created_at": ISO 8601 with seconds, "lines": the first
    `conversation.MAX_DIFF_LINES` of `diff.describe(entry.diff)`, "truncated": whether
    more existed, "is_head": entry.id == log.head, "can_undo": entry is
    `changelog.undo_target(log)`, "can_redo": entry is `changelog.redo_target(log)`}`."""
    raise NotImplementedError


def changes_view(log: ChangeLog) -> dict[str, Any]:
    """The whole log for the Changes tab: `{"artifact_id", "head", "can_undo",
    "can_redo", "entries": [change_view(e, log) for e in entries, newest first]}`
    (newest first = reverse append order)."""
    raise NotImplementedError


def render_view(manifest: RenderManifest | None, *, base: str) -> dict[str, Any] | None:
    """A render for the interface, or None when there is none.

    `{"digest", "rendered", "note", "placeholders", "slide_ids", "images"}` where
    `images` is `[f"{base}/{manifest.digest}/{n}.png" for n in 1..len(images)]` when
    rendered, else `[]`. `base` is the artifact's renders URL prefix, e.g.
    `/api/engagements/<c>/<p>/artifacts/<a>/renders`, with no trailing slash."""
    raise NotImplementedError


def artifact_summary(deck: DeckArtifact, log: ChangeLog) -> dict[str, Any]:
    """`{"id", "kind", "title", "slide_count", "head", "entries": len(log.entries),
    "updated_at": the last entry's created_at (ISO, seconds) or None}`."""
    raise NotImplementedError


def artifact_view(
    deck: DeckArtifact, log: ChangeLog, manifest: RenderManifest | None, *, base: str
) -> dict[str, Any]:
    """The artifact panel's data: `artifact_summary(deck, log)` plus
    `{"deck": deck.model_dump(mode="json"), "can_undo", "can_redo",
    "render": render_view(manifest, base=base)}`."""
    raise NotImplementedError


def engagement_view(record: EngagementRecord) -> dict[str, Any]:
    """`{"client", "project", "title", "created_at"}` (ISO, seconds)."""
    raise NotImplementedError


def thread_summary(record: ThreadRecord, lines: Sequence[ThreadLine]) -> dict[str, Any]:
    """A row of the engagement home's thread list:

    `{"id", "title", "created_at", "opening", "model_id", "turns": number of TurnEndLines,
    "last_activity": the last line's created_at, or the record's when there is no line,
    "preview": clip(flat(first owner UserLine's text), PREVIEW_CHARS) or ""}`.
    Times are ISO 8601 with seconds."""
    raise NotImplementedError


def messages_view(lines: Sequence[ThreadLine]) -> list[dict[str, Any]]:
    """The thread as the interface shows it, in log order. Each item has a `type`:

    * `UserLine` with origin `owner` or `choice` → `{"type": "user", "turn_id",
      "origin", "text", "created_at"}`. Origins `context` and `recap` are not shown.
    * The `AssistantLine`s, `ToolLine`s and `TurnEndLine` of one turn → one item
      `{"type": "assistant", "turn_id", "texts": the non-blank assistant texts in order,
      "tools": [{"name", "summary", "error"}] per ToolLine in order, "model_id" (of the
      first assistant line, else the turn end's), "kind": turn_kind or None while the
      turn has not ended, "stop_reason" or None, "error" ("" unless errored),
      "change_ids", "undone_ids", "redone_ids", "created_artifacts", "proposal_ids"
      (empty lists until the turn ends), "created_at": of the first of those lines}`,
      placed where the first of those lines is.
    * `NoteLine` → `{"type": "note", "note", "ref", "text", "created_at"}`.

    Times are ISO 8601 with seconds.
    """
    raise NotImplementedError


def proposal_view(
    record: ProposalRecord, *, previews: dict[OptionId, list[str]] | None = None
) -> dict[str, Any]:
    """`{"id", "thread_id", "turn_id", "artifact_id", "summary", "status", "chosen",
    "resolved_by", "resolved_at" (ISO or None), "created_at", "options": [{"id", "label",
    "text", "slide_ids": candidate slide ids in order, "insert_at", "previews":
    (previews or {}).get(option id, [])}]}`. `previews` maps an option id to its image
    URLs (built by the API)."""
    raise NotImplementedError
