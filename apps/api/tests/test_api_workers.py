"""Workers: Scheduler wakes on fact.superseded, hands off to FollowUp, which produces a ticket."""

from __future__ import annotations

import asyncio
import json

import pytest

from apps.api.agents.scheduler_agent import superseded_event_to_task
from apps.api.routes.board import SupersedeBody, demo_supersede
from apps.api.tests.conftest import make_ctx, seed
from apps.api.workers import WorkerPool


def test_superseded_event_normalisation():
    pipeline_shape = {"old_fact_id": "f1", "new_fact_id": "f2", "key": "upi flow|due", "subject": "UPI Flow", "predicate": "due", "new_object": "2026-09-28", "old_object": "2026-09-25", "episode_id": "ep1"}
    spec = superseded_event_to_task(pipeline_shape)
    assert spec["kind"] == "reschedule" and spec["requires"] == [] and spec["about_ids"] == ["f2", "f1"]
    assert spec["payload"]["due_at"] == "2026-09-28" and spec["payload"]["old_fact_id"] == "f1"
    hiveboard_shape = {"new_id": "f9", "old_ids": ["f8"], "key": "payu integration|due", "kind": "commitment", "object": "2026-10-02"}
    spec = superseded_event_to_task(hiveboard_shape)
    assert spec["payload"]["new_fact_id"] == "f9" and spec["payload"]["predicate"] == "due" and spec["payload"]["subject"] == "Payu Integration"
    assert superseded_event_to_task({"new_id": "f3", "old_ids": ["f2"], "key": "payment gateway|decided", "object": "PayU"}) is None


async def _wait_until(predicate, timeout=8.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.mark.asyncio
async def test_supersede_wakes_scheduler_and_followup_creates_issue(data_dir):
    ctx = make_ctx(data_dir, workers_enabled=True)
    seed(ctx, data_dir)
    ctx.bus.bind(asyncio.get_running_loop())
    pool = WorkerPool(ctx)
    ctx.workers = pool
    await pool.start(["orbit"])
    try:
        result = demo_supersede("orbit", SupersedeBody(new_object="2026-10-02", speaker_id="spk_priya"), ctx)
        new_id = result["new_fact_id"]

        def followup_done() -> bool:
            tasks = ctx.hive.list_tasks("orbit", status="completed", limit=50)
            return any(t["kind"] == "reschedule" and t["owner_agent"] == "followup_agent" for t in tasks)

        assert await _wait_until(followup_done), ctx.hive.list_tasks("orbit")
        task = next(t for t in ctx.hive.list_tasks("orbit", status="completed") if t["kind"] == "reschedule")
        assert new_id in task["about"]
        trace = ctx.hive.task_trace("orbit", task["id"])
        types = [e["type"] for e in trace["events"]]
        assert types.count("claimed") == 2 and "handed_off" in types and "artifact" in types
        handoff = next(e for e in trace["events"] if e["type"] == "handed_off")
        assert handoff["agent"] == "scheduler_agent" and handoff["to_agent"] == "followup_agent"
        assert new_id in handoff["subgraph_ids"]
        artifacts = [e["artifact"] for e in trace["events"] if e["type"] == "artifact"]
        issue = next(a for a in artifacts if a["kind"] == "github_issue")
        payload = json.loads(issue["text"])
        assert payload["simulated"] is True and "PayU Integration" in payload["title"]
        assert issue["uri"].startswith("https://github.com/")
        events = [e["event"] for e in ctx.hive.events["orbit"]]
        assert events.index("fact.superseded") < events.index("task.handed_off") < events.index("task.completed")
        agents = {a["id"]: a for a in ctx.hive.list_agents("orbit")}
        assert agents["scheduler_agent"]["state"] == "idle"
    finally:
        await pool.stop()


@pytest.mark.asyncio
async def test_worker_runs_skill_task_and_ignores_foreign_kinds(data_dir):
    ctx = make_ctx(data_dir, workers_enabled=True)
    seed(ctx, data_dir)
    ctx.bus.bind(asyncio.get_running_loop())
    pool = WorkerPool(ctx)
    ctx.workers = pool
    await pool.start(["orbit"])
    try:
        task_id = ctx.hive.submit_task("orbit", "run_skill", {"goal": "orbit standup"}, ["standup"], [], 4)
        foreign = ctx.hive.submit_task("orbit", "mystery", {}, [], [], 5)
        assert await _wait_until(lambda: (ctx.hive.get_task("orbit", task_id) or {}).get("status") == "completed")
        trace = ctx.hive.task_trace("orbit", task_id)
        assert any(e["type"] == "artifact" and e["artifact"]["kind"] == "standup_summary" for e in trace["events"])
        await asyncio.sleep(0.2)
        assert ctx.hive.get_task("orbit", foreign)["status"] == "submitted"
    finally:
        await pool.stop()


@pytest.mark.asyncio
async def test_failed_agent_marks_task_failed(data_dir):
    ctx = make_ctx(data_dir, workers_enabled=True)
    seed(ctx, data_dir)
    ctx.bus.bind(asyncio.get_running_loop())
    pool = WorkerPool(ctx)
    await pool.start(["orbit"])
    try:
        task_id = ctx.hive.submit_task("orbit", "extract_episode", {"episode_id": "ep_missing"}, ["extract"], [], 5)
        assert await _wait_until(lambda: (ctx.hive.get_task("orbit", task_id) or {}).get("status") == "failed")
        assert "not found" in ctx.hive.get_task("orbit", task_id)["failure_reason"]
        assert any(e["event"] == "task.failed" for e in ctx.hive.events["orbit"])
    finally:
        await pool.stop()

def test_fact_agent_reports_extraction_outage_as_failure(seeded):
    from apps.api.agents.fact_agent import FactAgent

    class UnavailableModel:
        backend = "unavailable"
        model = "unavailable"

        def complete_json(self, *args, **kwargs):
            raise RuntimeError("model unavailable")

    agent = FactAgent("orbit", seeded.hive, UnavailableModel(), seeded.embedder, seeded.settings)
    result = agent.run({"kind": "extract_episode", "payload": {"episode_id": "ep_mtg_orbit_001_001"}})
    assert result.failed is True
    assert "extract" in result.reason.lower()
    assert result.steps[0]["result"]["failed_episodes"] == ["ep_mtg_orbit_001_001"]

