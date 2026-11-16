"""Background previews: one render per deck state, reused, pruned, announced."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from autodeck.studio.conversation import (
    PreviewsReady,
    ProposalOption,
    ProposalPreviewsReady,
    RenderManifest,
)
from autodeck.studio.engagement import Engagement, create_engagement
from autodeck.studio.events import EventBus
from autodeck.studio.models import DeckArtifact
from autodeck.studio.previews import (
    PreviewService,
    digest12,
    read_manifest,
    render_with_libreoffice,
)
from autodeck.studio.proposals import ProposalStore
from autodeck.studio.serialise import artifact_digest
from tests.studio.helpers import (
    ARTIFACT_ID,
    CLIENT,
    FONTS_AVAILABLE,
    PROJECT,
    T0,
    T1,
    FakeRenderer,
    dev_tokens,
    with_text,
)

CHANNEL = f"{CLIENT}/{PROJECT}/t0001"  # events.channel_key, spelled out (pinned in test_events)


def _engagement(knowledge_root: Path, workspace_root: Path, deck: DeckArtifact) -> Engagement:
    engagement = create_engagement(
        CLIENT, PROJECT, knowledge_root=knowledge_root, workspace_root=workspace_root, now=T0
    )
    engagement.create_artifact(deck)
    return engagement


def _apply(engagement: Engagement, deck: DeckArtifact, text: str) -> None:
    engagement.artifact_store(ARTIFACT_ID).apply(
        with_text(deck, "s2", "number", text),
        instruction=f"Make it {text}",
        thread_id="t0001",
        layer="composition",
        model_id="m",
        now=T1,
    )


def test_digest12(base_deck: DeckArtifact) -> None:
    assert digest12(base_deck) == artifact_digest(base_deck)[:12]


def test_render_now_writes_one_directory_per_state_and_reuses_it(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact
) -> None:
    engagement = _engagement(knowledge_root, workspace_root, base_deck)
    store = engagement.artifact_store(ARTIFACT_ID)
    renderer = FakeRenderer()
    service = PreviewService(bus=EventBus(), renderer=renderer, synchronous=True)
    assert service.current(store) is None
    manifest = service.render_now(store)
    folder = store.paths.render_dir(digest12(base_deck))
    assert manifest.digest == digest12(base_deck) and manifest.rendered
    assert read_manifest(folder) == manifest
    assert (folder / "previews" / "deck-1.png").is_file()
    assert service.current(store) == manifest
    assert service.render_now(store) == manifest and len(renderer.calls) == 1
    assert not any(p.name.startswith(".tmp") for p in store.paths.renders.iterdir())
    _apply(engagement, base_deck, "38%")
    second = service.render_now(store)
    assert second.digest != manifest.digest and len(renderer.calls) == 2
    store.undo()
    assert service.render_now(store) == manifest and len(renderer.calls) == 2


def test_old_renders_are_pruned(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact
) -> None:
    engagement = _engagement(knowledge_root, workspace_root, base_deck)
    store = engagement.artifact_store(ARTIFACT_ID)
    service = PreviewService(bus=EventBus(), renderer=FakeRenderer(), synchronous=True, keep=2)
    digests = []
    for value in ("10%", "20%", "30%"):
        _apply(engagement, store.load(), value)
        digests.append(service.render_now(store).digest)
        time.sleep(0.01)
        os.utime(store.paths.render_dir(digests[-1]))
    kept = sorted(p.name for p in store.paths.renders.iterdir())
    assert kept == sorted(digests[1:])


def test_a_failed_render_is_reported_and_not_kept(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact
) -> None:
    engagement = _engagement(knowledge_root, workspace_root, base_deck)
    store = engagement.artifact_store(ARTIFACT_ID)

    def broken(deck: DeckArtifact, out_dir: Path, digest: str) -> RenderManifest:
        raise RuntimeError("LibreOffice exploded")

    service = PreviewService(bus=EventBus(), renderer=broken, synchronous=True)
    manifest = service.render_now(store)
    assert not manifest.rendered and "LibreOffice exploded" in manifest.note
    assert manifest.slide_ids == base_deck.slide_ids()
    assert service.current(store) is None


def test_request_artifact_publishes_previews_ready(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact
) -> None:
    engagement = _engagement(knowledge_root, workspace_root, base_deck)
    bus = EventBus()
    service = PreviewService(bus=bus, renderer=FakeRenderer(), synchronous=True)
    service.request_artifact(engagement, ARTIFACT_ID, thread_id="t0001", turn_id="u0003")
    events = [p.event for p in bus.replay(CHANNEL)]
    assert len(events) == 1 and isinstance(events[0], PreviewsReady)
    event = events[0]
    assert (event.turn_id, event.artifact_id, event.digest, event.rendered) == (
        "u0003",
        ARTIFACT_ID,
        digest12(base_deck),
        True,
    )
    assert event.slide_ids == base_deck.slide_ids()


def test_background_requests_finish_and_coalesce(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact
) -> None:
    engagement = _engagement(knowledge_root, workspace_root, base_deck)
    bus = EventBus()
    renderer = FakeRenderer()
    service = PreviewService(bus=bus, renderer=renderer)
    try:
        for _ in range(5):
            service.request_artifact(engagement, ARTIFACT_ID, thread_id="t0001", turn_id=None)
        assert service.wait_idle(10)
        ready = [p.event for p in bus.replay(CHANNEL) if p.event.type == "previews_ready"]
        assert 1 <= len(ready) <= 5 and len(renderer.calls) == 1
    finally:
        service.shutdown()


def test_proposal_previews(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact
) -> None:
    engagement = _engagement(knowledge_root, workspace_root, base_deck)
    candidate = base_deck.slide("s2").model_copy(update={"id": "s1", "serves": ["p1"]})
    proposal = ProposalStore(engagement).create(
        thread_id="t0001",
        turn_id="u0002",
        artifact_id=ARTIFACT_ID,
        summary="Openings",
        options=[
            ProposalOption(id="A", label="Number", text="x", slides=[candidate]),
            ProposalOption(id="B", label="Question", text="y"),
        ],
        now=T1,
    )
    bus = EventBus()
    renderer = FakeRenderer()
    service = PreviewService(bus=bus, renderer=renderer, synchronous=True)
    service.request_proposal(engagement, proposal, thread_id="t0001")
    events = [p.event for p in bus.replay(CHANNEL)]
    assert len(events) == 1 and isinstance(events[0], ProposalPreviewsReady)
    assert events[0].options == {"A": 1} and events[0].rendered
    manifest = service.proposal_manifest(engagement, "p0001", "A")
    assert manifest is not None and manifest.slide_ids == ["s1"]
    assert service.proposal_manifest(engagement, "p0001", "B") is None
    rendered_deck_ids = [call[0] for call in renderer.calls]
    assert rendered_deck_ids == [ARTIFACT_ID]
    assert service.proposal_render_dir(engagement, "p0001", "A").is_dir()


@pytest.mark.render
@pytest.mark.skipif(not FONTS_AVAILABLE, reason="Carlito is not installed")
def test_the_libreoffice_renderer_draws_the_fixture(
    knowledge_root: Path, workspace_root: Path, base_deck: DeckArtifact
) -> None:
    engagement = _engagement(knowledge_root, workspace_root, base_deck)
    store = engagement.artifact_store(ARTIFACT_ID)
    service = PreviewService(
        bus=EventBus(), renderer=render_with_libreoffice(dev_tokens()), synchronous=True
    )
    manifest = service.render_now(store)
    assert manifest.rendered, manifest.note
    assert manifest.placeholders == {} and len(manifest.images) == 4
    folder = store.paths.render_dir(manifest.digest)
    assert all((folder / image).is_file() for image in manifest.images)
    assert manifest.pptx == "deck.pptx" and (folder / "deck.pptx").is_file()
