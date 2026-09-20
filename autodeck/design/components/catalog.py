"""The component registry — one registration establishes everything about a component.

`budgets.py` can turn a box into a limit; nothing before this module turned a *component*
into a box. Without it the content agent has a measurement engine and nowhere to point it,
which is exactly v1's failure arriving one layer up: overflow was fought at render time
because nothing upstream declared how much a slot could hold. §6.7 requires slot budgets to
reach the writer as hard constraints *before* it writes, and this is the module that makes
"the slot" a concrete thing with a width and a height rather than a synonym for "some text".

## What a registration is for

The brief's registry fields are `name -> role -> slots -> budgets -> renderer -> golden
preview`, and the reason they belong to **one** declaration is that Phase 3b's assembler,
the preview gallery and the content prompt all need the same answers. Three modules each
keeping their own list is three lists that can disagree, and the one that has gone stale is
never the one being read. So `register()` takes all of it at once and nothing may be left
out — `preview=None` is a statement ("no golden PNG yet"), not an omission, because
`components_missing_previews()` has to answer "did this one ever get a preview committed"
from the registry rather than from a directory listing. Fifteen components are coming and
most will be written by cheaper models; the question needs an answer that does not depend
on anyone remembering to look.

Adding a component is a registration: a slot builder and a `register(...)` call in this
file. Nothing in `spec_for`, `render_budgets`, `check_overflow` or any caller changes.

## Variants: a component whose slots depend on its content

`big_number` lays out differently the moment it has supporting points — the figure moves
into a column half the width. That fact used to travel as `spec_for(...,
has_supporting_points=False)`: one component's private business sitting in the signature
every caller uses, with `check_overflow` inferring the flag back from the caller's blocks.
The inference was clever and it was a symptom.

A **variant** replaces it. A registration declares its variants, and a non-default variant
says which slot being filled selects it (`when_filled`). Resolution is then generic:
`variant_for` walks the component's own declarations, so no code outside this component's
registration knows that `big_number` has modes, and the generic API names no component.
`when_filled` is a slot name rather than a predicate function on purpose — a name can be
shown to the writer ("if you write supporting_points: ...") and a lambda cannot.

## Where the geometry comes from

A slot's box is read off the renderer that already computes it, not invented here — see
`docs/phases/PHASE-2B.md`'s 2b.2 entry. Two kinds of number appear:

* **Width and column position** are genuinely fixed by the renderer's own `Box` arithmetic
  (`split_columns`, `body_and_caption`, padding constants) and do not depend on what the
  writer puts in any slot. These are copied exactly.
* **Height**, for a slot the renderer sizes to its own measured content, has no single
  fixed value in the renderer — by design, since that is precisely what lets a one-line
  headline and a two-line headline both produce a correctly-laid-out slide. A *budget*
  still needs a number, so each such slot gets the most height it could use while
  guaranteeing every sibling slot still has room for at least one line of its own text —
  never the whole remaining region, which would make the budget vacuous, and never a made-up
  constant, since the "one line" reservation is measured from the same real font metrics
  `compute_budget` uses everywhere else. `two_column_compare`'s `point` slots keep a single
  line on purpose — see `_two_column_compare_slots` for what that cap actually buys, which
  turns out **not** to be the row-parity argument an earlier version of this docstring made.

These are upper bounds a slot could use *alone*; they are not a guarantee that every slot
filled to its own limit simultaneously fits the slide. That guarantee still rests on the
renderer's own `LayoutOverflowError` (§6.9's safety net) — this module makes overflow rare
by construction, per the phase brief, not impossible by construction.

## Repeatable slots: a real content model is a list, not one string

Two real cases have content that is a **list** of independent, roughly-one-line items
rather than one block of prose: `two_column_compare`'s columns carry several `points`, not
one, and `big_number.supporting_points` is a list too. A `ComponentSlot` with
`repeatable=True` declares that shape: `box` is the whole area the stack may use, `item_box`
is the area **one** item gets, and `row_gap` is the gap the renderer actually puts between
rows — read off the renderer's own gutter constant, never invented. `check_overflow` checks
each item against `item_box` and the whole stack against `box`; `budget_for` on a repeatable
slot returns the per-item budget, since that is the number a writer can hold in its head
while composing one bullet.

Owning phase: 2b (task 2b.2); made a registry in 3a (task 3a.3). Geometry is re-derived per
call from the caller's own `DesignTokens`, never cached at import time: margins, gutters and
the type scale all come from the client's theme, and a different client's tokens genuinely
move every box edge.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pptx.slide import Slide

from autodeck.design.budgets import SlotBudget, compute_budget
from autodeck.design.components.renderers import (
    agenda,
    before_after,
    big_number,
    bullets_supporting,
    callout_takeaway,
    closing_cta,
    data_card_grid,
    evidence_with_figure,
    quote,
    section_divider,
    title,
    two_column_compare,
)
from autodeck.design.layout_kit import MARKER_INSET, Box, Canvas, TextStyle
from autodeck.design.theme.tokens import DesignTokens

#: The component library's version, and the only definition of it.
#:
#: A6 requires the build manifest to record it, and `Deck.component_lib_version` records it
#: too — a deck laid out against different slot geometry is a different deck even from the
#: same IR. Two literals would be two answers to one question, and the manifest's would be
#: the one nobody noticed had gone stale, so both read this. Bump it whenever a slot's box,
#: its style, or the set of components changes.
#:
#: 0.2.0: `layout_kit` grew the `Frame`/`Stack` composition layer (task 3a.2) and bullet
#: geometry moved into the kit, so `two_column_compare`'s points hang at 18pt rather than
#: 17pt and every `point` slot is one point narrower. A small move, but it is a slot box
#: moving, which is exactly what this number is for.
#:
#: 0.3.0: task 3a.4's first tranche registers `quote`, `bullets_supporting` and
#: `callout_takeaway` — the set of components a deck may be built from changes, even though
#: no existing component's geometry moved.
COMPONENT_LIB_VERSION = "0.3.0"

#: Where golden preview PNGs live — the design artifact of record (D5, §6.6). One directory
#: so the preview gallery has somewhere to read from; the registry, not this directory, is
#: what says whether a given component has one.
PREVIEW_DIR = Path(__file__).resolve().parent / "previews"

#: Any non-empty, non-wrapping text. A single line's height in `budgets.wrap_text` depends
#: only on the font's metrics, size and line spacing — never on which characters are in it
#: — so this exists purely to ask "how tall is one line", not to guess real content.
_CALIBRATION_LINE = "Ag"

#: What a slot's real content looks like: one block of prose, or — for a `repeatable`
#: slot — a list of independent, roughly-one-line items.
BlockValue = str | Sequence[str]

SlotBuilder = Callable[[Canvas], Sequence["ComponentSlot"]]
"""Builds one variant's slot geometry against one client's theme."""


class ComponentRenderer(Protocol):
    """What every component's `render` looks like from the registry's side.

    The content argument is the renderer's own dataclass and is deliberately untyped here:
    a registry that insisted on one content type could not hold fifteen different ones.
    `ComponentRegistration.content_type` is what a caller uses to build the right object.
    """

    def __call__(self, slide: Slide, canvas: Canvas, content: Any, /) -> None: ...


class UnknownComponentError(ValueError):
    """No catalog entry for a component, variant or slot name.

    A `KeyError` would read naturally here, but every other unknown-name failure in the
    design system (`layout_kit.Canvas.size`, `draw.theme_color`) raises `ValueError` with
    the valid options listed in the message, and matching that is worth more than the
    marginal precision of a different exception type.
    """


class RegistrationError(ValueError):
    """A registration is malformed, and it says so at import time.

    Most of what `register()` checks could instead be discovered later, by a caller getting
    a confusing answer. Fifteen components are coming and most of them will be registered
    by a cheaper model working from this file's existing entries; a registration that is
    wrong should fail where it is written, not three layers away inside someone's prompt.
    """


@dataclass(frozen=True)
class ComponentSlot:
    """One text slot inside a component: where it sits, and what type-scale role it uses.

    `role` names one of `Canvas.style`'s roles (display/title/heading/body/caption) so a
    slot's type size and default line spacing always come from the theme, never a number
    written here. A slot rendered *off* that role — `big_number`'s figure, at 2x the
    display size — says so through `size_scale`, itself lifted from the renderer's own
    `_FIGURE_SCALE` constant rather than a fresh guess at "how much bigger".
    """

    name: str
    role: str
    box: Box
    face: Literal["major", "minor"] = "minor"
    size_scale: float = 1.0
    bold: bool = False
    italic: bool = False
    """Whether the renderer draws this slot bold and/or italic. Part of the geometry, not
    styling trivia: bold advances are wider (6.1% for Inter Display at 32pt), so a slot
    budgeted as regular but drawn bold passes text that then wraps one line further at
    render — 3a.6's defect, and this field is the half of the fix that lives here. A slot
    whose flags disagree with its renderer's `canvas.style(...)` call reintroduces it, so
    these are read straight off the renderer, exactly like every box in this module."""
    line_spacing: float | None = None
    """Overrides the role's default line spacing when the renderer's own style does — e.g.
    the figure is set at 0.95 rather than the tight 1.15 `display`/`title`/`heading` share.
    `None` means "use whatever `Canvas.style` gives that role", not "single-spaced"."""
    required: bool = True
    repeatable: bool = False
    """True when this slot holds a LIST of independent, roughly-one-line items stacked top
    to bottom — `two_column_compare`'s `points`, `big_number.supporting_points` — rather
    than one block of prose. `box` is then the whole area the stack may use; `item_box` and
    `row_gap` say what one item gets and what separates two of them."""
    item_box: Box | None = None
    """Only set when `repeatable`: the box ONE item may use. Same width as `box`; height is
    one line at this slot's `role`, read the same way every other height in this module is —
    measured, not guessed."""
    row_gap: float = 0.0
    """Vertical gap between stacked items. Only meaningful when `repeatable`; always the
    renderer's own gap constant between rows, never invented here."""

    def style(self, canvas: Canvas) -> TextStyle:
        """The exact `TextStyle` the renderer builds for this slot, from `canvas`'s tokens."""
        style = canvas.style(
            self.role,
            face=self.face,
            scale=self.size_scale,
            bold=self.bold,
            italic=self.italic,
        )
        if self.line_spacing is None:
            return style
        return style.with_(line_spacing=self.line_spacing)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentVariant:
    """One layout a component can take, and how the content selects it.

    The default variant has `when_filled=None`; every other one names the slot whose
    presence switches the component into it. That is the whole mechanism, and it is
    deliberately small: a component with genuinely content-dependent geometry can express
    it, and the generic API stays free of any particular component's vocabulary.
    """

    name: str
    slots: SlotBuilder
    when_filled: str | None = None
    """The slot whose non-empty value selects this variant. `None` marks the default."""
    note: str = ""
    """What changes, in the writer's terms — `render_budgets` shows this in the prompt."""

    @property
    def is_default(self) -> bool:
        return self.when_filled is None


@dataclass(frozen=True)
class ComponentRegistration:
    """Everything the rest of the system needs to know about one component.

    Held in one object so the assembler, the preview gallery and the content prompt read
    one source. See this module's docstring on why that matters more than it looks.
    """

    name: str
    narrative_roles: tuple[str, ...]
    renderer: ComponentRenderer
    content_type: type
    """The dataclass `renderer` takes. Phase 3b's assembler builds one of these per slide;
    without it the assembler needs its own component -> content-class table, which is the
    fourth parallel list this registry exists to prevent."""
    variants: tuple[ComponentVariant, ...]
    preview: Path | None
    """The golden preview PNG (D5's design artifact of record), or `None` for "not yet"."""

    @property
    def default_variant(self) -> ComponentVariant:
        return next(variant for variant in self.variants if variant.is_default)

    @property
    def has_preview(self) -> bool:
        """Whether a golden preview is actually committed, not merely declared."""
        return self.preview is not None and self.preview.exists()

    def variant(self, name: str) -> ComponentVariant:
        for candidate in self.variants:
            if candidate.name == name:
                return candidate
        known = ", ".join(v.name for v in self.variants)
        raise UnknownComponentError(f"{self.name!r} has no variant {name!r}. Known: {known}")

    def variant_for(self, blocks: Mapping[str, BlockValue]) -> ComponentVariant:
        """Which variant this content selects — the first whose trigger slot is filled.

        Declaration order decides, so a component with overlapping triggers has a defined
        answer rather than a dict-ordering one.
        """
        for candidate in self.variants:
            if candidate.when_filled is not None and blocks.get(candidate.when_filled):
                return candidate
        return self.default_variant


@dataclass(frozen=True)
class ComponentSpec:
    """One component's slots, resolved against one client's theme and one variant."""

    component: ComponentRegistration
    variant: str
    slots: tuple[ComponentSlot, ...]

    @property
    def name(self) -> str:
        return self.component.name

    @property
    def narrative_roles(self) -> tuple[str, ...]:
        return self.component.narrative_roles

    @property
    def renderer(self) -> ComponentRenderer:
        return self.component.renderer

    @property
    def preview(self) -> Path | None:
        return self.component.preview

    def slot(self, name: str) -> ComponentSlot:
        for candidate in self.slots:
            if candidate.name == name:
                return candidate
        known = ", ".join(s.name for s in self.slots)
        raise UnknownComponentError(f"{self.name!r} has no slot {name!r}. Known: {known}")


_REGISTRY: dict[str, ComponentRegistration] = {}


def register(
    *,
    name: str,
    narrative_roles: tuple[str, ...],
    renderer: ComponentRenderer,
    content_type: type,
    preview: Path | None,
    slots: SlotBuilder | None = None,
    variants: tuple[ComponentVariant, ...] = (),
) -> ComponentRegistration:
    """Register one component. The only way into the catalog.

    Pass `slots` for the common case of a component with one layout; pass `variants` when
    the layout depends on what the writer fills in (see `ComponentVariant`). `preview` has
    no default: a component author has to say whether a golden PNG exists, because the
    registry is what answers that question for the other fourteen.

    Raises:
        RegistrationError: the name is taken, or the registration is malformed.
    """
    if name in _REGISTRY:
        raise RegistrationError(f"{name!r} is already registered")
    if not narrative_roles:
        raise RegistrationError(
            f"{name!r} declares no narrative role. The outline chooses components by the "
            "job they do; one with no stated job can never be chosen deliberately."
        )
    if (slots is None) == (not variants):
        raise RegistrationError(
            f"{name!r} must declare either `slots` (one layout) or `variants` (several), "
            "not both and not neither."
        )

    resolved = variants or (ComponentVariant(name="default", slots=_required(slots)),)
    defaults = [variant for variant in resolved if variant.is_default]
    if len(defaults) != 1:
        raise RegistrationError(
            f"{name!r} declares {len(defaults)} default variants (those with no "
            "`when_filled`); exactly one is the layout used when nothing selects another."
        )
    for variant in resolved:
        if not variant.is_default and not variant.note:
            raise RegistrationError(
                f"{name!r} variant {variant.name!r} has no note. The note is what tells the "
                "writer how its budgets differ; without one the variant is invisible in the "
                "content prompt and the writer cannot know it is in it."
            )

    entry = ComponentRegistration(
        name=name,
        narrative_roles=narrative_roles,
        renderer=renderer,
        content_type=content_type,
        variants=resolved,
        preview=preview,
    )
    _REGISTRY[name] = entry
    return entry


def _required(slots: SlotBuilder | None) -> SlotBuilder:
    assert slots is not None
    return slots


def known_components() -> list[str]:
    """Every registered component name, sorted."""
    return sorted(_REGISTRY)


def registration(component: str) -> ComponentRegistration:
    """The registry entry for `component`.

    Raises:
        UnknownComponentError: `component` is not in the catalog.
    """
    try:
        return _REGISTRY[component]
    except KeyError:
        raise UnknownComponentError(
            f"no catalog entry for {component!r}. Known: {', '.join(known_components())}"
        ) from None


def renderer_for(component: str) -> ComponentRenderer:
    """The renderer registered for `component` — the assembler's lookup.

    Phase 3b assembles slides through this rather than importing renderer modules, so a new
    component reaches the assembler by being registered and by nothing else.
    """
    return registration(component).renderer


def preview_for(component: str) -> Path | None:
    """The golden preview declared for `component`, committed or not."""
    return registration(component).preview


def components_missing_previews() -> list[str]:
    """Registered components with no golden preview PNG actually committed.

    The question the phase brief needs answerable without looking in a directory: fifteen
    components, most of them written by cheaper models, and "did this one ever get a
    preview committed" must have a mechanical answer.
    """
    return [name for name in known_components() if not _REGISTRY[name].has_preview]


def variant_for(component: str, blocks: Mapping[str, BlockValue]) -> str:
    """Which of `component`'s layouts this content selects.

    The replacement for the old per-component keyword argument: a caller that already holds
    the blocks never has to know a component has variants at all.
    """
    return registration(component).variant_for(blocks).name


def spec_for(
    component: str, tokens: DesignTokens, *, variant: str | None = None
) -> ComponentSpec:
    """Build `component`'s slot geometry for one client's theme.

    Rebuilt on every call rather than cached at import time — see the module docstring.

    Args:
        variant: which layout to build; the component's default when omitted. A caller
            holding real content should use `variant_for` (or `check_overflow`, which does
            it for them) rather than naming a variant.

    Raises:
        UnknownComponentError: no such component, or no such variant of it.
    """
    entry = registration(component)
    chosen = entry.default_variant if variant is None else entry.variant(variant)
    return ComponentSpec(
        component=entry, variant=chosen.name, slots=tuple(chosen.slots(Canvas(tokens)))
    )


# ---------------------------------------------------------------------------
# Slot geometry, read off each renderer's own arithmetic
# ---------------------------------------------------------------------------


def _one_line_height(canvas: Canvas, style: TextStyle, width: float) -> float:
    """The height of exactly one line in `style` at `width`.

    Used only to reserve headroom for a *sibling* slot — never to guess how much text that
    sibling will actually hold. See the module docstring's "where the geometry comes from".
    """
    return canvas.measure(_CALIBRATION_LINE, width, style)


def _big_number_slots(canvas: Canvas, *, with_supporting_points: bool) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/big_number.py` computes for itself.

    Same stacks and gap constants as `render()`, so a slot's box is a read of the renderer's
    own arithmetic. The renderer leaves exactly one thing undetermined until content exists
    — how the space between the caption strip and the slide edge divides between the
    headline and the figure block below it — and that is the one place this function makes
    a policy choice, documented in the module docstring: each of `headline` and `figure`
    gets the most height it could use while still leaving the other room for one line.

    `with_supporting_points` mirrors `render()`'s own branch exactly: the moment
    `supporting_points` is non-empty, the renderer halves the body region into a figure
    column and a points column (`region.split_columns(2, canvas.gutter * 2)`), so `figure`,
    `figure_label` and `support` are each half the width they are otherwise. Getting this
    wrong is the carried finding from reviewing 2b.2 — the catalog had no slot for
    `supporting_points` at all, so the three slots it did declare were silently wrong by
    half in exactly the mode the codebase's own example (`design/spikes.py`) uses. It is a
    parameter of this private builder and not of the public API: the registration below
    binds one variant per value, and no caller ever passes it.
    """
    region, source_area = canvas.body_and_caption()

    headline_style = canvas.style("title", face="major", bold=True)
    figure_style = canvas.style(
        "display",
        face="major",
        scale=big_number._FIGURE_SCALE,
        line_spacing=0.95,
        bold=True,
    )
    label_style = canvas.style("heading")
    point_style = canvas.style("body")

    # The fixed distance `render()` puts between the headline and the figure block: a
    # baseline gap, the rule itself, then a second, larger gap.
    gap_headline_to_body = (
        canvas.baseline * 3 + big_number._RULE_THICKNESS + canvas.baseline * 4
    )

    # The least the figure block ever needs: one line of the figure and one of its label,
    # with no supporting points and no support sentence (the figure stack adds more only
    # when those are present, so this is the true floor, not a typical case). Measured at
    # the full region width: whether a one-line calibration string wraps does not depend on
    # which of the (equal) half-widths it is measured against once columns split, so the
    # reservation is the same either way and only the final boxes' widths differ below.
    min_figure_block = (
        _one_line_height(canvas, figure_style, region.width)
        + canvas.baseline
        + _one_line_height(canvas, label_style, region.width)
    )
    headline_height = max(region.height - gap_headline_to_body - min_figure_block, 0.0)
    headline_box = region.resize(height=headline_height)

    # Mirror image: bound the figure block by assuming the headline takes only one line.
    headline_one_line = _one_line_height(canvas, headline_style, region.width)
    _, body_region = region.split_top(headline_one_line, gutter=gap_headline_to_body)

    # `render()`'s own branch: split into a figure column and a points column, or don't.
    if with_supporting_points:
        content_region, points_region = body_region.split_columns(2, canvas.gutter * 2)
    else:
        content_region, points_region = body_region, None

    figure_one_line = _one_line_height(canvas, figure_style, content_region.width)
    label_one_line = _one_line_height(canvas, label_style, content_region.width)

    figure_height = max(body_region.height - canvas.baseline - label_one_line, 0.0)
    figure_box = content_region.resize(height=figure_height)

    _, after_figure = content_region.split_top(figure_one_line, gutter=canvas.baseline)
    label_box = after_figure  # everything left once the figure has its one reserved line

    _, after_label = after_figure.split_top(label_one_line, gutter=canvas.baseline * 3)
    support_box = after_label  # optional, so it may fairly claim whatever else is left

    slots = [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major", bold=True),
        ComponentSlot(
            name="figure",
            role="display",
            box=figure_box,
            face="major",
            size_scale=big_number._FIGURE_SCALE,
            line_spacing=0.95,
            bold=True,
        ),
        ComponentSlot(name="figure_label", role="heading", box=label_box),
        ComponentSlot(name="support", role="body", box=support_box, required=False),
        ComponentSlot(name="source", role="caption", box=source_area, required=False),
    ]

    if points_region is not None:
        # The bound the renderer itself already guards with: `render()` reserves one band
        # height for both columns out of this function's `body_region`, so
        # `body_region.height` is not invented here — it is the same ceiling the
        # render-time safety net already enforces.
        point_one_line = _one_line_height(canvas, point_style, points_region.width)
        slots.append(
            ComponentSlot(
                name="supporting_points",
                role="body",
                box=points_region.resize(height=body_region.height),
                item_box=points_region.resize(height=point_one_line),
                row_gap=canvas.baseline * 2.5,  # the points stack's own row gap.
                repeatable=True,
                required=False,
            )
        )
    return slots


def _two_column_compare_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/two_column_compare.py` computes for itself.

    Column width and x-position are genuinely fixed by `Box.split_columns` regardless of
    content, so those are copied exactly. Heights use the same "reserve one line for the
    sibling" policy as `_big_number_slots`.

    **`point`'s single-line cap — corrected.** An earlier version of this docstring justified
    capping `point` to one line by claiming a wrapped point would "grow both columns' row at
    once... before the panel-height overflow check ever gets a chance to fire", as if
    wrapping broke row parity. Checked against the renderer, that is not true: `_row_heights`
    measures each row's real height with `canvas.measure` — wrapped or not — and hands it to
    both columns' stacks as that row's `min_height`, so the two sides stay level regardless
    of how many lines a point wraps to. Row parity survives wrapping by construction; it was
    never what the cap protected.

    The cap is kept anyway, on a different and honest justification: a comparison `point` is
    meant to be a scannable phrase, and a point that wraps to a paragraph stops reading as a
    bullet next to its neighbour, cap or no cap. The real content model — `points`, plural,
    several per column — is `left_points`/`right_points` below, and *that* is where the
    carried finding from reviewing 2b.2 lived: multi-point columns had no budget coverage
    at all, singular `point` covering only the single-item case `design/spikes.py` never
    actually exercises alone.
    """
    region, source_area = canvas.body_and_caption()
    left_area, right_area = region.split_columns(2, canvas.gutter * 1.5)

    headline_style = canvas.style("title", face="major", bold=True)
    title_style = canvas.style("heading", bold=True)  # minor face, unlike big_number
    point_style = canvas.style("body")

    padding = two_column_compare._PANEL_PADDING
    inner_width = left_area.width - padding * 2
    text_width = inner_width - MARKER_INSET

    # The column stack's fixed chrome: gap under the title, the rule, gap under the rule.
    chrome = canvas.baseline * 1.5 + two_column_compare._RULE_THICKNESS + canvas.baseline * 3
    point_one_line = _one_line_height(canvas, point_style, text_width)
    title_one_line = _one_line_height(canvas, title_style, inner_width)
    min_column_height = padding * 2 + title_one_line + chrome + point_one_line
    gap_after_headline = canvas.baseline * 5

    headline_height = max(region.height - gap_after_headline - min_column_height, 0.0)
    headline_box = region.resize(height=headline_height)

    headline_one_line = _one_line_height(canvas, headline_style, region.width)
    _, body_area = region.split_top(headline_one_line, gutter=gap_after_headline)

    # `panel_height` in the renderer is the *max* of the two columns' own content heights,
    # and `Box.reserve` measures that max against `body_area.height` — so neither column
    # alone may exceed it either, and both share one height ceiling here.
    title_height = max(body_area.height - padding * 2 - chrome - point_one_line, 0.0)
    # The row stack's own ceiling, symmetric with `title_height` above: title gets the most
    # height it can use while reserving one line for the row stack; the row stack gets the
    # most height it can use while reserving one line for the title. Neither reservation
    # assumes how many rows the writer actually uses — `check_overflow` is what checks the
    # real count, against whichever of `left_points`/`right_points` the writer filled in.
    points_height = max(body_area.height - padding * 2 - chrome - title_one_line, 0.0)

    def title_box(area: Box) -> Box:
        return area.pad(padding).resize(height=title_height)

    def point_box(area: Box) -> Box:
        return area.pad(padding).inset(left=MARKER_INSET).resize(height=point_one_line)

    def points_box(area: Box) -> Box:
        return area.pad(padding).inset(left=MARKER_INSET).resize(height=points_height)

    row_gap = canvas.baseline * 2.5  # the column stack's own gap between rows.

    return [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major", bold=True),
        ComponentSlot(name="left_title", role="heading", box=title_box(left_area), bold=True),
        ComponentSlot(name="right_title", role="heading", box=title_box(right_area), bold=True),
        # Not required: the real content model is `left_points`/`right_points` below, a
        # LIST of several. These singular slots stay for a caller that genuinely has one
        # point, and requiring them would reject a slide that only ever fills the plural
        # form.
        ComponentSlot(name="left_point", role="body", box=point_box(left_area), required=False),
        ComponentSlot(
            name="right_point", role="body", box=point_box(right_area), required=False
        ),
        ComponentSlot(
            name="left_points",
            role="body",
            box=points_box(left_area),
            item_box=point_box(left_area),
            row_gap=row_gap,
            repeatable=True,
            required=False,
        ),
        ComponentSlot(
            name="right_points",
            role="body",
            box=points_box(right_area),
            item_box=point_box(right_area),
            row_gap=row_gap,
            repeatable=True,
            required=False,
        ),
        ComponentSlot(name="source", role="caption", box=source_area, required=False),
    ]


def _quote_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/quote.py` computes for itself.

    Same headline-and-rule chrome as `_big_number_slots` and
    `_two_column_compare_slots` (`gap_headline_to_body` is the identical
    `baseline*3 + rule_thickness + baseline*4` formula in all three), then a second block
    of `[mark, quote, attribution]`. The mark is `quote.py`'s own decorative glyph — not a
    `QuoteContent` field, so it carries no slot of its own — and its height is reserved as
    fixed chrome the same way the rule's thickness is.
    """
    region, source_area = canvas.body_and_caption()

    headline_style = canvas.style("title", face="major", bold=True)
    quote_style = canvas.style(
        "title", face="major", scale=quote._QUOTE_SCALE, line_spacing=1.15, italic=True
    )
    attribution_style = canvas.style("heading")
    mark_style = canvas.style("display", face="major", line_spacing=0.9, bold=True)

    gap_headline_to_body = canvas.baseline * 3 + quote._RULE_THICKNESS + canvas.baseline * 4
    gap_mark_to_quote = canvas.baseline * 2
    gap_quote_to_attribution = canvas.baseline * 3

    mark_one_line = _one_line_height(canvas, mark_style, region.width)
    quote_one_line = _one_line_height(canvas, quote_style, region.width)
    attribution_one_line = _one_line_height(canvas, attribution_style, region.width)

    # The least the quote block ever needs: the mark, one line of the quote, and one line
    # of the attribution, with `render()`'s own gaps between them — the same "assume every
    # sibling takes only its floor" bound `_big_number_slots` uses for its headline/figure
    # pair.
    min_quote_block = (
        mark_one_line
        + gap_mark_to_quote
        + quote_one_line
        + gap_quote_to_attribution
        + attribution_one_line
    )
    headline_height = max(region.height - gap_headline_to_body - min_quote_block, 0.0)
    headline_box = region.resize(height=headline_height)

    headline_one_line = _one_line_height(canvas, headline_style, region.width)
    _, quote_region = region.split_top(headline_one_line, gutter=gap_headline_to_body)

    # Mirror image: bound the quote block by assuming the headline takes only one line.
    _, after_mark = quote_region.split_top(mark_one_line, gutter=gap_mark_to_quote)
    quote_height = max(after_mark.height - gap_quote_to_attribution - attribution_one_line, 0.0)
    quote_box = after_mark.resize(height=quote_height)
    _, attribution_box = after_mark.split_top(quote_one_line, gutter=gap_quote_to_attribution)

    return [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major", bold=True),
        ComponentSlot(
            name="quote",
            role="title",
            box=quote_box,
            face="major",
            size_scale=quote._QUOTE_SCALE,
            line_spacing=1.15,
            italic=True,
        ),
        ComponentSlot(name="attribution", role="heading", box=attribution_box),
        ComponentSlot(name="source", role="caption", box=source_area, required=False),
    ]


def _bullets_supporting_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/bullets_supporting.py` computes for itself.

    The single-column counterpart to `_two_column_compare_slots`: one headline band (same
    chrome formula as every other component here) and one repeatable `points` slot below
    it, with no partner column to keep row parity with.
    """
    region, source_area = canvas.body_and_caption()

    headline_style = canvas.style("title", face="major", bold=True)
    point_style = canvas.style("body")

    gap_headline_to_body = (
        canvas.baseline * 3 + bullets_supporting._RULE_THICKNESS + canvas.baseline * 4
    )
    point_one_line = _one_line_height(canvas, point_style, region.width)

    headline_height = max(region.height - gap_headline_to_body - point_one_line, 0.0)
    headline_box = region.resize(height=headline_height)

    headline_one_line = _one_line_height(canvas, headline_style, region.width)
    _, points_region = region.split_top(headline_one_line, gutter=gap_headline_to_body)

    return [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major", bold=True),
        ComponentSlot(
            name="points",
            role="body",
            box=points_region,
            item_box=points_region.resize(height=point_one_line),
            row_gap=canvas.baseline * 3,
            repeatable=True,
        ),
        ComponentSlot(name="source", role="caption", box=source_area, required=False),
    ]


def _callout_takeaway_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/callout_takeaway.py` computes for itself.

    A single stack, unlike every other component registered so far: `render()` places one
    `Stack` holding `label`, `takeaway` and the optional `support` line, centred inside the
    padded panel, with no separate headline band above it (see the renderer's own
    docstring for why). `label` is capped to one line on purpose — the same policy
    `_two_column_compare_slots`' `point` slots use: an eyebrow tag that wraps to a
    paragraph stops reading as a tag.
    """
    body, source_area = canvas.body_and_caption()
    inner = body.pad(callout_takeaway._PANEL_PADDING)

    label_style = canvas.style("caption", bold=True)
    takeaway_style = canvas.style("title", face="major", line_spacing=1.15, bold=True)
    support_style = canvas.style("body")

    gap_label_to_takeaway = canvas.baseline * 2
    gap_takeaway_to_support = canvas.baseline * 3

    label_one_line = _one_line_height(canvas, label_style, inner.width)
    takeaway_one_line = _one_line_height(canvas, takeaway_style, inner.width)
    support_one_line = _one_line_height(canvas, support_style, inner.width)

    label_box = inner.resize(height=label_one_line)
    _, after_label = inner.split_top(label_one_line, gutter=gap_label_to_takeaway)

    # Symmetric bound, same shape as `_big_number_slots`' headline/figure pair: `takeaway`
    # gets the most height it could use while still leaving `support` one line, and vice
    # versa. Neither reservation assumes `support` is actually present — it is optional, so
    # an absent line simply leaves the takeaway with more room than the budget claims,
    # never less.
    takeaway_height = max(after_label.height - gap_takeaway_to_support - support_one_line, 0.0)
    takeaway_box = after_label.resize(height=takeaway_height)
    _, support_box = after_label.split_top(takeaway_one_line, gutter=gap_takeaway_to_support)

    return [
        ComponentSlot(name="label", role="caption", box=label_box, bold=True),
        ComponentSlot(
            name="takeaway",
            role="title",
            box=takeaway_box,
            face="major",
            line_spacing=1.15,
            bold=True,
        ),
        ComponentSlot(name="support", role="body", box=support_box, required=False),
        ComponentSlot(name="source", role="caption", box=source_area, required=False),
    ]


def _title_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/title.py` computes for itself."""
    body, _source_area = canvas.body_and_caption()

    title_style = canvas.style("display", face="major", bold=True)
    subtitle_style = canvas.style("title", face="minor")

    # The main content area is a panel with padding
    inner = body.pad(title._PANEL_PADDING)

    title_one_line = _one_line_height(canvas, title_style, inner.width)
    subtitle_one_line = _one_line_height(canvas, subtitle_style, inner.width)

    # Title gets most of the space; subtitle and footer share what's left
    title_height = max(
        inner.height - subtitle_one_line - canvas.baseline * 3,
        title_one_line * 2,
    )
    title_box = inner.resize(height=title_height)
    _, after_title = inner.split_top(title_height, gutter=canvas.baseline * 3)
    subtitle_box = after_title.resize(height=subtitle_one_line)

    return [
        ComponentSlot(name="title", role="display", box=title_box, face="major", bold=True),
        ComponentSlot(name="subtitle", role="title", box=subtitle_box, required=False),
        ComponentSlot(name="presenter", role="body", box=after_title, required=False),
        ComponentSlot(name="date", role="body", box=after_title, required=False),
    ]


def _section_divider_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/section_divider.py` computes for itself."""
    body, _source_area = canvas.body_and_caption()

    number_style = canvas.style("title", face="major", bold=True)
    name_style = canvas.style("heading", face="major", bold=True)

    # Centered stack at 80% of body width
    stack_width = body.width * 0.8
    number_height = _one_line_height(canvas, number_style, stack_width)
    name_height = _one_line_height(canvas, name_style, stack_width)

    # Reserve space for rule and gaps
    rule_gap = canvas.baseline * 3
    total_height = (
        number_height + rule_gap + section_divider._RULE_THICKNESS + rule_gap + name_height
    )

    # Allocate the space
    number_box = body.resize(height=number_height)
    _, after_number = body.split_top(total_height, gutter=0.0)

    return [
        ComponentSlot(
            name="section_number", role="title", box=number_box, face="major", bold=True
        ),
        ComponentSlot(
            name="section_name", role="heading", box=after_number, face="major", bold=True
        ),
    ]


def _agenda_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/agenda.py` computes for itself."""
    body, _source_area = canvas.body_and_caption()

    headline_style = canvas.style("title", face="major", bold=True)
    items_style = canvas.style("body")

    # Headline block
    headline_one_line = _one_line_height(canvas, headline_style, body.width)
    gap_headline_to_body = canvas.baseline * 3 + agenda._RULE_THICKNESS + canvas.baseline * 4

    # Items area — reserve space for up to 5 items
    item_one_line = _one_line_height(canvas, items_style, body.width)
    max_items = 5
    items_height = item_one_line * max_items + canvas.baseline * 2.5 * (max_items - 1)

    headline_height = max(body.height - gap_headline_to_body - items_height, headline_one_line)
    headline_box = body.resize(height=headline_height)
    _, items_area = body.split_top(headline_height, gutter=gap_headline_to_body)

    return [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major", bold=True),
        ComponentSlot(
            name="items",
            role="body",
            box=items_area,
            repeatable=True,
            item_box=items_area.resize(height=item_one_line),
            row_gap=canvas.baseline * 2.5,
        ),
    ]


def _closing_cta_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/closing_cta.py` computes for itself."""
    body, _source_area = canvas.body_and_caption()

    headline_style = canvas.style("title", face="major", bold=True)
    cta_style = canvas.style("heading", face="major", bold=True)

    # Headline block
    headline_one_line = _one_line_height(canvas, headline_style, body.width)
    gap_headline_to_body = (
        canvas.baseline * 3 + closing_cta._RULE_THICKNESS + canvas.baseline * 4
    )

    # CTA area — reserve space for 1-2 lines
    cta_one_line = _one_line_height(
        canvas, cta_style, body.width - closing_cta._PANEL_PADDING * 2
    )
    cta_height = cta_one_line * 2 + closing_cta._PANEL_PADDING * 2

    headline_height = max(body.height - gap_headline_to_body - cta_height, headline_one_line)
    headline_box = body.resize(height=headline_height)
    _, cta_area = body.split_top(headline_height, gutter=gap_headline_to_body)

    return [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major", bold=True),
        ComponentSlot(
            name="cta",
            role="heading",
            box=cta_area.resize(height=cta_height),
            face="major",
            bold=True,
        ),
    ]


def _before_after_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/before_after.py` computes for itself."""
    body, _source_area = canvas.body_and_caption()

    headline_style = canvas.style("title", face="major", bold=True)
    label_style = canvas.style("heading", bold=True)

    # Headline block
    headline_one_line = _one_line_height(canvas, headline_style, body.width)
    gap_headline_to_body = canvas.baseline * 5

    # Split into before/after columns
    _, body_region = body.split_top(headline_one_line, gutter=gap_headline_to_body)
    before_area, after_area = body_region.split_columns(2, canvas.gutter * 1.5)

    # Each column has: label, rule, and text
    col_width = before_area.width - before_after._PANEL_PADDING * 2
    label_height = _one_line_height(canvas, label_style, col_width)
    text_height = (
        body_region.height - label_height - before_after._RULE_THICKNESS - canvas.baseline * 3.5
    )

    headline_box = body.resize(height=headline_one_line)

    return [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major", bold=True),
        ComponentSlot(name="before_label", role="heading", box=before_area, bold=True),
        ComponentSlot(
            name="before_text",
            role="body",
            box=before_area.resize(height=text_height),
        ),
        ComponentSlot(name="after_label", role="heading", box=after_area, bold=True),
        ComponentSlot(
            name="after_text",
            role="body",
            box=after_area.resize(height=text_height),
        ),
    ]


def _evidence_with_figure_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/evidence_with_figure.py` computes for itself."""
    body, source_area = canvas.body_and_caption()

    headline_style = canvas.style("title", face="major", bold=True)

    # Headline block
    headline_one_line = _one_line_height(canvas, headline_style, body.width)
    gap_headline_to_body = (
        canvas.baseline * 3 + evidence_with_figure._RULE_THICKNESS + canvas.baseline * 4
    )

    # Split into text and figure columns
    _, body_region = body.split_top(headline_one_line, gutter=gap_headline_to_body)
    text_area, figure_area = body_region.split_columns(2, canvas.gutter * 2)

    headline_box = body.resize(height=headline_one_line)

    return [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major", bold=True),
        ComponentSlot(name="supporting_text", role="body", box=text_area),
        ComponentSlot(name="figure", role="body", box=figure_area, required=False, italic=True),
        ComponentSlot(name="source", role="caption", box=source_area, required=False),
    ]


def _data_card_grid_slots(canvas: Canvas) -> list[ComponentSlot]:
    """Reconstruct the boxes `renderers/data_card_grid.py` computes for itself."""
    body, _source_area = canvas.body_and_caption()

    headline_style = canvas.style("title", face="major", bold=True)

    # Headline block
    headline_one_line = _one_line_height(canvas, headline_style, body.width)
    gap_headline_to_body = canvas.baseline * 4

    # Grid of 2x3 (6 cards)
    _, _body_region = body.split_top(headline_one_line, gutter=gap_headline_to_body)

    # Cards are not treated as a repeatable slot in the budget sense — they are part of a
    # grid structure that the renderer handles entirely. Each card is small and fixed-size,
    # so the slot just reserves the whole region for the grid.
    headline_box = body.resize(height=headline_one_line)

    # Create slots for the headline and the grid region
    return [
        ComponentSlot(name="headline", role="title", box=headline_box, face="major", bold=True),
    ]


# ---------------------------------------------------------------------------
# The registrations
# ---------------------------------------------------------------------------

register(
    name="big_number",
    narrative_roles=("headline metric", "single-figure proof point"),
    renderer=big_number.render,
    content_type=big_number.BigNumberContent,
    preview=PREVIEW_DIR / "big_number.png",
    variants=(
        ComponentVariant(
            name="default",
            slots=lambda canvas: _big_number_slots(canvas, with_supporting_points=False),
        ),
        ComponentVariant(
            name="with_supporting_points",
            slots=lambda canvas: _big_number_slots(canvas, with_supporting_points=True),
            when_filled="supporting_points",
            note=(
                "figure/figure_label/support share the slide with them in two columns and "
                "are NARROWER than the widths above"
            ),
        ),
    ),
)

register(
    name="two_column_compare",
    narrative_roles=("comparison", "recommendation"),
    renderer=two_column_compare.render,
    content_type=two_column_compare.TwoColumnCompareContent,
    preview=PREVIEW_DIR / "two_column_compare.png",
    slots=_two_column_compare_slots,
)

register(
    name="quote",
    narrative_roles=("third-party validation", "testimonial"),
    renderer=quote.render,
    content_type=quote.QuoteContent,
    preview=PREVIEW_DIR / "quote.png",
    slots=_quote_slots,
)

register(
    name="bullets_supporting",
    narrative_roles=("supporting evidence", "headline argument"),
    renderer=bullets_supporting.render,
    content_type=bullets_supporting.BulletsSupportingContent,
    preview=PREVIEW_DIR / "bullets_supporting.png",
    slots=_bullets_supporting_slots,
)

register(
    name="callout_takeaway",
    narrative_roles=("single takeaway", "section close"),
    renderer=callout_takeaway.render,
    content_type=callout_takeaway.CalloutTakeawayContent,
    preview=PREVIEW_DIR / "callout_takeaway.png",
    slots=_callout_takeaway_slots,
)

register(
    name="title",
    narrative_roles=("deck introduction",),
    renderer=title.render,
    content_type=title.TitleContent,
    preview=PREVIEW_DIR / "title.png",
    slots=_title_slots,
)

register(
    name="section_divider",
    narrative_roles=("section break",),
    renderer=section_divider.render,
    content_type=section_divider.SectionDividerContent,
    preview=PREVIEW_DIR / "section_divider.png",
    slots=_section_divider_slots,
)

register(
    name="agenda",
    narrative_roles=("structure outline", "roadmap"),
    renderer=agenda.render,
    content_type=agenda.AgendaContent,
    preview=PREVIEW_DIR / "agenda.png",
    slots=_agenda_slots,
)

register(
    name="closing_cta",
    narrative_roles=("call to action", "closing statement"),
    renderer=closing_cta.render,
    content_type=closing_cta.ClosingCtaContent,
    preview=PREVIEW_DIR / "closing_cta.png",
    slots=_closing_cta_slots,
)

register(
    name="before_after",
    narrative_roles=("transformation", "evolution", "comparison"),
    renderer=before_after.render,
    content_type=before_after.BeforeAfterContent,
    preview=PREVIEW_DIR / "before_after.png",
    slots=_before_after_slots,
)

register(
    name="evidence_with_figure",
    narrative_roles=("evidence", "claim with proof"),
    renderer=evidence_with_figure.render,
    content_type=evidence_with_figure.EvidenceWithFigureContent,
    preview=PREVIEW_DIR / "evidence_with_figure.png",
    slots=_evidence_with_figure_slots,
)

register(
    name="data_card_grid",
    narrative_roles=("metrics", "key figures"),
    renderer=data_card_grid.render,
    content_type=data_card_grid.DataCardGridContent,
    preview=PREVIEW_DIR / "data_card_grid.png",
    slots=_data_card_grid_slots,
)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def _budget(slot: ComponentSlot, tokens: DesignTokens) -> SlotBudget:
    """The `SlotBudget` for a whole (non-repeatable) slot's own box."""
    style = slot.style(Canvas(tokens))
    return compute_budget(
        slot=slot.name,
        family=style.family,
        size_pt=style.size,
        width_pt=slot.box.width,
        height_pt=slot.box.height,
        line_spacing=style.line_spacing,
        bold=style.bold,
        italic=style.italic,
    )


def _item_budget(slot: ComponentSlot, tokens: DesignTokens) -> SlotBudget:
    """The `SlotBudget` for ONE item of a `repeatable` slot.

    This, not `_budget`, is the number a writer composing a single bullet needs — `_budget`
    on a repeatable slot's own `box` would describe the whole stack's height as if it were
    one line's budget, which no single item is meant to fill alone.
    """
    assert slot.item_box is not None, f"{slot.name!r} is not repeatable"
    style = slot.style(Canvas(tokens))
    return compute_budget(
        slot=f"{slot.name} (each item)",
        family=style.family,
        size_pt=style.size,
        width_pt=slot.item_box.width,
        height_pt=slot.item_box.height,
        line_spacing=style.line_spacing,
        bold=style.bold,
        italic=style.italic,
    )


def _max_items(slot: ComponentSlot) -> int:
    """How many items fit in a repeatable slot's stack, gaps included.

    `n` items need `n * item_height + (n - 1) * row_gap`; solving that for the box's own
    height gives the floor below. Used only to tell the writer a number it can hold in its
    head — `check_overflow` re-derives the same bound from the real item count it is given,
    rather than trusting this estimate.
    """
    assert slot.item_box is not None, f"{slot.name!r} is not repeatable"
    row = slot.item_box.height + slot.row_gap
    if row <= 0:
        return 0
    return max(int((slot.box.height + slot.row_gap + 1e-6) // row), 0)


def budget_for(
    component: str, slot: str, tokens: DesignTokens, *, variant: str | None = None
) -> SlotBudget:
    """The `SlotBudget` for one named slot of `component`, under `tokens`.

    For a `repeatable` slot this is the **per-item** budget (see `_item_budget`), since that
    is the constraint a writer composing one bullet actually needs.

    Raises:
        UnknownComponentError: no such component, variant or slot.
    """
    resolved = spec_for(component, tokens, variant=variant).slot(slot)
    return _item_budget(resolved, tokens) if resolved.repeatable else _budget(resolved, tokens)


def render_budgets(component: str, tokens: DesignTokens) -> str:
    """A compact block naming every slot's limit, ready to paste into the content prompt.

    §6.7: budgets reach the writer as explicit limits in its prompt, in terms it can hold
    in its head while writing — max characters and max lines, which is what `SlotBudget`
    already exposes through `describe()`. This function only has to assemble them.

    The default variant's slots come first. Each other variant then contributes only the
    slots it actually changes, under a line naming what the writer would have to write to
    end up in it — because the writer selects the variant by what it writes, not by reading
    a flag it cannot see. *Which* slots those are is computed rather than listed: a
    hand-written list of affected slots stays correct right up until a variant's geometry
    changes, and then silently does not.
    """
    entry = registration(component)
    default = spec_for(component, tokens)

    lines = [f"{component} text budgets:"]
    lines.extend(
        f"- {_describe_slot(slot, tokens)}{_optional_tag(slot)}" for slot in default.slots
    )

    for variant in entry.variants:
        if variant.is_default:
            continue
        changed = _changed_slots(spec_for(component, tokens, variant=variant.name), default)
        if not changed:
            continue
        lines.append(f"if you write {variant.when_filled}: {variant.note}:")
        lines.extend(
            f"  - {_describe_slot(slot, tokens)}{_optional_tag(slot)}" for slot in changed
        )
    return "\n".join(lines)


def _changed_slots(spec: ComponentSpec, default: ComponentSpec) -> list[ComponentSlot]:
    """The slots this variant adds or moves, relative to the default layout."""
    by_name = {slot.name: slot for slot in default.slots}
    return [slot for slot in spec.slots if by_name.get(slot.name) != slot]


def _describe_slot(slot: ComponentSlot, tokens: DesignTokens) -> str:
    if not slot.repeatable:
        return _budget(slot, tokens).describe()
    item = _item_budget(slot, tokens)
    return (
        f"{slot.name}: a LIST of items, up to {_max_items(slot)} of them, each at most "
        f"{item.max_lines} line(s), roughly {item.max_chars} characters, at "
        f"{item.size_pt:g}pt {item.family}"
    )


def _optional_tag(slot: ComponentSlot) -> str:
    return "" if slot.required else " (optional)"


# ---------------------------------------------------------------------------
# The deterministic pre-render gate
# ---------------------------------------------------------------------------


#: The exact tail every "missing/empty required slot" finding ends with, shared by the
#: non-repeatable and repeatable branches below. `is_missing_slot_finding` is the documented
#: way to test for it — a caller has no business re-deriving this string itself.
_MISSING_SLOT_SUFFIX = "required slot is missing or empty"


def is_missing_slot_finding(finding: str) -> bool:
    """True for a `check_overflow` finding that reports a required slot with nothing in it,
    as opposed to one reporting content the writer wrote that does not fit.

    `check_overflow` deliberately returns both kinds in one list (see its own docstring for
    why), but they are different events and a caller that needs to tell them apart — content
    dropped for being too long, versus content that was never written at all — should use
    this rather than re-parsing the finding text itself, which is exactly the fragile
    string-matching this function exists to centralise. `autodeck.agents.content` is the
    caller that needs the split, to keep `ContentResult.rejections` meaning "the writer wrote
    something that did not fit" and not also "the writer left an optional-to-this-call slot
    blank".
    """
    return finding.endswith(f": {_MISSING_SLOT_SUFFIX}")


def check_overflow(
    blocks: Mapping[str, BlockValue], component: str, tokens: DesignTokens
) -> list[str]:
    """One finding per slot of `component` that is wrong for render: either its written
    content does not fit its budget, or it is required and nothing was written for it.

    Returns findings rather than raising: the brief requires overflow to be rejected before
    render, but *how* — block the whole build, send one slide back, retry the writer — is
    an orchestrator decision, and Phase 2b's orchestrator wiring is a later task. This
    function only has to be right about which slots are wrong.

    **These are two different kinds of finding, sharing one list.** An *overflow* finding
    means the writer wrote something for the slot and it does not fit; render would have to
    truncate or shrink it, which nothing here does. A *missing-slot* finding
    (`is_missing_slot_finding` is true of it) means the writer wrote nothing for a slot
    render cannot proceed without — an omitted headline is not "zero overflow", it is a
    different failure this gate also has to catch, but it did not cause anything to be
    dropped, because there was nothing to drop. Reporting both in one list is deliberate:
    both must block render, and this function's job is only to be right about which slots
    are wrong, not to decide how a caller should file the two kinds. A caller that needs to
    tell them apart — `autodeck.agents.content._check_budgets` does, so that "the writer
    wrote something that didn't fit" and "the writer left this slot blank" land in separate
    `ContentResult` fields rather than one undifferentiated rejection count — should split
    the list with `is_missing_slot_finding`, not by re-parsing the finding text itself.

    The component's own variant rules decide which geometry the slots are checked against
    (`ComponentRegistration.variant_for`), so a caller handing over real content never has
    to know the component has modes at all.

    A `repeatable` slot's value is a `Sequence[str]`: each item is checked against the
    slot's per-item budget, and the whole list's stacked height (items plus the gaps between
    them) is checked against the slot's own box — the aggregate check the singular `point`
    slots never had, which is the carried finding this function closes.
    """
    spec = spec_for(component, tokens, variant=variant_for(component, blocks))
    findings: list[str] = []
    for slot in spec.slots:
        value = blocks.get(slot.name)
        if slot.repeatable:
            findings.extend(_check_repeatable(component, slot, value, tokens))
            continue
        text = value if isinstance(value, str) else None
        if not text:
            if slot.required:
                findings.append(f"{component}.{slot.name}: {_MISSING_SLOT_SUFFIX}")
            continue
        budget = _budget(slot, tokens)
        if not budget.fits(text):
            findings.append(
                f"{component}.{slot.name}: {len(text)} characters does not fit "
                f"({budget.describe()})"
            )
    return findings


def _items_of(value: BlockValue | None) -> list[str]:
    """Normalise a repeatable slot's value to a list, tolerating a bare string as one item."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [item for item in value if item]


def _check_repeatable(
    component: str, slot: ComponentSlot, value: BlockValue | None, tokens: DesignTokens
) -> list[str]:
    assert slot.item_box is not None, f"{slot.name!r} is not repeatable"
    items = _items_of(value)
    if not items:
        if slot.required:
            return [f"{component}.{slot.name}: {_MISSING_SLOT_SUFFIX}"]
        return []

    item_budget = _item_budget(slot, tokens)
    findings = [
        f"{component}.{slot.name}[{index}]: {len(item)} characters does not fit "
        f"({item_budget.describe()})"
        for index, item in enumerate(items)
        if not item_budget.fits(item)
    ]

    total_height = len(items) * slot.item_box.height + max(len(items) - 1, 0) * slot.row_gap
    if total_height > slot.box.height + 1e-6:
        findings.append(
            f"{component}.{slot.name}: {len(items)} item(s) need {total_height:.0f}pt "
            f"stacked but only {slot.box.height:.0f}pt is available"
        )
    return findings
