"""Per-process application context shared by routes, agents and workers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from .bus import EventBus
from .config import Settings
from .jobs import JobStore

log = logging.getLogger(__name__)


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
    bench_results: list[dict[str, Any]] = field(default_factory=list)
    started_at: int = 0
    startup_error: str | None = None

    def __post_init__(self) -> None:
        if self.bus is None:
            self.bus = EventBus(self.hive)

    @property
    def llm_is_fake(self) -> bool:
        return getattr(self.llm, "backend", "") == "fake"

    def ensure_tenant(self, tenant: str) -> None:
        """Raise the contract's 404 when the tenant graph does not exist."""
        from .errors import ApiError

        if tenant not in self.hive.list_tenants():
            raise ApiError(404, "tenant_not_found", f"tenant {tenant!r} does not exist")


def get_ctx(request: Request) -> AppContext:
    """FastAPI dependency returning the context stored on ``app.state``."""
    return request.app.state.ctx
