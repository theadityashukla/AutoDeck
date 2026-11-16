"""The designer's system prompt and user message (Phase 2-3), moved from the slide bench.

`prompts/studio/designer.md` is the bench's `prompts/slide.md` adapted for the product. It
has three placeholders, filled here exactly as the bench filled them (`bench/slides/run.py`:
`master_text`, `palette_text`, `vocabulary_text`), because that arithmetic and that
vocabulary listing are what the bench proved: `{{MASTER}}` (slide size, safe area, type
roles and sizes, minimum size), `{{PALETTE}}` (each slot's hex and role), `{{VOCABULARY}}`
(the fields the layout accepts, generated from the models, never hand-written).

The user message is one slide's brief and the design system's direction
(`brief_user_text`). Its first lines are fixed (`Slide id: <id>`, and `Name: <system name>`
when the system states a direction) because the scripted designer matches on them.

These are pure functions of their arguments (plus the prompt file and v2's icon list).
"""

from __future__ import annotations

import types
import typing
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from autodeck.design.icons.library import icon_names
from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir import models as v2
from autodeck.studio import models as studio_models
from autodeck.studio.design import DesignSystem
from autodeck.studio.errors import StudioConfigError
from autodeck.studio.models import COLOR_SLOTS, SlideBrief
from autodeck.studio.prompt import DESIGNER_PROMPT_PATH
from autodeck.studio.tool_args import DesignedSlideInput

TOOL_NAME = "write_slide"

PLACEHOLDERS: tuple[str, ...] = ("{{MASTER}}", "{{PALETTE}}", "{{VOCABULARY}}")

NO_DIRECTION = "None stated. Use your own judgement."
"""The design-system section of the user text when the system has no concept and no rules
(the provisional default)."""

_VALUE_SETS: dict[str, Any] = {
    "ColorToken": v2.ColorToken,
    "TextRole": v2.TextRole,
    "HAlign": v2.HAlign,
    "VAnchor": v2.VAnchor,
    "ShapeKind": v2.ShapeKind,
    "BlockKind": studio_models.BlockKind,
    "ChartKind": v2.ChartKind,
}
"""The named value sets the vocabulary lists, by the alias the bench used for them."""

_SKIPPED_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("Slide", "intent"),
        ("Slide", "speaker_notes"),
        ("Block", "source_note"),
    }
)
"""Fields the designer must not see: the brief owns the intent, notes are not the designer's,
and a source note is not part of the base slide."""

_VOCABULARY_NOTES: tuple[str, ...] = (
    "Layout elements (FreeLayout.elements) are `text`, `chart`, `figure`, `icon` or `shape`.",
    "A `text` element places a text block, a `chart`/`figure`/`icon` element places the block "
    "of that kind, a `shape` places a block-less panel, band, rule or marker. Every block is "
    "placed exactly once. A `diagram` element is not available.",
    "A `figure` block draws only a captioned empty frame (there is no image library).",
)
"""The bench's notes that do not depend on the icon library, in the bench's order."""


def _type_str(annotation: Any) -> str:
    """How a field's type reads in the vocabulary (the bench's `_type_str`)."""
    for name, value_set in _VALUE_SETS.items():
        if annotation is value_set:
            return name
    origin = get_origin(annotation)
    if origin is Literal:
        return " | ".join(repr(a) for a in get_args(annotation))
    if origin is typing.Union or origin is types.UnionType:
        parts = [a for a in get_args(annotation) if a is not type(None)]
        text = " or ".join(_type_str(a) for a in parts)
        return f"{text} (optional)" if len(parts) != len(get_args(annotation)) else text
    if origin is list:
        return f"list of {_type_str(get_args(annotation)[0])}"
    if origin is typing.Annotated:
        return _type_str(get_args(annotation)[0])
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


def _describe_model(cls: type[BaseModel], name: str) -> str:
    """One model as `<name>:` and one line per field: type, default when optional, and the
    field's description when it has one. Skipped fields are left out."""
    lines = [f"{name}:"]
    for field_name, info in cls.model_fields.items():
        if (name, field_name) in _SKIPPED_FIELDS:
            continue
        annotation = info.annotation
        if get_origin(annotation) is typing.Annotated:
            annotation = get_args(annotation)[0]
        text = f"  {field_name}: {_type_str(annotation)}"
        if not info.is_required():
            default = info.get_default(call_default_factory=True)
            text += f" = {default!r}"
        if info.description:
            text += f" -- {info.description}"
        lines.append(text)
    return "\n".join(lines)


def master_text(tokens: DesignTokens) -> str:
    """The `{{MASTER}}` text: the bench's `master_text(tokens)` line for line (slide size in
    points and what 1% is; the safe area in points and percent; the master's margins; the
    fonts and line height; the type roles with sizes, `label`, the minimum size and
    `size_pt`), with its last line replaced by: `Source band: none. The slide draws no
    source line, so the whole safe area is yours.` Lines joined by `\\n`."""
    width = tokens.slide_width_emu / 12700
    height = tokens.slide_height_emu / 12700
    spacing = tokens.spacing
    typo = tokens.typography
    sx = spacing.safe_area / width * 100
    sy = spacing.safe_area / height * 100
    mx = spacing.margin_x / width * 100
    my = spacing.margin_y / height * 100
    lines = [
        f"Slide: {width:g} x {height:g} pt (16:9). Placements are percent of the slide, so 1% "
        f"of the width is {width / 100:g}pt and 1% of the height is {height / 100:g}pt.",
        f"Safe area: text and visuals must stay inside {spacing.safe_area:g}pt of every edge, "
        f"that is x from {sx:.1f}% to {100 - sx:.1f}% and y from {sy:.1f}% to "
        f"{100 - sy:.1f}%. A shape may bleed to the slide edge; text may not.",
        f"Page margins used by the master: {spacing.margin_x:g}pt left and right "
        f"({mx:.1f}%), {spacing.margin_y:g}pt top and bottom ({my:.1f}%).",
        f"Fonts: headings {typo.major}, body {typo.minor}; line height {typo.line_height:g}. "
        "Fonts are fixed; only colours can change.",
        "Type roles (point size): "
        + ", ".join(
            f"{role} {getattr(typo, role):g}pt"
            for role in ("display", "title", "heading", "body", "caption")
        )
        + ", label (caption size, capitals, letter-spaced). "
        + f"Minimum text size {typo.minimum:g}pt; "
        "`size_pt` overrides a role's size.",
        "Source band: none. The slide draws no source line, so the whole safe area is yours.",
    ]
    return "\n".join(lines)


def palette_text(system: DesignSystem) -> str:
    """The `{{PALETTE}}` text, lines joined by `\\n`:

    * one line per slot in `models.COLOR_SLOTS` order: `- <slot>: #<HEX>` followed by
      ` -- <role>` when `system.roles` has a non-blank role for it;
    * `Background: <system.background>`;
    * `Text pairs that pass the contrast check: <text> on <ground>, ...` (pairs in order;
      a large-only pair written `<text> on <ground> (24pt and above)`), joined by `, `;
    * `Colour tokens are used by name (for example `accent1`), never as hex.`
    """
    lines: list[str] = []
    for slot in COLOR_SLOTS:
        role = system.roles.get(slot, "").strip()
        lines.append(f"- {slot}: #{system.palette.hex(slot)}" + (f" -- {role}" if role else ""))
    lines.append(f"Background: {system.background}")
    pairs = ", ".join(
        f"{pair.text} on {pair.ground}" + (" (24pt and above)" if pair.large_only else "")
        for pair in system.text_pairs
    )
    lines.append(f"Text pairs that pass the contrast check: {pairs}")
    lines.append("Colour tokens are used by name (for example `accent1`), never as hex.")
    return "\n".join(lines)


def vocabulary_text() -> str:
    """The `{{VOCABULARY}}` text: the bench's `vocabulary_text()` with the same type
    aliases, value sets and notes, describing these models in this order:
    `tool_args.DesignedSlideInput` (as `Slide`, skipping its `intent` and `speaker_notes`
    fields), `models.Block` (skipping `source_note`), `models.ChartData`, v2 `ChartSeries`,
    `IconRef`, `FreeLayout`, `Placement`, `TextElement`, `VisualElement`, `ShapeElement`.
    The value sets are `ColorToken`, `TextRole`, `HAlign`, `VAnchor`, `ShapeKind`,
    `BlockKind` and `ChartKind`; the notes are the bench's five, the icon note listing
    `autodeck.design.icons.library.icon_names()`."""
    classes: list[tuple[type[BaseModel], str]] = [
        (DesignedSlideInput, "Slide"),
        (studio_models.Block, "Block"),
        (studio_models.ChartData, "ChartData"),
        (v2.ChartSeries, "ChartSeries"),
        (v2.IconRef, "IconRef"),
        (v2.FreeLayout, "FreeLayout"),
        (v2.Placement, "Placement"),
        (v2.TextElement, "TextElement"),
        (v2.VisualElement, "VisualElement"),
        (v2.ShapeElement, "ShapeElement"),
    ]
    parts = [_describe_model(cls, name) for cls, name in classes]
    sets = ["Value sets:"]
    for name, annotation in _VALUE_SETS.items():
        sets.append(f"  {name}: " + ", ".join(str(a) for a in get_args(annotation)))
    notes = [
        *_VOCABULARY_NOTES,
        f"icon `glyph_id` must be one of: {', '.join(icon_names())}.",
        "Placement `x`, `y`, `w`, `h` are percent of the slide's width and height.",
    ]
    return "\n\n".join([*parts, "\n".join(sets), "\n".join(notes)])


def designer_system_prompt(
    tokens: DesignTokens, system: DesignSystem, *, template_path: Path = DESIGNER_PROMPT_PATH
) -> str:
    """The template with each placeholder replaced: `{{MASTER}}` by `master_text(tokens)`,
    `{{PALETTE}}` by `palette_text(system)`, `{{VOCABULARY}}` by `vocabulary_text()`.

    Raises:
        StudioConfigError: the template is unreadable or lacks one of `PLACEHOLDERS`.
    """
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StudioConfigError(
            f"designer prompt not readable: {template_path}: {exc}"
        ) from exc
    missing = [p for p in PLACEHOLDERS if p not in template]
    if missing:
        raise StudioConfigError(
            f"designer prompt {template_path} lacks placeholder(s): {', '.join(missing)}"
        )
    filled = {
        "{{MASTER}}": master_text(tokens),
        "{{PALETTE}}": palette_text(system),
        "{{VOCABULARY}}": vocabulary_text(),
    }
    for placeholder, text in filled.items():
        template = template.replace(placeholder, text)
    return template


def brief_user_text(slide_id: str, brief: SlideBrief, system: DesignSystem) -> str:
    """The designer's user message for one slide. Lines joined by `\\n`, exactly:

    ```
    # Slide brief
    Slide id: <slide_id>
    Header: <brief.header>

    What the slide must make the audience conclude:
    <brief.intent stripped>

    ## Content (the only content you may put on the slide)
    ```

    then, each block preceded by one blank line and only when non-empty: `Points:` and one
    `- <point>` per point; `Key figures:` and one `- <value>: <label>` per figure
    (`- <value>` when the label is blank); `Chart (<kind>), categories: <c1>, <c2>` then
    one `- <series name>: <v1>, <v2>` per series (values with `:g`) and, when set,
    `Emphasise: <e1>, <e2>`. When the content is empty, one blank line and
    `(nothing beyond the header)`. Then, when `brief.notes` is not blank, a blank line,
    `Notes (what matters; not for the slide):` and the stripped notes. Then:

    ```

    ## Design system
    ```

    followed by `NO_DIRECTION` when the system has a blank concept and no rules; otherwise
    `Name: <name>`, `Concept: <concept stripped>` (only when not blank), and `Rules:` with
    one `- <rule>` per rule (only when there are rules). Finally a blank line and
    `Design this slide and call write_slide.`
    """
    lines = [
        "# Slide brief",
        f"Slide id: {slide_id}",
        f"Header: {brief.header}",
        "",
        "What the slide must make the audience conclude:",
        brief.intent.strip(),
        "",
        "## Content (the only content you may put on the slide)",
    ]

    content = brief.content
    body: list[str] = []
    if content.points:
        body += ["", "Points:", *[f"- {point}" for point in content.points]]
    if content.figures:
        body += ["", "Key figures:"]
        for figure in content.figures:
            label = figure.label.strip()
            body.append(f"- {figure.value}: {label}" if label else f"- {figure.value}")
    if content.chart is not None:
        chart = content.chart
        body += ["", f"Chart ({chart.kind}), categories: {', '.join(chart.categories)}"]
        for series in chart.series:
            body.append(f"- {series.name}: " + ", ".join(f"{v:g}" for v in series.values))
        if chart.emphasis:
            body.append(f"Emphasise: {', '.join(chart.emphasis)}")
    if body:
        lines += body
    else:
        lines += ["", "(nothing beyond the header)"]

    if brief.notes.strip():
        lines += ["", "Notes (what matters; not for the slide):", brief.notes.strip()]

    lines += ["", "## Design system"]
    concept = system.concept.strip()
    if not concept and not system.rules:
        lines.append(NO_DIRECTION)
    else:
        lines.append(f"Name: {system.name}")
        if concept:
            lines.append(f"Concept: {concept}")
        if system.rules:
            lines += ["Rules:", *[f"- {rule}" for rule in system.rules]]

    lines += ["", f"Design this slide and call {TOOL_NAME}."]
    return "\n".join(lines)
