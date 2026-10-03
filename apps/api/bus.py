"""Event fan-out: one hive subscription per tenant, many asyncio consumers (SSE clients, workers)."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from typing import Any

log = logging.getLogger(__name__)


class EventBus:
    """Attach queues to a tenant's event stream; the hive's listener pushes into every queue.

    Works with both hives: ``FakeHive.publish`` calls listeners synchronously (any thread) and
    ``RealHive`` pumps Redis pub/sub messages from a background thread; both land on the loop
    through ``call_soon_threadsafe``.
    """

    def __init__(self, hive: Any, *, replay: int = 200) -> None:
        self.hive = hive
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
        self._listeners: dict[str, Any] = {}
        self._history: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=replay))
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _ensure_listener(self, tenant: str) -> None:
        if tenant in self._listeners:
            return

        def listener(event: dict[str, Any]) -> None:
            self._history[tenant].append(event)
            loop = self._loop
            if loop is None or loop.is_closed():
                for queue in list(self._queues.get(tenant, [])):
                    queue.put_nowait(event)
                return
            loop.call_soon_threadsafe(self._dispatch, tenant, event)

        self._listeners[tenant] = listener
        self.hive.add_listener(tenant, listener)

    def _dispatch(self, tenant: str, event: dict[str, Any]) -> None:
        for queue in list(self._queues.get(tenant, [])):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("event queue full for %s; dropping %s", tenant, event.get("event"))

    def attach(self, tenant: str, *, replay: int = 0) -> asyncio.Queue[dict[str, Any]]:
        """New consumer queue; ``replay`` pre-fills it with the last N events seen by this process."""
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = None
        self._ensure_listener(tenant)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        if replay:
            for event in list(self._history[tenant])[-replay:]:
                queue.put_nowait(event)
        self._queues[tenant].append(queue)
        return queue

    def detach(self, tenant: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if queue in self._queues.get(tenant, []):
            self._queues[tenant].remove(queue)

    def recent(self, tenant: str, n: int = 50) -> list[dict[str, Any]]:
        self._ensure_listener(tenant)
        return list(self._history[tenant])[-n:]

    def close(self) -> None:
        for tenant, listener in self._listeners.items():
            try:
                self.hive.remove_listener(tenant, listener)
            except Exception as exc:  # noqa: BLE001
                log.debug("remove_listener failed: %s", exc)
        self._listeners.clear()
        self._queues.clear()
