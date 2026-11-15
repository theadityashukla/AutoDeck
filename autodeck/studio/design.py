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
    pal = {k: str(getattr(base.palette, k)).upper() for k in COLOR_SLOTS}
    return DesignSystem(id=DEFAULT_SYSTEM_ID, version=DEFAULT_SYSTEM_VERSION, marker="provisional",
        name=DEFAULT_SYSTEM_NAME, concept="", rules=[], palette=DesignPalette.model_validate(pal),
        roles={}, background="lt1", text_pairs=[TextPair(text=t, ground=g) for t, g in DEFAULT_TEXT_PAIRS],
        made_by=DEFAULT_MADE_BY, created_at=None)


def design_tokens(palette, base):
    from autodeck.design.theme.tokens import Palette
    if palette is None:
        return base
    merged = base.palette.model_dump()
    merged.update(palette.model_dump())
    return base.model_copy(update={"palette": Palette.model_validate(merged), "name": f"{base.name} + design"})


def deck_tokens(deck, base):
    ref = deck.design_system
    return design_tokens(ref.palette if ref is not None else None, base)


def check_palette(palette, *, background, text_pairs):
    from autodeck.design.free_layout import contrast_ratio
    out = []
    for p in text_pairs:
        need = CONTRAST_LARGE if p.large_only else CONTRAST_TEXT
        r = contrast_ratio(palette.hex(p.text), palette.hex(p.ground))
        if r < need:
            out.append(PaletteFinding(p.text, p.ground, round(r, 2), need, "large text pair" if p.large_only else "text pair"))
    if background != CHART_LABEL_SLOT:
        r = contrast_ratio(palette.hex(CHART_LABEL_SLOT), palette.hex(background))
        if r < CONTRAST_TEXT:
            out.append(PaletteFinding(CHART_LABEL_SLOT, background, round(r, 2), CONTRAST_TEXT, "charts draw labels in dk2"))
    return out


def findings_text(findings):
    return "\n".join(f"- {f.text} on {f.ground}: {f.ratio:.2f}:1, needs {f.needed:g}:1 ({f.why})" for f in findings)


def check_draft(draft):
    return check_palette(draft.palette, background=draft.background, text_pairs=draft.text_pairs)


def slugify(name):
    s = _SLUG.sub("-", name.lower()).strip("-")[:40].strip("-")
    if not s:
        return "design"
    return "design-default" if s == DEFAULT_SYSTEM_ID else s


class DesignSystemStore:
    def __init__(self, engagement, *, base=None):
        self.engagement = engagement
        self.base = base

    def _dir(self, sid):
        return self.engagement.guard(self.engagement.paths.design_system_dir(sid))

    def ids(self):
        root = self.engagement.paths.design_systems
        if not root.is_dir():
            return []
        return sorted(d.name for d in root.iterdir() if d.is_dir() and self.versions(d.name))

    def versions(self, sid):
        if sid == DEFAULT_SYSTEM_ID:
            return [1]
        d = self._dir(sid)
        if not d.is_dir():
            return []
        return sorted(int(m.group(1)) for f in d.iterdir() if (m := re.fullmatch(r"v([0-9]{4,})\.json", f.name)))

    def load(self, sid, version):
        from autodeck.studio.errors import DesignSystemNotFoundError
        from autodeck.studio import serialise
        if sid == DEFAULT_SYSTEM_ID:
            if version != 1:
                raise DesignSystemNotFoundError("no such version")
            if self.base is None:
                raise DesignSystemNotFoundError("the default system needs base tokens")
            return default_design_system(self.base)
        path = self.engagement.guard(self.engagement.paths.design_system_version(sid, version))
        if not path.is_file():
            raise DesignSystemNotFoundError(f"no design system {sid} v{version}")
        sys_ = DesignSystem.model_validate_json(serialise.read_text(path))
        if (sys_.id, sys_.version) != (sid, version):
            raise ValueError("mismatch")
        return sys_

    def for_deck(self, deck):
        from autodeck.studio.models import effective_system
        return self.load(*effective_system(deck))

    def add(self, draft, *, marker, now, system_id=None):
        from autodeck.studio.errors import InvalidSegmentError, PaletteRefusedError
        from autodeck.studio import serialise
        if system_id == DEFAULT_SYSTEM_ID:
            raise InvalidSegmentError("no")
        sid = system_id or slugify(draft.name)
        f = check_draft(draft)
        if f:
            raise PaletteRefusedError(findings_text(f))
        v = max(self.versions(sid), default=0) + 1
        sys_ = DesignSystem(id=sid, version=v, marker=marker, created_at=now, **draft.model_dump())
        path = self.engagement.guard(self.engagement.paths.design_system_version(sid, v))
        path.parent.mkdir(parents=True, exist_ok=True)
        serialise.atomic_write_text(path, serialise.dump_model(sys_))
        return sys_
