"""Phase 2-3's exit test: the design flow end to end with scripted models per role, on the
real knowledge pair northwind-retail / llm-inference-efficiency.

Thread one: the lead writes three slide briefs and composes them (the designer, in the
provisional default design); the owner says the deck looks generic; the lead proposes two
design directions (the system layer makes each palette, the designer renders each on slide
2); the owner picks B with the button; the slides are stale; the owner asks and they are
recomposed in it. Thread two opens from state (no transcript), and "Retitle slide 2 to ..."
goes by rule to the mechanic, without the lead.

Pinned: the lead's model is never asked for a layout; design tokens reach both layout QA
and the render; picking a design marks composed slides stale and recomposing clears it; the
retitle turn records that the lead did not run; and the per-turn layer and cost record is
correct. The `render` version draws the recomposed deck with LibreOffice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from autodeck.studio import render_adapter, views
from autodeck.studio.context import build_context
from autodeck.studio.conversation import AssistantLine, RenderManifest, TurnFinished
from autodeck.studio.design import deck_tokens
from autodeck.studio.design_render import render_with_design
from autodeck.studio.models import DeckArtifact, deck_composition
from autodeck.studio.proposals import ProposalStore
from autodeck.studio.scripted import ScriptedModel
from autodeck.studio.threads import ThreadStore
from tests.studio.helpers import (
    CLIENT,
    DESIGN_FLOW_SCRIPT,
    FONTS_AVAILABLE,
    PROJECT,
    REAL_KNOWLEDGE,
    SCRIPTED_PRICES,
    FakeRenderer,
    dev_tokens,
    make_studio,
)

pytestmark = pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")

DECK = "pilot-readout"
NIGHT = "0F1D30"  # Demand curve's background (lt2)
OWNER_1 = (
    "Start a three-slide readout for Northwind's digital leadership on the serving-cost "
    "pilot: the promise, quantisation, then the business case."
)
OWNER_2 = "It looks generic."
OWNER_4 = "Yes, recompose them."
RETITLE = "Retitle slide 2 to Quantisation cuts the bill by 38%"


class RecordingRenderer(FakeRenderer):
    """`FakeRenderer` that also keeps every deck it was asked to draw."""

    def __init__(self) -> None:
        super().__init__()
        self.decks: list[DeckArtifact] = []

    def __call__(self, deck: DeckArtifact, out_dir: Path, digest12: str) -> RenderManifest:
        self.decks.append(deck)
        return super().__call__(deck, out_dir, digest12)


def states(deck: DeckArtifact) -> list[str]:
    return [status.state for status in deck_composition(deck).values()]


def check_costs(turn: TurnFinished) -> None:
    assert turn.usage is not None
    for layer in turn.usage.layers:
        expected = SCRIPTED_PRICES.cost(layer.model_id, layer.input_tokens, layer.output_tokens)
        assert layer.cost_usd == expected, layer.role
    assert turn.usage.total_cost_usd == round(
        sum(layer.cost_usd or 0 for layer in turn.usage.layers), 6
    )
    assert turn.usage.prices_assumed


def lead_tokens(lines: list[Any], turn_id: str) -> tuple[int, int, int]:
    mine = [
        line
        for line in lines
        if isinstance(line, AssistantLine) and line.turn_id == turn_id and line.role == "lead"
    ]
    return len(mine), sum(x.input_tokens for x in mine), sum(x.output_tokens for x in mine)


def test_the_design_flow_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    palettes_in_qa: list[str] = []
    real_check = render_adapter.check_slide

    def spy(slide: Any, tokens: Any) -> Any:
        palettes_in_qa.append(tokens.palette.lt2)
        return real_check(slide, tokens)

    monkeypatch.setattr(render_adapter, "check_slide", spy)
    model = ScriptedModel.from_file(DESIGN_FLOW_SCRIPT)
    renderer = RecordingRenderer()
    studio, _, _ = make_studio(
        tmp_path,
        model,
        knowledge_root=REAL_KNOWLEDGE,
        renderer=renderer,
        roles=True,
        prices=SCRIPTED_PRICES,
    )
    engagement = studio.create_engagement(CLIENT, PROJECT, title="Pilot readout")
    threads = ThreadStore(engagement)
    first, recap = studio.open_thread(engagement, title="Design")
    assert first.opening == "fresh" and recap is None

    # -- turn 1: three briefs, composed in the default design --------------------------
    t1 = studio.run_turn(engagement, first.id, text=OWNER_1)
    assert (t1.turn_kind, t1.stop_reason) == ("change", "replied"), t1.error
    assert t1.created_artifacts == [DECK]
    assert t1.change_ids == ["c0001", "c0002", "c0003", "c0004", "c0005", "c0006"]
    assert t1.route is not None and (t1.route.route, t1.route.by) == ("lead", "model")
    assert t1.usage is not None and t1.usage.roles() == ["router", "lead", "designer"]
    assert t1.usage.layer("designer").calls == 3  # type: ignore[union-attr]
    assert t1.usage.layer("router").calls == 1  # type: ignore[union-attr]
    calls, tin, tout = lead_tokens(threads.read_lines(first.id), t1.turn_id)
    lead = t1.usage.layer("lead")
    assert lead is not None and (lead.calls, lead.input_tokens, lead.output_tokens) == (
        calls,
        tin,
        tout,
    )
    assert t1.model_id == "scripted/lead" and t1.steps == calls
    check_costs(t1)
    store = engagement.artifact_store(DECK)
    deck = store.load()
    assert deck.slide_ids() == ["s1", "s2", "s3"] and deck.design_system is None
    assert states(deck) == ["fresh"] * 3
    entries = store.changelog().entries
    assert [(e.layer, e.model_id) for e in entries] == [
        ("direction", "scripted/lead"),
    ] * 3 + [("composition", "scripted/designer")] * 3
    assert renderer.decks[-1].design_system is None

    # -- turn 2: "it looks generic" -> two directions, rendered -------------------------
    before = store.current_text()
    t2 = studio.run_turn(engagement, first.id, text=OWNER_2)
    assert (t2.turn_kind, t2.proposal_ids) == ("proposal", ["p0001"]), t2.error
    assert t2.usage is not None and t2.usage.roles() == ["router", "lead", "system", "designer"]
    assert t2.usage.layer("system").calls == 2  # type: ignore[union-attr]
    assert t2.usage.layer("designer").calls == 2  # type: ignore[union-attr]
    check_costs(t2)
    assert store.current_text() == before
    proposal = ProposalStore(engagement).load("p0001")
    assert [o.label for o in proposal.options] == ["Itemised", "Demand curve"]
    for option in proposal.options:  # every sample's outcome is recorded with the proposal
        assert [(x.slide_id, x.clean, x.attempts) for x in option.samples] == [("s2", True, 1)]
        assert option.design is not None
        assert [(a.attempt, a.accepted) for a in option.design.palette_attempts] == [(1, True)]
    sample_decks = renderer.decks[-2:]
    assert [d.design_system.palette.lt2 for d in sample_decks] == ["D3DCCF", NIGHT]  # type: ignore[union-attr]
    for option in ("A", "B"):
        assert studio.previews.proposal_manifest(engagement, "p0001", option) is not None

    # -- the owner picks B: designed slides become stale ---------------------------------
    t3 = studio.pick_option(engagement, first.id, "p0001", "B")
    assert (t3.turn_kind, t3.change_ids) == ("change", ["c0007"]), t3.error
    assert t3.route is not None and t3.route.by == "origin"
    assert t3.usage is not None and t3.usage.roles() == ["lead"]
    deck = store.load()
    assert deck.design_system is not None
    assert (deck.design_system.id, deck.design_system.version) == ("demand-curve", 1)
    assert deck.design_system.marker == "decided"
    assert states(deck) == ["stale"] * 3
    assert store.changelog().entry("c0007").layer == "direction"

    # -- recompose: fresh again, in the night palette ------------------------------------
    palettes_in_qa.clear()
    t4 = studio.run_turn(engagement, first.id, text=OWNER_4)
    assert t4.change_ids == ["c0008", "c0009", "c0010"], t4.error
    assert t4.usage is not None and t4.usage.layer("designer").calls == 3  # type: ignore[union-attr]
    check_costs(t4)
    deck = store.load()
    assert states(deck) == ["fresh"] * 3
    assert palettes_in_qa and set(palettes_in_qa) == {NIGHT}  # tokens reached layout QA
    drawn = renderer.decks[-1]
    assert drawn.design_system is not None and drawn.design_system.palette.lt2 == NIGHT  # type: ignore[union-attr]
    assert deck_tokens(drawn, dev_tokens()).palette.lt2 == NIGHT  # and the render

    # -- the lead was never asked for a layout ---------------------------------------------
    for call in model.calls_for("lead"):
        assert not {"write_slide", "set_palette"} & set(call.tool_names)
    for line in threads.read_lines(first.id):
        if isinstance(line, AssistantLine):
            for tool_call in line.tool_calls:
                assert '"layout"' not in json.dumps(tool_call.arguments)
    assert {tuple(c.tool_names) for c in model.calls_for("designer")} == {("write_slide",)}

    # -- thread two: from state, then a retitle without the lead ----------------------------
    lead_calls = len(model.calls_for("lead"))
    second, recap = studio.open_thread(engagement, title="Polish")
    assert second.opening == "returning" and recap is not None
    assert recap.route is not None and recap.route.by == "origin"
    context = threads.context_text(second.id)
    assert context == build_context(
        engagement, owner_memory_path=studio.settings.owner_memory_path
    )
    for needle in (
        "Design system [decided]: demand-curve v1",
        "### Design system\n\nDemand curve (demand-curve v1, decided)",
        f"- p0001 ({DECK}, thread {first.id}) [accepted: option B]",
        '     brief: "Quantisation alone cuts serving cost by 38%" | 2 points, 1 figure, '
        "chart | designed",
    ):
        assert needle in context, needle
    for line in threads.read_lines(first.id):
        if isinstance(line, AssistantLine) and line.text.strip():
            assert line.text not in context

    t5 = studio.run_turn(engagement, second.id, text=RETITLE)
    assert t5.route is not None
    assert (t5.route.route, t5.route.by, t5.route.handed_off) == ("mechanic", "rule", False)
    assert t5.usage is not None and t5.usage.roles() == ["mechanic"]
    assert t5.usage.layer("lead") is None and t5.model_id == "scripted/mechanic"
    assert (t5.turn_kind, t5.change_ids) == ("change", ["c0011"])
    check_costs(t5)
    assert len(model.calls_for("lead")) == lead_calls + 1  # the recap only
    entry = store.changelog().entry("c0011")
    assert (entry.layer, entry.model_id, entry.thread_id) == (
        "mechanics",
        "scripted/mechanic",
        second.id,
    )
    deck = store.load()
    assert deck.slide("s2").block("header").text == "Quantisation cuts the bill by 38%"
    assert states(deck) == ["fresh"] * 3
    # the Changes tab reads in words, from the same entries
    summaries = {
        e["id"]: e["summary"]
        for e in views.changes_view(store.changelog(), deck=deck)["entries"]
    }
    assert summaries["c0001"].startswith("Wrote the brief for slide 1: ")
    assert [summaries[c] for c in ("c0004", "c0005", "c0006")] == [
        "Designed slide 1",
        "Designed slide 2",
        "Designed slide 3",
    ]
    assert summaries["c0007"] == "Adopted the design Demand curve (version 1)"
    assert [summaries[c] for c in ("c0008", "c0009", "c0010")] == [
        f"Redesigned slide {n} in Demand curve" for n in (1, 2, 3)
    ]
    assert summaries["c0011"] == (
        "Retitled slide 2: Quantisation alone cuts serving cost by 38% \u2192 "
        "Quantisation cuts the bill by 38%"
    )
    mechanic_lines = [
        line for line in threads.read_lines(second.id) if isinstance(line, AssistantLine)
    ]
    assert {line.role for line in mechanic_lines if line.turn_id == t5.turn_id} == {"mechanic"}
    assert model.remaining == 0 and model.overrun == 0


@pytest.mark.render
def test_the_recomposed_deck_renders_in_the_night_palette(tmp_path: Path) -> None:
    from PIL import Image

    model = ScriptedModel.from_file(DESIGN_FLOW_SCRIPT)
    studio, _, _ = make_studio(
        tmp_path,
        model,
        knowledge_root=REAL_KNOWLEDGE,
        renderer=render_with_design(dev_tokens()),  # type: ignore[arg-type]
        roles=True,
    )
    engagement = studio.create_engagement(CLIENT, PROJECT)
    thread, _ = studio.open_thread(engagement)
    studio.run_turn(engagement, thread.id, text=OWNER_1)
    studio.run_turn(engagement, thread.id, text=OWNER_2)
    studio.pick_option(engagement, thread.id, "p0001", "B")
    studio.run_turn(engagement, thread.id, text=OWNER_4)
    store = engagement.artifact_store(DECK)
    manifest = studio.previews.current(store)
    assert manifest is not None and manifest.rendered and manifest.placeholders == {}, manifest
    folder = store.paths.render_dir(manifest.digest)
    image = Image.open(folder / manifest.images[1]).convert("RGB")
    r, g, b = image.getpixel((image.width - 5, image.height - 5))
    assert r < 60 and b < 90, (r, g, b)  # night blue, not the default white
