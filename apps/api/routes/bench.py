"""Bench: results from ``docs/bench/*.json`` (Stream A's harness) plus a small in-process run (admin only).

In-process results are kept in a bounded deque (last 100 runs)."""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from ingest.fakes import new_id, now_ms
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..state import AppContext, get_ctx

log = logging.getLogger(__name__)

router = APIRouter(tags=["bench"])

RESULT_KEYS = ("run_id", "ts", "engine", "target", "agents", "tenants", "duration_s", "read_p50", "read_p95", "read_p99", "write_p50", "write_p95", "write_p99", "errors", "cas")


class BenchRunBody(BaseModel):
    agents: int = Field(default=10, ge=1, le=200)
    tenants: int = Field(default=1, ge=1, le=20)
    duration_s: float = Field(default=5.0, ge=0.5, le=120.0)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return round(ordered[index], 3)


def _normalise(raw: dict[str, Any], source: str) -> dict[str, Any]:
    cas = raw.get("cas") or {}
    row = {
        "run_id": raw.get("run_id") or Path(source).stem,
        "ts": raw.get("ts") or raw.get("timestamp") or 0,
        "engine": str(raw.get("engine") or raw.get("version") or "unknown"),
        "target": raw.get("target") or "local",
        "agents": raw.get("agents") or raw.get("n_agents") or 0,
        "tenants": raw.get("tenants") or raw.get("n_tenants") or 0,
        "duration_s": raw.get("duration_s") or raw.get("duration") or 0,
        "read_p50": raw.get("read_p50") or (raw.get("read") or {}).get("p50") or 0,
        "read_p95": raw.get("read_p95") or (raw.get("read") or {}).get("p95") or 0,
        "read_p99": raw.get("read_p99") or (raw.get("read") or {}).get("p99") or 0,
        "write_p50": raw.get("write_p50") or (raw.get("write") or {}).get("p50") or 0,
        "write_p95": raw.get("write_p95") or (raw.get("write") or {}).get("p95") or 0,
        "write_p99": raw.get("write_p99") or (raw.get("write") or {}).get("p99") or 0,
        "errors": raw.get("errors") or 0,
        "cas": {"attempts": cas.get("attempts") or 0, "winners": cas.get("winners") or 0, "losers": cas.get("losers") or 0},
        "source": source,
    }
    for key, value in raw.items():
        if key not in row and key not in ("read", "write"):
            row[key] = value
    return row


def load_results(directory: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("bench file %s unreadable: %s", path, exc)
            continue
        items = data if isinstance(data, list) else [data]
        rows.extend(_normalise(item, str(path.name)) for item in items if isinstance(item, dict))
    return rows


@router.get("/bench/results")
def bench_results(ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    rows = load_results(ctx.settings.bench_path) + [dict(r) for r in ctx.bench_results]
    rows.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return rows


@router.post("/bench/run", status_code=202, dependencies=[Depends(require_admin)])
async def bench_run(body: BenchRunBody, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Admin: small in-process harness, N agent coroutines over M tenants, 80/20 read/write, plus a CAS race.
    Its tasks are tagged ``kind: bench*`` so ``GET /tasks`` hides them unless ``include_bench=true``."""
    run_id = new_id("bench")
    ctx.spawn(_run_bench(run_id, body, ctx))
    return {"run_id": run_id}


async def _run_bench(run_id: str, body: BenchRunBody, ctx: AppContext) -> None:
    hive = ctx.hive
    tenants = hive.list_tenants()[: body.tenants] or []
    if not tenants:
        ctx.bench_results.append({"run_id": run_id, "ts": now_ms(), "engine": hive.db_version(), "target": "local", "agents": body.agents, "tenants": 0, "duration_s": 0, "errors": 1, "cas": {"attempts": 0, "winners": 0, "losers": 0}, "note": "no tenants"})
        return
    reads: list[float] = []
    writes: list[float] = []
    errors = 0
    deadline = time.perf_counter() + body.duration_s
    for tenant in tenants:
        for i in range(body.agents):
            hive.register_agent(tenant, f"bench_agent_{i:03d}", f"Bench {i}", ["bench"], "none")

    async def agent(index: int) -> None:
        nonlocal errors
        tenant = tenants[index % len(tenants)]
        agent_id = f"bench_agent_{index:03d}"
        counter = 0
        while time.perf_counter() < deadline:
            counter += 1
            started = time.perf_counter()
            try:
                if counter % 5 == 0:
                    task_id = await asyncio.to_thread(hive.submit_task, tenant, "bench", {"i": counter}, ["bench"], [], 5)
                    version = await asyncio.to_thread(hive.claim, tenant, task_id, agent_id, 0)
                    if version is not None:
                        await asyncio.to_thread(hive.complete, tenant, task_id, agent_id, None)
                    writes.append((time.perf_counter() - started) * 1000)
                else:
                    await asyncio.to_thread(hive.list_tasks, tenant, "submitted", 10)
                    reads.append((time.perf_counter() - started) * 1000)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                log.debug("bench op failed: %s", exc)
            await asyncio.sleep(0)

    await asyncio.gather(*(agent(i) for i in range(body.agents)))
    tenant = tenants[0]
    cas_task = await asyncio.to_thread(hive.submit_task, tenant, "bench_cas", {}, ["bench"], [], 5)
    results = await asyncio.gather(*(asyncio.to_thread(hive.claim, tenant, cas_task, f"bench_agent_{i:03d}", 0) for i in range(min(body.agents, 50))), return_exceptions=True)
    winners = sum(1 for r in results if isinstance(r, int))
    ctx.bench_results.append(
        {
            "run_id": run_id,
            "ts": now_ms(),
            "engine": hive.db_version(),
            "target": "local",
            "agents": body.agents,
            "tenants": len(tenants),
            "duration_s": body.duration_s,
            "read_p50": _percentile(reads, 50),
            "read_p95": _percentile(reads, 95),
            "read_p99": _percentile(reads, 99),
            "write_p50": _percentile(writes, 50),
            "write_p95": _percentile(writes, 95),
            "write_p99": _percentile(writes, 99),
            "reads": len(reads),
            "writes": len(writes),
            "read_mean": round(statistics.fmean(reads), 3) if reads else 0.0,
            "errors": errors,
            "cas": {"attempts": len(results), "winners": winners, "losers": len(results) - winners},
            "source": "in-process",
        }
    )
