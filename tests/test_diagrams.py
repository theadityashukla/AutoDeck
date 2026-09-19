"""The `DiagramSpec` type system: A1 at a node, and geometry that means something.

The first test in this file is the invariant. Everything else exists because of it: the
label/claim seam that makes the invariant survivable for real content, the fence that keeps
the seam from becoming the hole it replaced, and the structure that stops a geometry
claiming a relationship its content does not hold.

Owning phase: 3a (task 3a.6, the type system).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import get_args

import pytest
from pydantic import Field, ValidationError

from autodeck.audit.framing_linter import lint_framing_text
from autodeck.ir.models import (
    GEOMETRIES,
    Block,
    Citation,
    Claim,
    Deck,
    DiagramAxis,
    DiagramGeometry,
    DiagramNode,
    DiagramSpec,
    IRModel,
    LabelFraming,
    LayeredStackSpec,
    ProcessFlowSpec,
    ProcessStep,
    QuadrantItem,
    Slide,
    StackLayer,
    TwoByTwoSpec,
    geometries_for,
    relationships_without_geometry,
)
from autodeck.ir.store import IRStore

QUOTE = "Inference cost per request fell from $0.41 to $0.24 after the cutover."


def citation() -> Citation:
    return Citation.for_quote(
        doc_id="vendor-report",
        page=4,
        bbox=(10.0, 20.0, 300.0, 44.0),
        quote=QUOTE,
        retrieved_by="writer",
    )


def claim(text: str = "Inference cost per request fell by 41%.") -> Claim:
    return Claim(text=text, citations=[citation()])


def stage(node_id: str, label: str, order: int) -> ProcessStep:
    """A step whose label names a stage of the work and asserts nothing about the world."""
    return ProcessStep(
        id=node_id, label=label, order=order, framing=LabelFraming(reason="stage_name")
    )


# ---------------------------------------------------------------------------
# A1 — the invariant. This is the test the type system exists to pass.
# ---------------------------------------------------------------------------


def test_a_factual_node_without_a_citation_cannot_be_constructed() -> None:
    """Catches: a fact reaching a slide inside a box, with no evidence behind it.

    The whole reason a diagram needs its own answer to A1: three words in a shape read as a
    label, so an assertion typed into one is the least likely thing in the deck to be
    challenged. `Claim.citations` already makes an evidence-free claim unconstructible; the
    node's job is to make "no claim at all" equally unconstructible, so that omission is
    not the way round the constraint.
    """
    with pytest.raises(ValidationError, match="neither claim nor framing"):
        ProcessStep(id="n1", label="Cost fell 41%", order=1)

    # And the same node with its evidence is fine — the constraint is about citations,
    # not about what a node may say.
    ProcessStep(id="n1", label="Cost fell 41%", order=1, claim=claim())


def test_a_node_cannot_be_both_claimed_and_framed() -> None:
    """Catches: a node that says both "this is evidenced" and "this asserts nothing".

    Ambiguity here is not harmless. Every consumer downstream — the validator, the audit
    report, the numeric linter, the render guard — would be free to resolve it differently,
    and the one that resolved it as `framing` would be the one that let the fact through.
    """
    with pytest.raises(ValidationError, match="both claim and framing"):
        ProcessStep(
            id="n1",
            label="Cost fell 41%",
            order=1,
            claim=claim(),
            framing=LabelFraming(reason="stage_name"),
        )


def test_the_citation_constraint_is_what_stops_it_disable_it_and_this_goes_red() -> None:
    """Disable the defence, confirm red — the tripwire `Demotion.a1_error` uses on blocks.

    Two defences stand between a factual node label and a slide, and this test names both
    so that removing either is loud. The second is the one that matters: if
    `Claim.citations`' `min_length=1` were ever relaxed, a node could carry an
    evidence-free claim, every node in the deck would satisfy the seam above, and A1 would
    be a docstring. The `RuntimeError` fires in that world instead of the test quietly
    continuing to pass.
    """
    # Defence one: a node that declares no status at all.
    with pytest.raises(ValidationError, match="exactly one is required"):
        ProcessStep(id="n1", label="Cost fell 41%", order=1)

    # Defence two: a node that declares a claim, and the claim has no evidence.
    try:
        ProcessStep(
            id="n1",
            label="Cost fell 41%",
            order=1,
            claim=Claim(text="Inference cost per request fell by 41%.", citations=[]),
        )
    except ValidationError as exc:
        assert "citations" in str(exc)
    else:  # pragma: no cover — reached only once A1 has been relaxed
        raise RuntimeError(
            "a diagram node accepted a claim with no citations. A1 is enforced by "
            "Claim.citations' min_length=1 and something has relaxed it; the diagram "
            "engine is now a loophole in it. See INVARIANTS A1."
        )


def test_the_unguarded_twin_shows_what_the_validator_is_holding_back() -> None:
    """What the IR would carry if `_label_is_claimed_or_framed` were deleted.

    The same fields, the same values, no validator: an uncited assertion sitting in a
    diagram looking exactly like a stage name. Spelled out because the defence is four
    lines long and reads like tidiness rather than like the invariant it is.
    """

    class UnguardedNode(IRModel):
        id: str = Field(min_length=1)
        label: str = Field(min_length=1)
        claim: Claim | None = None
        framing: LabelFraming | None = None

    smuggled = UnguardedNode(id="n1", label="Cost fell 41%")
    assert smuggled.claim is None and smuggled.framing is None

    with pytest.raises(ValidationError):
        DiagramNode.model_validate(smuggled.model_dump())


# ---------------------------------------------------------------------------
# The label/claim seam — and the attack on it
# ---------------------------------------------------------------------------


def test_a_genuine_label_is_constructible_and_passes_the_fence() -> None:
    """Not every node is factual, and the type system may not pretend otherwise.

    `Discovery` on a process flow and `Low cost` on an axis assert nothing about the world;
    a type system that demanded citations for them would be one nobody could use, which is
    how constraints end up relaxed. So the exemption exists — and the same A5 fence that
    keeps `framing` blocks honest finds nothing to complain about in these.
    """
    flow = DiagramSpec(
        relationship="sequence",
        kind="process_flow",
        process_flow=ProcessFlowSpec(
            steps=[stage("n1", "Discovery", 1), stage("n2", "Pilot", 2)]
        ),
    )

    assert [node.label for node in flow.nodes] == ["Discovery", "Pilot"]
    assert flow.framing_texts() == (("node n1", "Discovery"), ("node n2", "Pilot"))
    assert not [f for site in flow.framing_texts() for f in lint_framing_text(site.text)]


def test_the_framing_declaration_cannot_smuggle_a_fact_past_the_fence() -> None:
    """The attack: declare the fact a category name and walk it through the exemption.

    `Cheaper than Oracle` is an assertion about the world with a `category_name` waiver
    stapled to it. The IR cannot see that — it holds the text, and deciding whether a
    sentence asserts something is exactly the judgement `framing_linter.py` keeps
    deterministic by owning it in one place, which the IR cannot call without closing an
    import cycle. So the declaration is not the defence.

    The defence is that the declaration is **enumerable**: every uncited text in a diagram
    comes back from one call, and A5's existing fence — unchanged, not reimplemented here —
    demotes this one on sight. The attack succeeds against the type and fails against the
    lint, which is the same division of labour A5 already has for prose.
    """
    attack = DiagramSpec(
        relationship="sequence",
        kind="process_flow",
        process_flow=ProcessFlowSpec(
            steps=[
                stage("n1", "Migrate", 1),
                ProcessStep(
                    id="n2",
                    label="Cheaper than Oracle",
                    order=2,
                    framing=LabelFraming(reason="category_name"),
                ),
            ]
        ),
    )

    findings = [
        (site.location, finding)
        for site in attack.framing_texts()
        for finding in lint_framing_text(site.text, location=site.location)
    ]
    assert [location for location, _ in findings] == ["node n2"]
    assert all(finding.severity == "blocking" for _, finding in findings)
    assert "factual comparative" in {finding.check for _, finding in findings}


def test_a_transition_label_and_an_axis_pole_are_on_the_fenced_list_too() -> None:
    """Catches: the fact moved out of the node and into the geometry's own furniture.

    A node is not the only text a diagram puts on a slide. An arrow's label and an axis's
    poles are uncited by construction, so if the enumeration missed them the smuggler would
    simply move one word to the left.
    """
    flow = DiagramSpec(
        relationship="sequence",
        kind="process_flow",
        process_flow=ProcessFlowSpec(
            steps=[
                ProcessStep(
                    id="n1",
                    label="Migrate",
                    order=1,
                    transition="Twice as fast",
                    framing=LabelFraming(reason="stage_name"),
                ),
                stage("n2", "Serve", 2),
            ]
        ),
    )
    grid = two_by_two(x_low="Cheaper than Oracle")

    def caught_by_the_fence(spec: DiagramSpec) -> list[str]:
        return [site.location for site in spec.framing_texts() if lint_framing_text(site.text)]

    assert ("step n1 transition", "Twice as fast") in flow.framing_texts()
    assert ("x_axis low", "Cheaper than Oracle") in grid.framing_texts()
    assert caught_by_the_fence(flow) == ["step n1 transition"]
    assert caught_by_the_fence(grid) == ["x_axis low"]


# ---------------------------------------------------------------------------
# The relationship is named first, and the geometry must encode it
# ---------------------------------------------------------------------------


def test_a_geometry_that_does_not_match_its_relationship_is_rejected() -> None:
    """Catches: N points becoming N shapes chosen for looks rather than for meaning.

    The skill's step 1 is the load-bearing one — classify, then choose. A spec that could
    name `cycle` and draw a chevron flow would let the shape misstate how the points
    relate, which is the one claim a geometry makes that no caption can retract.
    """
    with pytest.raises(ValidationError, match="cannot encode 'cycle'"):
        DiagramSpec(
            relationship="cycle",
            kind="process_flow",
            process_flow=ProcessFlowSpec(
                steps=[stage("n1", "Discovery", 1), stage("n2", "Pilot", 2)]
            ),
        )


def test_the_rejection_says_which_geometry_would_have_worked() -> None:
    """A refusal that does not name the alternative gets worked around, not fixed."""
    with pytest.raises(ValidationError) as caught:
        DiagramSpec(
            relationship="hierarchy_foundation",
            kind="process_flow",
            process_flow=ProcessFlowSpec(
                steps=[stage("n1", "Discovery", 1), stage("n2", "Pilot", 2)]
            ),
        )
    message = str(caught.value)
    assert "layered_stack" in message and "pyramid" in message
    assert geometries_for("hierarchy_foundation") == ("layered_stack", "pyramid")


def test_a_kind_the_catalog_describes_but_this_phase_does_not_model_is_refused() -> None:
    """Catches: an unmodelled geometry accepting a shapeless bag of nodes on its behalf.

    Three of the seven kinds are modelled because three are rendered this phase. The rest
    are registered — their relationships, budgets and catalog entries are known — and
    refused, with an error that says what adding one takes. The alternative, a generic node
    list for "the others", is the design this type system exists to replace.
    """
    with pytest.raises(ValidationError, match="not modelled yet"):
        DiagramSpec(relationship="cycle", kind="cycle")

    assert GEOMETRIES["cycle"].payload_field is None
    assert GEOMETRIES["cycle"].relationships == ("cycle",)


def test_relationships_the_skill_names_that_no_geometry_can_encode_are_listed() -> None:
    """The mechanical half of PHASE-3A's "keep the two in sync" review.

    Five of the skill's relationships have no geometry here. That is a finding about
    coverage, not a bug, and it is worth failing if it changes silently: a classifier can
    legitimately conclude `overlap`, and nothing downstream can draw one.
    """
    assert relationships_without_geometry() == (
        "mutual_reinforcement",
        "complement",
        "overlap",
        "containment",
        "transformation",
    )


# ---------------------------------------------------------------------------
# Each geometry models its own relationship, not a common bag of nodes
# ---------------------------------------------------------------------------


def two_by_two(*, x_low: str = "Low") -> DiagramSpec:
    return DiagramSpec(
        relationship="classification",
        kind="two_by_two",
        two_by_two=TwoByTwoSpec(
            x_axis=DiagramAxis(name="Cost to serve", low=x_low, high="High"),
            y_axis=DiagramAxis(name="Switching effort", low="Low", high="High"),
            items=[
                QuadrantItem(
                    id="q1",
                    label="Self-serve",
                    x=0.2,
                    y=0.1,
                    framing=LabelFraming(reason="category_name"),
                ),
                QuadrantItem(id="q2", label="Managed", x=0.8, y=0.7, claim=claim()),
            ],
        ),
    )


def layered_stack() -> DiagramSpec:
    return DiagramSpec(
        relationship="hierarchy_foundation",
        kind="layered_stack",
        layered_stack=LayeredStackSpec(
            support="rests_on",
            layers=[
                StackLayer(
                    id="l1",
                    label="Data platform",
                    level=1,
                    framing=LabelFraming(reason="actor_name"),
                ),
                StackLayer(
                    id="l2",
                    label="Serving",
                    level=2,
                    framing=LabelFraming(reason="actor_name"),
                ),
            ],
        ),
    )


def process_flow() -> DiagramSpec:
    return DiagramSpec(
        relationship="sequence",
        kind="process_flow",
        title="How the cutover runs",
        process_flow=ProcessFlowSpec(
            steps=[
                stage("s3", "Cutover", 3),
                stage("s1", "Discovery", 1),
                ProcessStep(id="s2", label="Pilot", order=2, claim=claim()),
            ]
        ),
    )


def test_a_step_knows_it_is_the_third_step_without_a_convention_about_list_order() -> None:
    """Catches: a shuffled list silently becoming a different diagram.

    The steps are declared 3, 1, 2. Order is a field, so the flow runs 1, 2, 3 and the
    arrows follow it. Were order a convention about list position, this diagram would be
    wrong and nothing in the system could tell — and a reordering in a gate diff would read
    as an edit to every step after the first.
    """
    flow = process_flow()

    assert [node.id for node in flow.nodes] == ["s1", "s2", "s3"]
    assert [(e.source, e.target) for e in flow.edges] == [("s1", "s2"), ("s2", "s3")]


def test_an_item_holds_a_position_in_two_dimensions_and_a_layer_holds_a_level() -> None:
    """Each geometry models its own relationship rather than sharing a node bag."""
    grid = two_by_two()
    stack = layered_stack()

    assert [i.quadrant for i in grid.payload_as(TwoByTwoSpec).items] == ["low_low", "high_high"]
    assert [node.id for node in stack.nodes] == ["l1", "l2"]
    # No arrows: neither geometry claims flow, and an arrow would say it did.
    assert grid.edges == () and stack.edges == ()


def test_a_two_by_two_needs_two_real_continuums() -> None:
    """The catalog's own rule: *"If you cannot name both axes as continuums, this is not a
    2x2 — reclassify."* Four boxes with arrowheads is the anti-pattern it names."""
    with pytest.raises(ValidationError, match="same label at both ends"):
        DiagramAxis(name="Cost", low="High", high="High")

    with pytest.raises(ValidationError, match="continuums"):
        TwoByTwoSpec(
            x_axis=DiagramAxis(name="Cost", low="Low", high="High"),
            y_axis=DiagramAxis(name="Cost", low="Low", high="High"),
            items=[
                QuadrantItem(
                    id="q1",
                    label="A",
                    x=0.1,
                    y=0.1,
                    framing=LabelFraming(reason="category_name"),
                ),
                QuadrantItem(
                    id="q2",
                    label="B",
                    x=0.9,
                    y=0.9,
                    framing=LabelFraming(reason="category_name"),
                ),
            ],
        )


def test_a_gap_in_a_sequence_or_a_stack_is_refused() -> None:
    """Catches: a flow with two third steps and no second, which nobody can draw twice."""
    with pytest.raises(ValidationError, match=r"expected exactly 1\.\.2"):
        ProcessFlowSpec(steps=[stage("n1", "A", 1), stage("n2", "B", 3)])

    with pytest.raises(ValidationError, match=r"expected exactly 1\.\.2"):
        LayeredStackSpec(
            support="peers",
            layers=[
                StackLayer(
                    id="l1", label="A", level=2, framing=LabelFraming(reason="actor_name")
                ),
                StackLayer(
                    id="l2", label="B", level=3, framing=LabelFraming(reason="actor_name")
                ),
            ],
        )


def test_node_labels_obey_the_geometrys_word_budget() -> None:
    """The brief's done-when, in the skill's own unit: node labels of 2 to 4 words.

    Declared here and measured in `autodeck/design/` — the IR may not import the font
    metrics, and a budget stated in words is one a writer can hold in its head and a
    renderer can check before it has a box. Geometry buys clarity, not room.
    """
    with pytest.raises(ValidationError, match="over the 4-word budget"):
        DiagramSpec(
            relationship="sequence",
            kind="process_flow",
            process_flow=ProcessFlowSpec(
                steps=[
                    stage("n1", "Discovery", 1),
                    stage("n2", "Migrate the last workload off Oracle", 2),
                ]
            ),
        )

    assert GEOMETRIES["process_flow"].max_label_words == 4


# ---------------------------------------------------------------------------
# Claim sites, enumerated once
# ---------------------------------------------------------------------------


def test_a_diagrams_claims_are_enumerated_in_one_place() -> None:
    """Catches: every caller inventing its own walk to find claims inside a diagram.

    Four already do. `Block.claims()` is the answer for a block, `DiagramSpec.claims()` for
    a diagram, and `DiagramSpec.blocks_render()` answers A3's question about a diagram
    without the caller having to know that claims can hide one level down.
    """
    grid = two_by_two()
    block = Block(id="b1", kind="diagram", slot="body", diagram=grid)

    assert [c.text for c in grid.claims()] == ["Inference cost per request fell by 41%."]
    assert block.claims() == grid.claims()
    assert not grid.blocks_render()

    contradicted = grid.model_copy(deep=True)
    verdict_holder = contradicted.payload_as(TwoByTwoSpec).items[1].claim
    assert verdict_holder is not None
    verdict_holder.verdict = "contradicted"
    assert contradicted.blocks_render()
    assert [c.blocks_render() for c in contradicted.claims()] == [True]


def test_a_framed_node_is_not_a_claim_site() -> None:
    """A1's seam composes with the deck-wide walk, in the direction that matters.

    `DiagramNode` demands exactly one of `claim` and `framing`, so "no claim here" is a
    declaration rather than an omission — and the walk must take it at its word. A framed
    label produces no claim site, is not sent to the validator, and cannot block a render;
    the fence that keeps that honest is `framing_linter`'s, not the walk's.
    """
    grid = two_by_two()
    block = Block(id="b1", kind="diagram", slot="body", diagram=grid)

    assert [node.id for node in grid.nodes if node.framing is not None] == ["q1"]
    assert [site.node_id for site in block.claim_sites()] == ["q2"]
    assert block.claims() == grid.claims()


def test_a_claim_site_names_the_field_the_node_is_actually_stored_in() -> None:
    """Catches: a path that describes the derived view rather than the IR.

    `nodes` is derived, so `diagram.nodes[q2]` names nothing a stored deck contains, and
    `test_the_claim_walk_visits_every_place_a_claim_can_live` compares the walk against
    the *model graph*. A path naming the geometry's own field is what lets that comparison
    stay an equality instead of becoming a translation table.
    """
    block = Block(id="b1", kind="diagram", slot="body", diagram=two_by_two())

    assert [site.path for site in block.claim_sites()] == [
        "blocks[b1].diagram.two_by_two.items[q2].claim"
    ]


def layered_stack_with_a_claim() -> DiagramSpec:
    """A stack whose upper band asserts something; the foundation is only a name."""
    return DiagramSpec(
        relationship="hierarchy_foundation",
        kind="layered_stack",
        layered_stack=LayeredStackSpec(
            support="rests_on",
            layers=[
                StackLayer(
                    id="l1",
                    label="Data platform",
                    level=1,
                    framing=LabelFraming(reason="actor_name"),
                ),
                StackLayer(id="l2", label="Serving cost fell", level=2, claim=claim()),
            ],
        ),
    )


#: Every geometry, with a builder that puts a claim in it. Kept as a table so that
#: `test_every_geometry_is_covered_by_the_write_through_test` can hold it to the union.
CLAIM_BEARING_GEOMETRIES: tuple[tuple[str, Callable[[], DiagramSpec], type], ...] = (
    ("process_flow", process_flow, ProcessFlowSpec),
    ("two_by_two", two_by_two, TwoByTwoSpec),
    ("layered_stack", layered_stack_with_a_claim, LayeredStackSpec),
)


def stored_nodes(spec: DiagramSpec) -> list[DiagramNode]:
    """The payload's own node objects, read off its fields and never through `nodes`.

    The point of the detour: the write-through test must not prove its conclusion with the
    same derived property whose behaviour is under test.
    """
    payload = spec.payload
    found: list[DiagramNode] = []
    for field in type(payload).model_fields:
        value = getattr(payload, field)
        if isinstance(value, list):
            found.extend(item for item in value if isinstance(item, DiagramNode))
    return found


def test_every_geometry_is_covered_by_the_write_through_test() -> None:
    """Catches: a fourth geometry arriving with nobody checking a verdict can reach it."""
    covered = {payload for _, _, payload in CLAIM_BEARING_GEOMETRIES}

    assert covered == set(get_args(DiagramGeometry))


@pytest.mark.parametrize(
    ("build", "payload_type"),
    [(build, payload) for _, build, payload in CLAIM_BEARING_GEOMETRIES],
    ids=[name for name, _, _ in CLAIM_BEARING_GEOMETRIES],
)
def test_a_verdict_written_through_a_claim_site_reaches_the_stored_node(
    build: Callable[[], DiagramSpec], payload_type: type
) -> None:
    """**If this fails, a validator's judgement is written to a temporary and lost.**

    `ClaimSite._write` does `node.claim = new_claim` on whatever object the walk handed
    it, and the walk gets its nodes from a *derived* property. Write-through therefore
    holds only while every geometry's `nodes` returns the objects its payload stores. That
    is a property of three implementations rather than of the type, so it is asserted per
    geometry, and asserted by reading the payload's own fields back.
    """
    spec = build()
    block = Block(id="b1", kind="diagram", slot="body", diagram=spec)
    sites = block.claim_sites(slide_id="s1")

    assert sites, "the fixture is meant to carry a claim"
    assert not block.blocks_render()

    for site in sites:
        site.replace(site.claim.model_copy(update={"verdict": "contradicted"}))

    verdicts_stored = [
        node.claim.verdict for node in stored_nodes(spec) if node.claim is not None
    ]
    assert verdicts_stored == ["contradicted"] * len(sites)
    assert isinstance(spec.payload, payload_type)
    assert block.blocks_render(), "the write reached the object A3 reads"
    assert spec.blocks_render()


def test_a_geometry_whose_nodes_are_rebuilt_is_refused_rather_than_silently_ignored() -> None:
    """Catches: the *fourth* geometry, written with a `nodes` that builds fresh objects.

    This is the failure the three real geometries happen not to have. A `nodes` property
    returning copies type-checks, round-trips, renders and passes every other test in this
    file — and quietly swallows every verdict written through a `ClaimSite`, so a
    contradicted claim would reach the slide. `claim_nodes()` locates each node in the
    payload by identity, so the copy is caught where it is made rather than three phases
    later on a rendered deck.
    """

    class RebuildingFlow(ProcessFlowSpec):
        @property
        def nodes(self) -> tuple[DiagramNode, ...]:
            return tuple(step.model_copy(deep=True) for step in self.steps_in_order())

    spec = process_flow()
    rebuilt = RebuildingFlow(steps=spec.payload_as(ProcessFlowSpec).steps)
    broken = spec.model_copy(update={"process_flow": rebuilt})

    with pytest.raises(TypeError, match="not an object this payload stores"):
        broken.claim_nodes()

    with pytest.raises(TypeError, match="not an object this payload stores"):
        Block(id="b1", kind="diagram", slot="body", diagram=broken).claim_sites()


# ---------------------------------------------------------------------------
# Round trip — a diagram that comes back reordered is a wrong diagram
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "build"),
    [
        ("process_flow", process_flow),
        ("two_by_two", two_by_two),
        ("layered_stack", layered_stack),
    ],
)
def test_each_type_round_trips_through_the_ir_store(
    tmp_path: Path, name: str, build: Callable[[], DiagramSpec]
) -> None:
    """Catches: order or position lost in serialisation.

    A process flow whose steps come back in a different order is a wrong diagram, not a
    cosmetic bug — the arrows would point somewhere else and the slide would say something
    the corpus never said. Position on a 2x2 and level in a stack are the same claim in a
    different geometry, so all three go through the real store rather than through
    `model_dump` alone.
    """
    spec = build()
    deck = Deck(
        run_id="run-diagrams",
        project="p",
        client="c",
        audience="a",
        version=1,
        theme_ref="theme-1",
        component_lib_version="0.2.0",
        slides=[
            Slide(
                id="s1",
                narrative_role="evidence",
                component="framework_diagram",
                blocks=[Block(id=f"b-{name}", kind="diagram", slot="body", diagram=spec)],
            )
        ],
    )

    store = IRStore(tmp_path, deck.run_id)
    store.save(deck)
    loaded = store.load()

    assert loaded == deck
    restored = loaded.slides[0].blocks[0].diagram
    assert restored is not None
    assert [node.id for node in restored.nodes] == [node.id for node in spec.nodes]
    assert [node.label for node in restored.nodes] == [node.label for node in spec.nodes]
    assert restored.edges == spec.edges
    assert restored.claims() == spec.claims()


def test_the_round_trip_survives_a_shuffled_payload(tmp_path: Path) -> None:
    """The stronger version: the list arrives in the wrong order on purpose.

    `process_flow()` declares its steps 3, 1, 2 — so this passes only because order is
    carried by a field. A JSON file hand-edited into a different list order is the same
    diagram, which is exactly the property a convention about list position would not have.
    """
    spec = process_flow()
    shuffled = spec.model_dump(mode="json")
    shuffled["process_flow"]["steps"].reverse()

    assert [node.id for node in DiagramSpec.model_validate(shuffled).nodes] == [
        "s1",
        "s2",
        "s3",
    ]


def test_the_old_untyped_shape_is_refused_with_an_explanation(tmp_path: Path) -> None:
    """A stored IR or a copied example from before this phase gets told what replaced it.

    `extra="forbid"` would refuse `nodes=[...]` anyway, saying only that the field is
    unknown. What a caller needs to hear is that nodes moved into the geometry's payload
    and gained the fields that geometry needs.
    """
    with pytest.raises(ValidationError, match="no longer takes nodes"):
        DiagramSpec.model_validate(
            {
                "relationship": "sequence",
                "kind": "process_flow",
                "nodes": [{"id": "n1", "label": "Discovery"}],
            }
        )
