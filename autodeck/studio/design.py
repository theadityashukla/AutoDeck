"""The design system as an artifact, its palette check, and the tokens it renders with
(Phase 2-3; plan §7.2, P5).

A **design system** is decided once, before slides are composed, because the slide bench
showed that eight separately designed slides read as one deck only when they share one
(`bench/slides/results/README.md`). It is a versioned artifact in the engagement:

    <engagement>/design_systems/<system id>/v0001.json, v0002.json, ...

Each version is a `DesignSystem`, written once and never rewritten. A deck refers to one
version (`models.DesignSystemRef`, which also carries a copy of the palette so rendering is
a pure function of the deck). A new engagement is in the **default system**
(`models.DEFAULT_SYSTEM_ID` version 1): the base tokens' palette, no stated concept,
provisional. It is built in memory (`default_design_system`) and never stored.

**Three objects, three owners.**

* `DesignDirection` (L1, the lead): a name, the concept in a sentence or two, and three to
  five rules. Words only: no colour.
* `DesignDraft` (L2, the system layer, `system_layer.py`): the direction made concrete: a
  palette (hex per slot), what each slot is for (`roles`), the slide background slot, and
  the text pairs the roles allow (`text_pairs`). Every draft is checked by code
  (`check_palette`) before it is accepted.
* `DesignSystem`: a draft stored as one version, with an id, a version and a marker.

**The palette check** (`check_palette`) is the contrast rule of layout QA applied to the
palette itself, so a palette that would make every slide fail is refused before any slide
is composed in it: every declared text pair must reach 4.5:1 (3:1 for a pair declared
large-text only), at least one normal-size pair must sit on the background, and `dk2` must
reach 4.5:1 on the background, because v2 draws every chart's labels in `dk2`.

**Tokens.** Rendering and layout QA take `DesignTokens`. A system's tokens are the base
tokens (`config/studio.yaml`'s `tokens` file) with the ten colour slots replaced by its
palette (`design_tokens`); fonts, sizes and spacing never change (only installed fonts can
be measured). The bench did the same (`tokens_for_concept`).

Implementer: everything above the marker line is lead-owned (models and constants);
implement the functions and `DesignSystemStore` below it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from pydantic import AwareDatetime, Field, model_validator

from autodeck.design.theme.tokens import DesignTokens
from autodeck.ir.models import ColorToken
from autodeck.studio.models import (
    COLOR_SLOTS,
    DEFAULT_SYSTEM_ID,
    DEFAULT_SYSTEM_VERSION,
    SEGMENT_PATTERN,
    DeckArtifact,
    DesignPalette,
    DesignSystemRef,
    Marker,
    StudioModel,
)

MAX_NAME_CHARS = 60
MAX_CONCEPT_CHARS = 400
MAX_RULE_CHARS = 300
MIN_RULES = 3
MAX_RULES = 5

CONTRAST_TEXT = 4.5
"""WCAG AA for normal text; v2's `free_layout.CONTRAST_NORMAL`."""
CONTRAST_LARGE = 3.0
"""For text 24pt and above; v2's `free_layout.CONTRAST_LARGE`."""

CHART_LABEL_SLOT = "dk2"
"""v2's chart code draws axis and value labels in `dk2`, on whatever is behind the chart."""

DEFAULT_SYSTEM_NAME = "Default"
DEFAULT_MADE_BY = "default"
"""`DesignSystem.made_by` of the default system: no model made it."""

DEFAULT_TEXT_PAIRS: tuple[tuple[str, str], ...] = (("dk1", "lt1"), ("dk2", "lt1"))
"""The default system's declared text pairs: dark text on the white background."""


def _one_line(value: str, what: str) -> None:
    if not value.strip() or "\n" in value or "\r" in value:
        raise ValueError(f"{what} must be one non-blank line")


class DesignDirection(StudioModel):
    """A design direction in words (L1): what the lead proposes or adopts. No colour."""

    name: str = Field(
        min_length=1,
        max_length=MAX_NAME_CHARS,
        description="Two or three words.",
    )
    concept: str = Field(
        min_length=1,
        max_length=MAX_CONCEPT_CHARS,
        description="The visual idea in one or two sentences: what every slide is built "
        "around. Words, never colours by hex.",
    )
    rules: list[str] = Field(
        min_length=MIN_RULES,
        max_length=MAX_RULES,
        description="Three to five short rules every slide follows (what the background "
        "is, what marks the one thing that matters, what the deck never does).",
    )

    @model_validator(mode="after")
    def _plain(self) -> DesignDirection:
        _one_line(self.name, "a design name")
        for rule in self.rules:
            _one_line(rule, "a design rule")
            if len(rule) > MAX_RULE_CHARS:
                raise ValueError(f"a design rule is at most {MAX_RULE_CHARS} characters")
        return self


class TextPair(StudioModel):
    """One declared use of a slot as text on a ground: `text` on `ground`. `large_only`
    declares the pair safe only at 24pt and above (3:1 instead of 4.5:1)."""

    text: ColorToken
    ground: ColorToken
    large_only: bool = False

    @model_validator(mode="after")
    def _distinct(self) -> TextPair:
        if self.text == self.ground:
            raise ValueError(f"text pair {self.text} on {self.ground}: a slot on itself")
        return self


class DesignDraft(StudioModel):
    """A direction made concrete by the system layer (L2): palette, roles, background and
    the text pairs the roles allow. Not yet stored; not yet checked unless it came from
    `system_layer.make_design` (which only returns drafts that pass `check_palette`).

    Structural rules (validated here): `roles` names only colour slots, and every slot has a
    role; `background` has a role; at least one text pair sits on `background` and is not
    `large_only`; pairs do not repeat.
    """

    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    concept: str = Field(default="", max_length=MAX_CONCEPT_CHARS)
    rules: list[str] = Field(default_factory=list, max_length=MAX_RULES)
    palette: DesignPalette
    roles: dict[str, str] = Field(description="Colour slot -> what it is for, in words.")
    background: ColorToken = Field(description="The slot every slide's background uses.")
    text_pairs: list[TextPair] = Field(min_length=1)
    made_by: str = Field(min_length=1, description="The model id that made it, or 'default'.")

    @model_validator(mode="after")
    def _structure(self) -> DesignDraft:
        unknown = sorted(set(self.roles) - set(COLOR_SLOTS))
        if unknown:
            raise ValueError(f"roles name unknown colour slots: {', '.join(unknown)}")
        missing = [slot for slot in COLOR_SLOTS if not self.roles.get(slot, "").strip()]
        if missing and self.made_by != DEFAULT_MADE_BY:
            raise ValueError(f"every colour slot needs a role; missing: {', '.join(missing)}")
        on_ground = [p for p in self.text_pairs if p.ground == self.background]
        if not any(not p.large_only for p in on_ground):
            raise ValueError(
                f"no normal-size text colour is declared on the background {self.background}"
            )
        keys = [(p.text, p.ground) for p in self.text_pairs]
        if len(set(keys)) != len(keys):
            raise ValueError("a text pair is declared twice")
        return self

    def preview_ref(self, ref_id: str) -> DesignSystemRef:
        """A reference that renders in this draft's palette, for previews of a proposal
        option (`previews.request_proposal`): `DesignSystemRef(id=ref_id, version=1,
        marker="provisional", palette=self.palette)`. Only the palette is read from it."""
        return DesignSystemRef(id=ref_id, version=1, marker="provisional", palette=self.palette)


class DesignSystem(StudioModel):
    """One stored version of a design system: a draft with an id, a version and a marker.

    `created_at` is None only for the in-memory default system. `id` is a safe path segment
    and never `models.DEFAULT_SYSTEM_ID` for a stored version.
    """

    schema_version: int = 1
    id: str = Field(pattern=SEGMENT_PATTERN)
    version: int = Field(ge=1)
    marker: Marker = "provisional"
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    concept: str = Field(default="", max_length=MAX_CONCEPT_CHARS)
    rules: list[str] = Field(default_factory=list, max_length=MAX_RULES)
    palette: DesignPalette
    roles: dict[str, str] = Field(default_factory=dict)
    background: ColorToken = "lt1"
    text_pairs: list[TextPair] = Field(min_length=1)
    made_by: str = Field(min_length=1)
    created_at: AwareDatetime | None = None

    @property
    def is_default(self) -> bool:
        return self.id == DEFAULT_SYSTEM_ID

    def ref(self, *, marker: Marker | None = None) -> DesignSystemRef:
        """`DesignSystemRef(id, version, marker=marker or self.marker, palette=palette)`:
        what a deck stores to be in this system."""
        return DesignSystemRef(
            id=self.id, version=self.version, marker=marker or self.marker, palette=self.palette
        )

    def draft(self) -> DesignDraft:
        """The draft fields of this version (for re-checking or re-adding)."""
        return DesignDraft(
            name=self.name,
            concept=self.concept,
            rules=list(self.rules),
            palette=self.palette,
            roles=dict(self.roles),
            background=self.background,
            text_pairs=list(self.text_pairs),
            made_by=self.made_by,
        )


@dataclass(frozen=True)
class PaletteFinding:
    """One contrast that fails: `text` on `ground` measured `ratio`, needs `needed`.
    `why` is `"text pair"`, `"large text pair"` or `"charts draw labels in dk2"`."""

    text: str
    ground: str
    ratio: float
    needed: float
    why: str


_SLUG = re.compile(r"[^a-z0-9]+")
"""What `slugify` replaces with `-`."""

DEFAULT_REF: tuple[str, int] = (DEFAULT_SYSTEM_ID, DEFAULT_SYSTEM_VERSION)
"""`models.effective_system` of a deck with no reference."""

# ---------------------------------------------------------------------------
# Implementer: everything below this line.
# ---------------------------------------------------------------------------


def default_design_system(base: DesignTokens) -> DesignSystem:
    """The provisional default system every engagement starts in.

    `DesignSystem(id=DEFAULT_SYSTEM_ID, version=DEFAULT_SYSTEM_VERSION, marker="provisional",
    name=DEFAULT_SYSTEM_NAME, concept="", rules=[], palette=<the ten slots of
    base.palette>, roles={}, background="lt1", text_pairs=[TextPair(text=t, ground=g) for
    t, g in DEFAULT_TEXT_PAIRS], made_by=DEFAULT_MADE_BY, created_at=None)`. Pure.
    """
    raise NotImplementedError


def design_tokens(palette: DesignPalette | None, base: DesignTokens) -> DesignTokens:
    """`base` with its ten colour slots replaced by `palette` (hyperlink slots, fonts,
    sizes and spacing kept), as a new object: `base.model_copy(update={"palette":
    <validated v2 Palette>})`. `palette=None` returns `base` itself. The token name becomes
    `f"{base.name} + design"` when a palette is applied. Never writes a file."""
    raise NotImplementedError


def deck_tokens(deck: DeckArtifact, base: DesignTokens) -> DesignTokens:
    """The tokens a deck renders and is checked with: `design_tokens(deck.design_system.
    palette, base)`, or `base` when the deck has no design-system reference. Pure: the
    same deck state always gets the same tokens, so a render digest names one image."""
    raise NotImplementedError


def check_palette(
    palette: DesignPalette, *, background: str, text_pairs: list[TextPair]
) -> list[PaletteFinding]:
    """Every contrast the palette fails, `[]` when it passes.

    Ratios use v2's `autodeck.design.free_layout.contrast_ratio` on the two slots' hex. In
    order: each pair in `text_pairs` order, needing `CONTRAST_LARGE` when `large_only` (why
    `"large text pair"`) else `CONTRAST_TEXT` (why `"text pair"`); then `CHART_LABEL_SLOT`
    on `background`, needing `CONTRAST_TEXT` (why `"charts draw labels in dk2"`), skipped
    when `background` is `dk2`. A ratio is a failure when `ratio < needed` (compare the
    unrounded ratio). `ratio` is stored rounded to 2 decimals.
    """
    raise NotImplementedError


def findings_text(findings: list[PaletteFinding]) -> str:
    """One line per finding, joined by `\\n`, exactly:
    `- <text> on <ground>: <ratio:.2f>:1, needs <needed:g>:1 (<why>)`.
    Example: `- accent1 on lt2: 2.31:1, needs 4.5:1 (text pair)`. `""` for no findings."""
    raise NotImplementedError


def check_draft(draft: DesignDraft) -> list[PaletteFinding]:
    """`check_palette(draft.palette, background=draft.background,
    text_pairs=draft.text_pairs)`."""
    raise NotImplementedError


def slugify(name: str) -> str:
    """A design-system id from a name: lower-cased, every run of characters outside
    `[a-z0-9]` replaced by one `-`, `-` stripped from both ends, clipped to 40 characters
    (and `-` stripped again). Empty → `"design"`. Equal to `DEFAULT_SYSTEM_ID` →
    `"design-default"`. Always matches `SEGMENT_PATTERN`. Examples: `"Shelf price"` →
    `"shelf-price"`, `"  Demand / Curve! "` → `"demand-curve"`."""
    raise NotImplementedError


class DesignSystemStore:
    """The engagement's design-system versions on disk (`paths.EngagementPaths.
    design_system_version`), behind the engagement's guard. Versions are immutable: a
    version file is written once (atomically, `serialise.atomic_write_text` of
    `serialise.dump_model`) and never rewritten or deleted."""

    def __init__(self, engagement: object, *, base: DesignTokens | None = None) -> None:
        """`engagement` is an `engagement.Engagement` (typed loosely to avoid an import
        cycle); `base` builds the default system (without it, `load` of the default system
        raises `DesignSystemNotFoundError("the default system needs base tokens")`; the
        context builder loads only stored versions). Stores both; touches no file."""
        raise NotImplementedError

    def ids(self) -> list[str]:
        """Stored system ids (directories under `design_systems/` holding at least one
        valid version file), sorted. Never includes the default system."""
        raise NotImplementedError

    def versions(self, system_id: str) -> list[int]:
        """The stored versions of `system_id`, ascending; `[1]` for the default system;
        `[]` for an unknown id. Only files named `v<4+ digits>.json` count."""
        raise NotImplementedError

    def load(self, system_id: str, version: int) -> DesignSystem:
        """One version. The default system `(DEFAULT_SYSTEM_ID, 1)` is
        `default_design_system(base)` and reads no file.

        Raises:
            DesignSystemNotFoundError: no such stored version (also for the default id with
                a version other than 1).
            ClientIsolationError: (v2's) the path resolves into another client's tree.
            InvalidSegmentError: `system_id` is not a safe segment.
            pydantic.ValidationError: the file is not a valid `DesignSystem`, or its `id` /
                `version` disagree with its path (checked: raise `ValueError` naming both).
        """
        raise NotImplementedError

    def for_deck(self, deck: DeckArtifact) -> DesignSystem:
        """The version the deck is in: `load(*models.effective_system(deck))`."""
        raise NotImplementedError

    def add(
        self,
        draft: DesignDraft,
        *,
        marker: Marker,
        now: datetime,
        system_id: str | None = None,
    ) -> DesignSystem:
        """Store `draft` as the next version and return it.

        The id is `system_id` when given (it must not be `DEFAULT_SYSTEM_ID`:
        `InvalidSegmentError`), else `slugify(draft.name)`. The version is one more than
        the highest stored version of that id (1 for a new id). The draft is checked first:
        if `check_draft` finds anything, `PaletteRefusedError(findings_text(...))` and
        nothing is written. Writes `v<NNNN>.json` with `created_at=now`.
        """
        raise NotImplementedError
