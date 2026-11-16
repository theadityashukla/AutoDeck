"""Shared builders for the studio tests (plain functions, so a test that calls an
unimplemented body fails inside the test rather than erroring in a fixture)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from autodeck.design.fonts import is_available
from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio.conversation import RenderManifest
from autodeck.studio.design import DesignDraft
from autodeck.studio.events import EventBus
from autodeck.studio.models import DeckArtifact, SlideBrief
from autodeck.studio.previews import PreviewService, Renderer
from autodeck.studio.scripted import ScriptedModel, scripted_binding, scripted_bindings
from autodeck.studio.session import Studio, StudioSettings
from autodeck.studio.usage import Price, Prices

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DECK = Path(__file__).resolve().parent / "fixtures" / "base_deck.json"
DEV_TOKENS = REPO_ROOT / "config" / "tokens" / "dev.json"

CLIENT = "northwind-retail"
OTHER_CLIENT = "contoso-health"
PROJECT = "llm-inference-efficiency"
ARTIFACT_ID = "inference-readout"

T0 = datetime(2026, 11, 13, 9, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 13, 9, 5, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 13, 9, 10, 0, tzinfo=UTC)

FONTS_AVAILABLE = is_available("Carlito")
"""config/tokens/dev.json draws in Carlito; layout QA cannot measure without it."""


def load_fixture_deck() -> DeckArtifact:
    return DeckArtifact.model_validate_json(FIXTURE_DECK.read_text(encoding="utf-8"))


def dev_tokens() -> DesignTokens:
    return DesignTokens.load(DEV_TOKENS)


def with_text(deck: DeckArtifact, slide_id: str, block_id: str, text: str) -> DeckArtifact:
    """`deck` with one block's text replaced, built without studio code (so store tests
    do not depend on `edits`)."""
    data = deck.model_dump()
    for slide in data["slides"]:
        if slide["id"] == slide_id:
            for block in slide["blocks"]:
                if block["id"] == block_id:
                    block["text"] = text
    return DeckArtifact.model_validate(data)


def with_slide_changes(deck: DeckArtifact, slide_id: str, **changes: object) -> DeckArtifact:
    """`deck` with top-level fields of one slide replaced (e.g. `layout=None`)."""
    data = deck.model_dump()
    for slide in data["slides"]:
        if slide["id"] == slide_id:
            slide.update(changes)
    return DeckArtifact.model_validate(data)


def overflowing(
    deck: DeckArtifact, slide_id: str = "s4", block_id: str = "heading"
) -> DeckArtifact:
    """`deck` with one text element set to 240pt in its small frame: valid IR whose layout
    fails v2's text-fit check."""
    data = deck.model_dump()
    for slide in data["slides"]:
        if slide["id"] == slide_id:
            for element in slide["layout"]["elements"]:
                if element.get("block_id") == block_id:
                    element["size_pt"] = 240
    return DeckArtifact.model_validate(data)


def make_knowledge_root(root: Path) -> Path:
    """A minimal two-client knowledge tree satisfying v2's KnowledgeLoader."""
    for client in (CLIENT, OTHER_CLIENT):
        folder = root / "clients" / client
        folder.mkdir(parents=True)
        (folder / "client.md").write_text(f"# {client}\n", encoding="utf-8")
        (folder / "value_prop.md").write_text("Framing only.\n", encoding="utf-8")
    project = root / "projects" / PROJECT
    project.mkdir(parents=True)
    (project / "project.md").write_text("# Project\n", encoding="utf-8")
    (project / "claims.md").write_text("", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------

REAL_KNOWLEDGE = REPO_ROOT / "knowledge"
"""The repository's knowledge tree (read-only in tests; workspaces are always temporary)."""
SCRIPTS = Path(__file__).resolve().parent / "fixtures" / "scripts"
DESIGN_FLOW_SCRIPT = SCRIPTS / "design_flow.json"
"""Phase 2-3's walk-through (it replaces Phase 1's `two_threads.json`, whose `write_slide`
calls the lead no longer has)."""

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class StepClock:
    """A deterministic clock: T0, then one second later on every call."""

    def __init__(self, start: datetime = T0) -> None:
        self.start = start
        self.calls = 0

    def __call__(self) -> datetime:
        value = self.start + timedelta(seconds=self.calls)
        self.calls += 1
        return value


class FakeRenderer:
    """A `previews.Renderer` that never calls LibreOffice: writes one tiny file per slide
    (PNG signature + slide id) under `previews/` and returns a rendered manifest. Records
    every call as `(deck id, out_dir, digest12)`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path, str]] = []

    def __call__(self, deck: DeckArtifact, out_dir: Path, digest12: str) -> RenderManifest:
        self.calls.append((deck.id, out_dir, digest12))
        previews = out_dir / "previews"
        previews.mkdir(parents=True, exist_ok=True)
        images = []
        for n, slide in enumerate(deck.slides, start=1):
            (previews / f"deck-{n}.png").write_bytes(PNG_SIGNATURE + slide.id.encode())
            images.append(f"previews/deck-{n}.png")
        return RenderManifest(
            digest=digest12,
            slide_ids=[s.id for s in deck.slides],
            rendered=True,
            images=images,
        )


SCRIPTED_PRICES = Prices(
    {
        "scripted/lead": Price(12, 60),
        "scripted/system": Price(12, 60),
        "scripted/designer": Price(5, 25),
        "scripted/mechanic": Price(3, 15),
        "scripted/router": Price(3, 15),
    }
)
"""Assumed prices for the design-flow script's model ids (the bench's values for the roles
they stand in for), so the per-turn cost record can be checked exactly."""


def make_studio(
    tmp_path: Path,
    model: ScriptedModel,
    *,
    knowledge_root: Path,
    renderer: Renderer | None = None,
    roles: bool = False,
    prices: Prices | None = None,
) -> tuple[Studio, EventBus, Renderer]:
    """A `Studio` over a temporary workspace, with the scripted `model`, a synchronous
    `PreviewService` on `FakeRenderer` (or `renderer`), a `StepClock`, dev tokens and an
    owner memory file under `tmp_path`. Calls studio constructors, so call it inside a test,
    never in a fixture. Returns `(studio, bus, renderer)`.

    `roles=False` (Phase 1 tests): `Studio(lead=scripted_binding(model))`, one model for
    every role, no router model. `roles=True` (Phase 2-3): `Studio(bindings=
    scripted_bindings(model))`, each role answered from its own steps of the script.
    `prices` defaults to empty (unpriced)."""
    renderer = renderer or FakeRenderer()
    bus = EventBus()
    previews = PreviewService(bus=bus, renderer=renderer, synchronous=True)
    settings = StudioSettings(
        knowledge_root=knowledge_root,
        workspace_root=tmp_path / "workspace",
        corpus_root=tmp_path / "corpus",
        owner_memory_path=tmp_path / "owner" / "owner.md",
        tokens=dev_tokens(),
        prices=prices or Prices(),
    )
    if roles:
        studio = Studio(
            settings,
            bindings=scripted_bindings(model),
            bus=bus,
            previews=previews,
            clock=StepClock(),
        )
    else:
        studio = Studio(
            settings,
            lead=scripted_binding(model),
            bus=bus,
            previews=previews,
            clock=StepClock(),
        )
    return studio, bus, renderer


# ---------------------------------------------------------------------------
# Phase 2-3: builders drawn from the prepared design-flow script, so every test uses the
# same briefs, palettes and designer slides (which pass layout QA in their palettes).
# ---------------------------------------------------------------------------


def flow_steps() -> list[Any]:
    from autodeck.studio.scripted import load_script

    return list(load_script(DESIGN_FLOW_SCRIPT).steps)


def flow_call(label: str) -> dict[str, Any]:
    """The arguments of the first tool call of the script step with this label."""
    step = next(s for s in flow_steps() if s.label == label)
    return dict(step.tool_calls[0].arguments)


def flow_brief(slide_id: str) -> SlideBrief:
    """The brief the lead writes for `s1`, `s2` or `s3` in the script."""
    for step in flow_steps():
        for call in step.tool_calls:
            if call.name == "set_slide_brief" and call.arguments["slide_id"] == slide_id:
                return SlideBrief.model_validate(call.arguments["brief"])
    raise KeyError(slide_id)


def flow_designed(slide_id: str, design: str = "default") -> dict[str, Any]:
    """The designer's `write_slide` arguments for a slide: `design` is `default` (light,
    also used for the Itemised sample) or `Demand curve` (dark)."""
    label = f"designer: {slide_id} in the default design"
    if design != "default":
        label = f"designer: {slide_id} in {design}"
    return flow_call(label)


def flow_palette_args(name: str) -> dict[str, Any]:
    """The system layer's `set_palette` arguments for `Itemised` or `Demand curve`."""
    return flow_call(f"system: {name}")


def flow_directions() -> list[dict[str, Any]]:
    return list(flow_call("t1 u2: propose two directions")["directions"])


def flow_draft(name: str, *, made_by: str = "scripted/system") -> DesignDraft:
    """A `DesignDraft` for a scripted direction, as the system layer would return it."""
    args = flow_palette_args(name)
    direction = next(d for d in flow_directions() if d["name"] == name)
    return DesignDraft(
        name=direction["name"],
        concept=direction["concept"],
        rules=direction["rules"],
        palette=args["palette"],
        roles=args["roles"],
        background=args["background"],
        text_pairs=args["text_pairs"],
        made_by=made_by,
    )


def write_slide_step(slide_id: str, design: str = "default", **extra: Any) -> dict[str, Any]:
    """A designer step writing the scripted slide (for `ScriptedModel.from_steps`)."""
    return {
        "role": "designer",
        "match": f"Slide id: {slide_id}",
        "tool_calls": [{"name": "write_slide", "arguments": flow_designed(slide_id, design)}],
        **extra,
    }
