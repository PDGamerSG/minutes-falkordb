"""Agent workers: one asyncio loop per (tenant, agent), plus one lease reaper per tenant.

Each worker subscribes to the tenant's events (through the EventBus), polls ``next_open_task`` (every
``WORKER_POLL_S``, default 15 s, and immediately on ``task.submitted``/``task.handed_off``), claims with
compare-and-set and a lease (``TASK_LEASE_MS``, default 120 s), heartbeats the lease every
``WORKER_HEARTBEAT_S`` while the agent runs in a thread, and completes or fails the task.

The Scheduler reacts to ``fact.superseded`` for date-like predicates by submitting a ``reschedule`` task
addressed to itself with ``requires: ["schedule"]`` (only the Scheduler has that capability, so the
claim is deterministic) and claims it right away; it then hands off to the FollowUp agent, which owns the
task from there. Supersessions whose new ``valid_from`` is older than ``LIVE_EVENT_MAX_AGE_DAYS`` are
historical imports and do not wake anyone unless the payload says ``live: true``.

The reaper calls ``reap_expired`` every ``REAPER_INTERVAL_S``: a task whose worker died mid-run returns to
``submitted`` (the trace shows ``lease_expired``) and the tenant's workers are woken.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from collections import deque
from typing import Any

from .agents import build_agents
from .agents.base import AgentResult, BaseAgent
from .agents.scheduler_agent import superseded_event_to_task
from .hive_adapter import HiveNotFound, register_default_agents

log = logging.getLogger(__name__)

WAKE_EVENTS = ("task.submitted", "task.handed_off", "task.lease_expired")


class AgentWorker:
    """Runs one agent for one tenant until stopped."""

    def __init__(
        self,
        tenant: str,
        agent: BaseAgent,
        ctx: Any,
        *,
        poll_s: float = 15.0,
        touch_s: float = 30.0,
        heartbeat_s: float = 30.0,
        lease_ms: int = 120_000,
    ) -> None:
        self.tenant = tenant
        self.agent = agent
        self.ctx = ctx
        self.poll_s = poll_s
        self.touch_s = touch_s
        self.heartbeat_s = heartbeat_s
        self.lease_ms = int(lease_ms)
        self.wake = asyncio.Event()
        self.stopped = asyncio.Event()
        self.processed: deque[dict[str, Any]] = deque(maxlen=200)
        self.queue: asyncio.Queue[dict[str, Any]] | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._last_touch = 0.0
        self.skipped_historical = 0

    def subscribe(self) -> None:
        """Attach to the tenant's event stream now (before the loop schedules ``run``), so no event is missed."""
        if self.queue is None:
            self.queue = self.ctx.bus.attach(self.tenant)

    # -- events --------------------------------------------------------------------------------
    async def _listen(self) -> None:
        self.subscribe()
        queue = self.queue
        assert queue is not None
        try:
            while not self.stopped.is_set():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    continue
                try:
                    await self.on_event(event)
                except Exception as exc:  # noqa: BLE001 - one bad event must not kill the listener
                    log.exception("worker %s/%s event handling failed: %s", self.tenant, self.agent.agent_id, exc)
        finally:
            self.ctx.bus.detach(self.tenant, queue)

    async def on_event(self, event: dict[str, Any]) -> None:
        name = event.get("event", "")
        payload = event.get("payload") or {}
        if name in WAKE_EVENTS:
            self.wake.set()
        if name == "fact.superseded" and "fact.superseded" in getattr(self.agent, "wake_on", ()):
            if payload.get("head_changed") is False:
                return
            spec = await asyncio.to_thread(self._spec_for, payload)
            if spec is None:
                return
            await asyncio.to_thread(self._submit_and_claim, spec)
            self.wake.set()

    def _spec_for(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Normalise the event; look the new fact up when the payload does not say when it became valid."""
        enriched = dict(payload)
        if enriched.get("valid_from") is None and not enriched.get("live"):
            fact_id = enriched.get("new_fact_id") or enriched.get("new_id")
            if fact_id:
                try:
                    fact = self.ctx.hive.get_fact(self.tenant, fact_id) or {}
                except Exception as exc:  # noqa: BLE001
                    log.debug("get_fact(%s) for age check failed: %s", fact_id, exc)
                    fact = {}
                if fact.get("valid_from") is not None:
                    enriched["valid_from"] = fact["valid_from"]
        spec = superseded_event_to_task(enriched, max_age_days=self.ctx.settings.live_event_max_age_days)
        if spec is None and enriched.get("valid_from") is not None:
            self.skipped_historical += 1
        return spec

    def _submit_and_claim(self, spec: dict[str, Any]) -> None:
        hive = self.ctx.hive
        task_id = hive.submit_task(
            self.tenant, spec["kind"], spec["payload"], spec["requires"], spec["about_ids"], spec.get("priority", 5), owner_agent=self.agent.agent_id
        )
        version = hive.claim(self.tenant, task_id, self.agent.agent_id, 0, lease_ms=self.lease_ms)
        if version is None:
            # Our own poll loop already took it (same agent): nothing lost, it runs there.
            log.info("%s did not win the first claim on its own wake-up task %s; the poll loop has it", self.agent.agent_id, task_id)
            return
        task = hive.get_task(self.tenant, task_id) or {"id": task_id, "kind": spec["kind"], "payload": spec["payload"], "about": spec["about_ids"]}
        task["version"] = version
        self._run_claimed(task)

    # -- polling -------------------------------------------------------------------------------
    async def run(self) -> None:
        self._listener_task = asyncio.create_task(self._listen(), name=f"listen-{self.tenant}-{self.agent.agent_id}")
        try:
            while not self.stopped.is_set():
                try:
                    await asyncio.to_thread(self.poll_once)
                except Exception as exc:
                    log.exception("worker %s/%s poll failed: %s", self.tenant, self.agent.agent_id, exc)
                self.wake.clear()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.wake.wait(), timeout=self.poll_s)
        finally:
            if self._listener_task:
                self._listener_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._listener_task

    def _touch(self) -> None:
        """Agent.last_seen is written at most every ``touch_s`` seconds (finding 3.6)."""
        now = time.monotonic()
        if now - self._last_touch < self.touch_s:
            return
        self._last_touch = now
        try:
            self.ctx.hive.touch_agent(self.tenant, self.agent.agent_id)
        except Exception as exc:  # noqa: BLE001
            log.debug("touch_agent failed: %s", exc)

    def poll_once(self) -> bool:
        """Claim and run at most one task; returns True when a task was processed."""
        hive = self.ctx.hive
        self._touch()
        task = self._pick_task()
        if task is None:
            return False
        version = hive.claim(self.tenant, task["id"], self.agent.agent_id, int(task.get("version", 0)), lease_ms=self.lease_ms)
        if version is None:
            return False
        task["version"] = version
        self._run_claimed(task)
        return True

    def _mine(self, task: dict[str, Any]) -> bool:
        """A task this worker should claim: addressed to it, or unaddressed with a kind it handles and the capabilities."""
        if task.get("status", "submitted") != "submitted":
            return False
        owner = task.get("owner_agent")
        if owner == self.agent.agent_id:
            return True
        if owner is not None:
            return False
        if not set(task.get("requires") or []) <= set(self.agent.capabilities):
            return False
        return task.get("kind") in self.agent.handles

    def _pick_task(self) -> dict[str, Any] | None:
        """``next_open_task`` first; otherwise (or when the best open task is for another agent) scan the backlog.
        The scan matters in two cases: one unhandled task must not block every worker, and a task addressed to this
        agent by a hand-off may still ``require`` a capability the agent lacks (the Scheduler's ``schedule``), which
        ``next_open_task`` filters out. Highest priority first, then oldest."""
        hive = self.ctx.hive
        candidate = hive.next_open_task(self.tenant, self.agent.agent_id)
        if candidate is not None and self._mine(candidate):
            return candidate
        backlog = [t for t in reversed(hive.list_tasks(self.tenant, status="submitted", limit=50)) if self._mine(t)]
        if not backlog:
            return None
        return max(backlog, key=lambda t: int(t.get("priority") or 0)) if len({int(t.get("priority") or 0) for t in backlog}) > 1 else backlog[0]

    def _heartbeat_loop(self, task_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_s):
            try:
                if not self.ctx.hive.heartbeat(self.tenant, task_id, self.agent.agent_id, lease_ms=self.lease_ms):
                    log.warning("%s lost the lease on %s while running it", self.agent.agent_id, task_id)
                    return
            except Exception as exc:  # noqa: BLE001
                log.debug("heartbeat failed: %s", exc)

    def _run_claimed(self, task: dict[str, Any]) -> None:
        hive = self.ctx.hive
        stop = threading.Event()
        beat = threading.Thread(target=self._heartbeat_loop, args=(task["id"], stop), name=f"lease-{task['id']}", daemon=True)
        beat.start()
        try:
            try:
                result = self.agent.run(task)
            except Exception as exc:
                log.exception("agent %s crashed on %s", self.agent.agent_id, task["id"])
                result = AgentResult(failed=True, reason=f"{type(exc).__name__}: {exc}"[:500])
        finally:
            stop.set()
        self.processed.append({"task_id": task["id"], **result.as_dict()})
        if result.handed_off:
            return
        try:
            if result.failed:
                hive.fail(self.tenant, task["id"], self.agent.agent_id, result.reason or "unknown failure")
            else:
                artifact = result.artifact or {"kind": "summary", "text": result.final or ""}
                if result.used_skill_id and isinstance(artifact, dict):
                    artifact = {**artifact, "text": artifact.get("text") or result.final or ""}
                hive.complete(self.tenant, task["id"], self.agent.agent_id, _artifact_for_store(artifact))
        except HiveNotFound as exc:
            log.warning("could not close task %s (lease lost or state changed): %s", task["id"], exc)

    def stop(self) -> None:
        self.stopped.set()
        self.wake.set()


def _artifact_for_store(artifact: dict[str, Any]) -> dict[str, Any]:
    """hiveboard stores {id, kind, uri, text}; fold the extra keys into text when they are not strings."""
    text = artifact.get("text")
    extras = {k: v for k, v in artifact.items() if k not in {"id", "kind", "uri", "text"}}
    if extras and (text is None or isinstance(text, str)):
        try:
            payload = json.loads(text) if text and text.strip().startswith("{") else {"text": text}
        except json.JSONDecodeError:
            payload = {"text": text}
        if isinstance(payload, dict):
            payload.update(extras)
            text = json.dumps(payload, default=str)
    return {"id": artifact.get("id"), "kind": artifact.get("kind"), "uri": artifact.get("uri"), "text": text}


class LeaseReaper:
    """Per tenant: every ``interval_s`` return expired leases to ``submitted`` and wake the tenant's workers."""

    def __init__(self, tenant: str, ctx: Any, workers: list[AgentWorker], *, interval_s: float) -> None:
        self.tenant = tenant
        self.ctx = ctx
        self.workers = workers
        self.interval_s = interval_s
        self.stopped = asyncio.Event()
        self.reaped: deque[str] = deque(maxlen=200)

    async def run(self) -> None:
        while not self.stopped.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.stopped.wait(), timeout=self.interval_s)
            if self.stopped.is_set():
                return
            await self.reap_once()

    async def reap_once(self) -> list[str]:
        try:
            expired = list(await asyncio.to_thread(self.ctx.hive.reap_expired, self.tenant))
        except Exception as exc:  # noqa: BLE001
            log.warning("reap_expired(%s) failed: %s", self.tenant, exc)
            return []
        if expired:
            log.warning("tenant %s: %d task lease(s) expired and returned to submitted: %s", self.tenant, len(expired), expired)
            self.reaped.extend(expired)
            for worker in self.workers:
                worker.wake.set()
        return expired

    def stop(self) -> None:
        self.stopped.set()


class WorkerPool:
    """Starts and stops the workers (and the lease reaper) of every tenant."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.workers: dict[tuple[str, str], AgentWorker] = {}
        self.reapers: dict[str, LeaseReaper] = {}
        self._tasks: dict[str, list[asyncio.Task[None]]] = {}

    def agents_for(self, tenant: str) -> dict[str, BaseAgent]:
        ctx = self.ctx
        return build_agents(tenant, ctx.hive, ctx.llm, ctx.embedder, ctx.settings)

    async def start_tenant(self, tenant: str) -> None:
        if tenant in self._tasks:
            return
        settings = self.ctx.settings
        register_default_agents(self.ctx.hive, tenant, getattr(self.ctx.llm, "model", "fake"))
        tasks: list[asyncio.Task[None]] = []
        started: list[AgentWorker] = []
        for agent_id, agent in self.agents_for(tenant).items():
            worker = AgentWorker(
                tenant,
                agent,
                self.ctx,
                poll_s=settings.worker_poll_s,
                touch_s=getattr(settings, "worker_touch_s", 30.0),
                heartbeat_s=getattr(settings, "worker_heartbeat_s", 30.0),
                lease_ms=getattr(settings, "task_lease_ms", 120_000),
            )
            worker.subscribe()
            self.workers[(tenant, agent_id)] = worker
            started.append(worker)
            tasks.append(asyncio.create_task(worker.run(), name=f"worker-{tenant}-{agent_id}"))
        reaper = LeaseReaper(tenant, self.ctx, started, interval_s=getattr(settings, "reaper_interval_s", 30.0))
        self.reapers[tenant] = reaper
        tasks.append(asyncio.create_task(reaper.run(), name=f"reaper-{tenant}"))
        self._tasks[tenant] = tasks
        log.info("started %d workers and a lease reaper for tenant %s", len(started), tenant)

    async def start(self, tenants: list[str]) -> None:
        for tenant in tenants:
            await self.start_tenant(tenant)

    async def stop_tenant(self, tenant: str) -> None:
        tasks = self._tasks.pop(tenant, [])
        for key in [k for k in self.workers if k[0] == tenant]:
            self.workers.pop(key).stop()
        reaper = self.reapers.pop(tenant, None)
        if reaper is not None:
            reaper.stop()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def stop(self) -> None:
        for tenant in list(self._tasks):
            await self.stop_tenant(tenant)

    def alive(self) -> int:
        """Worker coroutines still running (a crashed one is a health signal)."""
        return sum(1 for tasks in self._tasks.values() for t in tasks if not t.done())

    def expected(self) -> int:
        return sum(len(tasks) for tasks in self._tasks.values())

    def status(self) -> list[dict[str, Any]]:
        return [
            {"tenant": t, "agent": a, "processed": len(w.processed), "skipped_historical": w.skipped_historical, "stopped": w.stopped.is_set()}
            for (t, a), w in self.workers.items()
        ]
