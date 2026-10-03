"""Agent workers: one asyncio loop per (tenant, agent).

Each worker subscribes to the tenant's events (through the EventBus), polls ``next_open_task``,
claims with compare-and-set, runs the agent in a thread and completes or fails the task.
The Scheduler additionally reacts to ``fact.superseded`` for date-like predicates by submitting a
``reschedule`` task that it claims right away; the Standup worker learns a Skill once two meetings
share a title prefix (triggered by ``learn_standup`` tasks submitted after imports).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from .agents import build_agents
from .agents.base import AgentResult, BaseAgent
from .agents.scheduler_agent import superseded_event_to_task
from .hive_adapter import HiveNotFound, register_default_agents

log = logging.getLogger(__name__)


class AgentWorker:
    """Runs one agent for one tenant until stopped."""

    def __init__(self, tenant: str, agent: BaseAgent, ctx: Any, *, poll_s: float = 2.0) -> None:
        self.tenant = tenant
        self.agent = agent
        self.ctx = ctx
        self.poll_s = poll_s
        self.wake = asyncio.Event()
        self.stopped = asyncio.Event()
        self.processed: list[dict[str, Any]] = []
        self.queue: asyncio.Queue[dict[str, Any]] | None = None
        self._listener_task: asyncio.Task[None] | None = None

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
                await self.on_event(event)
        finally:
            self.ctx.bus.detach(self.tenant, queue)

    async def on_event(self, event: dict[str, Any]) -> None:
        name = event.get("event", "")
        payload = event.get("payload") or {}
        if name in ("task.submitted", "task.handed_off"):
            self.wake.set()
        if name == "fact.superseded" and "fact.superseded" in getattr(self.agent, "wake_on", ()):
            if payload.get("head_changed") is False:
                return
            spec = superseded_event_to_task(payload)
            if spec is None:
                return
            await asyncio.to_thread(self._submit_and_claim, spec)
            self.wake.set()

    def _submit_and_claim(self, spec: dict[str, Any]) -> None:
        hive = self.ctx.hive
        task_id = hive.submit_task(self.tenant, spec["kind"], spec["payload"], spec["requires"], spec["about_ids"], spec.get("priority", 5))
        version = hive.claim(self.tenant, task_id, self.agent.agent_id, 0)
        if version is None:
            log.info("%s lost the claim on its own wake-up task %s", self.agent.agent_id, task_id)
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

    def poll_once(self) -> bool:
        """Claim and run at most one task; returns True when a task was processed."""
        hive = self.ctx.hive
        try:
            hive.touch_agent(self.tenant, self.agent.agent_id)
        except Exception as exc:  # noqa: BLE001
            log.debug("touch_agent failed: %s", exc)
        task = self._pick_task()
        if task is None:
            return False
        version = hive.claim(self.tenant, task["id"], self.agent.agent_id, int(task.get("version", 0)))
        if version is None:
            return False
        task["version"] = version
        self._run_claimed(task)
        return True

    def _mine(self, task: dict[str, Any]) -> bool:
        """A task this worker should claim: a kind it handles (or addressed to it), capabilities satisfied."""
        if task.get("status", "submitted") != "submitted":
            return False
        owner = task.get("owner_agent")
        if owner not in (None, self.agent.agent_id):
            return False
        if not set(task.get("requires") or []) <= set(self.agent.capabilities):
            return False
        return task.get("kind") in self.agent.handles or owner == self.agent.agent_id

    def _pick_task(self) -> dict[str, Any] | None:
        """``next_open_task`` first; when the oldest open task is for another agent, scan the backlog
        so one unhandled task cannot block every worker."""
        hive = self.ctx.hive
        candidate = hive.next_open_task(self.tenant, self.agent.agent_id)
        if candidate is None:
            return None
        if self._mine(candidate):
            return candidate
        for task in reversed(hive.list_tasks(self.tenant, status="submitted", limit=50)):
            if self._mine(task):
                return task
        return None

    def _run_claimed(self, task: dict[str, Any]) -> None:
        hive = self.ctx.hive
        try:
            result = self.agent.run(task)
        except Exception as exc:
            log.exception("agent %s crashed on %s", self.agent.agent_id, task["id"])
            result = AgentResult(failed=True, reason=f"{type(exc).__name__}: {exc}"[:500])
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
            log.warning("could not close task %s: %s", task["id"], exc)

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


class WorkerPool:
    """Starts and stops the workers of every tenant."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.workers: dict[tuple[str, str], AgentWorker] = {}
        self._tasks: list[asyncio.Task[None]] = []

    def agents_for(self, tenant: str) -> dict[str, BaseAgent]:
        ctx = self.ctx
        return build_agents(tenant, ctx.hive, ctx.llm, ctx.embedder, ctx.settings)

    async def start_tenant(self, tenant: str) -> None:
        if any(t == tenant for t, _ in self.workers):
            return
        register_default_agents(self.ctx.hive, tenant, getattr(self.ctx.llm, "model", "fake"))
        for agent_id, agent in self.agents_for(tenant).items():
            worker = AgentWorker(tenant, agent, self.ctx, poll_s=self.ctx.settings.worker_poll_s)
            worker.subscribe()
            self.workers[(tenant, agent_id)] = worker
            self._tasks.append(asyncio.create_task(worker.run(), name=f"worker-{tenant}-{agent_id}"))
        log.info("started %d workers for tenant %s", len(self.agents_for(tenant)), tenant)

    async def start(self, tenants: list[str]) -> None:
        for tenant in tenants:
            await self.start_tenant(tenant)

    async def stop(self) -> None:
        for worker in self.workers.values():
            worker.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        self.workers.clear()

    def status(self) -> list[dict[str, Any]]:
        return [{"tenant": t, "agent": a, "processed": len(w.processed), "stopped": w.stopped.is_set()} for (t, a), w in self.workers.items()]
