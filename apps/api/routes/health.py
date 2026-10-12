"""Health: database, model and embedder status.

``ok`` reflects the database and startup preparation. ``llm.reachable`` (a cheap probe, cached 60 s)
and ``workers.alive`` are reported but only take part in ``ok`` when ``STRICT_HEALTH=1``.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, Response

from ..auth import admin_mode
from ..state import AppContext, get_ctx

router = APIRouter(tags=["health"])

LLM_PROBE_TTL_S = 60.0
_probe_lock = threading.Lock()
_probe_cache: dict[int, tuple[float, bool | None, str | None]] = {}


def llm_reachable(llm: Any, *, ttl_s: float = LLM_PROBE_TTL_S, now: float | None = None) -> tuple[bool | None, str | None]:
    """``(reachable, error)``; None when the backend has no probe. Cached per client object for ``ttl_s``."""
    now = time.monotonic() if now is None else now
    key = id(llm)
    with _probe_lock:
        cached = _probe_cache.get(key)
        if cached and now - cached[0] < ttl_s:
            return cached[1], cached[2]
    if getattr(llm, "backend", "") == "fake":
        result: tuple[bool | None, str | None] = (True, None)
    else:
        probe = getattr(llm, "probe", None)
        if probe is None:
            result = (None, None)
        else:
            try:
                result = (bool(probe()), None)
            except Exception as exc:  # noqa: BLE001 - the probe's failure is the finding
                result = (False, f"{type(exc).__name__}: {str(exc)[:200]}")
    with _probe_lock:
        _probe_cache[key] = (now, result[0], result[1])
    return result


def reset_probe_cache() -> None:
    with _probe_lock:
        _probe_cache.clear()


@router.get("/health")
def health(response: Response, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ok = False
    graphs: list[str] = []
    version = "unknown"
    error: str | None = None
    try:
        ok = bool(ctx.hive.ping())
        graphs = [f"team_{t}" for t in ctx.hive.list_tenants()]
        version = ctx.hive.db_version()
    except Exception as exc:  # noqa: BLE001 - health must answer even when the DB is down
        ok = False
        error = f"{type(exc).__name__}: {exc}"[:300]
    if ctx.startup_error:
        ok = False
        error = ctx.startup_error
    reachable, llm_error = llm_reachable(ctx.llm) if ctx.llm is not None else (None, "not started")
    workers = ctx.workers
    expected = workers.expected() if workers is not None and hasattr(workers, "expected") else 0
    alive = workers.alive() if workers is not None and hasattr(workers, "alive") else 0
    workers_ok = workers is None or not ctx.settings.workers_enabled or alive == expected
    if ctx.settings.strict_health:
        if reachable is False:
            ok = False
            error = error or f"llm unreachable: {llm_error}"
        if not workers_ok:
            ok = False
            error = error or f"workers: {alive}/{expected} alive"
    if not ok:
        response.status_code = 503
    body: dict[str, Any] = {
        "ok": ok,
        "falkordb": {"version": version, "graphs": graphs, "kind": getattr(ctx.hive, "kind", "unknown")},
        "llm": {
            "backend": getattr(ctx.llm, "backend", "unknown"),
            "model": getattr(ctx.llm, "model", "unknown"),
            "native_tools": bool(getattr(ctx.llm, "native_tools", False)),
            "reachable": reachable,
            **({"error": llm_error} if llm_error else {}),
        },
        "embeddings": {"model": getattr(ctx.embedder, "model", "unknown"), "dim": getattr(ctx.embedder, "dim", 768), "backend": getattr(ctx.embedder, "name", "unknown")},
        "workers": {"alive": alive, "expected": expected, "enabled": bool(ctx.settings.workers_enabled), "agents": workers.status() if workers is not None else []},
        "auth": admin_mode(ctx),
        "env": ctx.settings.env,
        "started_at": ctx.started_at,
    }
    if ctx.embedding_mismatch:
        body["embedding_mismatch"] = ctx.embedding_mismatch
    if error:
        body["error"] = error
    return body
