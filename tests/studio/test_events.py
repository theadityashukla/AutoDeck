"""The in-process event bus behind Server-Sent Events."""

from __future__ import annotations

import threading
import time

from autodeck.studio.conversation import AssistantText, TurnStarted
from autodeck.studio.events import EventBus, channel_key


def _started(turn: str = "u0001", thread: str = "t0001") -> TurnStarted:
    return TurnStarted(thread_id=thread, turn_id=turn, origin="owner", text="hi", model_id="m")


def _text(step: int) -> AssistantText:
    return AssistantText(
        thread_id="t0001", turn_id="u0001", step=step, text=f"s{step}", model_id="m"
    )


def test_channel_key() -> None:
    assert channel_key("c", "p", "t0001") == "c/p/t0001"


def test_ids_are_global_and_increasing() -> None:
    bus = EventBus()
    first = bus.publish("a", _started())
    second = bus.publish("b", _started(thread="t0002"))
    third = bus.publish("a", _text(1))
    assert (first.id, second.id, third.id) == (1, 2, 3)
    assert [p.id for p in bus.replay("a")] == [1, 3]
    assert [p.id for p in bus.replay("a", after_id=1)] == [3]
    assert bus.replay("missing") == []


def test_subscription_replays_then_follows() -> None:
    bus = EventBus()
    bus.publish("a", _started())
    sub = bus.subscribe("a")
    got = sub.get(timeout=1)
    assert got is not None and got.id == 1
    assert sub.get(timeout=0.05) is None

    def later() -> None:
        time.sleep(0.05)
        bus.publish("a", _text(1))

    threading.Thread(target=later).start()
    nxt = sub.get(timeout=2)
    assert nxt is not None and nxt.id == 2 and isinstance(nxt.event, AssistantText)


def test_subscription_after_id_skips_what_was_seen() -> None:
    bus = EventBus()
    for step in (1, 2, 3):
        bus.publish("a", _text(step))
    sub = bus.subscribe("a", after_id=2)
    got = sub.get(timeout=1)
    assert got is not None and got.id == 3
    assert sub.get(timeout=0.05) is None


def test_buffer_drops_the_oldest() -> None:
    bus = EventBus(buffer=2)
    for step in (1, 2, 3):
        bus.publish("a", _text(step))
    assert [p.id for p in bus.replay("a")] == [2, 3]
    sub = bus.subscribe("a")
    got = sub.get(timeout=1)
    assert got is not None and got.id == 2


def test_close_wakes_a_blocked_reader() -> None:
    bus = EventBus()
    sub = bus.subscribe("a")
    results: list[object] = []
    reader = threading.Thread(target=lambda: results.append(sub.get(timeout=5)))
    reader.start()
    time.sleep(0.05)
    started = time.monotonic()
    bus.close()
    reader.join(timeout=2)
    assert results == [None] and time.monotonic() - started < 1.5
    assert sub.closed
    other = bus.subscribe("a")
    other.close()
    other.close()
    assert other.get(timeout=0.01) is None
