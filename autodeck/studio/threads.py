"""Threads on disk: the record, the opening context, and the append-only log (plan §4, P2).

Layout, from `paths.ThreadPaths`, under `<engagement>/threads/<thread-id>/`:

* `thread.json`: the `ThreadRecord`, written once at creation;
* `context.md`: the opening context the thread was given (built from state by `context`),
  written once at creation; its SHA-256 is the record's `context_digest`;
* `messages.jsonl`: one `ThreadLine` per line, appended in order, never rewritten.

**Who reads `messages.jsonl`.** The interface (to display the thread) and the same
thread's loop (to rebuild its own conversation). Nothing else: the context builder never
imports this module's readers, which is pinned by a test. That is what "a thread's
context is built from state, never from an earlier thread's transcript" means in code.

**Isolation.** A `ThreadStore` is bound to one `Engagement`; every path it touches comes
from `engagement.paths.thread(...)` and passes `engagement.guard` before any read or write,
so a thread directory that is a symlink into another client's engagements raises v2's
`ClientIsolationError`.

Single writer: the session runs one turn at a time per engagement (`session`), so appends
are not locked here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from autodeck.studio.conversation import ThreadLine, ThreadRecord
from autodeck.studio.engagement import Engagement
from autodeck.studio.paths import ThreadPaths


class ThreadStore:
    """Create, read and append to the threads of one engagement. The constructor stores
    the engagement and touches no file."""

    def __init__(self, engagement: Engagement) -> None:
        self.engagement = engagement

    def paths(self, thread_id: str) -> ThreadPaths:
        """`engagement.paths.thread(thread_id)`, with its root passed through
        `engagement.guard`.

        Raises:
            InvalidSegmentError: not a thread id (`t0001`, ...).
            ClientIsolationError: the thread directory resolves into another client's
                engagements (for example a symlink).
        """
        raise NotImplementedError

    def next_thread_id(self) -> str:
        """`t` + the 1-based ordinal of the next thread, zero-padded to 4 digits: `t0001`
        when the engagement has no thread directory, else one more than the highest
        existing id's number (`engagement.paths.thread_ids()`), so ids are never reused."""
        raise NotImplementedError

    def create(
        self,
        *,
        context_text: str,
        opening: str,
        model_id: str,
        title: str = "",
        now: datetime,
    ) -> ThreadRecord:
        """Create the next thread and return its record.

        Steps, in order: id = `next_thread_id()`; build the `ThreadRecord` (client and
        project from the engagement, `context_digest = serialise.text_digest(context_text)`,
        `opening` must be `"fresh"` or `"returning"`; an invalid value or a naive `now`
        fails validation before anything is written); `paths(id).ensure()`; write
        `context.md` (exact text, `serialise.atomic_write_text`); then `thread.json`
        (`serialise.dump_model`). `messages.jsonl` is not created until the first append.

        Raises:
            pydantic.ValidationError: as above (nothing written).
        """
        raise NotImplementedError

    def load(self, thread_id: str) -> ThreadRecord:
        """The validated record.

        Raises:
            ThreadNotFoundError: no `thread.json` for this id (the message names the id).
            ClientIsolationError: (v2's) the record names another client (a record copied
                from another client's engagement).
            ThreadLogError: the record's `project` is not this engagement's, or its `id`
                is not `thread_id`.
            InvalidSegmentError, ClientIsolationError: as `paths`.
            pydantic.ValidationError: malformed.
        """
        raise NotImplementedError

    def list(self) -> list[ThreadRecord]:
        """Every thread's record, sorted by id. A directory whose record is missing,
        invalid, or refused by `load` for any reason (isolation included) is skipped: a
        listing for the interface, not a validation, and nothing refused is ever shown."""
        raise NotImplementedError

    def context_text(self, thread_id: str) -> str:
        """The exact text of `context.md` (`serialise.read_text`).

        Raises:
            ThreadNotFoundError: the thread (record) does not exist.
            ThreadLogError: `context.md` is missing, or its digest is not the record's
                `context_digest`.
        """
        raise NotImplementedError

    def read_lines(self, thread_id: str) -> list[ThreadLine]:
        """Every line of `messages.jsonl`, validated (`conversation.THREAD_LINE`), in order.

        `[]` when the file does not exist yet. Blank lines are not allowed.

        Raises:
            ThreadNotFoundError: the thread (record) does not exist.
            ThreadLogError: a line is blank, is not valid JSON or not a valid `ThreadLine`,
                or the n-th line's `seq` is not n. The message names the line number.
        """
        raise NotImplementedError

    def append(self, thread_id: str, fields: dict[str, Any], *, now: datetime) -> ThreadLine:
        """Append one line and return it validated.

        `fields` is a line's data without `seq` and `created_at` (it must include `kind`).
        The line is `THREAD_LINE.validate_python({**fields, "seq": n + 1,
        "created_at": now})` where n is the number of lines already in the file
        (`read_lines`). It is written as `json.dumps(line.model_dump(mode="json"),
        ensure_ascii=False)` plus `"\\n"`, opened in append mode with `newline=""`, then
        flushed and `os.fsync`ed. Validation happens before the file is opened, so an
        invalid line writes nothing.

        Raises:
            ThreadNotFoundError: the thread does not exist.
            ThreadLogError: the existing file is corrupt (as `read_lines`).
            pydantic.ValidationError: `fields` do not make a valid line; `fields` that
                contain `seq` or `created_at` raise `ValueError` before validation.
        """
        raise NotImplementedError

    def next_turn_id(self, thread_id: str) -> str:
        """`u` + the 1-based ordinal of the next turn, zero-padded to 4 digits: one more
        than the number of distinct `turn_id`s among the thread's `UserLine`s (`u0001` for
        an empty log)."""
        raise NotImplementedError
