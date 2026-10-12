"""Per-process application context shared by routes, agents and workers."""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from .bus import EventBus
from .config import Settings
from .jobs import JobStore

log = logging.getLogger(__name__)

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")  # anything else cannot be a tenant (and must not reach the graph layer)


@dataclass
class AppContext:
    """Everything a request handler needs; built once in the lifespan (or by tests)."""

    settings: Settings
    hive: Any
    llm: Any
    embedder: Any
    jobs: JobStore = field(default_factory=JobStore)
    bus: EventBus | None = None
    workers: Any = None
    bench_results: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    started_at: int = 0
    startup_error: str | None = None
    embedding_mismatch: dict[str, dict[str, Any]] = field(default_factory=dict)
    background: set[Any] = field(default_factory=set, repr=False)  # strong references to fire-and-forget tasks

    def __post_init__(self) -> None:
        if self.bus is None:
            self.bus = EventBus(self.hive)
        if not isinstance(self.bench_results, deque):
            self.bench_results = deque(self.bench_results, maxlen=100)

    def spawn(self, coro: Any) -> Any:
        """``asyncio.create_task`` that keeps a strong reference until the task finishes (the loop only holds a weak one)."""
        import asyncio

        task = asyncio.create_task(coro)
        self.background.add(task)
        task.add_done_callback(self.background.discard)
        return task

    @property
    def llm_is_fake(self) -> bool:
        return getattr(self.llm, "backend", "") == "fake"

    def ensure_tenant(self, tenant: str) -> None:
        """Raise the contract's 404 when the tenant graph does not exist (or the slug cannot be one)."""
        from .errors import ApiError

        if getattr(self.hive, "kind", "") == "unavailable":
            raise ApiError(503, "database_unavailable", self.startup_error or "the database is not reachable yet; retrying in the background")
        if not _SLUG.match(tenant) or "__snap_" in tenant or tenant not in self.hive.list_tenants():
            raise ApiError(404, "tenant_not_found", f"tenant {tenant!r} does not exist")


def get_ctx(request: Request) -> AppContext:
    """FastAPI dependency returning the context stored on ``app.state``."""
    return request.app.state.ctx
