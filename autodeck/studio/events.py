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

from dataclasses import dataclass

from autodeck.studio.conversation import TurnEvent

DEFAULT_BUFFER = 512
"""Events kept per channel for replay."""


def channel_key(client: str, project: str, thread_id: str) -> str:
    """`"<client>/<project>/<thread_id>"`."""
    raise NotImplementedError


@dataclass(frozen=True)
class Published:
    id: int
    channel: str
    event: TurnEvent


class Subscription:
    """A reader of one channel from a starting id. Created by `EventBus.subscribe`."""

    def get(self, timeout: float) -> Published | None:
        """The next event on the channel with an id greater than the last one returned
        (or than `after_id` at first), waiting up to `timeout` seconds; None on timeout or
        once the subscription or the bus is closed. Events are returned in id order and
        never twice. If the subscriber fell so far behind that events it has not read were
        dropped from the buffer, it continues from the oldest buffered event."""
        raise NotImplementedError

    def close(self) -> None:
        """Stop this subscription; a blocked `get` returns None promptly. Idempotent."""
        raise NotImplementedError

    @property
    def closed(self) -> bool:
        raise NotImplementedError


class EventBus:
    def __init__(self, *, buffer: int = DEFAULT_BUFFER) -> None:
        """`buffer` (>= 1) events are kept per channel; older ones are dropped."""
        raise NotImplementedError

    def publish(self, channel: str, event: TurnEvent) -> Published:
        """Assign the next id, append to the channel's buffer (dropping the oldest beyond
        `buffer`), wake every waiting subscriber, and return the published record."""
        raise NotImplementedError

    def replay(self, channel: str, *, after_id: int = 0) -> list[Published]:
        """The buffered events of `channel` with id > `after_id`, in id order."""
        raise NotImplementedError

    def subscribe(self, channel: str, *, after_id: int = 0) -> Subscription:
        """A subscription that first yields the buffered events with id > `after_id`, then
        new ones as they are published."""
        raise NotImplementedError

    def close(self) -> None:
        """Close every subscription (server shutdown). Publishing after close is allowed
        and buffered, but no subscriber is woken."""
        raise NotImplementedError
