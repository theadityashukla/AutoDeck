"""Task 23.15: the API's Phase 2-3 additions (`api.py`) and the entry point (`__main__.py`):
bindings in health, the routing override on messages, the routing record on assistant
messages, composition and the design system on the artifact view."""

from __future__ import annotations

import time
from argparse import Namespace
from pathlib import Path

import pytest

from autodeck.studio import edits
from autodeck.studio.__main__ import build, parse_args
from autodeck.studio.api import Response, StudioApp
from autodeck.studio.design import DesignSystemStore
from autodeck.studio.models import DesignSystemRef
from autodeck.studio.scripted import ScriptedModel
from autodeck.studio.session import Studio
from tests.studio.helpers import (
    CLIENT,
    DESIGN_FLOW_SCRIPT,
    PROJECT,
    T0,
    dev_tokens,
    flow_brief,
    flow_draft,
    make_studio,
)

E = f"/api/engagements/{CLIENT}/{PROJECT}"


def app(tmp_path: Path, knowledge_root: Path, steps: list[dict]) -> tuple[StudioApp, Studio]:  # type: ignore[type-arg]
    model = ScriptedModel.from_steps(
        steps, model_id="scripted/lead", model_ids={"mechanic": "scripted/mechanic"}
    )
    studio, _, _ = make_studio(tmp_path, model, knowledge_root=knowledge_root, roles=True)
    return StudioApp(studio, env="scripted", scripted=True), studio


def ok(response: Response, status: int = 200) -> dict:  # type: ignore[type-arg]
    assert response.status == status, response.payload
    assert response.payload is not None
    return response.payload


def wait(studio: Studio) -> None:
    engagement = studio.engagement(CLIENT, PROJECT)
    for _ in range(200):
        if studio.running_turn(engagement) is None:
            return
        time.sleep(0.02)
    raise AssertionError("turn did not finish")


def test_health_lists_every_roles_model(tmp_path: Path, knowledge_root: Path) -> None:
    api, _ = app(tmp_path, knowledge_root, [{"text": "x"}])
    health = ok(api.handle("GET", "/api/health", None))
    assert health["bindings"] == {
        "lead": "scripted/lead",
        "system": "scripted/lead-system",
        "designer": "scripted/lead-designer",
        "mechanic": "scripted/mechanic",
        "router": "scripted/lead-router",
    }


def test_messages_take_a_route_and_report_it(tmp_path: Path, knowledge_root: Path) -> None:
    api, studio = app(
        tmp_path,
        knowledge_root,
        [{"text": "Pinned to me."}, {"role": "mechanic", "text": "Nothing to swap yet."}],
    )
    ok(api.handle("POST", "/api/engagements", {"client": CLIENT, "project": PROJECT}), 201)
    thread = ok(api.handle("POST", f"{E}/threads", {}), 201)["thread"]["id"]
    bad = api.handle(
        "POST", f"{E}/threads/{thread}/messages", {"text": "Swap slides 1 and 2", "route": "x"}
    )
    assert bad.status == 400 and bad.payload["error"]["code"] == "bad_request"  # type: ignore[index]
    ok(
        api.handle(
            "POST",
            f"{E}/threads/{thread}/messages",
            {"text": "Swap slides 1 and 2", "route": "lead"},
        ),
        202,
    )
    wait(studio)
    ok(
        api.handle("POST", f"{E}/threads/{thread}/messages", {"text": "Swap slides 1 and 2"}),
        202,
    )
    wait(studio)
    messages = ok(api.handle("GET", f"{E}/threads/{thread}", None))["messages"]
    turns = [m for m in messages if m["type"] == "assistant"]
    assert turns[0]["route"]["by"] == "override" and turns[0]["roles"] == ["lead"]
    assert turns[1]["route"]["route"] == "mechanic" and turns[1]["roles"] == ["mechanic"]
    assert turns[1]["usage"]["layers"][0]["role"] == "mechanic"
    assert turns[1]["usage"]["price_note"].startswith("Estimated from assumed prices")


def test_the_artifact_view_carries_composition_and_the_design_system(
    tmp_path: Path, knowledge_root: Path
) -> None:
    api, studio = app(tmp_path, knowledge_root, [{"text": "x"}])
    engagement = studio.create_engagement(CLIENT, PROJECT)
    from autodeck.studio.models import DeckArtifact

    deck = DeckArtifact(id="d", client=CLIENT, project=PROJECT)
    deck, _, _ = edits.set_slide_brief(deck, "s1", flow_brief("s1"))
    engagement.create_artifact(deck)
    view = ok(api.handle("GET", f"{E}/artifacts/d", None))
    assert view["composition"]["s1"]["state"] == "undesigned"
    assert view["design_system"]["is_default"] is True
    assert view["design_system"]["name"] == "Default"
    system = DesignSystemStore(engagement, base=dev_tokens()).add(
        flow_draft("Demand curve"), marker="decided", now=T0
    )
    store = engagement.artifact_store("d")
    store.apply(
        edits.set_design_system(store.load(), system.ref()),
        instruction="Adopt",
        thread_id="t0001",
        layer="direction",
        model_id="scripted/lead",
        now=T0,
    )
    view = ok(api.handle("GET", f"{E}/artifacts/d", None))
    assert view["design_system"]["id"] == "demand-curve"
    assert view["design_system"]["palette"][3]["hex"] == "#0F1D30"
    dangling = edits.set_design_system(
        store.load(), DesignSystemRef(id="gone", version=3, palette=system.palette)
    )
    store.apply(
        dangling,
        instruction="Break",
        thread_id="t0001",
        layer="direction",
        model_id="scripted/lead",
        now=T0,
    )
    assert ok(api.handle("GET", f"{E}/artifacts/d", None))["design_system"] is None


def test_the_changes_carry_a_plain_summary_with_the_designs_real_name(
    tmp_path: Path, knowledge_root: Path
) -> None:
    api, studio = app(tmp_path, knowledge_root, [{"text": "x"}])
    engagement = studio.create_engagement(CLIENT, PROJECT)
    from autodeck.studio.models import DeckArtifact

    deck = DeckArtifact(id="d", client=CLIENT, project=PROJECT)
    deck, _, _ = edits.set_slide_brief(deck, "s1", flow_brief("s1"))
    engagement.create_artifact(deck)
    draft = flow_draft("Demand curve").model_copy(update={"name": "Demand Curve NIGHT"})
    system = DesignSystemStore(engagement, base=dev_tokens()).add(
        draft, marker="decided", now=T0
    )
    store = engagement.artifact_store("d")
    store.apply(
        edits.set_design_system(store.load(), system.ref()),
        instruction="Adopt",
        thread_id="t0001",
        layer="direction",
        model_id="scripted/lead",
        now=T0,
    )
    changes = ok(api.handle("GET", f"{E}/artifacts/d/changes", None))
    assert changes["entries"][0]["summary"] == (
        "Adopted the design Demand Curve NIGHT (version 1)"  # the stored name, not the slug
    )
    assert changes["entries"][0]["lines"]  # the raw lines are still there
    undone = ok(api.handle("POST", f"{E}/artifacts/d/undo", {}))
    assert undone["entry"]["summary"] == "Adopted the design Demand Curve NIGHT (version 1)"
    assert undone["changes"]["entries"][0]["summary"]


def test_the_entry_point_binds_every_role_from_a_script(tmp_path: Path) -> None:
    args = parse_args(
        ["--script", str(DESIGN_FLOW_SCRIPT), "--workspace", str(tmp_path / "w"), "--no-render"]
    )
    assert args.prices is None
    api, studio = build(args)
    try:
        assert api.scripted and studio.use_router_model
        assert studio.bindings.designer.model_id == "scripted/designer"
        assert studio.bindings.mechanic.model_id == "scripted/mechanic"
        assert studio.settings.prices.by_model["openai/gpt-5.6-luna"].input == 5
    finally:
        studio.shutdown()


def test_the_entry_point_binds_every_role_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISTRAL_API_KEY", "dummy-not-used")
    api, studio = build(
        Namespace(
            env="dev-mistral",
            port=0,
            script=None,
            workspace=tmp_path / "w",
            knowledge=None,
            corpus=None,
            owner_memory=tmp_path / "owner.md",
            no_render=True,
            prices=None,
        )
    )
    try:
        assert not api.scripted
        assert {
            studio.bindings.for_role(r).model_id for r in ("lead", "designer", "router")
        } == {"mistral/ministral-14b-2512"}
    finally:
        studio.shutdown()
