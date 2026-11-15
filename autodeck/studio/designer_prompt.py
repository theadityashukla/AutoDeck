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

from pathlib import Path

from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio.design import DesignSystem
from autodeck.studio.models import SlideBrief
from autodeck.studio.prompt import DESIGNER_PROMPT_PATH

TOOL_NAME = "write_slide"

PLACEHOLDERS: tuple[str, ...] = ("{{MASTER}}", "{{PALETTE}}", "{{VOCABULARY}}")

NO_DIRECTION = "None stated. Use your own judgement."
"""The design-system section of the user text when the system has no concept and no rules
(the provisional default)."""


def master_text(tokens: DesignTokens) -> str:
    """The `{{MASTER}}` text: the bench's `master_text(tokens)` line for line (slide size in
    points and what 1% is; the safe area in points and percent; the master's margins; the
    fonts and line height; the type roles with sizes, `label`, the minimum size and
    `size_pt`), with its last line replaced by: `Source band: none. The slide draws no
    source line, so the whole safe area is yours.` Lines joined by `\\n`."""
    raise NotImplementedError


def palette_text(system: DesignSystem) -> str:
    """The `{{PALETTE}}` text, lines joined by `\\n`:

    * one line per slot in `models.COLOR_SLOTS` order: `- <slot>: #<HEX>` followed by
      ` -- <role>` when `system.roles` has a non-blank role for it;
    * `Background: <system.background>`;
    * `Text pairs that pass the contrast check: <text> on <ground>, ...` (pairs in order;
      a large-only pair written `<text> on <ground> (24pt and above)`), joined by `, `;
    * `Colour tokens are used by name (for example `accent1`), never as hex.`
    """
    raise NotImplementedError


def vocabulary_text() -> str:
    """The `{{VOCABULARY}}` text: the bench's `vocabulary_text()` with the same type
    aliases, value sets and notes, describing these models in this order:
    `tool_args.DesignedSlideInput` (as `Slide`, skipping its `intent` and `speaker_notes`
    fields), `models.Block` (skipping `source_note`), `models.ChartData`, v2 `ChartSeries`,
    `IconRef`, `FreeLayout`, `Placement`, `TextElement`, `VisualElement`, `ShapeElement`.
    The value sets are `ColorToken`, `TextRole`, `HAlign`, `VAnchor`, `ShapeKind`,
    `BlockKind` and `ChartKind`; the notes are the bench's five, the icon note listing
    `autodeck.design.icons.library.icon_names()`."""
    raise NotImplementedError


def designer_system_prompt(
    tokens: DesignTokens, system: DesignSystem, *, template_path: Path = DESIGNER_PROMPT_PATH
) -> str:
    """The template with each placeholder replaced: `{{MASTER}}` by `master_text(tokens)`,
    `{{PALETTE}}` by `palette_text(system)`, `{{VOCABULARY}}` by `vocabulary_text()`.

    Raises:
        StudioConfigError: the template is unreadable or lacks one of `PLACEHOLDERS`.
    """
    raise NotImplementedError


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
    raise NotImplementedError
