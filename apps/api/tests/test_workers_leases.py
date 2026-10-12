"""Leases, heartbeats and the reaper (finding 3.1), deterministic Scheduler claim (3.3), historical
supersessions ignored (3.2), throttled touch_agent (3.6), bounded processed list (3.7)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from apps.api.agents.base import AgentResult, BaseAgent
from apps.api.routes.board import SupersedeBody, demo_supersede
from apps.api.tests.conftest import make_ctx, seed
from apps.api import workers as workers_module
from apps.api.workers import AgentWorker, WorkerPool


async def _wait_until(predicate, timeout=8.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


class SlowAgent(BaseAgent):
    agent_id = "slow_agent"
    name = "SlowAgent"
    capabilities = ["slow"]
    handles = ("slow",)
    delays: list[float] = []

    def run(self, task: dict[str, Any]) -> AgentResult:
        delay = self.delays.pop(0) if self.delays else 0.0
        time.sleep(delay)
        return AgentResult(final="done", artifact={"kind": "summary", "text": "slow work"})


def _slow_pool(ctx: Any, monkeypatch: pytest.MonkeyPatch, delays: list[float]) -> WorkerPool:
    SlowAgent.delays = list(delays)
    monkeypatch.setattr(workers_module, "build_agents", lambda tenant, hive, llm, embedder, settings: {"slow_agent": SlowAgent(tenant, hive, llm, embedder, settings)})
    ctx.hive.register_agent("orbit", "slow_agent", "SlowAgent", ["slow"], "fake")
    return WorkerPool(ctx)


@pytest.mark.asyncio
async def test_expired_lease_is_reaped_and_the_task_runs_again(data_dir, monkeypatch):
    ctx = make_ctx(data_dir, workers_enabled=True, task_lease_ms=120, worker_heartbeat_s=30.0, reaper_interval_s=0.05)
    ctx.bus.bind(asyncio.get_running_loop())
    pool = _slow_pool(ctx, monkeypatch, delays=[0.6, 0.0])
    await pool.start(["orbit"])
    try:
        task_id = ctx.hive.submit_task("orbit", "slow", {}, ["slow"], [], 5)
        assert await _wait_until(lambda: (ctx.hive.get_task("orbit", task_id) or {}).get("status") == "working")
        assert await _wait_until(lambda: task_id in pool.reapers["orbit"].reaped, timeout=3.0)
        requeued = ctx.hive.get_task("orbit", task_id)
        assert requeued["status"] in ("submitted", "working", "completed") and requeued["version"] >= 2
        assert await _wait_until(lambda: (ctx.hive.get_task("orbit", task_id) or {}).get("status") == "completed", timeout=5.0)
        types = [e["type"] for e in ctx.hive.task_trace("orbit", task_id)["events"]]
        assert types == ["claimed", "lease_expired", "claimed", "artifact", "completed"], types
        events = [e["event"] for e in ctx.hive.events["orbit"]]
        assert "task.lease_expired" in events and events.count("task.claimed") == 2
    finally:
        await pool.stop()


@pytest.mark.asyncio
async def test_heartbeat_keeps_a_long_task_alive(data_dir, monkeypatch):
    ctx = make_ctx(data_dir, workers_enabled=True, task_lease_ms=150, worker_heartbeat_s=0.03, reaper_interval_s=0.05)
    ctx.bus.bind(asyncio.get_running_loop())
    pool = _slow_pool(ctx, monkeypatch, delays=[0.5])
    await pool.start(["orbit"])
    try:
        task_id = ctx.hive.submit_task("orbit", "slow", {}, ["slow"], [], 5)
        assert await _wait_until(lambda: (ctx.hive.get_task("orbit", task_id) or {}).get("status") == "completed", timeout=5.0)
        types = [e["type"] for e in ctx.hive.task_trace("orbit", task_id)["events"]]
        assert types == ["claimed", "artifact", "completed"] and not pool.reapers["orbit"].reaped
    finally:
        await pool.stop()


def test_fakehive_lease_primitives(ctx):
    hive = ctx.hive
    task_id = hive.submit_task("orbit", "followup", {}, ["followup"], [], 5)
    assert hive.claim("orbit", task_id, "followup_agent", 0, lease_ms=50) == 1
    assert hive.get_task("orbit", task_id)["lease_until"] > 0
    assert hive.heartbeat("orbit", task_id, "followup_agent", lease_ms=50) is True
    assert hive.heartbeat("orbit", task_id, "scheduler_agent") is False
    assert hive.reap_expired("orbit", now=hive.get_task("orbit", task_id)["lease_until"] - 1) == []
    assert hive.reap_expired("orbit", now=hive.get_task("orbit", task_id)["lease_until"] + 1) == [task_id]
    task = hive.get_task("orbit", task_id)
    assert task["status"] == "submitted" and task["owner_agent"] is None and task["version"] == 2 and task["lease_until"] is None
    assert hive.heartbeat("orbit", task_id, "followup_agent") is False
    with pytest.raises(Exception):
        hive.complete("orbit", task_id, "followup_agent", None)  # the lease is gone; completing is refused
    assert hive.claim("orbit", task_id, "scheduler_agent", 2) == 3
    assert [e["type"] for e in hive.task_trace("orbit", task_id)["events"]] == ["claimed", "lease_expired", "claimed"]


@pytest.mark.asyncio
async def test_scheduler_claim_is_deterministic_over_twenty_runs(data_dir):
    """The reschedule task requires `schedule`, so only the Scheduler claims it; FollowUp only ever receives a hand-off."""
    for run in range(20):
        ctx = make_ctx(data_dir, workers_enabled=True)
        seed(ctx, data_dir)
        ctx.bus.bind(asyncio.get_running_loop())
        pool = WorkerPool(ctx)
        ctx.workers = pool
        await pool.start(["orbit"])
        try:
            demo_supersede("orbit", SupersedeBody(new_object="2026-10-02", speaker_id="spk_priya"), ctx)

            def done() -> bool:
                return any(t["kind"] == "reschedule" and t["status"] == "completed" for t in ctx.hive.list_tasks("orbit", limit=50))

            assert await _wait_until(done), f"run {run}: {ctx.hive.list_tasks('orbit')}"
            tasks = [t for t in ctx.hive.list_tasks("orbit", limit=50) if t["kind"] == "reschedule"]
            assert len(tasks) == 1 and tasks[0]["requires"] == ["schedule"], f"run {run}"
            trace = ctx.hive.task_trace("orbit", tasks[0]["id"])
            events = [(e["type"], e.get("agent")) for e in trace["events"]]
            assert events == [
                ("claimed", "scheduler_agent"),
                ("handed_off", "scheduler_agent"),
                ("claimed", "followup_agent"),
                ("artifact", None),
                ("completed", "followup_agent"),
            ], f"run {run}: {events}"
        finally:
            await pool.stop()


@pytest.mark.asyncio
async def test_historical_supersessions_do_not_wake_the_scheduler(data_dir):
    ctx = make_ctx(data_dir, workers_enabled=True, live_event_max_age_days=14)
    seed(ctx, data_dir)
    ctx.bus.bind(asyncio.get_running_loop())
    pool = WorkerPool(ctx)
    await pool.start(["orbit"])
    try:
        old = int(time.time() * 1000) - 40 * 86_400_000
        payload = {"old_fact_id": "f1", "new_fact_id": "f2", "key": "upi flow|due", "subject": "UPI flow", "predicate": "due", "old_object": "2026-08-01", "new_object": "2026-08-05", "valid_from": old, "head_changed": True}
        ctx.hive.publish("orbit", "fact.superseded", payload)
        scheduler = pool.workers[("orbit", "scheduler_agent")]
        assert await _wait_until(lambda: scheduler.skipped_historical == 1, timeout=3.0)
        assert not [t for t in ctx.hive.list_tasks("orbit", limit=50) if t["kind"] == "reschedule"]
        # the same event flagged live (the demo button) does wake it
        ctx.hive.publish("orbit", "fact.superseded", {**payload, "live": True, "new_fact_id": "f3"})
        assert await _wait_until(lambda: any(t["kind"] == "reschedule" for t in ctx.hive.list_tasks("orbit", limit=50)), timeout=3.0)
        # an event without valid_from is looked up on the fact: a seeded (September) fact is historical
        head = next(f for f in ctx.hive.list_facts("orbit", status="active") if f["predicate"] == "due")
        ctx.hive.publish("orbit", "fact.superseded", {"new_fact_id": head["id"], "old_fact_id": "f0", "key": head["key"], "predicate": "due", "new_object": head["object"], "head_changed": True})
        assert await _wait_until(lambda: scheduler.skipped_historical == 2, timeout=3.0)
    finally:
        await pool.stop()


def test_touch_agent_is_throttled_and_processed_is_bounded(seeded):
    worker = AgentWorker("orbit", BaseAgent("orbit", seeded.hive, seeded.llm, seeded.embedder, seeded.settings), seeded, touch_s=30.0)
    worker.agent.agent_id = "answer_agent"
    before = seeded.hive.list_agents("orbit")
    first = next(a for a in before if a["id"] == "answer_agent")["last_seen"]
    worker._touch()
    time.sleep(0.01)
    touched = next(a for a in seeded.hive.list_agents("orbit") if a["id"] == "answer_agent")["last_seen"]
    worker._touch()
    again = next(a for a in seeded.hive.list_agents("orbit") if a["id"] == "answer_agent")["last_seen"]
    assert touched >= first and again == touched  # the second call within 30 s writes nothing
    assert worker.processed.maxlen == 200
