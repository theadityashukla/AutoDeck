"""In-process event bus for streaming turns to the interface (Server-Sent Events).

One bus per server. Events are published to a **channel**, one per thread
(`channel_key(client, project, thread_id)`), and every published event gets the next
integer id from a single counter shared by all channels (ids start at 1 and only grow),
which becomes the SSE `id:` line. Each channel keeps its last `buffer` events so a client
that reconnects with `Last-Event-ID: n` is sent everything after n that is still buffered.

Thread-safe: turns publish from worker threads while request handlers subscribe from
others. Standard library only (`threading.Condition`).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from autodeck.studio.conversation import TurnEvent

DEFAULT_BUFFER = 512
"""Events kept per channel for replay."""


def channel_key(client: str, project: str, thread_id: str) -> str:
    """`"<client>/<project>/<thread_id>"`."""
    return f"{client}/{project}/{thread_id}"


@dataclass(frozen=True)
class Published:
    id: int
    channel: str
    event: TurnEvent


class Subscription:
    """A reader of one channel from a starting id. Created by `EventBus.subscribe`."""

    def __init__(self, bus: EventBus, channel: str, after_id: int) -> None:
        self._bus = bus
        self._channel = channel
        self._last_id = after_id
        self._closed = False

    def get(self, timeout: float) -> Published | None:
        """The next event on the channel with an id greater than the last one returned
        (or than `after_id` at first), waiting up to `timeout` seconds; None on timeout or
        once the subscription or the bus is closed. Events are returned in id order and
        never twice. If the subscriber fell so far behind that events it has not read were
        dropped from the buffer, it continues from the oldest buffered event."""
        cond = self._bus._cond
        deadline = time.monotonic() + max(timeout, 0.0)
        with cond:
            while True:
                if self._closed:
                    return None
                buffer = self._bus._channels.get(self._channel)
                if buffer:
                    # Ids ascend along the buffer: walk back to the first one not yet read.
                    found: Published | None = None
                    for item in reversed(buffer):
                        if item.id <= self._last_id:
                            break
                        found = item
                    if found is not None:
                        self._last_id = found.id
                        return found
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                cond.wait(remaining)

    def close(self) -> None:
        """Stop this subscription; a blocked `get` returns None promptly. Idempotent."""
        cond = self._bus._cond
        with cond:
            self._closed = True
            self._bus._subscriptions.discard(self)
            cond.notify_all()

    @property
    def closed(self) -> bool:
        with self._bus._cond:
            return self._closed


class EventBus:
    def __init__(self, *, buffer: int = DEFAULT_BUFFER) -> None:
        """`buffer` (>= 1) events are kept per channel; older ones are dropped."""
        if buffer < 1:
            raise ValueError("buffer must be >= 1")
        self._buffer = buffer
        self._cond = threading.Condition()
        self._channels: dict[str, deque[Published]] = {}
        self._subscriptions: set[Subscription] = set()
        self._next_id = 1
        self._closed = False

    def publish(self, channel: str, event: TurnEvent) -> Published:
        """Assign the next id, append to the channel's buffer (dropping the oldest beyond
        `buffer`), wake every waiting subscriber, and return the published record."""
        with self._cond:
            record = Published(id=self._next_id, channel=channel, event=event)
            self._next_id += 1
            buffer = self._channels.get(channel)
            if buffer is None:
                buffer = self._channels[channel] = deque(maxlen=self._buffer)
            buffer.append(record)
            if not self._closed:
                self._cond.notify_all()
            return record

    def replay(self, channel: str, *, after_id: int = 0) -> list[Published]:
        """The buffered events of `channel` with id > `after_id`, in id order."""
        with self._cond:
            return [p for p in self._channels.get(channel, ()) if p.id > after_id]

    def subscribe(self, channel: str, *, after_id: int = 0) -> Subscription:
        """A subscription that first yields the buffered events with id > `after_id`, then
        new ones as they are published."""
        sub = Subscription(self, channel, after_id)
        with self._cond:
            if self._closed:
                sub._closed = True
            else:
                self._subscriptions.add(sub)
        return sub

    def close(self) -> None:
        """Close every subscription (server shutdown). Publishing after close is allowed
        and buffered, but no subscriber is woken."""
        with self._cond:
            self._closed = True
            for sub in self._subscriptions:
                sub._closed = True
            self._subscriptions.clear()
            self._cond.notify_all()
