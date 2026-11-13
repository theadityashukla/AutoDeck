"""Background previews: re-render a deck after a change and tell the interface (Phase 1).

**One render per deck state.** A deck state is identified by its digest
(`serialise.artifact_digest`); its render lives in `renders/<first 12 hex>/`
(`ArtifactPaths.render_dir`) as `deck.pptx`, `previews/deck-<n>.png` and `render.json`
(`conversation.RenderManifest`), written last. A directory with a manifest is complete and
is reused as is: undoing back to an earlier state needs no LibreOffice run. A render is
built in a temporary sibling directory (`renders/.tmp-<digest12>-<uuid hex>`) and renamed
into place, so a half-written render is never visible. At most `KEEP_RENDERS` render
directories are kept per artifact; after each new render the oldest by modification time
are deleted, never the one just written.

**Whole deck, in the background.** Phase 1 re-renders the whole deck (per-slide caching is
a later optimisation). Requests run on one worker thread, so LibreOffice runs one at a
time. Requests for an artifact coalesce: while a request for it is queued and not yet
started, further requests do nothing (the queued job reads the state current when it
starts). Each finished job publishes one `PreviewsReady` event on the requesting thread's
channel.

**Proposal previews.** An option's candidate slides are rendered as a small deck (the
current deck with `slides` replaced by the candidates, so storyline links stay valid) into
`proposals/<id>/renders/<option>/`, same file layout; then one `ProposalPreviewsReady`.

A slide with no layout, or one failing layout QA, is drawn by `render.build_pptx` as the
labelled placeholder Phase 0 already draws. A render that fails entirely (fonts missing,
LibreOffice missing) produces `rendered=False` with the reason; the interface keeps
showing the placeholder.

The renderer is injectable (`Renderer`) so tests never need LibreOffice, and
`synchronous=True` runs jobs inline in the calling thread (tests, scripts).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio.conversation import ProposalRecord, RenderManifest
from autodeck.studio.engagement import Engagement
from autodeck.studio.events import EventBus
from autodeck.studio.models import DeckArtifact
from autodeck.studio.store import ArtifactStore

KEEP_RENDERS = 6
RENDER_MANIFEST_FILE = "render.json"

Renderer = Callable[[DeckArtifact, Path, str], RenderManifest]
"""`(deck, out_dir, digest12) -> manifest`: render `deck` into the existing, empty
`out_dir` and return its manifest (not yet written; the service writes it). Must not raise
for a slide that cannot be drawn (that is a placeholder) or for missing LibreOffice (that
is `rendered=False`); may raise for anything else."""


def render_with_libreoffice(tokens: DesignTokens) -> Renderer:
    """The production renderer: `render.render_artifact(deck, tokens=tokens,
    out_dir=out_dir)`, mapped to a manifest: `slide_ids` from the build, `placeholders`,
    `rendered` and `note` from the previews, `images` as paths relative to `out_dir`
    (`previews/<name>.png`), `pptx="deck.pptx"`, and both timings. v2's
    `FontNotFoundError` from the build becomes `rendered=False` with its message,
    `slide_ids` from the deck, no images and `pptx=None`."""
    raise NotImplementedError


def read_manifest(render_dir: Path) -> RenderManifest | None:
    """The manifest in `render_dir`, or None when it has none (or it is invalid)."""
    raise NotImplementedError


def digest12(deck: DeckArtifact) -> str:
    """The first 12 hex characters of `serialise.artifact_digest(deck)`."""
    raise NotImplementedError


class PreviewService:
    def __init__(
        self,
        *,
        bus: EventBus,
        renderer: Renderer,
        synchronous: bool = False,
        keep: int = KEEP_RENDERS,
    ) -> None:
        """Stores its arguments; with `synchronous=False` starts one daemon worker thread
        on first use (not in the constructor)."""
        raise NotImplementedError

    def current(self, store: ArtifactStore) -> RenderManifest | None:
        """The manifest for the artifact's current state if it has been rendered, else
        None. Reads `current.json` through `store.load()`."""
        raise NotImplementedError

    def render_now(self, store: ArtifactStore) -> RenderManifest:
        """Render the current state in the calling thread (reusing an existing render of
        that state), prune old renders, and return the manifest. No event. Used by the
        background job and by tests.

        Renderer exceptions are caught: the result is a manifest with `rendered=False`,
        `note=str(exc)`, the deck's slide ids, which is returned but **not** written (so
        the state is retried next time)."""
        raise NotImplementedError

    def request_artifact(
        self, engagement: Engagement, artifact_id: str, *, thread_id: str, turn_id: str | None
    ) -> None:
        """Queue (or, synchronous, run) a render of the artifact's current state, then
        publish `PreviewsReady` (thread_id, turn_id, artifact_id, digest, slide_ids,
        rendered, note, placeholders) on `events.channel_key(client, project, thread_id)`.
        Coalesces as the module docstring says. Never raises for a render failure; an
        artifact that no longer loads is logged to stderr and dropped."""
        raise NotImplementedError

    def proposal_render_dir(
        self, engagement: Engagement, proposal_id: str, option_id: str
    ) -> Path:
        """`ProposalStore(engagement).paths(proposal_id).option_renders(option_id)`."""
        raise NotImplementedError

    def proposal_manifest(
        self, engagement: Engagement, proposal_id: str, option_id: str
    ) -> RenderManifest | None:
        """The manifest of an option's render, or None."""
        raise NotImplementedError

    def request_proposal(
        self, engagement: Engagement, proposal: ProposalRecord, *, thread_id: str
    ) -> None:
        """Queue (or run) renders of every option that has candidate slides, then publish
        one `ProposalPreviewsReady` with `options` = option id -> number of images
        (0 when not rendered), `rendered` = every option rendered, `note` = the first
        failure's note or "". A proposal with no candidate slides publishes nothing."""
        raise NotImplementedError

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until no job is queued or running (True), or the timeout passes (False).
        Immediately True when synchronous."""
        raise NotImplementedError

    def shutdown(self) -> None:
        """Stop the worker after the current job; queued jobs are dropped. Idempotent."""
        raise NotImplementedError
