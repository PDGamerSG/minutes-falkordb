"""The RealHive event pump keeps one long-lived subscription (finding 3.4): an event published during an idle
window of 3 s is delivered and the channel is subscribed exactly once."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any

from apps.api.hive_adapter import RealHive


class FakePubSub:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.messages: deque[dict[str, Any]] = deque()
        self.closed = False

    def subscribe(self, channel: str) -> None:
        self.log.append(f"subscribe:{channel}")

    def get_message(self, timeout: float = 0.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.messages:
                return self.messages.popleft()
            time.sleep(0.01)
        return None

    def close(self) -> None:
        self.closed = True
        self.log.append("close")


class FakeConnection:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.pubsubs: list[FakePubSub] = []

    def pubsub(self, ignore_subscribe_messages: bool = True) -> FakePubSub:
        ps = FakePubSub(self.log)
        self.pubsubs.append(ps)
        self.log.append("pubsub")
        return ps


class FakeDB:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def close(self) -> None:
        return None


def test_event_published_during_a_three_second_idle_window_is_delivered():
    db = FakeDB()
    hive = RealHive(db, rw_password="rw", ro_password="ro")
    received: list[dict[str, Any]] = []
    got = threading.Event()

    def listener(event: dict[str, Any]) -> None:
        received.append(event)
        got.set()

    hive.add_listener("orbit", listener)
    try:
        time.sleep(2.6)  # longer than the old 2 s idle_timeout that used to re-subscribe (and drop events)
        assert db.connection.pubsubs, "the pump did not subscribe"
        db.connection.pubsubs[0].messages.append({"type": "message", "data": json.dumps({"event": "fact.superseded", "payload": {"new_fact_id": "f2"}, "ts": 1})})
        assert got.wait(3.0), "event was not delivered"
        assert received[0]["event"] == "fact.superseded"
        assert db.connection.log.count("pubsub") == 1 and db.connection.log.count("subscribe:team_orbit:events") == 1
    finally:
        hive.close()
    thread = hive._subscriber_threads["orbit"]
    thread.join(timeout=3.0)
    assert not thread.is_alive() and db.connection.pubsubs[0].closed


def test_pump_resubscribes_after_a_connection_error():
    db = FakeDB()
    hive = RealHive(db, rw_password="rw", ro_password="ro")
    hive.add_listener("orbit", lambda event: None)
    try:
        deadline = time.monotonic() + 2.0
        while not db.connection.pubsubs and time.monotonic() < deadline:
            time.sleep(0.01)
        broken = db.connection.pubsubs[0]

        def explode(timeout: float = 0.0):
            raise ConnectionError("socket closed")

        broken.get_message = explode  # type: ignore[method-assign]
        deadline = time.monotonic() + 4.0
        while len(db.connection.pubsubs) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(db.connection.pubsubs) == 2 and broken.closed
    finally:
        hive.close()
