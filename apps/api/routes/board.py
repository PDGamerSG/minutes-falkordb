"""Board: agents, tasks, traces, demo buttons and the SSE event stream."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from ingest.dates import date_to_ms, normalize_date
from ingest.fakes import now_ms
from ingest.models import fact_key
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..errors import ApiError
from ..state import AppContext, get_ctx

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/{tenant}", tags=["board"])

DEMO_SUPERSEDE_KEY = fact_key("PayU integration", "due")
DEMO_CLAIMERS = 25


class TaskCreate(BaseModel):
    kind: str = Field(min_length=2, max_length=60)
    payload: dict[str, Any] = Field(default_factory=dict)
    requires: list[str] = Field(default_factory=list)
    about_ids: list[str] = Field(default_factory=list)
    priority: int = Field(default=5, ge=1, le=10)


class SupersedeBody(BaseModel):
    fact_id: str | None = None
    new_object: str = Field(min_length=1, max_length=200)
    speaker_id: str | None = None


class DoubleClaimBody(BaseModel):
    task_id: str | None = None


def task_view(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task.get("id"),
        "kind": task.get("kind"),
        "status": task.get("status"),
        "version": task.get("version", 0),
        "owner_agent": task.get("owner_agent"),
        "priority": task.get("priority", 5),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "payload": task.get("payload") or {},
        "about": task.get("about") or [],
        "requires": task.get("requires") or [],
        "failure_reason": task.get("failure_reason"),
        "question": task.get("question"),
    }


def agent_view(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": agent.get("id"),
        "name": agent.get("name"),
        "model": agent.get("model"),
        "capabilities": agent.get("capabilities") or [],
        "last_seen": agent.get("last_seen"),
        "state": agent.get("state") or "idle",
    }


def _artifact_view(artifact: dict[str, Any] | None) -> dict[str, Any] | None:
    if not artifact:
        return None
    out = {"id": artifact.get("id"), "kind": artifact.get("kind"), "uri": artifact.get("uri"), "text": artifact.get("text")}
    text = artifact.get("text")
    if isinstance(text, str) and text.strip().startswith("{"):
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                for key in ("title", "simulated", "body", "skill_id"):
                    if key in payload:
                        out[key] = payload[key]
                # hiveboard stores extra artifact fields as a JSON envelope in `text`; unwrap the human-readable text.
                if isinstance(payload.get("text"), str):
                    out["text"] = payload["text"]
                if payload.get("uri") and not out.get("uri"):
                    out["uri"] = payload["uri"]
        except json.JSONDecodeError:
            pass
    for key in ("title", "simulated"):
        if key in artifact and key not in out:
            out[key] = artifact[key]
    return out


@router.get("/agents")
def list_agents(tenant: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return [agent_view(a) for a in ctx.hive.list_agents(tenant)]


@router.get("/tasks")
def list_tasks(tenant: str, status: str | None = Query(None), limit: int = Query(50, ge=1, le=500), ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return [task_view(t) for t in ctx.hive.list_tasks(tenant, status=status or None, limit=limit)]


@router.post("/tasks", status_code=201)
def create_task(tenant: str, body: TaskCreate, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    task_id = ctx.hive.submit_task(tenant, body.kind, body.payload, body.requires, body.about_ids, body.priority)
    task = ctx.hive.get_task(tenant, task_id)
    return task_view(task or {"id": task_id, "kind": body.kind, "status": "submitted", "version": 0, "payload": body.payload, "requires": body.requires, "about": body.about_ids, "priority": body.priority})


@router.get("/tasks/{task_id}")
def get_task(tenant: str, task_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    task = ctx.hive.get_task(tenant, task_id)
    if task is None:
        raise ApiError(404, "task_not_found", f"task {task_id!r} not found")
    return task_view(task)


@router.get("/tasks/{task_id}/trace")
def task_trace(tenant: str, task_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    trace = ctx.hive.task_trace(tenant, task_id)
    task = trace.get("task") or {}
    events = [{"t": task.get("created_at"), "type": "submitted", "agent": None}]
    for event in trace.get("events") or []:
        item = dict(event)
        if item.get("type") == "artifact":
            item["artifact"] = _artifact_view(item.get("artifact"))
        events.append(item)
    events.sort(key=lambda e: (e.get("t") or 0, 0 if e.get("type") == "submitted" else 1))
    return {"task": task_view(task), "events": events, "about": trace.get("about") or task.get("about") or [], "cypher": trace.get("cypher")}


# --------------------------------------------------------------------------- demo buttons
def _pick_demo_commitment(ctx: AppContext, tenant: str) -> dict[str, Any]:
    active = ctx.hive.active_facts(tenant, key=DEMO_SUPERSEDE_KEY)
    if not active:
        dated = [f for f in ctx.hive.list_facts(tenant, status="active", kind="commitment") if f.get("due_at")]
        if not dated:
            raise ApiError(404, "no_commitment", "no active dated commitment to supersede; import a meeting first")
        active = sorted(dated, key=lambda f: -(f.get("valid_from") or 0))
    return max(active, key=lambda f: (f.get("valid_from") or 0, f.get("created_at") or 0))


@router.post("/demo/supersede")
def demo_supersede(tenant: str, body: SupersedeBody, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """The "move it to Friday" path: supersede a dated commitment and let the Scheduler wake up."""
    ctx.ensure_tenant(tenant)
    old = ctx.hive.get_fact(tenant, body.fact_id) if body.fact_id else _pick_demo_commitment(ctx, tenant)
    if old is None:
        raise ApiError(404, "fact_not_found", f"fact {body.fact_id!r} not found")
    if old.get("status") != "active":
        raise ApiError(409, "not_active", f"fact {old['id']} is {old.get('status')!r}; only active facts can be superseded")
    speaker_id = body.speaker_id or old.get("speaker_id") or (old.get("speaker") or {}).get("id")
    new_object = normalize_date(body.new_object) or body.new_object
    due_ms = date_to_ms(new_object)
    now = now_ms()
    speaker = ctx.hive.get_person(tenant, speaker_id) or {}
    text = f"{speaker.get('name') or 'Someone'} moved {old.get('subject')} {str(old.get('predicate', '')).replace('_', ' ')} from {old.get('object')} to {new_object}"
    new_fact: dict[str, Any] = {
        "id": f"fact_demo_{now}",
        "kind": old.get("kind") or "commitment",
        "subject": old.get("subject"),
        "predicate": old.get("predicate"),
        "object": new_object,
        "key": old.get("key") or fact_key(str(old.get("subject")), str(old.get("predicate"))),
        "text": text,
        "confidence": 0.9,
        "speaker_id": speaker_id,
        "episode_id": old.get("episode_id"),
        "entity_ids": list(old.get("entity_ids") or []),
        "valid_from": now,
        "embedding": ctx.embedder.embed_one(text, "document"),
    }
    if due_ms is not None:
        new_fact["due_at"] = due_ms
    result = ctx.hive.supersede_fact(tenant, old["id"], new_fact)
    if not getattr(ctx.hive, "publishes_memory_events", False):
        payload = {
            "old_fact_id": old["id"],
            "new_fact_id": result["id"],
            "key": new_fact["key"],
            "kind": new_fact["kind"],
            "subject": new_fact["subject"],
            "predicate": new_fact["predicate"],
            "old_object": old.get("object"),
            "new_object": new_object,
            "object": new_object,
            "due_at": due_ms,
            "speaker_id": speaker_id,
            "episode_id": old.get("episode_id"),
            "head_changed": True,
            "demo": True,
        }
        ctx.hive.publish(tenant, "fact.superseded", payload)
        if new_fact["kind"] == "commitment":
            ctx.hive.publish(tenant, "commitment.updated", {**payload, "commitment_id": result["id"]})
    return {"old_fact_id": old["id"], "new_fact_id": result["id"], "subject": old.get("subject"), "old_object": old.get("object"), "new_object": new_object, "due_at": due_ms}


@router.post("/demo/double-claim")
async def demo_double_claim(tenant: str, body: DoubleClaimBody | None = None, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """25 concurrent compare-and-set claims on one task: exactly one wins."""
    ctx.ensure_tenant(tenant)
    body = body or DoubleClaimBody()
    hive = ctx.hive
    agent_ids = [f"demo_claimer_{i:02d}" for i in range(DEMO_CLAIMERS)]
    for agent_id in agent_ids:
        hive.register_agent(tenant, agent_id, f"Demo claimer {agent_id[-2:]}", ["demo"], "none")
    task = hive.get_task(tenant, body.task_id) if body.task_id else None
    if body.task_id and task is None:
        raise ApiError(404, "task_not_found", f"task {body.task_id!r} not found")
    if task is None:
        submitted = [t for t in hive.list_tasks(tenant, status="submitted", limit=50) if t.get("kind") == "demo_double_claim" and not t.get("owner_agent")]
        task = submitted[0] if submitted else None
    if task is None:
        task_id = hive.submit_task(tenant, "demo_double_claim", {"demo": "double-claim", "note": "25 agents race for this task"}, ["demo"], [], 5)
        task = hive.get_task(tenant, task_id) or {"id": task_id, "version": 0, "status": "submitted"}
    if task.get("status") != "submitted":
        raise ApiError(409, "not_claimable", f"task {task['id']} is {task.get('status')!r}")
    version = int(task.get("version", 0))
    results = await asyncio.gather(*(asyncio.to_thread(hive.claim, tenant, task["id"], agent_id, version) for agent_id in agent_ids), return_exceptions=True)
    winners = [a for a, r in zip(agent_ids, results) if isinstance(r, int)]
    errors = [str(r) for r in results if isinstance(r, Exception)]
    winner = winners[0] if winners else None
    if winner:
        try:
            hive.complete(tenant, task["id"], winner, {"kind": "demo", "text": json.dumps({"winners": len(winners), "losers": len(agent_ids) - len(winners)})})
        except Exception as exc:  # noqa: BLE001
            log.warning("could not complete demo task: %s", exc)
    return {"winners": len(winners), "losers": len(agent_ids) - len(winners), "task_id": task["id"], "winner_agent": winner, "attempts": len(agent_ids), "errors": errors[:3]}


# --------------------------------------------------------------------------- SSE
@router.get("/events")
async def events(
    tenant: str,
    request: Request,
    replay: int = Query(0, ge=0, le=200, description="re-send the last N events seen by this process"),
    limit: int | None = Query(None, ge=1, description="close after N events (tests/debugging)"),
    ctx: AppContext = Depends(get_ctx),
) -> EventSourceResponse:
    ctx.ensure_tenant(tenant)
    queue = ctx.bus.attach(tenant, replay=replay)

    async def stream():
        sent = 0
        try:
            yield {"event": "connected", "data": json.dumps({"event": "connected", "payload": {"tenant": tenant}, "ts": now_ms()})}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield {"comment": "keep-alive"}
                    continue
                yield {"event": str(event.get("event", "message")), "data": json.dumps(event, default=str)}
                sent += 1
                if limit is not None and sent >= limit:
                    break
        finally:
            ctx.bus.detach(tenant, queue)

    return EventSourceResponse(stream(), ping=15)
