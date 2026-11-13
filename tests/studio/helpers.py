"""Shared builders for the studio tests (plain functions, so a test that calls an
unimplemented body fails inside the test rather than erroring in a fixture)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from autodeck.design.fonts import is_available
from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio.conversation import RenderManifest
from autodeck.studio.events import EventBus
from autodeck.studio.models import DeckArtifact
from autodeck.studio.previews import PreviewService, Renderer
from autodeck.studio.scripted import ScriptedModel, scripted_binding
from autodeck.studio.session import Studio, StudioSettings

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
TWO_THREADS_SCRIPT = SCRIPTS / "two_threads.json"

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


def make_studio(
    tmp_path: Path,
    model: ScriptedModel,
    *,
    knowledge_root: Path,
    renderer: Renderer | None = None,
) -> tuple[Studio, EventBus, Renderer]:
    """A `Studio` over a temporary workspace, with the scripted `model`, a synchronous
    `PreviewService` on `FakeRenderer` (or `renderer`), a `StepClock`, dev tokens and an
    owner memory file under `tmp_path`. Calls studio constructors, so call it inside a test,
    never in a fixture. Returns `(studio, bus, renderer)`."""
    renderer = renderer or FakeRenderer()
    bus = EventBus()
    previews = PreviewService(bus=bus, renderer=renderer, synchronous=True)
    settings = StudioSettings(
        knowledge_root=knowledge_root,
        workspace_root=tmp_path / "workspace",
        corpus_root=tmp_path / "corpus",
        owner_memory_path=tmp_path / "owner" / "owner.md",
        tokens=dev_tokens(),
    )
    studio = Studio(
        settings, lead=scripted_binding(model), bus=bus, previews=previews, clock=StepClock()
    )
    return studio, bus, renderer
