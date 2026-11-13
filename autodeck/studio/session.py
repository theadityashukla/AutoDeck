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

import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from autodeck.agents.tools.registry import ToolResult
from autodeck.design.theme.tokens import DesignTokens
from autodeck.providers.base import ToolCall
from autodeck.studio import context as context_module
from autodeck.studio import loop, prompt, tools
from autodeck.studio.bindings import BoundModel
from autodeck.studio.conversation import (
    MAX_SUMMARY_CHARS,
    ProposalRecord,
    ProposalResolved,
    ThreadRecord,
    ToolCallRecord,
    TurnEndLine,
    TurnEvent,
    TurnFinished,
    TurnStarted,
    UserOrigin,
    classify_turn,
)
from autodeck.studio.conversation import ChangeReverted as ChangeRevertedEvent
from autodeck.studio.engagement import (
    Engagement,
    create_engagement,
    open_engagement,
)
from autodeck.studio.errors import ProposalStateError, TurnInProgressError
from autodeck.studio.events import EventBus, channel_key
from autodeck.studio.loop import LoopLimits
from autodeck.studio.models import ChangeEntry
from autodeck.studio.previews import PreviewService
from autodeck.studio.proposals import ProposalStore
from autodeck.studio.sources import SourceLibrary
from autodeck.studio.threads import ThreadStore
from autodeck.studio.views import clip


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


class _TurnRecorder:
    """The loop's sink for one turn: appends lines to the thread log, publishes events on
    the thread's channel, and counts steps and tokens as they happen."""

    def __init__(
        self,
        studio: Studio,
        store: ThreadStore,
        thread_id: str,
        turn_id: str,
        model_id: str,
        channel: str,
        counted: dict[str, int],
    ) -> None:
        self.studio = studio
        self.store = store
        self.thread_id = thread_id
        self.turn_id = turn_id
        self.model_id = model_id
        self.channel = channel
        self.counted = counted

    def assistant(
        self,
        *,
        step: int,
        text: str,
        tool_calls: list[ToolCall],
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self.store.append(
            self.thread_id,
            {
                "kind": "assistant",
                "turn_id": self.turn_id,
                "step": step,
                "text": text,
                "tool_calls": [
                    ToolCallRecord(
                        id=c.id, name=c.name, arguments=dict(c.arguments)
                    ).model_dump()
                    for c in tool_calls
                ],
                "model_id": self.model_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            now=self.studio.clock(),
        )
        self.counted["steps"] = step
        self.counted["input"] += input_tokens
        self.counted["output"] += output_tokens

    def tool(self, *, step: int, call: ToolCall, result: ToolResult) -> None:
        self.store.append(
            self.thread_id,
            {
                "kind": "tool",
                "turn_id": self.turn_id,
                "step": step,
                "tool_call_id": call.id,
                "tool_name": call.name,
                "text": result.text,
                "summary": result.summary,
                "error": result.error,
            },
            now=self.studio.clock(),
        )

    def event(self, event: TurnEvent) -> None:
        self.studio.bus.publish(self.channel, event)


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
        self.settings = settings
        self.lead = lead
        self.bus = bus
        self.previews = previews
        self.clock = clock or (lambda: datetime.now(UTC))
        self.system = prompt.system_prompt()
        self._table_lock = threading.Lock()
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._running: dict[tuple[str, str], str] = {}

    # -- engagements ----------------------------------------------------------------

    def engagement(self, client: str, project: str) -> Engagement:
        """`open_engagement(client, project, knowledge_root=..., workspace_root=...)`: the
        only way any operation reaches an engagement, so every request is re-validated
        against the knowledge folders and bound to one client (A4)."""
        return open_engagement(
            client,
            project,
            knowledge_root=self.settings.knowledge_root,
            workspace_root=self.settings.workspace_root,
        )

    def create_engagement(self, client: str, project: str, *, title: str = "") -> Engagement:
        """`create_engagement(...)` with this studio's roots and clock."""
        return create_engagement(
            client,
            project,
            knowledge_root=self.settings.knowledge_root,
            workspace_root=self.settings.workspace_root,
            title=title,
            now=self.clock(),
        )

    # -- threads ----------------------------------------------------------------------

    def create_thread(self, engagement: Engagement, *, title: str = "") -> ThreadRecord:
        """Create a thread without running anything: build the context
        (`context.gather_inputs` + `render_context`), `opening = "returning" if
        context.is_returning(inputs) else "fresh"`, `ThreadStore.create(context_text=...,
        opening=..., model_id=self.lead.model_id, title=title, now=clock())`. Takes the
        engagement lock for the duration (`TurnInProgressError` if held)."""
        key = self._key(engagement)
        self._acquire(key)
        try:
            return self._create_thread_locked(engagement, title)
        finally:
            self._release(key)

    def open_thread(
        self, engagement: Engagement, *, title: str = ""
    ) -> tuple[ThreadRecord, TurnFinished | None]:
        """`create_thread`, then, when its opening is `returning`, `run_turn(...,
        text=prompt.RECAP_REQUEST, origin="recap")`. Returns the record and the recap
        turn's result (None for a fresh thread). Synchronous."""
        record = self.create_thread(engagement, title=title)
        if record.opening != "returning":
            return record, None
        finished = self.run_turn(
            engagement, record.id, text=prompt.RECAP_REQUEST, origin="recap"
        )
        return record, finished

    # -- turns ------------------------------------------------------------------------

    def run_turn(
        self, engagement: Engagement, thread_id: str, *, text: str, origin: UserOrigin = "owner"
    ) -> TurnFinished:
        """Run one turn synchronously: take the engagement lock without blocking
        (`TurnInProgressError`), `_run_turn_locked`, release. See `begin_turn` for the
        server's asynchronous form."""
        key = self._key(engagement)
        self._acquire(key)
        try:
            return self._run_turn_locked(engagement, thread_id, text=text, origin=origin)
        finally:
            self._release(key)

    def begin_turn(
        self, engagement: Engagement, thread_id: str, *, text: str, origin: UserOrigin = "owner"
    ) -> str:
        """Start a turn on a daemon thread and return its turn id at once.

        In the calling thread: take the lock without blocking (`TurnInProgressError`),
        check the thread exists (`ThreadNotFoundError`, releasing the lock), compute the
        turn id (`ThreadStore.next_turn_id`). The worker runs `_run_turn_locked` and
        releases the lock when it ends, whatever happens."""
        key = self._key(engagement)
        self._acquire(key)
        try:
            return self._start_worker(engagement, thread_id, text=text, origin=origin)
        except BaseException:
            self._release(key)
            raise

    def begin_open_thread(
        self, engagement: Engagement, *, title: str = ""
    ) -> tuple[ThreadRecord, str | None]:
        """`create_thread`, then, when returning, `begin_turn(..., RECAP_REQUEST,
        origin="recap")`. Returns the record and the recap turn id (None when fresh)."""
        record = self.create_thread(engagement, title=title)
        if record.opening != "returning":
            return record, None
        turn_id = self.begin_turn(
            engagement, record.id, text=prompt.RECAP_REQUEST, origin="recap"
        )
        return record, turn_id

    def running_turn(self, engagement: Engagement) -> str | None:
        """`"<thread id>/<turn id>"` of the turn running in this engagement, or None."""
        with self._table_lock:
            return self._running.get(self._key(engagement))

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
        key = self._key(engagement)
        store = ThreadStore(engagement)
        store.load(thread_id)
        lines = store.read_lines(thread_id)
        turn_id = store.next_turn_id(thread_id)
        with self._table_lock:
            self._running[key] = f"{thread_id}/{turn_id}"
        instruction = "Opening recap" if origin == "recap" else tools.instruction_line(text)
        lead = self.lead  # read once: a later phase may route a turn elsewhere
        channel = channel_key(engagement.client, engagement.project, thread_id)

        if not lines:
            store.append(
                thread_id,
                {
                    "kind": "user",
                    "turn_id": turn_id,
                    "origin": "context",
                    "text": store.context_text(thread_id),
                },
                now=self.clock(),
            )
        store.append(
            thread_id,
            {"kind": "user", "turn_id": turn_id, "origin": origin, "text": text},
            now=self.clock(),
        )
        self.bus.publish(
            channel,
            TurnStarted(
                thread_id=thread_id,
                turn_id=turn_id,
                origin=origin,
                text=text if origin in ("owner", "choice") else "",
                model_id=lead.model_id,
            ),
        )

        ledger = tools.TurnLedger()
        counted: dict[str, int] = {"steps": 0, "input": 0, "output": 0}
        stop_reason: Any = "replied"
        error = ""

        try:
            messages, summaries = loop.build_model_messages(store.read_lines(thread_id))
            tool_ctx = tools.ToolContext(
                engagement=engagement,
                thread_id=thread_id,
                turn_id=turn_id,
                instruction=instruction,
                model_id=lead.model_id,
                tokens=self.settings.tokens,
                sources=SourceLibrary(engagement, corpus_root=self.settings.corpus_root),
                proposals=ProposalStore(engagement),
                ledger=ledger,
                clock=self.clock,
            )
            toolbox = tools.build_toolbox(tool_ctx)
            outcome = loop.run_steps(
                lead,
                system=self.system,
                messages=messages,
                summaries=summaries,
                toolbox=toolbox,
                ledger=ledger,
                sink=_TurnRecorder(
                    self, store, thread_id, turn_id, lead.model_id, channel, counted
                ),
                thread_id=thread_id,
                turn_id=turn_id,
                limits=self.settings.limits,
            )
            stop_reason = outcome.stop_reason
            counted["steps"] = outcome.steps
            counted["input"] = outcome.input_tokens
            counted["output"] = outcome.output_tokens
        except Exception as exc:
            stop_reason = "error"
            error = f"{type(exc).__name__}: {exc}"

        change_ids = [entry.id for _, entry in ledger.changes]
        undone_ids = [entry.id for _, entry in ledger.undone]
        redone_ids = [entry.id for _, entry in ledger.redone]
        proposal_ids = [proposal.id for proposal in ledger.proposals]
        totals: dict[str, Any] = {
            "turn_id": turn_id,
            "turn_kind": classify_turn(
                change_ids=change_ids,
                undone_ids=undone_ids,
                redone_ids=redone_ids,
                created_artifacts=list(ledger.created),
                proposal_ids=proposal_ids,
            ),
            "stop_reason": stop_reason,
            "model_id": lead.model_id,
            "steps": counted["steps"],
            "change_ids": change_ids,
            "undone_ids": undone_ids,
            "redone_ids": redone_ids,
            "created_artifacts": list(ledger.created),
            "proposal_ids": proposal_ids,
            "input_tokens": counted["input"],
            "output_tokens": counted["output"],
            "error": error,
        }
        finished = TurnFinished(thread_id=thread_id, **totals)
        end = TurnEndLine.model_validate(
            {**totals, "kind": "turn_end", "seq": 1, "created_at": self.clock()}
        )
        store.append(
            thread_id,
            {
                "kind": "turn_end",
                **end.model_dump(mode="json", exclude={"kind", "seq", "created_at"}),
            },
            now=end.created_at,
        )
        self.bus.publish(channel, finished)

        for artifact_id in ledger.touched_artifacts():
            self.previews.request_artifact(
                engagement, artifact_id, thread_id=thread_id, turn_id=turn_id
            )
        for proposal in ledger.proposals:
            self.previews.request_proposal(engagement, proposal, thread_id=thread_id)
        return finished

    # -- owner actions between turns ----------------------------------------------------

    def pick_option(
        self, engagement: Engagement, thread_id: str, proposal_id: str, option_id: str
    ) -> TurnFinished:
        """The owner picked an option with the button. Under the lock: resolve the
        proposal `accepted` with `by="owner"` (`ProposalStateError` when it is not open, or
        the option is unknown), publish `ProposalResolved`, then run the turn with
        `text=prompt.choice_text(proposal_id, option_id, option.label)`, `origin="choice"`.
        Synchronous; `begin_pick_option` is the server's form."""
        key = self._key(engagement)
        self._acquire(key)
        try:
            text = self._resolve_pick(engagement, thread_id, proposal_id, option_id)
            return self._run_turn_locked(engagement, thread_id, text=text, origin="choice")
        finally:
            self._release(key)

    def begin_pick_option(
        self, engagement: Engagement, thread_id: str, proposal_id: str, option_id: str
    ) -> str:
        """As `pick_option`, but the resolution happens in the calling thread and the turn
        runs on a daemon thread (as `begin_turn`); returns the turn id. If resolving fails
        (`ProposalStateError`, `ProposalNotFoundError`, `ThreadNotFoundError`) the lock is
        released before the error propagates and nothing runs."""
        key = self._key(engagement)
        self._acquire(key)
        try:
            text = self._resolve_pick(engagement, thread_id, proposal_id, option_id)
            return self._start_worker(engagement, thread_id, text=text, origin="choice")
        except BaseException:
            self._release(key)
            raise

    def dismiss_proposal(
        self, engagement: Engagement, thread_id: str, proposal_id: str
    ) -> ProposalRecord:
        """The owner dismissed a proposal. Under the lock: resolve it `dismissed` with
        `by="owner"`, append `NoteLine(note="proposal_dismissed", ref=proposal_id,
        artifact_id=proposal.artifact_id, text="The owner dismissed proposal <id>:
        <summary>")` to `thread_id` (clipped to `conversation.MAX_SUMMARY_CHARS`), publish
        `ProposalResolved`. No turn runs."""
        key = self._key(engagement)
        self._acquire(key)
        try:
            ThreadStore(engagement).load(thread_id)
            proposals = ProposalStore(engagement)
            proposal = proposals.resolve(
                proposal_id, status="dismissed", chosen=None, by="owner", now=self.clock()
            )
            ThreadStore(engagement).append(
                thread_id,
                {
                    "kind": "note",
                    "note": "proposal_dismissed",
                    "ref": proposal_id,
                    "artifact_id": proposal.artifact_id,
                    "text": clip(
                        f"The owner dismissed proposal {proposal_id}: {proposal.summary}",
                        MAX_SUMMARY_CHARS,
                    ),
                },
                now=self.clock(),
            )
            self.bus.publish(
                channel_key(engagement.client, engagement.project, thread_id),
                ProposalResolved(
                    thread_id=thread_id,
                    proposal_id=proposal_id,
                    status="dismissed",
                    chosen=None,
                    by="owner",
                ),
            )
            return proposal
        finally:
            self._release(key)

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
        return self._owner_revert(engagement, artifact_id, thread_id, "undo")

    def owner_redo(
        self, engagement: Engagement, artifact_id: str, *, thread_id: str | None = None
    ) -> ChangeEntry:
        """As `owner_undo`, with `store.redo()`, note `owner_redo` ("The owner redid ..."),
        action `redo`.

        Raises:
            NothingToRedoError and the others as `owner_undo`.
        """
        return self._owner_revert(engagement, artifact_id, thread_id, "redo")

    def request_render(
        self, engagement: Engagement, artifact_id: str, *, thread_id: str
    ) -> None:
        """Ask for previews of the artifact's current state (the interface does this when
        it opens a thread and the artifact has no render, e.g. after a server restart):
        check the thread exists (`ThreadNotFoundError`) and the artifact loads
        (`ArtifactNotFoundError`), then `previews.request_artifact(..., thread_id,
        turn_id=None)`. Takes no lock: rendering only reads."""
        ThreadStore(engagement).load(thread_id)
        engagement.artifact_store(artifact_id).load()
        self.previews.request_artifact(
            engagement, artifact_id, thread_id=thread_id, turn_id=None
        )

    def shutdown(self) -> None:
        """`previews.shutdown()` and `bus.close()`."""
        self.previews.shutdown()
        self.bus.close()

    # -- internals ----------------------------------------------------------------------

    @staticmethod
    def _key(engagement: Engagement) -> tuple[str, str]:
        return (engagement.client, engagement.project)

    def _acquire(self, key: tuple[str, str]) -> None:
        with self._table_lock:
            lock = self._locks.setdefault(key, threading.Lock())
        if not lock.acquire(blocking=False):
            raise TurnInProgressError(
                "a turn is already running in this engagement; try again when it finishes"
            )

    def _release(self, key: tuple[str, str]) -> None:
        with self._table_lock:
            self._running.pop(key, None)
            lock = self._locks[key]
        lock.release()

    def _create_thread_locked(self, engagement: Engagement, title: str) -> ThreadRecord:
        inputs = context_module.gather_inputs(
            engagement, owner_memory_path=self.settings.owner_memory_path
        )
        text = context_module.render_context(inputs)
        opening = "returning" if context_module.is_returning(inputs) else "fresh"
        return ThreadStore(engagement).create(
            context_text=text,
            opening=opening,
            model_id=self.lead.model_id,
            title=title,
            now=self.clock(),
        )

    def _start_worker(
        self, engagement: Engagement, thread_id: str, *, text: str, origin: UserOrigin
    ) -> str:
        """With the lock held: check the thread, compute the turn id and run the turn on a
        daemon thread that releases the lock when it ends. On an exception here the caller
        releases the lock (the worker was not started)."""
        key = self._key(engagement)
        store = ThreadStore(engagement)
        store.load(thread_id)
        turn_id = store.next_turn_id(thread_id)
        with self._table_lock:
            self._running[key] = f"{thread_id}/{turn_id}"

        def work() -> None:
            try:
                self._run_turn_locked(engagement, thread_id, text=text, origin=origin)
            except BaseException as exc:  # the lock must be released whatever happens
                print(
                    f"studio: turn {thread_id}/{turn_id} failed: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
            finally:
                self._release(key)

        threading.Thread(target=work, name=f"turn-{thread_id}-{turn_id}", daemon=True).start()
        return turn_id

    def _resolve_pick(
        self, engagement: Engagement, thread_id: str, proposal_id: str, option_id: str
    ) -> str:
        """Resolve the proposal as accepted by the owner, publish it, and return the choice
        text for the turn. The caller holds the lock."""
        ThreadStore(engagement).load(thread_id)
        proposals = ProposalStore(engagement)
        try:
            option = proposals.load(proposal_id).option(option_id)
        except KeyError as exc:
            raise ProposalStateError(str(exc.args[0])) from exc
        record = proposals.resolve(
            proposal_id,
            status="accepted",
            chosen=option.id,
            by="owner",
            now=self.clock(),
        )
        self.bus.publish(
            channel_key(engagement.client, engagement.project, thread_id),
            ProposalResolved(
                thread_id=thread_id,
                proposal_id=proposal_id,
                status="accepted",
                chosen=record.chosen,
                by="owner",
            ),
        )
        return prompt.choice_text(proposal_id, option.id, option.label)

    def _owner_revert(
        self,
        engagement: Engagement,
        artifact_id: str,
        thread_id: str | None,
        action: str,
    ) -> ChangeEntry:
        key = self._key(engagement)
        self._acquire(key)
        try:
            threads = ThreadStore(engagement)
            if thread_id is not None:
                threads.load(thread_id)
            store = engagement.artifact_store(artifact_id)
            entry = store.undo() if action == "undo" else store.redo()
            if thread_id is not None:
                verb = "undid" if action == "undo" else "redid"
                threads.append(
                    thread_id,
                    {
                        "kind": "note",
                        "note": "owner_undo" if action == "undo" else "owner_redo",
                        "ref": entry.id,
                        "artifact_id": artifact_id,
                        "text": clip(
                            f"The owner {verb} {entry.id} on {artifact_id}: "
                            f"{entry.instruction}",
                            MAX_SUMMARY_CHARS,
                        ),
                    },
                    now=self.clock(),
                )
                self.bus.publish(
                    channel_key(engagement.client, engagement.project, thread_id),
                    ChangeRevertedEvent(
                        thread_id=thread_id,
                        turn_id=None,
                        artifact_id=artifact_id,
                        entry_id=entry.id,
                        action="undo" if action == "undo" else "redo",
                        by="owner",
                    ),
                )
                self.previews.request_artifact(
                    engagement, artifact_id, thread_id=thread_id, turn_id=None
                )
            return entry
        finally:
            self._release(key)
