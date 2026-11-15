"""The plain base IR, the engagement record and the change log (v3 plan §4, §8.1).

These models are the contracts every other studio module is written against. Three rules
shape them, and each one is a v3 principle made structural:

* **Text is text (P3, V8).** A `Block` is plain words, a chart, a figure or an icon. It has
  no claim type, no citation, no verdict and no approval. A block may carry a `SourceNote`
  saying which document and page a fact came from; it is a convenience for the owner and
  no code enforces anything about it. The strict overlay (plan §8.2, Phase 6) will be an
  annotation set *keyed by* `slide_id:block_id`, which is why block and slide ids must stay
  stable across edits: an edit changes a block's content, never its id.
* **No stages, only state (P7).** Every deck-level part (brief, storyline, design concept,
  design-system reference) may be absent, and every part that exists carries a `Marker`:
  `decided`, `provisional` or `stale`. Markers are plain data in Phase 0; nothing computes
  staleness yet (that is Phase 4).
* **Every change is recorded and reversible (V4).** A `ChangeEntry` records what changed
  (an id-keyed diff), why (the instruction, in a sentence), who (thread, layer, model) and
  whether it has been undone. `ChangeLog` holds the entries plus a `head` pointer and
  validates that the two agree, so undo and redo have exactly one meaning.

Carried from v2 unchanged and imported, not copied: `FreeLayout` and its elements
(`Placement`, `TextElement`, `VisualElement`, `ShapeElement`), `ChartSeries`, `ChartKind`,
`IconRef` and the theme colour tokens. v2's `ChartSpec` and `FigureRef` are *not* reused:
both require a `Citation` (A1 for charts and figures), which is a strict-mode rule. Their
base forms here, `ChartData` and `FigureData`, are the same fields minus the citation.

Diagrams are left out of Phase 0: every v2 diagram node must declare itself a `Claim` or a
`LabelFraming`, which is the strict model, not a plain one. See docs/phases/V3-PHASE-0.md.

Unlike v2's `Deck`, nothing here is held to A6 reproducibility (V7): change-log entries and
the engagement record carry timestamps. The deck artifact itself carries none, so that two
serialisations of one deck state are byte-identical, which is what exact undo compares.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from autodeck.ir.models import (
    ChartKind,
    ChartSeries,
    FreeLayout,
    IconRef,
    ShapeElement,
    TextElement,
)

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

SEGMENT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
"""A name that is safe as one path segment: client, project and artifact ids are directory
names under the workspace, so isolation can be enforced by path (A4). It cannot be empty,
cannot start with a dot (so never `.` or `..`) and cannot contain a separator."""

ENTRY_ID_PATTERN = r"^c[0-9]{4,}$"
"""Change-log entry ids: `c0001`, `c0002`, ... assigned in append order by
`changelog.next_entry_id`. Readable in a listing and sortable as text up to 9999 entries."""

DIGEST_PATTERN = r"^[0-9a-f]{64}$"
"""A lower-case SHA-256 hex digest (`serialise.artifact_digest`)."""

THREAD_ID_PATTERN = r"^t[0-9]{4,}$"
"""Thread ids (Phase 1): `t0001`, `t0002`, ... per engagement, in creation order."""

TURN_ID_PATTERN = r"^u[0-9]{4,}$"
"""Turn ids (Phase 1): `u0001`, `u0002`, ... per thread, in order."""

PROPOSAL_ID_PATTERN = r"^p[0-9]{4,}$"
"""Proposal ids (Phase 1): `p0001`, `p0002`, ... per engagement, in creation order."""

RENDER_DIGEST_PATTERN = r"^[0-9a-f]{12}$"
"""The first 12 hex characters of an artifact digest: names one render directory."""

Marker = Literal["decided", "provisional", "stale"]
"""Plan §4. `decided`: the owner chose or accepted it. `provisional`: the system filled it
in so work could continue. `stale`: something upstream changed after it was made."""

DEFAULT_MARKER: Marker = "provisional"
"""What a part is until the owner says otherwise: nobody has decided it yet."""

Layer = Literal["direction", "system", "composition", "placement", "mechanics", "review"]
"""Plan §6.1: L1 Direction, L2 System, L3 Composition, L4 Placement, L5 Mechanics, Review.
Every change-log entry records the layer that made it (V5)."""

BlockKind = Literal["text", "chart", "figure", "icon"]
"""What a base block holds. No `claim`/`framing` split: in the base, text is text."""

ArtifactKind = Literal["deck"]
"""Phase 0 has one artifact type. Notes (plan §10) arrive in Phase 5."""

OptionId = Literal["A", "B", "C", "D"]
"""Phase 1: the id of one option of a proposal, assigned in order. At most four options."""

OPTION_IDS: tuple[OptionId, ...] = ("A", "B", "C", "D")

DiffKind = Literal["added", "removed", "changed"]
"""The same three kinds `autodeck.ir.store.Change` uses."""

HUMAN_MODEL_ID = "human"
"""`ChangeEntry.model_id` for an edit the owner made by hand rather than through a model."""

SCHEMA_VERSION: Literal[1] = 1
"""On-disk format version of every studio JSON file. Bumped only with a migration."""


class StudioModel(BaseModel):
    """Base for every studio model. `extra="forbid"` for the reason v2's `IRModel` gives:
    these are written by models through structured output, and an invented field must fail
    loudly rather than vanish."""

    model_config = ConfigDict(extra="forbid")


def _duplicates(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


# ---------------------------------------------------------------------------
# Engagement
# ---------------------------------------------------------------------------


class EngagementRecord(StudioModel):
    """`workspace/engagements/<client>/<project>/engagement.json` (plan §4, P1).

    One client and one project, both of which must exist as knowledge folders; that is
    checked by `engagement.create_engagement` through the v2 `KnowledgeLoader`, not here,
    because a model cannot see the filesystem. What this model guarantees is that the names
    are safe path segments, so the record can never point outside its own directory.

    Sources, artifacts and threads are not listed here. Artifacts are the directories under
    `artifacts/` (listing them avoids a second copy that could drift); sources and threads
    arrive in Phases 1 and 5.
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    client: str = Field(pattern=SEGMENT_PATTERN)
    project: str = Field(pattern=SEGMENT_PATTERN)
    title: str = Field(default="", description="A human label for the engagement; optional.")
    created_at: AwareDatetime


# ---------------------------------------------------------------------------
# Deck-level parts: brief, storyline, concept, design-system reference
# ---------------------------------------------------------------------------


class Brief(StudioModel):
    """Who the deck is for and what it must achieve (L1). Plain text; any field may be
    empty while the conversation has not reached it."""

    audience: str = ""
    goal: str = ""
    notes: str = Field(default="", description="Anything else the owner said about the job.")
    marker: Marker = DEFAULT_MARKER


class StorylinePoint(StudioModel):
    """One step of the argument. Slides link to points by `id` (`Slide.serves`), so a point
    can be reworded without breaking the links."""

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class Storyline(StudioModel):
    """The argument as ordered points (L1). Order is the list order."""

    points: list[StorylinePoint] = Field(default_factory=list)
    marker: Marker = DEFAULT_MARKER

    @model_validator(mode="after")
    def _point_ids_unique(self) -> Storyline:
        duplicates = _duplicates([p.id for p in self.points])
        if duplicates:
            raise ValueError(f"duplicate storyline point ids: {', '.join(duplicates)}")
        return self

    def point_ids(self) -> list[str]:
        return [p.id for p in self.points]


class DesignConcept(StudioModel):
    """The deck's visual idea in one or two sentences (plan §7.2, L1). It names the idea,
    not the tokens."""

    text: str = Field(min_length=1)
    marker: Marker = DEFAULT_MARKER


COLOR_SLOTS: tuple[str, ...] = (
    "dk1",
    "lt1",
    "dk2",
    "lt2",
    "accent1",
    "accent2",
    "accent3",
    "accent4",
    "accent5",
    "accent6",
)
"""The ten theme colour slots a layout may name (v2's `ColorToken`), in theme order."""

_HEX = re.compile(r"^[0-9A-F]{6}$")


class DesignPalette(StudioModel):
    """Phase 2-3: one hex colour per theme slot, the concrete palette of a design system.

    Hex is stored upper-case without `#`; a leading `#` and lower case are accepted on input
    (models write `"#0B2A22"`). Every slot is required: a design system states its whole
    palette, so a deck rendered in it never mixes in a default colour by accident. The two
    hyperlink slots of v2's `Palette` are not part of a design system; they keep the base
    tokens' values (`design.design_tokens`).
    """

    dk1: str
    lt1: str
    dk2: str
    lt2: str
    accent1: str
    accent2: str
    accent3: str
    accent4: str
    accent5: str
    accent6: str

    @field_validator(*COLOR_SLOTS, mode="before")
    @classmethod
    def _normalise_hex(cls, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip().lstrip("#").upper()
            if not _HEX.fullmatch(text):
                raise ValueError(f"{value!r} is not a six-digit hex colour such as #0B2A22")
            return text
        return value

    def hex(self, slot: str) -> str:
        """The slot's hex (upper case, no `#`). Raises KeyError for an unknown slot."""
        if slot not in COLOR_SLOTS:
            raise KeyError(f"unknown colour slot {slot!r}; slots are {', '.join(COLOR_SLOTS)}")
        return str(getattr(self, slot))


class DesignSystemRef(StudioModel):
    """A pointer to one version of a design system artifact (plan §7.2, L2).

    Phase 2-3 adds `palette`: a copy of that version's palette, taken when the reference is
    set (`design.DesignSystem.ref`). Versions are immutable, so the copy cannot drift from
    the artifact, and it makes the deck self-contained for rendering and layout QA: the
    tokens of a deck are a pure function of the deck and the base tokens
    (`design.deck_tokens`), which is what lets the preview service render any deck state
    (including undone ones) without reading the design-system store. `palette` is None only
    on records written before Phase 2-3; such a deck renders in the base palette.

    A deck with no reference (`DeckArtifact.design_system is None`) is in the provisional
    default system, `DEFAULT_SYSTEM_ID` version `DEFAULT_SYSTEM_VERSION`.
    """

    id: str = Field(pattern=SEGMENT_PATTERN)
    version: int = Field(ge=1)
    marker: Marker = DEFAULT_MARKER
    palette: DesignPalette | None = None


DEFAULT_SYSTEM_ID = "default"
"""The id of the provisional default design system every engagement starts with: the base
tokens' palette and no stated concept (`design.default_design_system`). It is never written
to disk; a deck with `design_system is None` is in it."""

DEFAULT_SYSTEM_VERSION = 1


# ---------------------------------------------------------------------------
# Slide briefs and composition (Phase 2-3)
# ---------------------------------------------------------------------------

MAX_HEADER_CHARS = 160
"""A slide header is one line of at most this many characters."""

MAX_FAILURE_FINDINGS = 12
"""`CompositionFailure.findings` keeps at most this many lines."""


class BriefFigure(StudioModel):
    """One key number of a brief and what it counts, e.g. `38%` / `lower serving cost`."""

    value: str = Field(min_length=1, description="The number as it should read, e.g. '38%'.")
    label: str = Field(default="", description="What the number is, in a few words.")


class BriefSeries(StudioModel):
    name: str = Field(min_length=1, description="The series name with its unit: 'Cost ($k)'.")
    values: list[float] = Field(min_length=1)


class BriefChart(StudioModel):
    """Data for one chart, in the bench's case shape. The designer draws it; the lead only
    supplies the numbers. `emphasis` names categories to highlight, copied exactly."""

    kind: Literal["bar", "column", "line"]
    categories: list[str] = Field(min_length=1)
    series: list[BriefSeries] = Field(min_length=1)
    emphasis: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _aligned(self) -> BriefChart:
        width = len(self.categories)
        bad = [s.name for s in self.series if len(s.values) != width]
        if bad:
            raise ValueError(
                f"series {', '.join(bad)} do not have one value per category ({width} expected)"
            )
        unknown = sorted(set(self.emphasis) - set(self.categories))
        if unknown:
            raise ValueError(f"emphasis names categories not in the chart: {unknown}")
        if len(set(self.categories)) != width:
            raise ValueError("chart categories repeat")
        return self


class BriefContent(StudioModel):
    """Everything the designer may put on the slide besides the header: short text points,
    key figures, optional chart data. Already written; the designer does not add facts."""

    points: list[str] = Field(default_factory=list, description="Short text items, in order.")
    figures: list[BriefFigure] = Field(default_factory=list)
    chart: BriefChart | None = None

    @model_validator(mode="after")
    def _points_not_blank(self) -> BriefContent:
        if any(not p.strip() for p in self.points):
            raise ValueError("a brief point may not be blank")
        return self


class SlideBrief(StudioModel):
    """The contract between direction and composition (Phase 2-3, plan §6.2).

    Written by the lead (L1) in words: the slide's talking header, what the audience must
    conclude (`intent`), and the content, already written. The designer (L3/L4) turns a
    brief plus the deck's design system into the slide's blocks and free layout; the lead
    never writes those. `notes` are hints about what matters (what is the hero, what is
    quieter evidence); they are not drawn and are not speaker notes.

    `header` is one non-blank line; the designed slide must carry it word for word (line
    breaks aside), which the designer's conformance check enforces.
    """

    header: str = Field(min_length=1, max_length=MAX_HEADER_CHARS)
    intent: str = Field(min_length=1)
    content: BriefContent = Field(default_factory=BriefContent)
    notes: str = ""

    @model_validator(mode="after")
    def _header_one_line(self) -> SlideBrief:
        if not self.header.strip() or "\n" in self.header or "\r" in self.header:
            raise ValueError("a slide header is one non-blank line")
        if not self.intent.strip():
            raise ValueError("a slide brief states its intent")
        return self


def brief_digest(brief: SlideBrief) -> str:
    """The fingerprint of a brief: SHA-256 hex of
    `json.dumps(brief.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
    ensure_ascii=False)` encoded as UTF-8. Two briefs with equal fields have equal digests;
    any change to any field (a reworded point, a changed figure) changes it."""
    text = json.dumps(
        brief.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ComposedFrom(StudioModel):
    """What a slide's designed form (its blocks and layout) was composed from (plan §8.3):
    the fingerprint of the brief and the design system version, and the model that composed
    it. Set by the designer's result handler (`edits.apply_composition`), never by the lead.
    """

    brief_digest: str = Field(pattern=DIGEST_PATTERN)
    system_id: str = Field(pattern=SEGMENT_PATTERN)
    system_version: int = Field(ge=1)
    model_id: str = Field(min_length=1)


class CompositionFailure(StudioModel):
    """The designer could not make this slide clean for this brief and system. The previous
    designed form, if any, is kept; this record says what failed, so the lead and the owner
    can see it. Cleared by the next clean composition."""

    brief_digest: str = Field(pattern=DIGEST_PATTERN)
    system_id: str = Field(pattern=SEGMENT_PATTERN)
    system_version: int = Field(ge=1)
    model_id: str = Field(min_length=1)
    attempts: int = Field(ge=1)
    findings: list[str] = Field(default_factory=list, max_length=MAX_FAILURE_FINDINGS)

    @model_validator(mode="after")
    def _findings_one_line(self) -> CompositionFailure:
        if any("\n" in f or not f.strip() for f in self.findings):
            raise ValueError("each composition finding is one non-blank line")
        return self


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


class SourceNote(StudioModel):
    """Where a specific fact came from: a document and, optionally, a page (plan §8.1).

    No rule reads this. It is not a `Citation`: nothing resolves it, nothing checks the
    quote, and a block without one is exactly as valid as a block with one (V8)."""

    doc_id: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    note: str = ""


class ChartData(StudioModel):
    """A native, editable chart (D10): v2's `ChartSpec` minus `source_citations`.

    Same field names and the same alignment rule, so the render adapter can hand it to
    v2's `charts.place_chart` unchanged. With no citations, no source line is drawn under
    the chart; a `SourceNote` on the block is where provenance goes in the base.
    """

    chart_type: ChartKind
    title: str | None = None
    categories: list[str] = Field(min_length=1)
    series: list[ChartSeries] = Field(min_length=1)
    x_axis_label: str | None = None
    y_axis_label: str | None = None

    @model_validator(mode="after")
    def _series_align_with_categories(self) -> ChartData:
        width = len(self.categories)
        bad = [s.name for s in self.series if len(s.values) != width]
        if bad:
            raise ValueError(
                f"series {', '.join(bad)} do not have one value per category ({width} expected)"
            )
        return self


class FigureData(StudioModel):
    """A figure from the asset library: v2's `FigureRef` minus its citation. The v2 free
    layout draws a figure as a framed panel with its caption (it has no image yet)."""

    asset_id: str = Field(min_length=1)
    caption: str | None = None


#: kind -> the payload field that must be set for that kind; every other payload is None.
_PAYLOAD_FOR_KIND: dict[str, str] = {
    "text": "text",
    "chart": "chart",
    "figure": "figure",
    "icon": "icon",
}
_PAYLOAD_FIELDS: tuple[str, ...] = ("text", "chart", "figure", "icon")


class Block(StudioModel):
    """One unit of slide content: plain text, a chart, a figure or an icon.

    Exactly one payload, the one its `kind` names. A `text` block's text is non-empty after
    stripping. There is no `slot`: a base slide is always placed by a `FreeLayout`, which
    addresses blocks by id. No claim, no citation, no verdict (P3).
    """

    id: str = Field(min_length=1)
    kind: BlockKind
    text: str | None = None
    chart: ChartData | None = None
    figure: FigureData | None = None
    icon: IconRef | None = None
    source_note: SourceNote | None = None

    @model_validator(mode="after")
    def _one_payload_matching_kind(self) -> Block:
        required = _PAYLOAD_FOR_KIND[self.kind]
        if getattr(self, required) is None:
            raise ValueError(f"block {self.id!r} of kind {self.kind!r} needs a {required}")
        if self.kind == "text" and not (self.text or "").strip():
            raise ValueError(f"block {self.id!r} is a text block with empty text")
        foreign = [f for f in _PAYLOAD_FIELDS if f != required and getattr(self, f) is not None]
        if foreign:
            raise ValueError(
                f"block {self.id!r} of kind {self.kind!r} also carries {', '.join(foreign)}; "
                "a block has exactly one payload"
            )
        return self


# ---------------------------------------------------------------------------
# Slides and the deck
# ---------------------------------------------------------------------------

#: Which layout element type may place which block kind. Text elements place text blocks;
#: a visual element's `type` must equal the block's kind. v2's `diagram` element type has
#: no base block kind, so a diagram element can never validate here.
_VISUAL_TYPE_FOR_KIND: dict[str, str] = {"chart": "chart", "figure": "figure", "icon": "icon"}


class Slide(StudioModel):
    """One slide: its intent, its blocks, plain speaker notes, an optional free layout, a
    marker, and the storyline points it serves (plan §8.1).

    `layout` may be None while the slide has been composed but not yet placed (P7); the
    renderer draws such a slide as a placeholder. When `layout` is set it must place every
    block exactly once, each as what it is: the rule v2's `Slide` enforces for creative mode
    (B69), restated for base block kinds so a layout that drops a block cannot exist.
    """

    id: str = Field(min_length=1)
    intent: str | None = Field(
        default=None,
        description=(
            "What this slide must do, in words (L1): what it proves and the visual idea. "
            "Never coordinates or colours."
        ),
    )
    blocks: list[Block] = Field(default_factory=list)
    speaker_notes: str = Field(
        default="", description="Plain text; newlines separate paragraphs."
    )
    layout: FreeLayout | None = None
    marker: Marker = DEFAULT_MARKER
    serves: list[str] = Field(
        default_factory=list,
        description="Ids of the storyline points this slide serves; checked by DeckArtifact.",
    )
    brief: SlideBrief | None = Field(
        default=None,
        description="Phase 2-3: the slide's brief (header, intent, content), by the lead.",
    )
    composed: ComposedFrom | None = Field(
        default=None, description="Phase 2-3: what the designed form was composed from."
    )
    compose_failure: CompositionFailure | None = Field(
        default=None, description="Phase 2-3: the last composition that failed, if any."
    )

    @model_validator(mode="after")
    def _brief_and_composition_agree(self) -> Slide:
        if self.brief is not None and self.intent != self.brief.intent:
            raise ValueError(
                f"slide {self.id!r}: intent must equal the brief's intent when a brief is set"
            )
        if self.composed is not None and (self.brief is None or self.layout is None):
            raise ValueError(f"slide {self.id!r}: a composed slide has a brief and a layout")
        if self.compose_failure is not None and self.brief is None:
            raise ValueError(f"slide {self.id!r}: a composition failure needs a brief")
        return self

    @model_validator(mode="after")
    def _block_ids_unique(self) -> Slide:
        duplicates = _duplicates([b.id for b in self.blocks])
        if duplicates:
            raise ValueError(
                f"duplicate block ids on slide {self.id!r}: {', '.join(duplicates)}"
            )
        duplicates = _duplicates(self.serves)
        if duplicates:
            raise ValueError(f"slide {self.id!r} serves {', '.join(duplicates)} more than once")
        return self

    @model_validator(mode="after")
    def _layout_places_every_block_once(self) -> Slide:
        if self.layout is None:
            return self
        blocks = {b.id: b for b in self.blocks}
        placed = self.layout.placed_block_ids()
        problems = [f"block {i!r} is placed more than once" for i in _duplicates(placed)]
        for element in self.layout.elements:
            if isinstance(element, ShapeElement):
                continue
            block = blocks.get(element.block_id)
            if block is None:
                problems.append(
                    f"element places {element.block_id!r}, which is not on this slide"
                )
            elif isinstance(element, TextElement):
                if block.kind != "text":
                    problems.append(f"block {block.id!r} is a {block.kind}, placed as text")
            elif _VISUAL_TYPE_FOR_KIND.get(block.kind) != element.type:
                problems.append(
                    f"block {block.id!r} is a {block.kind}, placed as {element.type}"
                )
            elif element.emphasis:
                categories = set(block.chart.categories) if block.chart is not None else set()
                unknown = sorted(set(element.emphasis) - categories)
                if unknown:
                    problems.append(f"emphasis names categories not in the chart: {unknown}")
        problems += [f"block {i!r} is not placed" for i in blocks if i not in placed]
        if problems:
            raise ValueError(f"slide {self.id!r} layout: " + "; ".join(problems))
        return self

    def block(self, block_id: str) -> Block:
        """The block with this id. Raises KeyError naming it when absent."""
        for block in self.blocks:
            if block.id == block_id:
                return block
        raise KeyError(f"slide {self.id!r} has no block {block_id!r}")


class DeckArtifact(StudioModel):
    """A deck being made: the root of the base IR (plan §8.1).

    Holds `client` and `project` as well as living under that engagement's directory: the
    path is the isolation mechanism, and these fields let `ArtifactStore.load` detect a deck
    file that was copied into another client's engagement (it raises `ClientIsolationError`).

    Carries no timestamp and no version number. The change log is the version history, and
    leaving time out keeps the serialisation of a deck state a pure function of that state,
    which is what makes "undo restores it byte for byte" testable.
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    kind: ArtifactKind = "deck"
    id: str = Field(pattern=SEGMENT_PATTERN, description="The artifact id; a directory name.")
    client: str = Field(pattern=SEGMENT_PATTERN)
    project: str = Field(pattern=SEGMENT_PATTERN)
    title: str = ""
    brief: Brief | None = None
    storyline: Storyline = Field(default_factory=Storyline)
    design_concept: DesignConcept | None = None
    design_system: DesignSystemRef | None = None
    slides: list[Slide] = Field(default_factory=list)

    @model_validator(mode="after")
    def _slide_ids_unique(self) -> DeckArtifact:
        duplicates = _duplicates([s.id for s in self.slides])
        if duplicates:
            raise ValueError(f"duplicate slide ids: {', '.join(duplicates)}")
        return self

    @model_validator(mode="after")
    def _links_name_real_points(self) -> DeckArtifact:
        known = set(self.storyline.point_ids())
        problems = [
            f"slide {slide.id!r} serves unknown storyline point {point!r}"
            for slide in self.slides
            for point in slide.serves
            if point not in known
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def slide(self, slide_id: str) -> Slide:
        """The slide with this id. Raises KeyError naming it when absent."""
        for slide in self.slides:
            if slide.id == slide_id:
                return slide
        raise KeyError(f"deck {self.id!r} has no slide {slide_id!r}")

    def slide_ids(self) -> list[str]:
        return [s.id for s in self.slides]


# ---------------------------------------------------------------------------
# Change log
# ---------------------------------------------------------------------------


class DiffItem(StudioModel):
    """One difference between two deck states, in the shape of v2's `ir.store.Change`.

    `path` uses v2's notation: dotted field names, `[<id>]` for an element of an id-keyed
    list, `[<index>]` for a positional one, `[order]` for a reordering of an id-keyed list.
    `before`/`after` are JSON values (from `model_dump(mode="json")`); `before` is None for
    `added` and `after` is None for `removed`. A diff is for display and for thread context;
    undo does not replay it (it restores a snapshot), so it never has to be invertible.
    """

    path: str = Field(min_length=1)
    kind: DiffKind
    before: Any = None
    after: Any = None


class ChangeEntry(StudioModel):
    """One change to an artifact (plan §4, V4, V5).

    `parent_id` is the entry whose resulting state this change was applied to (None: the
    artifact's initial state). With `ChangeLog.head` it makes undo and redo unambiguous even
    after a change is made on top of an undone one. `before_digest`/`after_digest` are the
    SHA-256 of the canonical serialisation of the state before and after; the store checks
    them on every undo and redo, which is what makes undo provably exact.
    """

    id: str = Field(pattern=ENTRY_ID_PATTERN)
    parent_id: str | None = Field(default=None, pattern=ENTRY_ID_PATTERN)
    diff: list[DiffItem] = Field(min_length=1, description="An empty diff is not a change.")
    instruction: str = Field(
        min_length=1,
        description="What caused the change, in one sentence, as the owner or model put it.",
    )
    thread_id: str = Field(min_length=1)
    layer: Layer
    model_id: str = Field(
        min_length=1,
        description=(
            f"The model that made it, as a free string; {HUMAN_MODEL_ID!r} for a hand edit."
        ),
    )
    created_at: AwareDatetime
    undone: bool = False
    before_digest: str = Field(pattern=DIGEST_PATTERN)
    after_digest: str = Field(pattern=DIGEST_PATTERN)

    @model_validator(mode="after")
    def _a_change_changes_something(self) -> ChangeEntry:
        if not self.instruction.strip() or "\n" in self.instruction:
            raise ValueError(f"entry {self.id!r}: the instruction is one non-blank line")
        if self.before_digest == self.after_digest:
            raise ValueError(f"entry {self.id!r}: before and after states are identical")
        if self.parent_id == self.id:
            raise ValueError(f"entry {self.id!r} is its own parent")
        return self


class ChangeLog(StudioModel):
    """Every change to one artifact, in the order made, plus where the artifact now is.

    `head` is the entry whose `after` state is the artifact's current state (None: the
    initial state, `initial_digest`). Entries are never deleted; undo flips `undone`.

    Invariants, checked on construction and therefore on every load:

    * entry ids are unique, and each `parent_id` names an *earlier* entry (or is None);
    * `head` is None or an entry id;
    * the entries reached by walking `parent_id` back from `head` are exactly the entries
      with `undone == False` (the live chain). Everything else is undone. So "undo" always
      means: mark `head` undone and move `head` to its parent; and "redo" means: among the
      undone entries whose parent is `head`, re-apply the most recent;
    * each entry's `before_digest` equals its parent's `after_digest` (or `initial_digest`
      for a root entry): the chain of states has no gaps.
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    artifact_id: str = Field(pattern=SEGMENT_PATTERN)
    initial_digest: str = Field(pattern=DIGEST_PATTERN)
    head: str | None = Field(default=None, pattern=ENTRY_ID_PATTERN)
    entries: list[ChangeEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _entries_form_a_consistent_tree(self) -> ChangeLog:
        seen: dict[str, ChangeEntry] = {}
        for entry in self.entries:
            if entry.id in seen:
                raise ValueError(f"duplicate change-log entry id {entry.id!r}")
            if entry.parent_id is not None and entry.parent_id not in seen:
                raise ValueError(
                    f"entry {entry.id!r} names parent {entry.parent_id!r}, not an earlier entry"
                )
            expected = (
                self.initial_digest
                if entry.parent_id is None
                else seen[entry.parent_id].after_digest
            )
            if entry.before_digest != expected:
                raise ValueError(
                    f"entry {entry.id!r} starts from a state its parent did not produce"
                )
            seen[entry.id] = entry

        if self.head is not None and self.head not in seen:
            raise ValueError(f"head {self.head!r} is not an entry")
        live: set[str] = set()
        cursor = self.head
        while cursor is not None:
            live.add(cursor)
            cursor = seen[cursor].parent_id
        wrong = sorted(e.id for e in self.entries if (e.id in live) == e.undone)
        if wrong:
            raise ValueError(
                "entries on the live chain must be not undone and all others undone; "
                f"inconsistent: {', '.join(wrong)}"
            )
        return self

    def entry(self, entry_id: str) -> ChangeEntry:
        """The entry with this id. Raises KeyError naming it when absent."""
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        raise KeyError(f"change log of {self.artifact_id!r} has no entry {entry_id!r}")


# ---------------------------------------------------------------------------
# Staleness (Phase 2-3, plan §8.3, P7)
# ---------------------------------------------------------------------------

CompositionState = Literal["unbriefed", "undesigned", "fresh", "stale", "failed"]
"""Where a slide stands against its brief and the deck's design system.

* `unbriefed`: no brief (a slide made before Phase 2-3, or by hand). Never stale.
* `undesigned`: a brief, and no designed form composed from any brief yet.
* `fresh`: its designed form was composed from the current brief and the current system.
* `stale`: it was composed, but the brief or the system has changed since.
* `failed`: the last composition for the current brief and system failed (the previous
  designed form, if any, is still what renders).
"""

STALE_BRIEF = "brief changed"
STALE_SYSTEM = "design system changed"


@dataclass(frozen=True)
class CompositionStatus:
    state: CompositionState
    reasons: tuple[str, ...] = ()
    """For `stale` only: `STALE_BRIEF` and/or `STALE_SYSTEM`, in that order."""


def effective_system(deck: DeckArtifact) -> tuple[str, int]:
    """`(id, version)` of the design system the deck is in: its reference, or the default
    system `(DEFAULT_SYSTEM_ID, DEFAULT_SYSTEM_VERSION)` when it has none."""
    ref = deck.design_system
    if ref is None:
        return DEFAULT_SYSTEM_ID, DEFAULT_SYSTEM_VERSION
    return ref.id, ref.version


def composition_status(slide: Slide, system: tuple[str, int]) -> CompositionStatus:
    """The staleness rule, computed from fingerprints only (pure; never triggers anything).

    In order: no brief → `unbriefed`. A `compose_failure` whose brief digest equals the
    current brief's and whose system equals `system` → `failed` (a failure recorded for an
    older brief or system is ignored). No `composed` → `undesigned`. Otherwise compare
    `composed` with the current brief digest and `system`: equal → `fresh`; else `stale`
    with the reasons that apply (`STALE_BRIEF` first, then `STALE_SYSTEM`).
    """
    if slide.brief is None:
        return CompositionStatus("unbriefed")
    digest = brief_digest(slide.brief)
    failure = slide.compose_failure
    if (
        failure is not None
        and failure.brief_digest == digest
        and (failure.system_id, failure.system_version) == system
    ):
        return CompositionStatus("failed")
    composed = slide.composed
    if composed is None:
        return CompositionStatus("undesigned")
    reasons: list[str] = []
    if composed.brief_digest != digest:
        reasons.append(STALE_BRIEF)
    if (composed.system_id, composed.system_version) != system:
        reasons.append(STALE_SYSTEM)
    if not reasons:
        return CompositionStatus("fresh")
    return CompositionStatus("stale", tuple(reasons))


def deck_composition(deck: DeckArtifact) -> dict[str, CompositionStatus]:
    """`composition_status` of every slide against `effective_system(deck)`, keyed by slide
    id in deck order."""
    system = effective_system(deck)
    return {slide.id: composition_status(slide, system) for slide in deck.slides}
