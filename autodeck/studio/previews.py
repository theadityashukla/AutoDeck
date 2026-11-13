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

import shutil
import sys
import threading
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path

from autodeck.design.fonts import FontNotFoundError
from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio import render, serialise
from autodeck.studio.conversation import (
    PreviewsReady,
    ProposalPreviewsReady,
    ProposalRecord,
    RenderManifest,
)
from autodeck.studio.engagement import Engagement
from autodeck.studio.events import EventBus, channel_key
from autodeck.studio.models import DeckArtifact, OptionId
from autodeck.studio.proposals import ProposalStore
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

    def renderer(deck: DeckArtifact, out_dir: Path, digest: str) -> RenderManifest:
        try:
            report = render.render_artifact(deck, tokens=tokens, out_dir=out_dir)
        except FontNotFoundError as exc:
            return RenderManifest(
                digest=digest, slide_ids=deck.slide_ids(), rendered=False, note=str(exc)
            )
        previews = report.previews
        images = [f"{render.PREVIEWS_DIRNAME}/{image.name}" for image in previews.images]
        return RenderManifest(
            digest=digest,
            slide_ids=list(report.built.slide_ids),
            rendered=previews.rendered,
            note=previews.note,
            placeholders=dict(report.built.placeholders),
            images=images if previews.rendered else [],
            pptx=render.PPTX_FILENAME,
            seconds_build=report.built.seconds,
            seconds_previews=previews.seconds,
        )

    return renderer


def read_manifest(render_dir: Path) -> RenderManifest | None:
    """The manifest in `render_dir`, or None when it has none (or it is invalid)."""
    try:
        text = serialise.read_text(render_dir / RENDER_MANIFEST_FILE)
        return RenderManifest.model_validate_json(text)
    except (OSError, ValueError):
        return None


def digest12(deck: DeckArtifact) -> str:
    """The first 12 hex characters of `serialise.artifact_digest(deck)`."""
    return serialise.artifact_digest(deck)[:12]


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
        self._bus = bus
        self._renderer = renderer
        self._synchronous = synchronous
        self._keep = keep
        self._render_lock = threading.RLock()
        self._cond = threading.Condition()
        self._queue: deque[tuple[tuple[str, str, str] | None, Callable[[], None]]] = deque()
        self._queued_keys: set[tuple[str, str, str]] = set()
        self._running = False
        self._stopped = False
        self._thread: threading.Thread | None = None

    def current(self, store: ArtifactStore) -> RenderManifest | None:
        """The manifest for the artifact's current state if it has been rendered, else
        None. Reads `current.json` through `store.load()`."""
        deck = store.load()
        return read_manifest(store.paths.render_dir(digest12(deck)))

    def render_now(self, store: ArtifactStore) -> RenderManifest:
        """Render the current state in the calling thread (reusing an existing render of
        that state), prune old renders, and return the manifest. No event. Used by the
        background job and by tests.

        Renderer exceptions are caught: the result is a manifest with `rendered=False`,
        `note=str(exc)`, the deck's slide ids, which is returned but **not** written (so
        the state is retried next time)."""
        deck = store.load()
        manifest, _ = self._render_deck(
            deck, store.paths.render_dir(digest12(deck)), prune=True
        )
        return manifest

    def request_artifact(
        self, engagement: Engagement, artifact_id: str, *, thread_id: str, turn_id: str | None
    ) -> None:
        """Queue (or, synchronous, run) a render of the artifact's current state, then
        publish `PreviewsReady` (thread_id, turn_id, artifact_id, digest, slide_ids,
        rendered, note, placeholders) on `events.channel_key(client, project, thread_id)`.
        Coalesces as the module docstring says. Never raises for a render failure; an
        artifact that no longer loads is logged to stderr and dropped."""
        key = (engagement.client, engagement.project, artifact_id)

        def job() -> None:
            try:
                store = engagement.artifact_store(artifact_id)
                manifest = self.render_now(store)
            except Exception as exc:
                _log(f"previews: dropping render of {artifact_id!r}: {exc}")
                return
            self._bus.publish(
                channel_key(engagement.client, engagement.project, thread_id),
                PreviewsReady(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    artifact_id=artifact_id,
                    digest=manifest.digest,
                    slide_ids=manifest.slide_ids,
                    rendered=manifest.rendered,
                    note=manifest.note,
                    placeholders=manifest.placeholders,
                ),
            )

        self._submit(key, job)

    def proposal_render_dir(
        self, engagement: Engagement, proposal_id: str, option_id: str
    ) -> Path:
        """`ProposalStore(engagement).paths(proposal_id).option_renders(option_id)`."""
        return ProposalStore(engagement).paths(proposal_id).option_renders(option_id)

    def proposal_manifest(
        self, engagement: Engagement, proposal_id: str, option_id: str
    ) -> RenderManifest | None:
        """The manifest of an option's render, or None."""
        return read_manifest(self.proposal_render_dir(engagement, proposal_id, option_id))

    def request_proposal(
        self, engagement: Engagement, proposal: ProposalRecord, *, thread_id: str
    ) -> None:
        """Queue (or run) renders of every option that has candidate slides, then publish
        one `ProposalPreviewsReady` with `options` = option id -> number of images
        (0 when not rendered), `rendered` = every option rendered, `note` = the first
        failure's note or "". A proposal with no candidate slides publishes nothing."""
        if not any(option.slides for option in proposal.options):
            return

        def job() -> None:
            try:
                if proposal.artifact_id is None:
                    raise ValueError("proposal with candidate slides names no artifact")
                deck = engagement.artifact_store(proposal.artifact_id).load()
            except Exception as exc:
                _log(f"previews: dropping proposal {proposal.id!r}: {exc}")
                return
            options: dict[OptionId, int] = {}
            note = ""
            all_rendered = True
            for option in proposal.options:
                if not option.slides:
                    continue
                candidate = deck.model_copy(update={"slides": list(option.slides)})
                try:
                    folder = self.proposal_render_dir(engagement, proposal.id, option.id)
                    manifest, _ = self._render_deck(candidate, folder)
                except Exception as exc:
                    _log(f"previews: proposal {proposal.id!r} option {option.id}: {exc}")
                    options[option.id] = 0
                    all_rendered = False
                    note = note or str(exc) or type(exc).__name__
                    continue
                options[option.id] = len(manifest.images) if manifest.rendered else 0
                if not manifest.rendered:
                    all_rendered = False
                    note = note or manifest.note
            self._bus.publish(
                channel_key(engagement.client, engagement.project, proposal_thread),
                ProposalPreviewsReady(
                    thread_id=proposal_thread,
                    proposal_id=proposal.id,
                    options=options,
                    rendered=all_rendered,
                    note=note,
                ),
            )

        proposal_thread = thread_id
        self._submit(None, job)

    # -- internals ---------------------------------------------------------

    def _submit(self, key: tuple[str, str, str] | None, job: Callable[[], None]) -> None:
        if self._synchronous:
            self._run_job(job)
            return
        with self._cond:
            if self._stopped:
                return
            if key is not None:
                if key in self._queued_keys:
                    return
                self._queued_keys.add(key)
            self._queue.append((key, job))
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._work, name="autodeck-previews", daemon=True
                )
                self._thread.start()
            self._cond.notify_all()

    def _work(self) -> None:
        while True:
            with self._cond:
                while not self._queue and not self._stopped:
                    self._cond.wait()
                if self._stopped:
                    self._cond.notify_all()
                    return
                key, job = self._queue.popleft()
                if key is not None:
                    self._queued_keys.discard(key)
                self._running = True
            try:
                self._run_job(job)
            finally:
                with self._cond:
                    self._running = False
                    self._cond.notify_all()

    @staticmethod
    def _run_job(job: Callable[[], None]) -> None:
        try:
            job()
        except Exception as exc:  # a job must never kill the worker
            _log(f"previews: job failed: {exc!r}")

    def _render_deck(
        self, deck: DeckArtifact, folder: Path, *, prune: bool = False
    ) -> tuple[RenderManifest, bool]:
        """Render `deck` into `folder` (built in a temporary sibling, then renamed) unless
        `folder` already holds a complete render of this digest. Returns the manifest and
        whether it is stored in `folder`."""
        dig = digest12(deck)
        with self._render_lock:
            existing = read_manifest(folder)
            if existing is not None and existing.digest == dig:
                return existing, True
            parent = folder.parent
            parent.mkdir(parents=True, exist_ok=True)
            tmp = parent / f".tmp-{dig}-{uuid.uuid4().hex}"
            tmp.mkdir()
            try:
                manifest = self._renderer(deck, tmp, dig)
                serialise.atomic_write_text(
                    tmp / RENDER_MANIFEST_FILE, serialise.dump_model(manifest)
                )
                if folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
                tmp.rename(folder)
            except Exception as exc:
                shutil.rmtree(tmp, ignore_errors=True)
                failed = RenderManifest(
                    digest=dig,
                    slide_ids=deck.slide_ids(),
                    rendered=False,
                    note=str(exc) or type(exc).__name__,
                )
                return failed, False
            if prune:
                self._prune(parent, folder)
            return manifest, True

    def _prune(self, parent: Path, keep_dir: Path) -> None:
        """Delete the oldest render directories beyond `self._keep`, never `keep_dir`."""
        try:
            folders = [
                p for p in parent.iterdir() if p.is_dir() and not p.name.startswith(".tmp")
            ]
            folders.sort(key=lambda p: p.stat().st_mtime)
        except OSError:
            return
        excess = len(folders) - max(self._keep, 1)
        for old in folders:
            if excess <= 0:
                break
            if old == keep_dir:
                continue
            shutil.rmtree(old, ignore_errors=True)
            excess -= 1

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until no job is queued or running (True), or the timeout passes (False).
        Immediately True when synchronous."""
        if self._synchronous:
            return True
        with self._cond:
            return self._cond.wait_for(lambda: not self._queue and not self._running, timeout)

    def shutdown(self) -> None:
        """Stop the worker after the current job; queued jobs are dropped. Idempotent."""
        with self._cond:
            self._stopped = True
            self._queue.clear()
            self._queued_keys.clear()
            self._cond.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=60)


def _log(message: str) -> None:
    print(message, file=sys.stderr)
