"""The studio: threads, turns and owner actions over one workspace (plan §5, Phase 1).

`Studio` is what the HTTP API calls, and what the acceptance tests drive directly. It ties
together the engagement, the thread log, the context builder, the lead loop, the tools,
the previews and the event bus, and owns two rules:

* **One turn at a time per engagement.** A per-engagement lock (keyed by client and
  project) is taken without blocking by every operation that changes state (a turn, an
  owner undo/redo, a dismissal, a pick); if it is held, `TurnInProgressError`. Phase 0's
  store assumes one writer; several threads on one artifact is Phase 4.
* **A thread opens from state.** `open_thread` builds the context (`context`), records it
  as the thread's `context.md`, and, when the engagement has state to recap, runs the
  opening recap turn. The first turn of every thread writes the context as its first
  `UserLine` (origin `context`) before the turn's own line, so the model's first message
  is the context followed by the request (`loop.build_model_messages` merges them).

The order of side effects in a turn is fixed (see `run_turn`) so the event stream and the
thread log always agree.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from autodeck.design.theme.tokens import DesignTokens
from autodeck.studio.bindings import BoundModel
from autodeck.studio.conversation import (
    ProposalRecord,
    ThreadRecord,
    TurnFinished,
    UserOrigin,
)
from autodeck.studio.engagement import Engagement
from autodeck.studio.events import EventBus
from autodeck.studio.loop import LoopLimits
from autodeck.studio.models import ChangeEntry
from autodeck.studio.previews import PreviewService


@dataclass(frozen=True)
class StudioSettings:
    knowledge_root: Path
    workspace_root: Path
    corpus_root: Path
    """Where v2's ingested documents live (`<corpus_root>/<project>`)."""
    owner_memory_path: Path
    """The owner memory file (v2's default is `~/.autodeck/memory/owner.md`)."""
    tokens: DesignTokens
    limits: LoopLimits = field(default_factory=LoopLimits)


class Studio:
    """One per server process (or per test)."""

    settings: StudioSettings
    lead: BoundModel
    bus: EventBus
    previews: PreviewService
    clock: Callable[[], datetime]
    system: str

    def __init__(
        self,
        settings: StudioSettings,
        *,
        lead: BoundModel,
        bus: EventBus,
        previews: PreviewService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Stores its arguments as `self.settings`, `self.lead`, `self.bus`, `self.previews`
        and `self.clock` (`clock` defaults to `datetime.now(UTC)`), reads the system prompt
        once into `self.system` (`prompt.system_prompt()`), and creates the lock table.
        Touches no workspace file. `self.lead` is read at the start of every turn, so a
        test (or Phase 2's routing) may replace it between turns."""
        raise NotImplementedError

    # -- engagements ----------------------------------------------------------------

    def engagement(self, client: str, project: str) -> Engagement:
        """`open_engagement(client, project, knowledge_root=..., workspace_root=...)`: the
        only way any operation reaches an engagement, so every request is re-validated
        against the knowledge folders and bound to one client (A4)."""
        raise NotImplementedError

    def create_engagement(self, client: str, project: str, *, title: str = "") -> Engagement:
        """`create_engagement(...)` with this studio's roots and clock."""
        raise NotImplementedError

    # -- threads ----------------------------------------------------------------------

    def create_thread(self, engagement: Engagement, *, title: str = "") -> ThreadRecord:
        """Create a thread without running anything: build the context
        (`context.gather_inputs` + `render_context`), `opening = "returning" if
        context.is_returning(inputs) else "fresh"`, `ThreadStore.create(context_text=...,
        opening=..., model_id=self.lead.model_id, title=title, now=clock())`. Takes the
        engagement lock for the duration (`TurnInProgressError` if held)."""
        raise NotImplementedError

    def open_thread(
        self, engagement: Engagement, *, title: str = ""
    ) -> tuple[ThreadRecord, TurnFinished | None]:
        """`create_thread`, then, when its opening is `returning`, `run_turn(...,
        text=prompt.RECAP_REQUEST, origin="recap")`. Returns the record and the recap
        turn's result (None for a fresh thread). Synchronous."""
        raise NotImplementedError

    # -- turns ------------------------------------------------------------------------

    def run_turn(
        self, engagement: Engagement, thread_id: str, *, text: str, origin: UserOrigin = "owner"
    ) -> TurnFinished:
        """Run one turn synchronously: take the engagement lock without blocking
        (`TurnInProgressError`), `_run_turn_locked`, release. See `begin_turn` for the
        server's asynchronous form."""
        raise NotImplementedError

    def begin_turn(
        self, engagement: Engagement, thread_id: str, *, text: str, origin: UserOrigin = "owner"
    ) -> str:
        """Start a turn on a daemon thread and return its turn id at once.

        In the calling thread: take the lock without blocking (`TurnInProgressError`),
        check the thread exists (`ThreadNotFoundError`, releasing the lock), compute the
        turn id (`ThreadStore.next_turn_id`). The worker runs `_run_turn_locked` and
        releases the lock when it ends, whatever happens."""
        raise NotImplementedError

    def begin_open_thread(
        self, engagement: Engagement, *, title: str = ""
    ) -> tuple[ThreadRecord, str | None]:
        """`create_thread`, then, when returning, `begin_turn(..., RECAP_REQUEST,
        origin="recap")`. Returns the record and the recap turn id (None when fresh)."""
        raise NotImplementedError

    def running_turn(self, engagement: Engagement) -> str | None:
        """`"<thread id>/<turn id>"` of the turn running in this engagement, or None."""
        raise NotImplementedError

    def _run_turn_locked(
        self, engagement: Engagement, thread_id: str, *, text: str, origin: UserOrigin
    ) -> TurnFinished:
        """The turn itself; the caller holds the engagement lock. Side effects in order:

        1. `store = ThreadStore(engagement)`; `store.load(thread_id)`; `lines =
           store.read_lines(thread_id)`; `turn_id = store.next_turn_id(thread_id)`;
           `instruction = tools.instruction_line(text)` (for `recap` origin:
           `"Opening recap"`).
        2. If `lines` is empty, append `UserLine(origin="context", text=
           store.context_text(thread_id), turn_id)`.
        3. Append `UserLine(origin, text, turn_id)`.
        4. Publish `TurnStarted(thread_id, turn_id, origin, text if origin in ("owner",
           "choice") else "", model_id)`.
        5. `messages, summaries = loop.build_model_messages(store.read_lines(thread_id))`;
           build a `TurnLedger`, `ToolContext` (with a `SourceLibrary(engagement,
           corpus_root=...)` and `ProposalStore(engagement)`) and `tools.build_toolbox`.
        6. `loop.run_steps(self.lead, system=..., messages, summaries, toolbox, ledger,
           sink, thread_id, turn_id, limits)` where the sink appends `AssistantLine` /
           `ToolLine` (with `model_id`) and publishes events on the thread's channel.
           Any exception: `stop_reason="error"`, `error=f"{type(exc).__name__}: {exc}"`,
           steps/tokens as counted by the sink so far.
        7. Classify (`conversation.classify_turn` over the ledger) and append the
           `TurnEndLine`; publish the matching `TurnFinished`.
        8. For each `ledger.touched_artifacts()`: `previews.request_artifact(...,
           thread_id, turn_id)`; for each proposal created: `previews.request_proposal`.
        9. Return the `TurnFinished`.
        """
        raise NotImplementedError

    # -- owner actions between turns ----------------------------------------------------

    def pick_option(
        self, engagement: Engagement, thread_id: str, proposal_id: str, option_id: str
    ) -> TurnFinished:
        """The owner picked an option with the button. Under the lock: resolve the
        proposal `accepted` with `by="owner"` (`ProposalStateError` when it is not open, or
        the option is unknown), publish `ProposalResolved`, then run the turn with
        `text=prompt.choice_text(proposal_id, option_id, option.label)`, `origin="choice"`.
        Synchronous; `begin_pick_option` is the server's form."""
        raise NotImplementedError

    def begin_pick_option(
        self, engagement: Engagement, thread_id: str, proposal_id: str, option_id: str
    ) -> str:
        """As `pick_option`, but the resolution happens in the calling thread and the turn
        runs on a daemon thread (as `begin_turn`); returns the turn id. If resolving fails
        (`ProposalStateError`, `ProposalNotFoundError`, `ThreadNotFoundError`) the lock is
        released before the error propagates and nothing runs."""
        raise NotImplementedError

    def dismiss_proposal(
        self, engagement: Engagement, thread_id: str, proposal_id: str
    ) -> ProposalRecord:
        """The owner dismissed a proposal. Under the lock: resolve it `dismissed` with
        `by="owner"`, append `NoteLine(note="proposal_dismissed", ref=proposal_id,
        artifact_id=proposal.artifact_id, text="The owner dismissed proposal <id>:
        <summary>")` to `thread_id` (clipped to `conversation.MAX_SUMMARY_CHARS`), publish
        `ProposalResolved`. No turn runs."""
        raise NotImplementedError

    def owner_undo(
        self, engagement: Engagement, artifact_id: str, *, thread_id: str | None = None
    ) -> ChangeEntry:
        """Undo from the Changes tab. Under the lock: `store.undo()`. With a `thread_id`,
        append `NoteLine(note="owner_undo", ref=entry.id, artifact_id, text="The owner
        undid <id> on <artifact>: <instruction>")` (clipped as above), publish
        `ChangeReverted(by="owner", action="undo", turn_id=None)` on that thread's
        channel, and request previews for that thread. Returns the entry as stored.

        Raises:
            NothingToUndoError, ArtifactNotFoundError, TurnInProgressError,
            ThreadNotFoundError (unknown `thread_id`, checked before undoing).
        """
        raise NotImplementedError

    def owner_redo(
        self, engagement: Engagement, artifact_id: str, *, thread_id: str | None = None
    ) -> ChangeEntry:
        """As `owner_undo`, with `store.redo()`, note `owner_redo` ("The owner redid ..."),
        action `redo`.

        Raises:
            NothingToRedoError and the others as `owner_undo`.
        """
        raise NotImplementedError

    def request_render(
        self, engagement: Engagement, artifact_id: str, *, thread_id: str
    ) -> None:
        """Ask for previews of the artifact's current state (the interface does this when
        it opens a thread and the artifact has no render, e.g. after a server restart):
        check the thread exists (`ThreadNotFoundError`) and the artifact loads
        (`ArtifactNotFoundError`), then `previews.request_artifact(..., thread_id,
        turn_id=None)`. Takes no lock: rendering only reads."""
        raise NotImplementedError

    def shutdown(self) -> None:
        """`previews.shutdown()` and `bus.close()`."""
        raise NotImplementedError
