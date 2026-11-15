"""Task 23.10: the Phase 2-3 views and context additions: each slide's brief and state in
the outline, the design system as the lead reads it (no colours), the Design tab's JSON,
the routing record on assistant messages, and staleness in the open items."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from autodeck.studio import edits
from autodeck.studio.context import (
    ArtifactState,
    ContextInputs,
    Knowledge,
    open_items,
    render_context,
)
from autodeck.studio.conversation import (
    AssistantLine,
    ProposalOption,
    ProposalRecord,
    TurnEndLine,
    UserLine,
)
from autodeck.studio.design import DesignSystem, default_design_system
from autodeck.studio.models import (
    ChangeLog,
    ComposedFrom,
    CompositionFailure,
    DeckArtifact,
    Slide,
    brief_digest,
)
from autodeck.studio.serialise import artifact_digest
from autodeck.studio.usage import LayerUsage, RouteRecord, TurnUsage
from autodeck.studio.views import (
    composition_view,
    deck_outline,
    design_draft_view,
    design_system_text,
    design_system_view,
    messages_view,
    proposal_view,
)
from tests.studio.helpers import T0, dev_tokens, flow_brief, flow_designed, flow_draft

DARK = "Demand curve"


def demand_curve(marker: str = "decided") -> DesignSystem:
    draft = flow_draft(DARK)
    return DesignSystem(
        id="demand-curve", version=1, marker=marker, created_at=T0, **draft.model_dump()
    )


def designed(slide_id: str, design: str = "default") -> Slide:
    data = flow_designed(slide_id, design)["slide"]
    b = flow_brief(slide_id)
    return Slide(
        id=slide_id, intent=b.intent, brief=b, blocks=data["blocks"], layout=data["layout"]
    )


def three_slide_deck() -> DeckArtifact:
    """s1 fresh (default), s2 stale (brief changed), s3 not designed."""
    deck = DeckArtifact(id="pilot-readout", client="c", project="p", title="Readout")
    for sid in ("s1", "s2", "s3"):
        deck, _, _ = edits.set_slide_brief(deck, sid, flow_brief(sid))
    for sid in ("s1", "s2"):
        deck = edits.apply_composition(
            deck,
            sid,
            designed(sid),
            ComposedFrom(
                brief_digest=brief_digest(flow_brief(sid)),
                system_id="default",
                system_version=1,
                model_id="scripted/designer",
            ),
        )
    changed = flow_brief("s2").model_copy(update={"notes": "Lead with the number."})
    deck, _, _ = edits.set_slide_brief(deck, "s2", changed)
    return deck


def test_the_outline_shows_each_slides_brief_and_state() -> None:
    lines = deck_outline(three_slide_deck()).split("\n")
    assert lines[-7] == (
        '     brief: "Northwind can serve its shopping assistant at 38% lower cost" | '
        "2 points, 2 figures, no chart | designed"
    )
    assert lines[-4] == (
        '     brief: "Quantisation alone cuts serving cost by 38%" | 2 points, 1 figure, '
        "chart | stale: brief changed"
    )
    assert lines[-1] == (
        '     brief: "What it costs and what it returns" | 1 point, 3 figures, no chart | '
        "not designed yet"
    )
    assert lines[-3] == "  3. s3 [provisional] serves - | no layout | intent: " + (
        flow_brief("s3").intent
    )


def test_a_failed_slide_says_why_in_the_outline() -> None:
    deck = three_slide_deck()
    failure = CompositionFailure(
        brief_digest=brief_digest(flow_brief("s3")),
        system_id="default",
        system_version=1,
        model_id="scripted/designer",
        attempts=4,
        findings=["[text_fit] f2: needs 90pt of height", "[overlap] a"],
    )
    deck = edits.record_compose_failure(deck, "s3", failure)
    assert (
        deck_outline(deck)
        .split("\n")[-1]
        .endswith("| failed to compose: [text_fit] f2: needs 90pt of height (4 attempts)")
    )


def test_the_design_system_text_has_no_colours() -> None:
    assert design_system_text(demand_curve()) == (
        "Demand curve (demand-curve v1, decided)\n"
        f"Concept: {flow_draft(DARK).concept}\nRules:\n"
        + "\n".join(f"- {r}" for r in flow_draft(DARK).rules)
    )
    default = design_system_text(default_design_system(dev_tokens()))
    assert default == "Default (default v1, provisional)\nConcept: none stated\nRules: none"
    assert "#" not in design_system_text(demand_curve())


def test_the_design_tab_views() -> None:
    view = design_system_view(demand_curve())
    assert (view["id"], view["version"], view["name"], view["marker"]) == (
        "demand-curve",
        1,
        DARK,
        "decided",
    )
    assert view["is_default"] is False and view["background"] == "lt2"
    assert view["created_at"] == "2026-11-13T09:00:00+00:00"
    assert view["palette"][3] == {
        "slot": "lt2",
        "hex": "#0F1D30",
        "role": flow_draft(DARK).roles["lt2"],
    }
    assert [p["slot"] for p in view["palette"]][:2] == ["dk1", "lt1"]
    assert view["text_pairs"][0] == {"text": "lt1", "ground": "lt2", "large_only": False}
    default = design_system_view(default_design_system(dev_tokens()))
    assert default["is_default"] and default["created_at"] is None
    assert default["palette"][0]["role"] == ""
    draft = design_draft_view(flow_draft(DARK))
    assert draft["name"] == DARK and draft["palette"][3]["hex"] == "#0F1D30"
    assert "id" not in draft


def test_composition_view() -> None:
    view = composition_view(three_slide_deck())
    assert view["s1"] == {
        "state": "fresh",
        "reasons": [],
        "failure": None,
        "composed_by": "scripted/designer",
    }
    assert view["s2"]["state"] == "stale" and view["s2"]["reasons"] == ["brief changed"]
    assert view["s3"]["state"] == "undesigned" and view["s3"]["composed_by"] is None


def test_assistant_messages_carry_roles_route_and_usage() -> None:
    usage = TurnUsage(
        layers=[
            LayerUsage(
                role="mechanic",
                layer="mechanics",
                model_id="scripted/mechanic",
                calls=2,
                input_tokens=900,
                output_tokens=30,
                cost_usd=0.003,
            )
        ],
        total_cost_usd=0.003,
    )
    route = RouteRecord(route="mechanic", by="rule", reason="retitle a slide")
    lines = [
        UserLine(seq=1, created_at=T0, turn_id="u0001", origin="owner", text="Retitle slide 2"),
        AssistantLine(
            seq=2,
            created_at=T0,
            turn_id="u0001",
            role="mechanic",
            step=1,
            model_id="m",
            text="Done.",
        ),
        TurnEndLine(
            seq=3,
            created_at=T0,
            turn_id="u0001",
            turn_kind="talk",
            stop_reason="replied",
            model_id="scripted/mechanic",
            steps=1,
            route=route,
            usage=usage,
        ),
    ]
    item = messages_view(lines)[1]
    assert item["roles"] == ["mechanic"]
    assert item["route"] == route.model_dump(mode="json")
    assert item["usage"]["layers"][0]["role"] == "mechanic"
    assert item["usage"]["total_cost_usd"] == 0.003 and item["usage"]["prices_assumed"] is True


def test_a_design_option_says_what_applying_it_does() -> None:
    sample = designed("s2", DARK)
    record = ProposalRecord(
        id="p0001",
        thread_id="t0001",
        turn_id="u0002",
        artifact_id="pilot-readout",
        summary="Two directions",
        options=[
            ProposalOption(
                id="A",
                label=DARK,
                text="Night blue",
                design=flow_draft(DARK),
                candidates=[{"slide": sample, "replaces": "s2"}],  # type: ignore[list-item]
            )
        ],
        created_at=T0,
    )
    option = proposal_view(record)["options"][0]
    assert option["applies"] == 'Adopts the design "Demand curve"; designed slides become stale'
    assert option["design"]["name"] == DARK


def _inputs(deck: DeckArtifact, system: DesignSystem | None) -> ContextInputs:
    log = ChangeLog(artifact_id=deck.id, initial_digest=artifact_digest(deck))
    return ContextInputs(
        client="c",
        project="p",
        title="",
        knowledge=Knowledge("p", "c", "v"),
        engagement_memory=(),
        owner_memory=(),
        artifacts=(ArtifactState(deck, log, system),),
        proposals=(),
    )


def test_open_items_list_stale_failed_undesigned_and_the_default_design() -> None:
    deck = three_slide_deck()
    items = open_items(_inputs(deck, None))
    assert (
        "pilot-readout: the design system is the provisional default (no concept decided)"
        in items
    )
    assert "pilot-readout: slide 2 (s2) is stale: brief changed" in items
    assert "pilot-readout: slide 3 (s3) is not designed yet" in items
    assert not any("s1) is stale" in i or "has no layout" in i for i in items)
    moved = edits.set_design_system(deck, demand_curve("provisional").ref())
    items = open_items(_inputs(moved, demand_curve("provisional")))
    assert "pilot-readout: the design system is provisional" in items
    assert "pilot-readout: slide 1 (s1) is stale: design system changed" in items


def test_the_context_shows_the_design_system_after_the_change_log() -> None:
    deck = edits.set_design_system(three_slide_deck(), demand_curve().ref())
    text = render_context(_inputs(deck, demand_curve()))
    block = "### Design system\n\n" + design_system_text(demand_curve())
    assert block in text
    assert text.index("### Recent changes") < text.index("### Design system")
    assert text.index("### Design system") < text.index("# Proposals")
    # Phase 1 decks (no brief, no design system) render exactly as before.
    assert "### Design system" not in render_context(_inputs(three_slide_deck(), None))


def test_gather_inputs_loads_the_decks_design_system(
    knowledge_root: Path, workspace_root: Path
) -> None:
    from autodeck.studio.context import gather_inputs
    from autodeck.studio.design import DesignSystemStore
    from autodeck.studio.engagement import create_engagement
    from tests.studio.helpers import CLIENT, PROJECT

    engagement = create_engagement(
        CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )
    system = DesignSystemStore(engagement, base=dev_tokens()).add(
        flow_draft(DARK), marker="decided", now=datetime(2026, 11, 14, tzinfo=UTC)
    )
    deck = edits.set_design_system(three_slide_deck(), system.ref()).model_copy(
        update={"client": CLIENT, "project": PROJECT}
    )
    engagement.create_artifact(deck)
    inputs = gather_inputs(engagement, owner_memory_path=workspace_root / "owner.md")
    assert inputs.artifacts[0].system == system


def test_an_option_without_recorded_samples_has_no_summary() -> None:
    """Records made before samples were recorded still load and show no summary."""
    from autodeck.studio.conversation import CandidateSlide, ProposalOption
    from autodeck.studio.models import Slide
    from autodeck.studio.views import samples_summary
    from tests.studio.helpers import flow_draft

    option = ProposalOption.model_validate(
        {
            "id": "A",
            "label": "Itemised",
            "text": "x",
            "design": flow_draft("Itemised").model_dump(
                mode="json", exclude={"palette_attempts"}
            ),
            "candidates": [
                CandidateSlide(slide=Slide(id="s1"), replaces="s1").model_dump(mode="json")
            ],
        }
    )
    assert option.samples == [] and option.design is not None
    assert option.design.palette_attempts == []
    assert samples_summary(option, None) == ""
