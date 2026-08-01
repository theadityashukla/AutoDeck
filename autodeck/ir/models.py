"""Deck IR — the single source of truth (D4).

Agents read and write these models; renderers consume them. Every intermediate artifact
in a build is a serialised `Deck`, so this module defines the contract that every later
phase derives from. Plan §6.1 sketches the shape; this is the finalised version.

**A1 is enforced here, structurally.** `Claim.citations` has `min_length=1`, so a claim
carrying no citation cannot be *constructed* — it is not a runtime check that a later pass
might skip, forget, or be talked out of. Everything else in the accuracy subsystem is
downstream of that one constraint, which is why the IR is built before anything else.

Owning phase: 0 (task 0.2). Opus tier — `autodeck/ir/` is a path guardrail in
docs/MODEL_ROUTING.md.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

BlockKind = Literal[
    "claim",
    "framing",
    "chart",
    "figure",
    "section_header",
    "diagram",
    "icon",
]
"""Block types. Only `framing` is citation-exempt, and only under the A5 lint."""

Verdict = Literal[
    "unverified",
    "supported",
    "partially_supported",
    "unsupported",
    "contradicted",
]
"""A3 verdicts. A deck cannot reach final render with an `unsupported` or `contradicted`
block; `unverified` means the validator has not run yet."""

RetrievedBy = Literal["writer", "validator"]
"""A3 requires the validator to re-retrieve *independently* rather than trusting the
writer's citation, so who found a span is part of the audit trail."""

CommunicationMode = Literal["text_led", "icon_anchored", "diagram_led"]
"""§6.11.2 — an explicit per-slide decision, not an emergent property."""

DiagramKind = Literal[
    "process_flow",
    "cycle",
    "funnel",
    "pyramid",
    "two_by_two",
    "hub_spoke",
    "layered_stack",
]
"""Seeded from the owner's `slide-geometry` skill (docs/reference/slide-geometry).
Keep the two in sync — decision B6."""

ChartKind = Literal["bar", "column", "line", "pie", "scatter", "area", "stacked_bar"]

BBox = Annotated[tuple[float, float, float, float], Field(description="(x0, y0, x1, y1)")]


class IRModel(BaseModel):
    """Base for every IR model.

    `extra="forbid"` is load-bearing rather than tidy. IR objects are produced by LLM
    structured output, and a model that invents a field must fail loudly instead of having
    it silently dropped — the same posture the provider layer takes on schema repair.
    """

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def quote_digest(quote: str) -> str:
    """Return the SHA-256 hex digest of a verbatim source quote.

    The single definition of the hash used for A1 verification. Ingestion, the IR, and the
    audit report must all agree on it, so nothing computes this inline.
    """
    return hashlib.sha256(quote.encode("utf-8")).hexdigest()


class Citation(IRModel):
    """A resolved source span: `(doc_id, page, bbox, verbatim_quote, quote_sha256)`.

    The hash is self-verifying — construction fails if it does not match `quote`. That
    catches the cheap half of A1 (a quote edited after the fact) without touching the
    document store. The other half, verifying the quote still exists verbatim at that
    location in the source, needs the store and lands in Phase 1.
    """

    doc_id: str = Field(min_length=1)
    page: int = Field(ge=1)
    bbox: BBox
    quote: str = Field(min_length=1, description="Verbatim text from the source span.")
    quote_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_by: RetrievedBy

    @model_validator(mode="after")
    def _hash_matches_quote(self) -> Citation:
        expected = quote_digest(self.quote)
        if self.quote_sha256 != expected:
            raise ValueError(
                "quote_sha256 does not match quote: "
                f"expected {expected}, got {self.quote_sha256}. "
                "A citation whose hash has drifted from its text cannot be trusted (A1)."
            )
        return self

    @classmethod
    def for_quote(
        cls,
        *,
        doc_id: str,
        page: int,
        bbox: tuple[float, float, float, float],
        quote: str,
        retrieved_by: RetrievedBy,
    ) -> Citation:
        """Build a citation, computing the digest from the quote."""
        return cls(
            doc_id=doc_id,
            page=page,
            bbox=bbox,
            quote=quote,
            quote_sha256=quote_digest(quote),
            retrieved_by=retrieved_by,
        )

    def identity(self) -> tuple[str, int, str]:
        """A comparable key for "is this the same span?" — used by derivation checks."""
        return (self.doc_id, self.page, self.quote_sha256)


class DerivationInput(IRModel):
    """One named input to a derivation: the number *and* the span it was copied from.

    Plan §6.1 sketches `inputs` as `dict[str, Citation]`, but A2 requires the numeric
    linter to **re-execute** the formula, and a citation alone does not carry a value —
    re-execution would have to re-parse the quote and guess which numeral was meant. The
    value is therefore recorded explicitly and the citation proves it was copied rather
    than invented. See decision B13.
    """

    value: float
    citation: Citation


class Derivation(IRModel):
    """A number computed from cited inputs (A2).

    Derivations are first-class, not an exception to A2: the content agent may compute
    percentages, deltas and conversions provided the formula and its cited inputs are
    recorded. The numeric linter re-executes `formula` against `inputs` in Phase 2b and
    compares to `result`, so this model has to carry enough to reproduce the arithmetic
    without the surrounding prose.
    """

    formula: str = Field(
        min_length=1,
        description="Expression over the input names, e.g. '(a - b) / b * 100'.",
    )
    inputs: dict[str, DerivationInput] = Field(min_length=1)
    result: float
    unit: str = Field(description="Unit of `result`; empty string for a bare ratio.")


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


class Claim(IRModel):
    """A factual assertion with its evidence.

    **This is where A1 lives.** `citations` has `min_length=1`, so pydantic rejects a
    claim with no evidence at construction time. The invariant is therefore a property of
    the type system rather than of anyone remembering to call a checker.
    """

    text: str = Field(min_length=1)
    citations: list[Citation] = Field(
        min_length=1,
        description="A1: at least one resolving source span. Never relax this.",
    )
    derivation: Derivation | None = None
    verdict: Verdict = "unverified"
    verdict_notes: str | None = None
    contradicting_spans: list[Citation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derivation_inputs_are_cited(self) -> Claim:
        """Every derivation input must also appear in `citations`.

        Without this a derived number could rest on a span that never reaches the claims
        table, which would make the audit report (A6) show working that cites sources it
        does not list. Cheaper to forbid than to reconcile downstream.
        """
        if self.derivation is None:
            return self
        cited = {c.identity() for c in self.citations}
        missing = sorted(
            name
            for name, item in self.derivation.inputs.items()
            if item.citation.identity() not in cited
        )
        if missing:
            raise ValueError(
                f"derivation inputs not present in claim citations: {', '.join(missing)}. "
                "A2 derivations must draw on spans the claim itself cites (A1, A6)."
            )
        return self

    def blocks_render(self) -> bool:
        """True when A3 forbids this claim from reaching final render."""
        return self.verdict in ("unsupported", "contradicted")


# ---------------------------------------------------------------------------
# Non-text block payloads
# ---------------------------------------------------------------------------


class ChartSeries(IRModel):
    """One data series. Values align positionally with `ChartSpec.categories`."""

    name: str = Field(min_length=1)
    values: list[float] = Field(min_length=1)


class ChartSpec(IRModel):
    """A native, editable PowerPoint chart (D10).

    `source_citations` is required for the same reason `Claim.citations` is: a chart is a
    dense set of factual assertions, and a chart whose numbers cannot be traced is exactly
    the pasted screenshot D10 exists to forbid.
    """

    chart_type: ChartKind
    title: str | None = None
    categories: list[str] = Field(min_length=1)
    series: list[ChartSeries] = Field(min_length=1)
    x_axis_label: str | None = None
    y_axis_label: str | None = None
    source_citations: list[Citation] = Field(
        min_length=1,
        description="D10 data provenance; typically the source table cell range.",
    )

    @model_validator(mode="after")
    def _series_align_with_categories(self) -> ChartSpec:
        width = len(self.categories)
        bad = [s.name for s in self.series if len(s.values) != width]
        if bad:
            raise ValueError(
                f"series {', '.join(bad)} do not have one value per category ({width} expected)"
            )
        return self


class DiagramNode(IRModel):
    """A node in a `DiagramSpec`.

    A node label that asserts a fact is a claim like any other — the diagram engine is not
    a loophole in A1. Labels also obey text budgets (§6.7), enforced at render time.
    """

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    claim: Claim | None = Field(
        default=None,
        description="Set when the label asserts a fact rather than naming a stage.",
    )


class DiagramEdge(IRModel):
    """A directed relationship between two nodes, by node id."""

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    label: str | None = None


class DiagramSpec(IRModel):
    """Structure rendered as native PowerPoint shapes and connectors (§6.11.2).

    The ChartSpec pattern applied to concepts instead of data: typed and parameterised, so
    art direction chooses a *kind* and the engine owns the geometry.
    """

    kind: DiagramKind
    title: str | None = None
    nodes: list[DiagramNode] = Field(min_length=1)
    edges: list[DiagramEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _edges_resolve_and_ids_are_unique(self) -> DiagramSpec:
        ids = [n.id for n in self.nodes]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate diagram node ids: {', '.join(duplicates)}")
        known = set(ids)
        dangling = sorted(
            {e.source for e in self.edges if e.source not in known}
            | {e.target for e in self.edges if e.target not in known}
        )
        if dangling:
            raise ValueError(f"edges reference unknown node ids: {', '.join(dangling)}")
        return self


class IconRef(IRModel):
    """An icon choice, reviewable and diffable like everything else in the IR (§6.11.3).

    `concept` is the semantic request and `glyph_id` the resolved library glyph; keeping
    both means a glyph swap is visible in a diff as a swap, not as an unexplained id change.
    """

    concept: str = Field(min_length=1)
    glyph_id: str = Field(min_length=1)
    color_token: str = Field(
        min_length=1, description="A DesignTokens palette key, never a literal colour."
    )


class FigureRef(IRModel):
    """A figure lifted from the corpus or the approved asset library.

    Carries its own citation: a figure is evidence, and A1 does not exempt pictures.
    """

    asset_id: str = Field(min_length=1)
    caption: str | None = None
    citation: Citation


# ---------------------------------------------------------------------------
# Blocks, slides, decks
# ---------------------------------------------------------------------------

#: kind -> the payload field that must be populated for that kind.
_REQUIRED_PAYLOAD: dict[str, str] = {
    "claim": "claim",
    "chart": "chart",
    "figure": "figure",
    "diagram": "diagram",
    "icon": "icon",
}

#: kinds whose content is plain text in `text`.
_TEXT_KINDS: frozenset[str] = frozenset({"framing", "section_header"})

#: every payload field, used to reject payloads foreign to the declared kind.
_PAYLOAD_FIELDS: tuple[str, ...] = ("claim", "chart", "figure", "diagram", "icon")


class Block(IRModel):
    """One unit of slide content, filling one component slot.

    The kind/payload agreement is validated rather than assumed. A `claim` block without a
    `Claim` is the exact shape A1 forbids, and a block carrying two payloads is ambiguous
    to every consumer downstream — the renderer, the linters, and the audit report would
    each be free to pick differently.
    """

    id: str = Field(min_length=1)
    kind: BlockKind
    slot: str = Field(min_length=1, description="Which component slot this fills.")
    text: str | None = None
    claim: Claim | None = None
    chart: ChartSpec | None = None
    figure: FigureRef | None = None
    diagram: DiagramSpec | None = None
    icon: IconRef | None = None

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> Block:
        required = _REQUIRED_PAYLOAD.get(self.kind)

        if required is not None and getattr(self, required) is None:
            detail = (
                " A claim block carries the assertion and its citations; without them "
                "there is nothing for validation or the audit report to act on (A1)."
                if self.kind == "claim"
                else ""
            )
            raise ValueError(
                f"block {self.id!r} of kind {self.kind!r} needs a {required}.{detail}"
            )

        if self.kind in _TEXT_KINDS and not (self.text and self.text.strip()):
            raise ValueError(f"block {self.id!r} of kind {self.kind!r} needs non-empty text")

        foreign = sorted(
            field
            for field in _PAYLOAD_FIELDS
            if field != required and getattr(self, field) is not None
        )
        if foreign:
            raise ValueError(
                f"block {self.id!r} of kind {self.kind!r} also carries "
                f"{', '.join(foreign)}; a block has exactly one payload"
            )
        return self

    def blocks_render(self) -> bool:
        """True when A3 forbids this block from reaching final render."""
        return self.claim is not None and self.claim.blocks_render()


class Slide(IRModel):
    """A single slide: a component assignment plus the blocks filling its slots.

    `speaker_notes` are blocks too, deliberately. A1 applies to notes exactly as it applies
    to the slide face — notes are the most common place for an uncited number to hide.
    """

    id: str = Field(min_length=1)
    narrative_role: str = Field(min_length=1)
    component: str = Field(min_length=1, description="Catalog component name (§6.6).")
    communication_mode: CommunicationMode | None = None
    blocks: list[Block] = Field(default_factory=list)
    speaker_notes: list[Block] = Field(default_factory=list)

    @model_validator(mode="after")
    def _block_ids_unique_within_slide(self) -> Slide:
        ids = [b.id for b in (*self.blocks, *self.speaker_notes)]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(
                f"duplicate block ids on slide {self.id!r}: {', '.join(duplicates)}"
            )
        return self

    def all_blocks(self) -> list[Block]:
        """Face blocks and notes together — what A1, A2 and A5 all iterate over."""
        return [*self.blocks, *self.speaker_notes]


class Deck(IRModel):
    """The root IR document, versioned per run.

    Deliberately carries no timestamp. A6 requires that the same manifest plus IR
    re-renders byte-comparable output, and an embedded build time would make every deck
    differ from itself. Time belongs in the manifest, which is exempt from the comparison.
    """

    run_id: str = Field(min_length=1)
    project: str = Field(min_length=1)
    client: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    version: int = Field(ge=1)
    slides: list[Slide] = Field(default_factory=list)
    theme_ref: str = Field(min_length=1)
    component_lib_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _slide_ids_unique(self) -> Deck:
        ids = [s.id for s in self.slides]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate slide ids: {', '.join(duplicates)}")
        return self

    def all_blocks(self) -> list[Block]:
        """Every block in the deck, faces and notes."""
        return [block for slide in self.slides for block in slide.all_blocks()]

    def blocking_blocks(self) -> list[Block]:
        """Blocks whose verdict forbids final render (A3).

        The orchestrator's render guard calls this; an empty list is the precondition for
        entering the render phase.
        """
        return [block for block in self.all_blocks() if block.blocks_render()]


# ---------------------------------------------------------------------------
# DeckBrief (§6.13)
# ---------------------------------------------------------------------------


class DeckBrief(IRModel):
    """The signed-off output of the planning session — the first of the four A7 approvals.

    Versioned into the run alongside the IR so GATE 1 can review the outline *against the
    brief* rather than against taste. `open_risks` carries accepted evidence gaps forward
    into the audit report, so a gap acknowledged at planning time cannot quietly disappear.
    """

    run_id: str = Field(min_length=1)
    objective: str = Field(
        min_length=1, description="The decision or action this deck should produce."
    )
    audience: str = Field(min_length=1)
    key_messages: list[str] = Field(min_length=1)
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    length_target: int | None = Field(default=None, ge=1)
    header_style: str | None = None
    layout_pins: list[str] = Field(default_factory=list)
    reference_deck: str | None = None
    open_risks: list[str] = Field(default_factory=list)
