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

import json
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from autodeck.studio import changelog, diff
from autodeck.studio.change_summary import SystemNamer, change_summary
from autodeck.studio.conversation import (
    MAX_DIFF_LINES,
    AssistantLine,
    NoteLine,
    ProposalOption,
    ProposalRecord,
    RenderManifest,
    ThreadLine,
    ThreadRecord,
    ToolLine,
    TurnEndLine,
    UserLine,
)
from autodeck.studio.design import DesignDraft, DesignSystem, PaletteAttempt, TextPair
from autodeck.studio.models import (
    COLOR_SLOTS,
    Block,
    ChangeEntry,
    ChangeLog,
    DeckArtifact,
    DesignPalette,
    EngagementRecord,
    OptionId,
    Slide,
    composition_status,
    deck_composition,
    effective_system,
)

MAX_BLOCK_TEXT = 80
"""`deck_outline` clips each text block to this many characters."""

PREVIEW_CHARS = 80
"""`thread_summary.preview` clips the first owner message to this many characters."""


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def flat(text: str) -> str:
    """Every run of whitespace collapsed to one space; ends stripped."""
    return re.sub(r"\s+", " ", text).strip()


def clip(text: str, limit: int) -> str:
    """`text` if it has at most `limit` characters, else its first `limit - 1` characters
    followed by `…` (U+2026). `limit` is at least 1."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _block_summary(block: Block, max_text: int) -> str:
    if block.kind == "text":
        return json.dumps(clip(flat(block.text or ""), max_text), ensure_ascii=False)
    if block.kind == "chart" and block.chart is not None:
        k = len(block.chart.categories)
        return (
            f"chart: {block.chart.chart_type}, {k} {'category' if k == 1 else 'categories'}, "
            f"{len(block.chart.series)} series"
        )
    if block.kind == "figure" and block.figure is not None:
        return f"figure: {block.figure.asset_id}"
    if block.kind == "icon" and block.icon is not None:
        return f"icon: {block.icon.concept}"
    return block.kind


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
    n = len(deck.slides)
    title = flat(deck.title) or "(untitled)"
    noun = "slide" if n == 1 else "slides"
    lines = [f"Deck `{deck.id}`: {title} ({n} {noun})"]
    brief = deck.brief
    if brief is None:
        lines.append("Brief: none")
    else:
        lines.append(
            f"Brief [{brief.marker}]: audience: {flat(brief.audience) or '-'}"
            f" | goal: {flat(brief.goal) or '-'} | notes: {flat(brief.notes) or '-'}"
        )
    story = deck.storyline
    if not story.points:
        lines.append(f"Storyline [{story.marker}]: none")
    else:
        lines.append(f"Storyline [{story.marker}]:")
        lines.extend(f"  {point.id}. {flat(point.text)}" for point in story.points)
    concept = deck.design_concept
    if concept is None:
        lines.append("Design concept: none")
    else:
        lines.append(f"Design concept [{concept.marker}]: {flat(concept.text)}")
    system = deck.design_system
    if system is None:
        lines.append("Design system: none")
    else:
        lines.append(f"Design system [{system.marker}]: {system.id} v{system.version}")
    if not deck.slides:
        lines.append("Slides: none")
    else:
        lines.append("Slides:")
        for i, slide in enumerate(deck.slides, start=1):
            serves = ", ".join(slide.serves) or "-"
            placed = "placed" if slide.layout is not None else "no layout"
            intent = flat(slide.intent or "") or "-"
            lines.append(
                f"  {i}. {slide.id} [{slide.marker}] serves {serves} | {placed}"
                f" | intent: {intent}"
            )
            summaries = " / ".join(_block_summary(b, max_text) for b in slide.blocks)
            lines.append(f"     {summaries or '(no blocks)'}")
            if slide.brief is not None:
                lines.append(slide_brief_line(slide, effective_system(deck), max_text=max_text))
    return "\n".join(lines)


def _palette_view(palette: DesignPalette, roles: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {"slot": slot, "hex": "#" + palette.hex(slot), "role": roles.get(slot, "")}
        for slot in COLOR_SLOTS
    ]


def _text_pairs_view(pairs: Sequence[TextPair]) -> list[dict[str, Any]]:
    return [{"text": p.text, "ground": p.ground, "large_only": p.large_only} for p in pairs]


def slide_brief_line(slide: Slide, system: tuple[str, int], *, max_text: int) -> str:
    """Phase 2-3: the third outline line of a slide that has a brief, exactly:

    `     brief: "<clip(flat(header), max_text)>" | <k> point|points, <f> figure|figures,
    <chart|no chart> | <state>` (one line; five leading spaces; the quote marks are literal
    `"`; singular only for 1), where `<state>` follows `models.composition_status(slide,
    system)`: `not designed yet` (undesigned), `designed` (fresh), `stale: <reasons joined
    by "; ">`, `failed to compose: <first finding, or "no findings"> (<a> attempts)`.
    Example: `     brief: "Quantisation alone cuts serving cost by 38%" | 2 points, 1
    figure, chart | stale: design system changed`.
    """
    status = composition_status(slide, system)
    brief = slide.brief
    assert brief is not None
    content = brief.content
    k = len(content.points)
    f = len(content.figures)
    if status.state == "undesigned":
        state = "not designed yet"
    elif status.state == "fresh":
        state = "designed"
    elif status.state == "stale":
        state = "stale: " + "; ".join(status.reasons)
    else:
        failure = slide.compose_failure
        first = (
            failure.findings[0] if failure is not None and failure.findings else "no findings"
        )
        attempts = failure.attempts if failure is not None else 0
        state = f"failed to compose: {first} ({attempts} attempts)"
    return (
        f'     brief: "{clip(flat(brief.header), max_text)}"'
        f" | {k} {'point' if k == 1 else 'points'},"
        f" {f} {'figure' if f == 1 else 'figures'}, {'chart' if content.chart else 'no chart'}"
        f" | {state}"
    )


def design_system_text(system: DesignSystem) -> str:
    """Phase 2-3: the design system as the lead reads it in the context (no colours: the
    lead never picks them). Lines joined by `\n`:

    `<name> (<id> v<version>, <marker>)`, `Concept: <flat(concept) or "none stated">`,
    then `Rules:` and one `- <rule>` per rule, or `Rules: none`.
    """
    lines = [
        f"{system.name} ({system.id} v{system.version}, {system.marker})",
        f"Concept: {flat(system.concept) or 'none stated'}",
    ]
    if system.rules:
        lines.append("Rules:")
        lines.extend(f"- {rule}" for rule in system.rules)
    else:
        lines.append("Rules: none")
    return "\n".join(lines)


def composition_view(deck: DeckArtifact) -> dict[str, Any]:
    """Phase 2-3: per slide id (deck order), `{"state", "reasons": [..], "failure":
    {"attempts", "findings", "model_id"} or None (only for state "failed"), "composed_by":
    composed.model_id or None}`, from `models.deck_composition(deck)`."""
    statuses = deck_composition(deck)
    out: dict[str, Any] = {}
    for slide in deck.slides:
        status = statuses[slide.id]
        failure = slide.compose_failure if status.state == "failed" else None
        out[slide.id] = {
            "state": status.state,
            "reasons": list(status.reasons),
            "failure": None
            if failure is None
            else {
                "attempts": failure.attempts,
                "findings": list(failure.findings),
                "model_id": failure.model_id,
            },
            "composed_by": slide.composed.model_id if slide.composed is not None else None,
        }
    return out


def _attempts_view(attempts: list[PaletteAttempt]) -> list[dict[str, Any]]:
    return [
        {"attempt": a.attempt, "accepted": a.accepted, "findings": list(a.findings)}
        for a in attempts
    ]


def design_system_view(system: DesignSystem) -> dict[str, Any]:
    """Phase 2-3: the Design tab's data: `{"id", "version", "name", "concept", "rules",
    "marker", "is_default", "background", "made_by", "created_at" (ISO or None),
    "palette": [{"slot", "hex": "#RRGGBB", "role": role or ""}] one per slot in
    `models.COLOR_SLOTS` order, "text_pairs": [{"text", "ground", "large_only"}],
    "palette_attempts": [{"attempt", "accepted", "findings": [str]}]}` (the system layer's
    attempts; empty for the default and for versions stored before they were recorded)."""
    return {
        "id": system.id,
        "version": system.version,
        "name": system.name,
        "concept": system.concept,
        "rules": list(system.rules),
        "marker": system.marker,
        "is_default": system.is_default,
        "background": system.background,
        "made_by": system.made_by,
        "created_at": _iso(system.created_at) if system.created_at is not None else None,
        "palette": _palette_view(system.palette, system.roles),
        "text_pairs": _text_pairs_view(system.text_pairs),
        "palette_attempts": _attempts_view(system.palette_attempts),
    }


def design_draft_view(draft: DesignDraft) -> dict[str, Any]:
    """Phase 2-3: a proposal option's design: `{"name", "concept", "rules", "background",
    "made_by", "palette": [...as design_system_view...], "text_pairs": [...],
    "palette_attempts": [...as design_system_view...]}`."""
    return {
        "name": draft.name,
        "concept": draft.concept,
        "rules": list(draft.rules),
        "background": draft.background,
        "made_by": draft.made_by,
        "palette": _palette_view(draft.palette, draft.roles),
        "text_pairs": _text_pairs_view(draft.text_pairs),
        "palette_attempts": _attempts_view(draft.palette_attempts),
    }


def slide_order(deck: DeckArtifact, *, max_intent: int = 50) -> str:
    """The slide order in one compact line: `1. <id> <intent clipped>; 2. ...`, `(no slides)`
    when there are none. The intent is flattened and clipped to `max_intent` characters;
    a slide without one shows only its id."""
    if not deck.slides:
        return "(no slides)"
    parts = []
    for i, slide in enumerate(deck.slides, start=1):
        intent = f" {clip(flat(slide.intent), max_intent)}" if slide.intent else ""
        parts.append(f"{i}. {slide.id}{intent}")
    return "; ".join(parts)


def slide_detail(deck: DeckArtifact, slide_id: str) -> str:
    """One slide in full, for `view_slide`: the first line
    `Slide <slide id> (<i> of <n>) in deck <deck id>`, a blank line, then
    `json.dumps(slide.model_dump(mode="json"), indent=2, ensure_ascii=False)`.

    Raises:
        KeyError: no such slide (from `DeckArtifact.slide`).
    """
    slide = deck.slide(slide_id)
    index = deck.slide_ids().index(slide_id) + 1
    dump = json.dumps(slide.model_dump(mode="json"), indent=2, ensure_ascii=False)
    return f"Slide {slide_id} ({index} of {len(deck.slides)}) in deck {deck.id}\n\n{dump}"


def change_line(entry: ChangeEntry) -> str:
    """One entry on one line, exactly:
    `<id> <live|undone> | <layer> | <model_id> | <thread_id> | <flat(instruction)>`."""
    state = "undone" if entry.undone else "live"
    return (
        f"{entry.id} {state} | {entry.layer} | {entry.model_id} | {entry.thread_id}"
        f" | {flat(entry.instruction)}"
    )


def change_view(
    entry: ChangeEntry,
    log: ChangeLog,
    *,
    deck: DeckArtifact | None = None,
    system_name: SystemNamer | None = None,
) -> dict[str, Any]:
    """An entry for the Changes tab:

    `{"id", "parent_id", "live": not undone, "layer", "model_id", "thread_id",
    "instruction", "created_at": ISO 8601 with seconds, "summary": one plain sentence
    (`change_summary.change_summary`: slides by their number in `deck` now, a design by
    the name `system_name` gives; "" only for an entry with nothing to say), "lines": the first
    `conversation.MAX_DIFF_LINES` of `diff.describe(entry.diff)`, "truncated": whether
    more existed, "is_head": entry.id == log.head, "can_undo": entry is
    `changelog.undo_target(log)`, "can_redo": entry is `changelog.redo_target(log)`}`."""
    described = diff.describe(entry.diff)
    numbers = (
        {s.id: n for n, s in enumerate(deck.slides, start=1)} if deck is not None else None
    )
    undo = changelog.undo_target(log)
    redo = changelog.redo_target(log)
    return {
        "id": entry.id,
        "parent_id": entry.parent_id,
        "live": not entry.undone,
        "layer": entry.layer,
        "model_id": entry.model_id,
        "thread_id": entry.thread_id,
        "instruction": entry.instruction,
        "created_at": _iso(entry.created_at),
        "summary": change_summary(entry, numbers=numbers, system_name=system_name),
        "lines": described[:MAX_DIFF_LINES],
        "truncated": len(described) > MAX_DIFF_LINES,
        "is_head": entry.id == log.head,
        "can_undo": undo is not None and undo.id == entry.id,
        "can_redo": redo is not None and redo.id == entry.id,
    }


def changes_view(
    log: ChangeLog,
    *,
    deck: DeckArtifact | None = None,
    system_name: SystemNamer | None = None,
) -> dict[str, Any]:
    """The whole log for the Changes tab: `{"artifact_id", "head", "can_undo",
    "can_redo", "entries": [change_view(e, log) for e in entries, newest first]}`
    (newest first = reverse append order)."""
    return {
        "artifact_id": log.artifact_id,
        "head": log.head,
        "can_undo": changelog.undo_target(log) is not None,
        "can_redo": changelog.redo_target(log) is not None,
        "entries": [
            change_view(e, log, deck=deck, system_name=system_name)
            for e in reversed(log.entries)
        ],
    }


def render_view(manifest: RenderManifest | None, *, base: str) -> dict[str, Any] | None:
    """A render for the interface, or None when there is none.

    `{"digest", "rendered", "note", "placeholders", "slide_ids", "images"}` where
    `images` is `[f"{base}/{manifest.digest}/{n}.png" for n in 1..len(images)]` when
    rendered, else `[]`. `base` is the artifact's renders URL prefix, e.g.
    `/api/engagements/<c>/<p>/artifacts/<a>/renders`, with no trailing slash."""
    if manifest is None:
        return None
    images = (
        [f"{base}/{manifest.digest}/{n}.png" for n in range(1, len(manifest.images) + 1)]
        if manifest.rendered
        else []
    )
    return {
        "digest": manifest.digest,
        "rendered": manifest.rendered,
        "note": manifest.note,
        "placeholders": dict(manifest.placeholders),
        "slide_ids": list(manifest.slide_ids),
        "images": images,
    }


def artifact_summary(deck: DeckArtifact, log: ChangeLog) -> dict[str, Any]:
    """`{"id", "kind", "title", "slide_count", "head", "entries": len(log.entries),
    "updated_at": the last entry's created_at (ISO, seconds) or None}`."""
    return {
        "id": deck.id,
        "kind": deck.kind,
        "title": deck.title,
        "slide_count": len(deck.slides),
        "head": log.head,
        "entries": len(log.entries),
        "updated_at": _iso(log.entries[-1].created_at) if log.entries else None,
    }


def artifact_view(
    deck: DeckArtifact,
    log: ChangeLog,
    manifest: RenderManifest | None,
    *,
    base: str,
    system: DesignSystem | None = None,
) -> dict[str, Any]:
    """The artifact panel's data: `artifact_summary(deck, log)` plus
    `{"deck": deck.model_dump(mode="json"), "can_undo", "can_redo",
    "render": render_view(manifest, base=base)}`, and (Phase 2-3) `"composition":
    composition_view(deck)` and `"design_system": design_system_view(system)`, or None when
    no system is given."""
    return {
        **artifact_summary(deck, log),
        "deck": deck.model_dump(mode="json"),
        "can_undo": changelog.undo_target(log) is not None,
        "can_redo": changelog.redo_target(log) is not None,
        "render": render_view(manifest, base=base),
        "composition": composition_view(deck),
        "design_system": design_system_view(system) if system is not None else None,
    }


def engagement_view(record: EngagementRecord) -> dict[str, Any]:
    """`{"client", "project", "title", "created_at"}` (ISO, seconds)."""
    return {
        "client": record.client,
        "project": record.project,
        "title": record.title,
        "created_at": _iso(record.created_at),
    }


def thread_summary(record: ThreadRecord, lines: Sequence[ThreadLine]) -> dict[str, Any]:
    """A row of the engagement home's thread list:

    `{"id", "title", "created_at", "opening", "model_id", "turns": number of TurnEndLines,
    "last_activity": the last line's created_at, or the record's when there is no line,
    "preview": clip(flat(first owner UserLine's text), PREVIEW_CHARS) or ""}`.
    Times are ISO 8601 with seconds."""
    preview = ""
    for line in lines:
        if isinstance(line, UserLine) and line.origin == "owner":
            preview = clip(flat(line.text), PREVIEW_CHARS)
            break
    last = lines[-1].created_at if lines else record.created_at
    return {
        "id": record.id,
        "title": record.title,
        "created_at": _iso(record.created_at),
        "opening": record.opening,
        "model_id": record.model_id,
        "turns": sum(1 for line in lines if isinstance(line, TurnEndLine)),
        "last_activity": _iso(last),
        "preview": preview,
    }


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
      placed where the first of those lines is. Phase 2-3 adds `"roles"`: the roles of its
      assistant lines in first-seen order (`["mechanic"]`, `["lead"]`, `["mechanic",
      "lead"]` after a handoff), and `"route"` / `"usage"`: the turn end's `RouteRecord` /
      `TurnUsage` as JSON, or None (while running, or on older lines).
    * `NoteLine` → `{"type": "note", "note", "ref", "text", "created_at"}`.

    Times are ISO 8601 with seconds.
    """
    items: list[dict[str, Any]] = []
    turns: dict[str, dict[str, Any]] = {}
    for line in lines:
        if isinstance(line, UserLine):
            if line.origin in ("owner", "choice"):
                items.append(
                    {
                        "type": "user",
                        "turn_id": line.turn_id,
                        "origin": line.origin,
                        "text": line.text,
                        "created_at": _iso(line.created_at),
                    }
                )
        elif isinstance(line, NoteLine):
            items.append(
                {
                    "type": "note",
                    "note": line.note,
                    "ref": line.ref,
                    "text": line.text,
                    "created_at": _iso(line.created_at),
                }
            )
        else:
            item = turns.get(line.turn_id)
            if item is None:
                item = {
                    "type": "assistant",
                    "turn_id": line.turn_id,
                    "texts": [],
                    "tools": [],
                    "model_id": None,
                    "kind": None,
                    "stop_reason": None,
                    "error": "",
                    "change_ids": [],
                    "undone_ids": [],
                    "redone_ids": [],
                    "created_artifacts": [],
                    "proposal_ids": [],
                    "roles": [],
                    "route": None,
                    "usage": None,
                    "created_at": _iso(line.created_at),
                }
                turns[line.turn_id] = item
                items.append(item)
            if isinstance(line, AssistantLine):
                if line.role not in item["roles"]:
                    item["roles"].append(line.role)
                if line.text.strip():
                    item["texts"].append(line.text)
                if item["model_id"] is None:
                    item["model_id"] = line.model_id
            elif isinstance(line, ToolLine):
                item["tools"].append(
                    {"name": line.tool_name, "summary": line.summary, "error": line.error}
                )
            else:
                if item["model_id"] is None:
                    item["model_id"] = line.model_id
                item["kind"] = line.turn_kind
                item["stop_reason"] = line.stop_reason
                item["error"] = line.error
                item["change_ids"] = list(line.change_ids)
                item["undone_ids"] = list(line.undone_ids)
                item["redone_ids"] = list(line.redone_ids)
                item["created_artifacts"] = list(line.created_artifacts)
                item["proposal_ids"] = list(line.proposal_ids)
                item["route"] = line.route.model_dump(mode="json") if line.route else None
                item["usage"] = line.usage.model_dump(mode="json") if line.usage else None
    for item in turns.values():
        if item["model_id"] is None:
            item["model_id"] = ""
    return items


def _option_effect(option: ProposalOption, deck: DeckArtifact | None) -> str:
    """What applying the option does, for the owner: `Replaces slide 1`, `Inserts a slide
    at position 3`, several joined by `; `, `Old proposal: what applying it does was not
    recorded` for a legacy option, "" without candidates. A replaced slide's number comes
    from `deck` (the deck now); without the deck, or when the slide is gone, its id."""
    if option.legacy:
        return "Old proposal: what applying it does was not recorded"
    if option.design is not None:
        return f'Adopts the design "{option.design.name}"; designed slides become stale'
    ids = [s.id for s in deck.slides] if deck is not None else []
    parts: list[str] = []
    for c in option.candidates:
        if c.replaces is not None:
            where = str(ids.index(c.replaces) + 1) if c.replaces in ids else c.replaces
            parts.append(f"Replaces slide {where}")
        else:
            parts.append(f"Inserts a slide at position {c.insert_at}")
    return "; ".join(parts)


def _slide_label(slide_id: str, ids: list[str]) -> str:
    return f"slide {ids.index(slide_id) + 1}" if slide_id in ids else f"slide {slide_id}"


def samples_summary(option: ProposalOption, deck: DeckArtifact | None) -> str:
    """For a design option that recorded its samples, one sentence the owner can read:
    `<k> of <n> samples rendered` and, per failed sample, `; slide <number> could not be
    designed: <first finding>`. "" for any other option or an old record without samples.
    Slide numbers come from `deck` (ids when it is not given or the slide is gone)."""
    if option.design is None or not option.samples:
        return ""
    ids = [s.id for s in deck.slides] if deck is not None else []
    n = len(option.samples)
    k = sum(1 for o in option.samples if o.clean)
    text = f"{k} of {n} sample{'s' if n != 1 else ''} rendered"
    for o in option.samples:
        if not o.clean:
            why = clip(flat(o.findings[0]), 160) if o.findings else "no reason recorded"
            text += f"; {_slide_label(o.slide_id, ids)} could not be designed: {why}"
    return text


def proposal_view(
    record: ProposalRecord,
    *,
    previews: dict[OptionId, list[str]] | None = None,
    deck: DeckArtifact | None = None,
) -> dict[str, Any]:
    """`{"id", "thread_id", "turn_id", "artifact_id", "summary", "status", "chosen",
    "resolved_by", "resolved_at" (ISO or None), "created_at", "options": [{"id", "label",
    "text", "slide_ids": candidate slide ids in order, "placements": [{"slide_id",
    "replaces": slide id or None, "insert_at": position or None}] one per candidate,
    "applies": what applying it does in words (`_option_effect`; "" without candidates),
    "previews": (previews or {}).get(option id, []), "design": design_draft_view(design) or
    None (Phase 2-3), "samples": [{"slide_id", "clean", "attempts", "findings": [str]}] (a
    design option's per-sample outcomes; [] otherwise), "samples_summary":
    `samples_summary(option, deck)`}]}`. `previews` maps an option id to
    its image URLs (built by the API); `deck` is the proposal's deck now, if it can be
    read, and gives the number of a replaced slide."""
    chosen_previews = previews or {}
    return {
        "id": record.id,
        "thread_id": record.thread_id,
        "turn_id": record.turn_id,
        "artifact_id": record.artifact_id,
        "summary": record.summary,
        "status": record.status,
        "chosen": record.chosen,
        "resolved_by": record.resolved_by,
        "resolved_at": _iso(record.resolved_at) if record.resolved_at else None,
        "created_at": _iso(record.created_at),
        "options": [
            {
                "id": o.id,
                "label": o.label,
                "text": o.text,
                "slide_ids": [s.id for s in o.slides],
                "placements": [
                    {"slide_id": c.slide.id, "replaces": c.replaces, "insert_at": c.insert_at}
                    for c in o.candidates
                ],
                "applies": _option_effect(o, deck),
                "previews": list(chosen_previews.get(o.id, [])),
                "design": design_draft_view(o.design) if o.design is not None else None,
                "samples": [
                    {
                        "slide_id": x.slide_id,
                        "clean": x.clean,
                        "attempts": x.attempts,
                        "findings": list(x.findings),
                    }
                    for x in o.samples
                ],
                "samples_summary": samples_summary(o, deck),
            }
            for o in record.options
        ],
    }
