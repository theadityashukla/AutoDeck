"""Deck IR — the single source of truth (D4).

Agents read and write these models; renderers consume them. Every intermediate artifact
in a build is a serialised `Deck`, so this module defines the contract that every later
phase derives from. Plan §6.1 sketches the shape; this is the finalised version.

**A1 is enforced here, structurally.** `Claim.citations` has `min_length=1`, so a claim
carrying no citation cannot be *constructed* — it is not a runtime check that a later pass
might skip, forget, or be talked out of. Everything else in the accuracy subsystem is
downstream of that one constraint, which is why the IR is built before anything else.

The same move is made once more, one level down. A diagram node is the place an uncited
fact is most likely to survive review — three words in a box read as a label rather than
as an assertion — so `DiagramNode` requires every node to declare itself either a `Claim`
or explicitly framed. "Nobody said" is not a state it can be in. See the diagram section.

Owning phase: 0 (task 0.2). Opus tier — `autodeck/ir/` is a path guardrail in
docs/MODEL_ROUTING.md.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from itertools import pairwise
from typing import Annotated, Any, Literal, NamedTuple, get_args

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

DiagramRelationship = Literal[
    "sequence",
    "cycle",
    "mutual_reinforcement",
    "tension_tradeoff",
    "complement",
    "convergence",
    "divergence",
    "hierarchy_foundation",
    "overlap",
    "containment",
    "transformation",
    "classification",
]
"""What a diagram's points have to do with each other — the classification the
slide-geometry skill makes step 1 of every slide with parallel points.

Eleven of these are the skill's own table. Its twelfth row, "None (a true list)", is
deliberately absent: an honest list is not a diagram, and the way to say so is to build no
`DiagramSpec` at all rather than to have a value for "this geometry means nothing".

`classification` is an AutoDeck addition and is owed back upstream (PHASE-3A, "keep the two
in sync"). The table has no row a real 2x2 fits: its four positions are defined by two
independent continuums, which is not tension — more cost does not mean less novelty — and
the skill's own catalog describes the geometry without naming the relationship it encodes.
"""

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
Keep the two in sync — decision B6. `GEOMETRIES` says which of these are modelled, which
relationships each may encode, and what each one's labels may cost."""

LabelReason = Literal[
    "stage_name",
    "actor_name",
    "artefact_name",
    "category_name",
    "question",
]
"""The closed set of reasons a diagram label may carry no citation. See `LabelFraming`."""

StackSupport = Literal["rests_on", "peers"]
"""Whether a `layered_stack`'s layers depend on the one below or merely sit in an order.
A rendering instruction and a claim at once — see `LayeredStackSpec`."""

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


# ---------------------------------------------------------------------------
# Diagrams — the geometry grammar (§6.11.2, task 3a.6)
# ---------------------------------------------------------------------------
#
# Three failures are designed out here, in this order.
#
# **A1 at a diagram node.** A box with three words in it reads as a label, not as an
# assertion, which makes it the best hiding place in the deck for an uncited fact. So a
# node's text must be *either* a `Claim` (and `Claim.citations` makes a citation-free one
# unconstructible) *or* an explicit `LabelFraming` saying it asserts nothing about the
# world. Neither is not an option: `DiagramNode` rejects a node that declares no status at
# all, so the safe reading is what you get by default and the exemption has to be asked for.
#
# **The relationship named before the geometry.** `slide-geometry`'s step 1 is the
# load-bearing one: *"If you catch yourself placing boxes before you have named the
# relationship, stop and classify."* `DiagramSpec.relationship` is required and is declared
# **before** `kind`, so a model filling this schema field by field states what the points
# have to do with each other before it is offered a shape to put them in. `GEOMETRIES` then
# refuses a geometry that does not encode the declared relationship.
#
# **Modelling the relationship, not a bag of nodes.** A process step has an order, a
# two-by-two item has a position in two dimensions, a stack layer has a level. Each
# geometry therefore carries its own payload type with its own fields, the way `Block`
# carries exactly one payload for its `kind`; `nodes` and `edges` are *derived* from that
# payload. A process flow's arrows come from its declared step order rather than from a
# convention about list order, which is why re-serialising a shuffled list cannot silently
# reorder the diagram — and why an edge to a node that does not exist is not a thing this
# type can hold.
#
# Adding `funnel` or `venn` later is a payload class plus a `GEOMETRIES` entry. It is not a
# redesign, and it is deliberately not done here for geometries nobody has asked for.


class LabelFraming(IRModel):
    """The positive declaration that a node's label asserts nothing about the world.

    **This is the label/claim seam, and it is A5's fence wearing a different hat.** A5 lets
    a `framing` block carry no citation because *"serve better before you buy more"* is the
    argument of a deck and there is no paper to cite for it; `audit/framing_linter.py`
    keeps that exemption honest by demoting any framing block that says something about the
    world. A diagram label like `Strategy` on a two-by-two axis, or `Discovery` on a
    process flow, is the same sentence in a smaller box — so it is the same exemption,
    declared the same way and fenced by the same lint.

    `reason` is a closed vocabulary rather than free text for the reason the framing
    linter's pattern tables are closed lists: a category anybody can widen is a category
    that ends up holding everything. Each value names a thing that is true *of this
    engagement's own vocabulary* rather than of the world:

    - `stage_name` — a phase of the process being described (`Discovery`, `Pilot`). That
      the stage exists is a fact about the plan on this slide, not about the world.
    - `actor_name` — a party, team or system in the client's own world (`Finance`).
    - `artefact_name` — a deliverable or document the engagement produces.
    - `category_name` — a regime or grouping the deck itself defines (`Quick wins`).
    - `question` — a question. A question asserts nothing; D12's `question_led` header
      voice is the same move one text size up.

    **What this cannot do, stated plainly.** Nothing here stops `40% cheaper than Oracle`
    being typed into a label and declared `category_name`. The IR cannot run the A5 fence
    itself — `autodeck/audit/` imports the design system, so the IR importing the audit
    layer would close an import cycle — and a prose test for "is this a fact?" is exactly
    the judgement `framing_linter.py` keeps deterministic by owning it in one place. So the
    obligation is handed over explicitly instead of being hoped for:
    `DiagramSpec.framing_texts()` enumerates every uncited text in a diagram, and a caller
    that runs `lint_framing_text` over them gets, for diagrams, the demotion A5 already
    performs for prose. Until that call exists, this declaration is a signature on a
    statement, not a proof of it.
    """

    reason: LabelReason
    note: str | None = Field(
        default=None,
        description="Why this text asserts nothing about the world, in the author's words.",
    )


class DiagramNode(IRModel):
    """A node in a `DiagramSpec`: one label, and the status of the text in it.

    **Exactly one of `claim` and `framing` must be set.** A node carrying neither is the
    uncited factual label A1 exists to forbid, and it fails at construction rather than at
    some later pass that might not run. A node carrying both is ambiguous about whether
    there is evidence behind the words, and every consumer downstream would be free to
    resolve it differently.

    `label` is what the reader sees in the shape; `claim.text` is the assertion being made
    and may be fuller (`Throughput rose from 412 to 671 sequences per second` behind a
    label reading `Throughput +63%`). Keeping them separate is what lets the label obey a
    four-word budget without the claim having to be compressed into something its citation
    no longer supports — and `audit/numeric_linter.py` already lints both.

    Subclasses add what their geometry needs. `DiagramNode` itself is not abstract, but a
    `DiagramSpec` only ever holds the node type its geometry declares.
    """

    id: str = Field(min_length=1)
    label: str = Field(min_length=1, description="The text in the shape. Budgeted; see A1.")
    claim: Claim | None = Field(
        default=None,
        description="Set when the label asserts a fact. Carries the citations A1 requires.",
    )
    framing: LabelFraming | None = Field(
        default=None,
        description="Set INSTEAD of `claim`, when the label asserts nothing about the world.",
    )

    @model_validator(mode="after")
    def _label_is_claimed_or_framed(self) -> DiagramNode:
        if (self.claim is None) == (self.framing is None):
            both = self.claim is not None
            raise ValueError(
                f"diagram node {self.id!r} sets "
                f"{'both claim and framing' if both else 'neither claim nor framing'}; "
                "exactly one is required. A node whose label asserts a fact carries a "
                "`claim` with its citations (A1); a node whose label names a stage, a "
                "party or a category says so with `framing`. There is no third case, "
                "because 'nobody said' is how an uncited fact reaches a slide in a box."
            )
        return self

    def word_count(self) -> int:
        """Words in the label — the unit the slide-geometry skill states budgets in."""
        return len(self.label.split())


class ProcessStep(DiagramNode):
    """One step of a `process_flow`, with its place in the sequence stated.

    `order` is a field, not a list position. A type that can only express "this node is the
    third step" as a convention about list order is not modelling sequence: a shuffled list
    would be a different diagram with no validator able to tell, and a diff of two IR
    versions would read as a rewrite whenever anything was inserted.
    """

    order: int = Field(ge=1, description="1 is the first step. Contiguous within the flow.")
    transition: str | None = Field(
        default=None,
        description=(
            "The label on the arrow leaving this step, if it needs one. Arrows mean flow, "
            "causality or influence and nothing else, so this names what happens between "
            "two steps; it is never a decorative connector caption."
        ),
    )


class QuadrantItem(DiagramNode):
    """One item plotted on a `two_by_two`, at its honest position on both axes.

    Positions are 0.0 at the axis's `low` pole and 1.0 at its `high` pole. They are real
    coordinates rather than a quadrant name because *"proportion is a factual claim"*: two
    items in the same quadrant are usually the slide's point, and a type that could only
    say "top right" would make that point unsayable.
    """

    x: float = Field(ge=0.0, le=1.0, description="Position along `x_axis`, low=0 to high=1.")
    y: float = Field(ge=0.0, le=1.0, description="Position along `y_axis`, low=0 to high=1.")

    @property
    def quadrant(self) -> str:
        """`low_low` … `high_high`, as `<x>_<y>`. The midpoint reads as `high`."""
        return f"{'high' if self.x >= 0.5 else 'low'}_{'high' if self.y >= 0.5 else 'low'}"


class StackLayer(DiagramNode):
    """One band of a `layered_stack`, with the level it occupies.

    Level 1 is the bottom. In a `rests_on` stack that is the foundation everything above
    depends on, which is the whole claim the geometry makes; in a `peers` stack the levels
    are only an order. Same reason as `ProcessStep.order`: the level is stated, never
    inferred from where the layer happens to sit in a list.
    """

    level: int = Field(ge=1, description="1 is the bottom layer. Contiguous within the stack.")


class DiagramEdge(IRModel):
    """A directed relationship between two nodes, by node id.

    **Derived, never authored.** Edges come from the geometry's own structure — a process
    flow's arrows are its step order — so an edge naming a node that does not exist, or
    contradicting the order the steps declare, is not a state this IR can reach. The class
    remains because consumers (`audit/numeric_linter.py` lints edge labels) read edges, and
    a future geometry whose edges are genuinely free-form will produce these too.
    """

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    label: str | None = None


class DiagramAxis(IRModel):
    """One labelled continuum of a `two_by_two`.

    The catalog is explicit that this is what separates a real 2x2 from four boxes wearing
    a costume: *"If you cannot name both axes as continuums, this is not a 2x2 —
    reclassify."* So the dimension and both of its poles are required, and poles that read
    the same are rejected: an axis whose ends are indistinguishable is not a continuum and
    the items plotted against it are not positioned by anything.
    """

    name: str = Field(min_length=1, description="The dimension, e.g. 'Cost to serve'.")
    low: str = Field(min_length=1, description="The label at the low end, e.g. 'Low'.")
    high: str = Field(min_length=1, description="The label at the high end, e.g. 'High'.")

    @model_validator(mode="after")
    def _poles_differ(self) -> DiagramAxis:
        if self.low.strip().casefold() == self.high.strip().casefold():
            raise ValueError(
                f"axis {self.name!r} has the same label at both ends ({self.low!r}). An axis "
                "with indistinguishable poles is not a continuum, and a 2x2 built on one is "
                "four boxes with arrowheads."
            )
        return self


class TextSite(NamedTuple):
    """One piece of on-slide diagram text, and where in the spec it came from."""

    location: str
    text: str


class ProcessFlowSpec(IRModel):
    """A sequence: A leads to B leads to C. Chevrons or a path (`references/construction.md`).

    Two or more steps, because a sequence of one is not a sequence, and `order` values that
    form exactly 1..n, because a flow with two third steps and no second is a diagram nobody
    can draw and everybody would draw differently.
    """

    steps: list[ProcessStep] = Field(min_length=2)

    @model_validator(mode="after")
    def _orders_are_contiguous(self) -> ProcessFlowSpec:
        orders = sorted(step.order for step in self.steps)
        if orders != list(range(1, len(self.steps) + 1)):
            raise ValueError(
                f"process flow step orders are {orders}; expected exactly "
                f"1..{len(self.steps)} with no gaps or repeats. Order is the whole content "
                "of a sequence — a gap in it is an unanswerable question about what the "
                "arrows connect."
            )
        return self

    def steps_in_order(self) -> list[ProcessStep]:
        """The steps as the flow runs them, by declared `order` and never by list order."""
        return sorted(self.steps, key=lambda step: step.order)

    @property
    def nodes(self) -> tuple[DiagramNode, ...]:
        return tuple(self.steps_in_order())

    @property
    def edges(self) -> tuple[DiagramEdge, ...]:
        """One arrow per adjacent pair, in declared order."""
        return tuple(
            DiagramEdge(source=first.id, target=second.id, label=first.transition)
            for first, second in pairwise(self.steps_in_order())
        )

    def structural_texts(self) -> tuple[TextSite, ...]:
        return tuple(
            TextSite(f"step {step.id} transition", step.transition)
            for step in self.steps_in_order()
            if step.transition
        )


class TwoByTwoSpec(IRModel):
    """Items positioned against two crossed continuums (`True 2x2` in the catalog).

    Both axes are required and so is more than one item: a single dot on a plane encodes no
    comparison, which is the form of the load-bearing test this geometry can actually be
    held to. The axes must also name different dimensions — plotting cost against cost is
    one continuum drawn twice, and the second axis is then decoration.
    """

    x_axis: DiagramAxis
    y_axis: DiagramAxis
    items: list[QuadrantItem] = Field(min_length=2)

    @model_validator(mode="after")
    def _axes_are_different_dimensions(self) -> TwoByTwoSpec:
        if self.x_axis.name.strip().casefold() == self.y_axis.name.strip().casefold():
            raise ValueError(
                f"both axes are named {self.x_axis.name!r}. A 2x2 claims two independent "
                "continuums; the same one twice positions nothing."
            )
        return self

    @property
    def nodes(self) -> tuple[DiagramNode, ...]:
        return tuple(self.items)

    @property
    def edges(self) -> tuple[DiagramEdge, ...]:
        """None. An arrow on a 2x2 would claim flow between positions, which it has not."""
        return ()

    def structural_texts(self) -> tuple[TextSite, ...]:
        return (
            TextSite("x_axis name", self.x_axis.name),
            TextSite("x_axis low", self.x_axis.low),
            TextSite("x_axis high", self.x_axis.high),
            TextSite("y_axis name", self.y_axis.name),
            TextSite("y_axis low", self.y_axis.low),
            TextSite("y_axis high", self.y_axis.high),
        )


class LayeredStackSpec(IRModel):
    """Layers resting on one another, or sitting as peers (`Four strata` in the catalog).

    `support` is a rendering instruction *and* a claim: the catalog gives the foundation the
    widest band when the argument is "everything rests on this", and equal bands when the
    layers are peers. Drawing one as the other misstates the relationship, so it is declared
    rather than inferred from how many layers there are.

    A `peers` stack is the variant closest to failing the skill's load-bearing test — peers
    in a fixed order are very nearly a list — which is a judgement about the slide's content
    and therefore belongs to the grammar lints (task 3a.9), not to this type. Flagged here
    so 3a.9 knows where to look.
    """

    support: StackSupport
    layers: list[StackLayer] = Field(min_length=2)

    @model_validator(mode="after")
    def _levels_are_contiguous(self) -> LayeredStackSpec:
        levels = sorted(layer.level for layer in self.layers)
        if levels != list(range(1, len(self.layers) + 1)):
            raise ValueError(
                f"stack levels are {levels}; expected exactly 1..{len(self.layers)}. A gap "
                "in a stack is a band with nothing in it, and 'what rests on what' is the "
                "only thing this geometry says."
            )
        return self

    def layers_upwards(self) -> list[StackLayer]:
        """The layers bottom first, by declared `level` and never by list order."""
        return sorted(self.layers, key=lambda layer: layer.level)

    @property
    def nodes(self) -> tuple[DiagramNode, ...]:
        """Bottom first, so index 0 is the foundation in a `rests_on` stack."""
        return tuple(self.layers_upwards())

    @property
    def edges(self) -> tuple[DiagramEdge, ...]:
        """None. Adjacency carries "rests on"; an arrow would claim flow instead."""
        return ()

    def structural_texts(self) -> tuple[TextSite, ...]:
        return ()


DiagramGeometry = ProcessFlowSpec | TwoByTwoSpec | LayeredStackSpec
"""The geometry payloads this phase models. One more is one more member plus one entry."""


@dataclass(frozen=True)
class Geometry:
    """One registered geometry: what it may encode, what it holds, and what it costs.

    The same idea as `design/components/catalog.py`'s registration — one declaration
    answering every question the rest of the system asks — kept here rather than there for
    one reason: the constraint this table exists to enforce (does this geometry encode the
    declared relationship?) has to hold at *construction* of the IR, and the IR may not
    import the design system. The catalog's own `register()` could not host a diagram type
    as it stands anyway: its `SlotBuilder` takes a `Canvas` and returns fixed boxes, while a
    diagram's boxes depend on how many nodes it has. See the handover note for 3a.6's
    renderer task.

    `max_label_words` is a *declaration*, not a measurement. `autodeck/design/` owns
    measurement (`budgets.compute_budget` turns a box and a font into a real limit) and the
    IR must not import it, so what lives here is the skill's own unit — node labels of 2 to
    4 words — which a renderer and a budget checker can both read and which is enforceable
    without a font. The physical check stays where the fonts are.

    `shapes` names python-pptx `MSO_SHAPE` members from `references/construction.md` as
    strings. It is a cross-reference for whoever writes the renderer, not an API: nothing
    here imports python-pptx, and the pptxgenjs column of that table is not modelled (D5).
    """

    kind: DiagramKind
    relationships: tuple[DiagramRelationship, ...]
    payload_field: str | None
    """The `DiagramSpec` field carrying this geometry's payload, or None if unmodelled."""
    node_type: type[DiagramNode]
    max_label_words: int
    encodes: str
    """What this geometry carries that a plain list would lose. The skill's step 3, stated
    per geometry so a lint or a reviewer can quote it rather than re-derive it."""
    label_anchor: str
    """Where the catalog puts this geometry's labels."""
    shapes: tuple[str, ...]
    catalog_entry: str
    """The heading in `references/geometry-catalog.md` this entry is a reading of."""


GEOMETRIES: dict[DiagramKind, Geometry] = {
    "process_flow": Geometry(
        kind="process_flow",
        relationships=("sequence",),
        payload_field="process_flow",
        node_type=ProcessStep,
        max_label_words=4,
        encodes="the order of the steps and what happens between them",
        label_anchor="inside each chevron; number the nodes on a journey path",
        shapes=("CHEVRON", "RIGHT_ARROW"),
        catalog_entry="Chevron / path sequence",
    ),
    "two_by_two": Geometry(
        kind="two_by_two",
        relationships=("classification", "tension_tradeoff"),
        payload_field="two_by_two",
        node_type=QuadrantItem,
        max_label_words=4,
        encodes="each item's position on two independent continuums at once",
        label_anchor="beside each plotted dot; pole labels small and muted at each arrowhead",
        shapes=("OVAL", "RECTANGLE"),
        catalog_entry="True 2x2",
    ),
    "layered_stack": Geometry(
        kind="layered_stack",
        relationships=("hierarchy_foundation",),
        payload_field="layered_stack",
        node_type=StackLayer,
        max_label_words=4,
        encodes="which layers rest on which, and therefore what fails if the base does",
        label_anchor="left-aligned inside each band",
        shapes=("RECTANGLE",),
        catalog_entry="Four strata / Pyramid, strata",
    ),
    "cycle": Geometry(
        kind="cycle",
        relationships=("cycle",),
        payload_field=None,
        node_type=DiagramNode,
        max_label_words=4,
        encodes="that the last phase feeds the first, so the process repeats",
        label_anchor="outside the ring at each segment's angular centre",
        shapes=("BLOCK_ARC", "OVAL", "ARC"),
        catalog_entry="Three- to six-node cycle / Ring cycle",
    ),
    "funnel": Geometry(
        kind="funnel",
        relationships=("convergence",),
        payload_field=None,
        node_type=DiagramNode,
        max_label_words=4,
        encodes="how much is lost at each stage, in the widths themselves",
        label_anchor="inside each band, left-padded; metrics right of the funnel",
        shapes=("TRAPEZOID",),
        catalog_entry="Funnel",
    ),
    "pyramid": Geometry(
        kind="pyramid",
        relationships=("hierarchy_foundation",),
        payload_field=None,
        node_type=DiagramNode,
        max_label_words=4,
        encodes="that each tier is narrower than the one it stands on",
        label_anchor="inside each band; outside-right with a leader if the band is thin",
        shapes=("TRAPEZOID", "ISOSCELES_TRIANGLE"),
        catalog_entry="Pyramid / strata",
    ),
    "hub_spoke": Geometry(
        kind="hub_spoke",
        relationships=("convergence", "divergence"),
        payload_field=None,
        node_type=DiagramNode,
        max_label_words=4,
        encodes="that every satellite relates to the centre and not to each other",
        label_anchor="outside each satellite on its radial line, by the anchoring rule",
        shapes=("OVAL", "RECTANGLE"),
        catalog_entry="Radial hub / orbit / compass",
    ),
}
"""Every geometry this IR knows, whether or not it is modelled yet.

An entry with `payload_field=None` is registered and **not constructible**: the catalog
describes it, this phase does not model it, and `DiagramSpec` says so in the error rather
than accepting a shapeless bag of nodes on its behalf. Adding one is a payload class, a
field on `DiagramSpec`, and the `payload_field` here — a registration, not a redesign.

`hub_spoke` is listed against both `convergence` and `divergence` because the relationship
table has no radial family at all: the catalog distinguishes a hub (satellites supporting a
centre) from a compass or starburst (a centre branching outwards) by the connectors, and
the two read as opposite relationships. That, and `classification`, are the two places this
table departs from the vendored skill; both are owed upstream (PHASE-3A, "keep the two in
sync").
"""


def geometry_for(kind: DiagramKind) -> Geometry:
    """The registered geometry for `kind`."""
    return GEOMETRIES[kind]


def geometries_for(relationship: DiagramRelationship) -> tuple[DiagramKind, ...]:
    """Every geometry that may encode `relationship`, in registration order.

    What art direction (Phase 3b) picks from once it has classified the relationship, and
    the reason classification comes first: the choice of shape is *downstream* of it.
    """
    return tuple(
        kind for kind, geometry in GEOMETRIES.items() if relationship in geometry.relationships
    )


def relationships_without_geometry() -> tuple[DiagramRelationship, ...]:
    """Relationships the skill names that no registered geometry can encode.

    A standing finding rather than a bug: PHASE-3A requires the vendored skill and this
    table to be kept in sync, and this is the mechanical half of that review — it answers
    "what can a classifier legitimately conclude that we cannot then draw?" without anyone
    re-reading the table by eye.
    """
    covered = {r for geometry in GEOMETRIES.values() for r in geometry.relationships}
    return tuple(r for r in get_args(DiagramRelationship) if r not in covered)


#: Which `DiagramSpec` field carries each geometry's payload. Derived from `GEOMETRIES` so
#: the registry stays the one place a geometry is declared.
_GEOMETRY_FIELDS: tuple[str, ...] = tuple(
    geometry.payload_field
    for geometry in GEOMETRIES.values()
    if geometry.payload_field is not None
)


def _payload_field(kind: DiagramKind) -> str:
    field = GEOMETRIES[kind].payload_field
    assert field is not None  # guaranteed by `_geometry_matches_kind`
    return field


class DiagramSpec(IRModel):
    """Structure rendered as native PowerPoint shapes and connectors (§6.11.2).

    **`relationship` is declared before `kind`, and that field order is load-bearing.**
    Fields are emitted in declaration order by structured output, so a model filling this
    schema names what its points have to do with each other before it is offered a geometry
    for them. A `DiagramSpec` that let a caller pick a shape first would reproduce the exact
    failure the slide-geometry skill exists to prevent — N points becoming N rounded
    rectangles — with a type system's blessing on it.

    Exactly one geometry payload is set and it must be the one `kind` names, the same
    kind/payload agreement `Block` enforces for its own payloads and for the same reason: a
    spec carrying two is ambiguous to the renderer, the linters and the audit report alike,
    and each would be free to resolve it differently.

    `nodes` and `edges` are derived from that payload rather than stored beside it. They
    read the same as before for every consumer that walks a diagram, and the states they
    used to allow — an edge to a node that does not exist, a step order contradicted by the
    list it sits in — are now unreachable instead of validated.

    What this type does **not** decide is the skill's load-bearing test — *"if this geometry
    were replaced by a plain list, would information be lost?"*. Its mechanisable half is
    here, per geometry (a 2x2 needs two named continuums and more than one item; a sequence
    needs more than one step); the other half is a judgement about whether *this slide's*
    content really holds the relationship it claims, which needs the slide, the deck's
    rhythm and the argument — none of which the IR has. That half is task 3a.9's, and
    `Geometry.encodes` is the sentence it should be holding the diagram to.
    """

    relationship: DiagramRelationship = Field(
        description="What the points have to do with each other. Classify BEFORE choosing a "
        "geometry — see `GEOMETRIES` for which geometries may encode which relationship."
    )
    kind: DiagramKind = Field(description="The geometry. Must encode `relationship`.")
    title: str | None = None
    process_flow: ProcessFlowSpec | None = None
    two_by_two: TwoByTwoSpec | None = None
    layered_stack: LayeredStackSpec | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_untyped_nodes(cls, data: Any) -> Any:
        """Catch the old shape — `nodes=[...]`, `edges=[...]` — with an explanation.

        `extra="forbid"` would already refuse these, saying only that the field is unknown.
        A stored IR written before this phase, or a model copying an older example, deserves
        to be told what replaced them.
        """
        if isinstance(data, dict):
            legacy = sorted(k for k in ("nodes", "edges") if k in data)
            if legacy:
                raise ValueError(
                    f"DiagramSpec no longer takes {', '.join(legacy)} directly. Nodes live "
                    "in the payload for the declared `kind` (`process_flow`, `two_by_two`, "
                    "`layered_stack`) with the fields that geometry needs — an order, a "
                    "position, a level — and `nodes`/`edges` are derived from it."
                )
        return data

    @model_validator(mode="after")
    def _geometry_matches_kind(self) -> DiagramSpec:
        geometry = GEOMETRIES[self.kind]
        present = sorted(
            field for field in _GEOMETRY_FIELDS if getattr(self, field) is not None
        )
        if geometry.payload_field is None:
            raise ValueError(
                f"diagram kind {self.kind!r} is in the catalog but is not modelled yet "
                f"({geometry.catalog_entry}). Adding it is a payload class, a field on "
                "DiagramSpec and a `payload_field` in GEOMETRIES — not an image and not a "
                "bag of untyped nodes standing in for one."
            )
        if present != [geometry.payload_field]:
            raise ValueError(
                f"diagram of kind {self.kind!r} must set exactly {geometry.payload_field!r}"
                f"; got {', '.join(present) or 'nothing'}. One kind, one geometry payload."
            )
        return self

    @model_validator(mode="after")
    def _relationship_matches_geometry(self) -> DiagramSpec:
        geometry = GEOMETRIES[self.kind]
        if self.relationship not in geometry.relationships:
            allowed = ", ".join(geometry.relationships)
            elsewhere = ", ".join(geometries_for(self.relationship)) or "none registered"
            raise ValueError(
                f"a {self.kind!r} cannot encode {self.relationship!r}: it encodes "
                f"{allowed}. Geometry that does not match the relationship misstates how "
                f"the points relate, which is the claim the shape makes. For "
                f"{self.relationship!r}, try: {elsewhere}."
            )
        return self

    @model_validator(mode="after")
    def _node_ids_are_unique(self) -> DiagramSpec:
        ids = [node.id for node in self.nodes]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate diagram node ids: {', '.join(duplicates)}")
        return self

    @model_validator(mode="after")
    def _labels_fit_the_budget(self) -> DiagramSpec:
        """Node labels and structural text obey the geometry's word budget.

        §6.7's rule one level down: geometry buys clarity, not room. The title is exempt
        because it is set in the component's own slot and measured there; everything inside
        the geometry has only the space the geometry gives it.
        """
        budget = GEOMETRIES[self.kind].max_label_words
        over = [
            f"{site.location} ({len(site.text.split())} words)"
            for site in (
                *(TextSite(f"node {n.id}", n.label) for n in self.nodes),
                *self.payload.structural_texts(),
            )
            if len(site.text.split()) > budget
        ]
        if over:
            raise ValueError(
                f"diagram labels over the {budget}-word budget for {self.kind!r}: "
                f"{', '.join(over)}. If the content cannot compress to that, the slide is "
                "overloaded — split it, rather than shrinking the label until it fits."
            )
        return self

    @property
    def geometry(self) -> Geometry:
        """This diagram's registry entry — budgets, label anchors, shape vocabulary."""
        return GEOMETRIES[self.kind]

    @property
    def payload(self) -> DiagramGeometry:
        """The geometry payload `kind` names. Present by construction."""
        payload = getattr(self, _payload_field(self.kind))
        assert payload is not None  # guaranteed by `_geometry_matches_kind`
        return payload

    @property
    def nodes(self) -> tuple[DiagramNode, ...]:
        """Every node, in the order the geometry puts them in — never list order."""
        return self.payload.nodes

    @property
    def edges(self) -> tuple[DiagramEdge, ...]:
        """The arrows this geometry implies, empty where an arrow would overclaim."""
        return self.payload.edges

    def claims(self) -> list[Claim]:
        """Every claim carried by this diagram's nodes.

        **The single enumeration of claim sites inside a diagram.** Four places already walk
        `diagram.nodes` looking for `node.claim` — the validator's claim sites, the audit
        report's rows, and the numeric linter twice — and a fifth (`Block.blocks_render`)
        does not, which is how a `contradicted` diagram-node claim can print in the claims
        table and still render. Callers that ask this question should ask it here.
        """
        return [node.claim for node in self.nodes if node.claim is not None]

    def blocks_render(self) -> bool:
        """True when A3 forbids any of this diagram's node claims from reaching render."""
        return any(claim.blocks_render() for claim in self.claims())

    def framing_texts(self) -> tuple[TextSite, ...]:
        """Every text in this diagram that reaches the slide with no citation behind it.

        Title, framed node labels, and the geometry's own structural text (axis poles,
        transition labels). **This is the A5 surface of a diagram**: `LabelFraming` is a
        declaration that these say nothing about the world, and `framing_linter`'s fence is
        what tests the declaration. Enumerated here so that check is one call over one list
        rather than a second answer invented per caller.
        """
        sites: list[TextSite] = []
        if self.title:
            sites.append(TextSite("title", self.title))
        sites.extend(
            TextSite(f"node {node.id}", node.label)
            for node in self.nodes
            if node.framing is not None
        )
        sites.extend(self.payload.structural_texts())
        return tuple(sites)


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

    # -- planning provenance (Phase 2a) ------------------------------------
    #
    # Written by the outline agent, read by GATE 1 and by the content agent. They are on
    # the slide rather than in a side-car because a slide that has drifted from the brief
    # should be visible in the artifact everyone already reads, not in a second file that
    # has to be remembered.

    intent: str | None = Field(
        default=None,
        description=(
            "What this slide must accomplish, in one line — 'establish that the constraint "
            "is memory, not compute', never 'KV cache slide'. The content agent writes to "
            "this; a topic label tells it nothing the component does not already say."
        ),
    )
    message_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Which DeckBrief key messages this slide serves. GATE 1's first mechanical "
            "check is that every key message maps to at least one slide, and matching on "
            "prose would break the moment somebody rewords one."
        ),
    )
    pin_deviation: str | None = Field(
        default=None,
        description=(
            "Set when a layout pin could not be honoured, naming what was pinned, what was "
            "used, and why. A pin silently dropped teaches the consultant that pinning "
            "does nothing — so deviation is recorded, never merely allowed."
        ),
    )

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


EvidenceStatus = Literal["unprobed", "supported", "thin", "unsupported"]
"""How a key message stands against the corpus after the planner's evidence-gap check
(task 2a.4).

`unprobed` is the honest default — it means nobody looked, which is different from
`unsupported` (somebody looked and found nothing). Collapsing the two would let a brief
that skipped the check read exactly like one that passed it.
"""

PinTarget = Literal["component", "communication_mode", "diagram_kind"]
"""What a layout pin fixes. A human pinning "make this a two-by-two" is pinning a
`diagram_kind`; pinning "this must be the big number slide" is pinning a `component`."""


class KeyMessage(IRModel):
    """One thing the deck must land, and how it stands against the evidence.

    Carries an id because everything downstream refers back to it: layout pins target a
    message, open risks excuse a message, and GATE 1 checks that every message maps to at
    least one slide. Matching on prose would break the moment someone rewords one.
    """

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_status: EvidenceStatus = "unprobed"
    supporting_claims: list[str] = Field(
        default_factory=list,
        description=(
            "doc_ids or claims.md quotes the planner found while probing. Leads for the "
            "writer, not citations — a real Citation is resolved through the document "
            "store at write time (A1), never carried from planning."
        ),
    )
    probe_notes: str | None = Field(
        default=None, description="What the evidence-gap check actually found."
    )

    def needs_a_risk(self) -> bool:
        """Whether carrying this message requires an accepted, recorded gap.

        `thin` counts. A message resting on one weak source is exactly the kind that reads
        as supported in a deck and collapses under a client's question, and the planner
        brief (§6.13) exists to surface it while it still costs one conversational turn.
        """
        return self.evidence_status in ("unsupported", "thin")


class OpenRisk(IRModel):
    """An evidence gap the owner chose to carry, recorded rather than resolved.

    Plan §7 Phase 2a is explicit that proceeding without support is *allowed* — and that
    the gap **is not allowed to disappear**. So this is the receipt: it names the message,
    says who accepted it, and resurfaces in the audit report (A8).

    `accepted_by` has no default. A gap with nobody's name on it is not an accepted risk,
    it is an unaccounted one, and defaulting the field to "owner" would manufacture consent
    from a missing value.
    """

    message_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    accepted_by: str = Field(
        min_length=1, description="Who decided to carry it. A7 — never defaulted."
    )
    mitigation: str | None = Field(
        default=None,
        description="How the deck will hedge it — softer wording, an explicit assumption.",
    )


class LayoutPin(IRModel):
    """A human decision to fix how a message is presented (task 2a.5).

    Pins are honoured by the outline agent or their deviation is **flagged**, never
    silently overridden: a pin is the one place in planning where the owner's judgement
    outranks the system's, and quietly ignoring it teaches them not to bother.
    """

    message_id: str = Field(min_length=1)
    target: PinTarget
    value: str = Field(min_length=1, description="Component name, mode, or diagram kind.")
    rationale: str | None = None


class DeckBrief(IRModel):
    """The signed-off output of the planning session — the first of the four A7 approvals.

    Versioned into the run alongside the IR so GATE 1 can review the outline *against the
    brief* rather than against taste.

    **The load-bearing rule is `_gaps_are_accounted_for`.** A key message the planner found
    unsupported or thin can still go in the deck — plan §7 says so — but only with a
    matching `OpenRisk` naming who accepted it. That makes "carry it anyway" a recorded
    decision instead of a silent one, and it is a schema constraint for the same reason A1
    is: a rule enforced by the type cannot be skipped by a pass that forgot to call the
    checker.

    Note what this does *not* do: it never blocks an unsupported message. Blocking would
    push the planner toward marking things `supported` to get past the validator, which is
    the failure A8 is about. Carrying it is free; carrying it silently is impossible.
    """

    run_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    objective: str = Field(
        min_length=1, description="The decision or action this deck should produce."
    )
    audience: str = Field(min_length=1)
    key_messages: list[KeyMessage] = Field(min_length=1)
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    length_target: int | None = Field(default=None, ge=1)
    header_style: str | None = None
    layout_pins: list[LayoutPin] = Field(default_factory=list)
    reference_deck: str | None = None
    open_risks: list[OpenRisk] = Field(default_factory=list)
    approved_by: str | None = Field(
        default=None,
        description=(
            "A7: set only by an explicit human sign-off. The planner session may not set "
            "it, and no CLI flag approves a brief — see `orchestrator.approve`."
        ),
    )

    @model_validator(mode="after")
    def _message_ids_unique(self) -> DeckBrief:
        ids = [message.id for message in self.key_messages]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate key message ids: {', '.join(duplicates)}")
        return self

    @model_validator(mode="after")
    def _references_resolve(self) -> DeckBrief:
        """Pins and risks must point at messages that exist.

        A pin on a deleted message is a decision the outline will never honour and nobody
        will ever see fail. Cheaper to reject here than to debug at GATE 1.
        """
        known = {message.id for message in self.key_messages}
        dangling = sorted(
            {pin.message_id for pin in self.layout_pins if pin.message_id not in known}
            | {risk.message_id for risk in self.open_risks if risk.message_id not in known}
        )
        if dangling:
            raise ValueError(
                f"layout pins or open risks reference unknown key messages: "
                f"{', '.join(dangling)}"
            )
        return self

    @model_validator(mode="after")
    def _gaps_are_accounted_for(self) -> DeckBrief:
        """Every unsupported or thin key message carries a recorded, accepted risk (A8).

        This is the structural half of the evidence-gap check. The planner surfaces the gap
        in conversation; this makes it impossible for the resulting brief to forget.
        """
        excused = {risk.message_id for risk in self.open_risks}
        unaccounted = sorted(
            message.id
            for message in self.key_messages
            if message.needs_a_risk() and message.id not in excused
        )
        if unaccounted:
            raise ValueError(
                f"key message(s) {', '.join(unaccounted)} have weak or absent evidence but "
                "no matching entry in open_risks. Carrying an unsupported message is "
                "allowed (plan §7); carrying it without recording who accepted the gap is "
                "not — it would vanish before the audit report (A8)."
            )
        return self

    def message(self, message_id: str) -> KeyMessage | None:
        return next((m for m in self.key_messages if m.id == message_id), None)

    def pins_for(self, message_id: str) -> list[LayoutPin]:
        return [pin for pin in self.layout_pins if pin.message_id == message_id]

    def unprobed_messages(self) -> list[KeyMessage]:
        """Messages the evidence-gap check never ran against.

        Not an error — a brief can legitimately be drafted before probing — but GATE 1
        should see them, because "nobody looked" reads far too much like "it's fine".
        """
        return [m for m in self.key_messages if m.evidence_status == "unprobed"]
