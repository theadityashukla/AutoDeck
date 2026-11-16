"""One plain sentence per change-log entry, for the interface (Phase 2-3 fixes).

The Changes tab and a Change message used to turn the first diff line into words in the
browser ("Changed slide s1, composed, system id: default -> demand-curve (+11 more)"). That
parsed diff paths in script and could not tell a redesign from a retitle. The server has the
structured diff (`ChangeEntry.diff`), so it writes the sentence: `change_summary(entry)`.
The raw lines stay in `ChangeView.lines`, behind the interface's disclosure.

What it says, by the paths the entry touched (examples are the exact output):

* a slide added with a brief: `Wrote the brief for slide 2: <header>`; without one: `Added
  slide 2`; removed: `Removed slide s2`;
* only brief fields changed: `Updated the brief for slide 2`; only the header (a retitle,
  which also moves the header block and the composition fingerprint): `Retitled slide 2: <old>
  -> <new>`;
* the designed form came to exist (`composed` appeared): `Designed slide 2` (and ` in <design>`
  when it is not the default); it changed (blocks, layout, fingerprint): `Redesigned slide 1
  in Demand curve` (the design is named when the entry moved the slide into one); only text
  of blocks changed: `Reworded text on slide 2`;
* a recorded composition failure: `Slide 3 could not be designed after 4 attempts`;
* the deck's design: `Adopted the design Demand curve (version 1)`, `Went back to the default
  design`, `Marked the design decided`;
* the order: `Swapped slides 2 and 3`, `Moved slide 3 to position 1`, `Reordered the slides`;
* markers: `Marked slide 2 as decided`; the deck brief and storyline: `Wrote the deck brief`,
  `Updated the deck brief`, `Added storyline point: <text>`, `Updated the storyline`;
* anything else: `Changed <path in words>`.

Several things in one entry are joined with `; ` (at most three, then `and <n> more`).
A slide is named by its number in the deck **now** (`numbers`), else by its id.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from autodeck.studio.models import DEFAULT_SYSTEM_ID, ChangeEntry, DiffItem

SystemNamer = Callable[[str, int], str | None]
"""`(system id, version) -> display name or None`; the API resolves it from the store."""

MAX_PARTS = 3
HEADER_CLIP = 60

_SLIDE = re.compile(r"^slides\[([^\]]+)\](.*)$", re.S)


def _clip(text: Any, limit: int = HEADER_CLIP) -> str:
    flat = re.sub(r"\s+", " ", str(text)).strip()
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def humanise_id(value: str) -> str:
    """`demand-curve` -> `Demand curve`: the fallback name of a design when it cannot be
    looked up."""
    words = value.replace("-", " ").replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else value


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _system_name(system_id: str, version: int | None, namer: SystemNamer | None) -> str:
    if system_id == DEFAULT_SYSTEM_ID:
        return "the default design"
    if namer is not None and version is not None:
        try:
            found = namer(system_id, version)
        except Exception:  # a name is a nicety; never fail a view over it
            found = None
        if found:
            return found
    return humanise_id(system_id)


def _label(key: str, ids: Mapping[str, int] | None) -> str:
    if ids is not None and key in ids:
        return f"slide {ids[key]}"
    return f"slide {key}"


def _split(path: str) -> tuple[str, str]:
    """`slides[s1].blocks[0]` -> `("s1", ".blocks[0]")`; `("", path)` for other paths."""
    match = _SLIDE.match(path)
    return (match.group(1), match.group(2)) if match else ("", path)


def _readable(path: str) -> str:
    text = re.sub(r"\[[^\]]*\]", "", path).replace(".", " ").replace("_", " ")
    return text.strip() or path


def _order_phrase(item: DiffItem, ids: Mapping[str, int] | None) -> str:
    before, after = item.before, item.after
    if not (isinstance(before, list) and isinstance(after, list)) or len(before) != len(after):
        return "Reordered the slides"
    differing = [i for i, (b, a) in enumerate(zip(before, after, strict=True)) if b != a]
    if len(differing) == 2:
        return f"Swapped slides {differing[0] + 1} and {differing[1] + 1}"
    for old, moved in enumerate(before):
        rest_before = before[:old] + before[old + 1 :]
        rest_after = [x for x in after if x != moved]
        if rest_before == rest_after:
            return f"Moved slide {old + 1} to position {after.index(moved) + 1}"
    return "Reordered the slides"


def _slide_phrase(
    key: str,
    items: list[DiffItem],
    ids: Mapping[str, int] | None,
    namer: SystemNamer | None,
) -> str:
    split = [(_split(i.path)[1], i) for i in items]
    whole = [i for r, i in split if r == ""]
    if whole:
        item = whole[0]
        if item.kind == "added" and isinstance(item.after, dict):
            slide_id = str(item.after.get("id", key))
            brief = item.after.get("brief")
            label = _label(slide_id, ids)
            if isinstance(brief, dict) and brief.get("header"):
                return f"Wrote the brief for {label}: {_clip(brief['header'])}"
            return f"Added {label}"
        if item.kind == "removed":
            before = item.before if isinstance(item.before, dict) else {}
            return f"Removed slide {before.get('id', key)}"
    label = _label(key, ids)
    rests = split

    def under(prefix: str) -> list[tuple[str, DiffItem]]:
        return [
            (r, i)
            for r, i in rests
            if r == prefix or r.startswith((prefix + ".", prefix + "["))
        ]

    failure = [i for r, i in rests if r == ".compose_failure"]
    if failure and isinstance(failure[0].after, dict):
        attempts = failure[0].after.get("attempts")
        tail = (
            f" after {_plural(int(attempts), 'attempt')}" if isinstance(attempts, int) else ""
        )
        return f"{_cap(label)} could not be designed{tail}"

    brief_items = under(".brief")
    layout_items = under(".layout")
    blocks_items = under(".blocks")
    composed_items = under(".composed")
    structural_blocks = [
        i for r, i in blocks_items if i.kind != "changed" or not r.endswith(".text")
    ]

    if brief_items and not layout_items and not structural_blocks:
        brief_paths = {r for r, _ in brief_items}
        if brief_paths == {".brief.header"}:
            header = brief_items[0][1]
            return f"Retitled {label}: {_clip(header.before)} → {_clip(header.after)}"
        if ".brief" in brief_paths and brief_items[0][1].before is None:
            return f"Wrote the brief for {label}"
        return f"Updated the brief for {label}"

    if layout_items or blocks_items or composed_items:
        appeared = any(r == ".composed" and i.before is None for r, i in composed_items)
        only_text = bool(blocks_items) and not layout_items and not structural_blocks
        only_text = only_text and all(r.endswith(".text") for r, _ in blocks_items)
        new_system: tuple[str, int | None] | None = None
        for r, i in composed_items:
            if r == ".composed" and isinstance(i.after, dict):
                new_system = (str(i.after.get("system_id", "")), i.after.get("system_version"))
            elif r == ".composed.system_id" and isinstance(i.after, str):
                version = next(
                    (
                        v.after
                        for rr, v in composed_items
                        if rr == ".composed.system_version" and isinstance(v.after, int)
                    ),
                    None,
                )
                new_system = (i.after, version)
        if appeared:
            where = ""
            if new_system and new_system[0] and new_system[0] != DEFAULT_SYSTEM_ID:
                where = f" in {_system_name(new_system[0], new_system[1], namer)}"
            return f"Designed {label}{where}"
        if only_text:
            return f"Reworded text on {label}"
        where = ""
        if new_system and new_system[0]:
            where = f" in {_system_name(new_system[0], new_system[1], namer)}"
        return f"Redesigned {label}{where}"

    for r, i in rests:
        if r == ".marker":
            return f"Marked {label} as {i.after}"
        if r == ".intent":
            return f"Changed the intent of {label}"
        if r.startswith(".serves"):
            return f"Changed which storyline points {label} serves"
        if r == ".speaker_notes":
            return f"Changed the speaker notes of {label}"
    return f"Changed {label}"


def _deck_phrase(item: DiffItem, namer: SystemNamer | None) -> str:
    path = item.path
    if path == "design_system":
        if isinstance(item.after, dict):
            sid = str(item.after.get("id", ""))
            version = item.after.get("version")
            name = _system_name(sid, version if isinstance(version, int) else None, namer)
            tail = f" (version {version})" if isinstance(version, int) else ""
            return f"Adopted the design {name}{tail}"
        return "Went back to the default design"
    if path == "design_system.marker":
        return f"Marked the design {item.after}"
    if path.startswith("design_system"):
        return "Changed the design"
    if path == "brief" or path.startswith("brief."):
        return "Wrote the deck brief" if item.before is None else "Updated the deck brief"
    if path.startswith("storyline"):
        if item.kind == "added" and isinstance(item.after, dict) and item.after.get("text"):
            return f"Added storyline point: {_clip(item.after['text'])}"
        return "Updated the storyline"
    if path == "title":
        return f"Renamed the deck: {_clip(item.before)} → {_clip(item.after)}"
    if path.startswith("design_concept"):
        return "Changed the design concept"
    return f"Changed {_readable(path)}"


def change_summary(
    entry: ChangeEntry,
    *,
    numbers: Mapping[str, int] | None = None,
    system_name: SystemNamer | None = None,
) -> str:
    """The one-sentence description of `entry` (see the module docstring). `numbers` maps a
    slide id to its 1-based position in the deck now; `system_name` resolves a design's
    display name. Pure apart from `system_name`."""
    phrases: list[str] = []
    slides: dict[str, list[DiffItem]] = {}
    for item in entry.diff:
        if item.path == "slides[order]":
            phrases.append(_order_phrase(item, numbers))
            continue
        key, rest = _split(item.path)
        if key:
            carried = item.after if isinstance(item.after, dict) else item.before
            if rest == "" and isinstance(carried, dict) and "id" in carried:
                key = str(carried["id"])
            slides.setdefault(key, []).append(item)
            continue
        phrase = _deck_phrase(item, system_name)
        if phrase not in phrases:
            phrases.append(phrase)
    for key, items in slides.items():
        phrases.append(_slide_phrase(key, items, numbers, system_name))
    if not phrases:
        return ""
    shown = phrases[:MAX_PARTS]
    text = "; ".join(shown)
    if len(phrases) > MAX_PARTS:
        text += f"; and {len(phrases) - MAX_PARTS} more"
    return text
