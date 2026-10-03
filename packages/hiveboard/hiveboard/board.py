"""Coordination board: agents, capabilities and tasks with A2A-shaped states
(submitted | working | input_required | completed | failed), compare-and-set claims and subgraph hand-offs."""

from __future__ import annotations

from typing import Any

import orjson
from falkordb import Node

from .db import HiveDB
from .errors import NotFound
from .events import publish
from .ids import new_id
from .queries import load_cypher
from .records import CypherRows, props
from .temporal import now_ms

RO_TIMEOUT_MS = 3000
TASK_STATES = ("submitted", "working", "input_required", "completed", "failed")


def _task_record(t: Node, requires: list | None = None, about: list | None = None) -> dict[str, Any]:
    rec = props(t) or {}
    raw = rec.get("payload")
    if isinstance(raw, str):
        try:
            rec["payload"] = orjson.loads(raw)
        except orjson.JSONDecodeError:
            rec["payload"] = {"raw": raw}
    rec["requires"] = [r for r in (requires or []) if r is not None]
    rec["about"] = [a for a in (about or []) if a is not None]
    return rec


def register_agent(
    db: HiveDB, tenant: str, agent_id: str, name: str, capabilities: list[str], model: str
) -> None:
    """Upsert an Agent and its HAS -> Capability edges."""
    db.graph(tenant).query(
        load_cypher("register_agent"),
        {"id": agent_id, "name": name, "model": model, "caps": list(capabilities), "now": now_ms()},
    )


def submit_task(
    db: HiveDB,
    tenant: str,
    kind: str,
    payload: dict,
    requires: list[str],
    about_ids: list[str] = (),
    priority: int = 5,
) -> str:
    """Create a `submitted` task (version 0); returns its id and publishes `task.submitted`."""
    task_id = new_id("task")
    db.graph(tenant).query(
        load_cypher("submit_task"),
        {
            "id": task_id,
            "kind": kind,
            "payload": orjson.dumps(payload or {}).decode(),
            "requires": list(requires),
            "about_ids": list(about_ids),
            "priority": int(priority),
            "now": now_ms(),
        },
    )
    publish(
        db,
        tenant,
        "task.submitted",
        {
            "task_id": task_id,
            "kind": kind,
            "requires": list(requires),
            "about": list(about_ids),
            "priority": priority,
        },
    )
    return task_id


def claim(db: HiveDB, tenant: str, task_id: str, agent_id: str, expected_version: int) -> int | None:
    """Compare-and-set claim; returns the new version, or None when another agent won (zero rows)."""
    res = db.graph(tenant).query(
        load_cypher("claim_task"),
        {"id": task_id, "v": int(expected_version), "agent": agent_id, "now": now_ms()},
    )
    if not res.result_set:
        return None
    version = int(res.result_set[0][0])
    publish(db, tenant, "task.claimed", {"task_id": task_id, "agent_id": agent_id, "version": version})
    return version


def next_open_task(db: HiveDB, tenant: str, agent_id: str) -> dict[str, Any] | None:
    """Oldest `submitted` task whose REQUIRES is a subset of the agent's HAS (and not addressed to someone else)."""
    res = db.ro(tenant).ro_query(load_cypher("next_open_task"), {"agent": agent_id}, timeout=RO_TIMEOUT_MS)
    if not res.result_set:
        return None
    t, reqs = res.result_set[0]
    return _task_record(t, reqs)


def handoff(
    db: HiveDB,
    tenant: str,
    task_id: str,
    from_agent: str,
    to_agent: str,
    expected_version: int,
    summary: str,
    subgraph_ids: list[str],
) -> int | None:
    """Hand a task to another agent with a subgraph reference; returns the new version or None if the version was stale."""
    res = db.graph(tenant).query(
        load_cypher("handoff_task"),
        {
            "id": task_id,
            "from": from_agent,
            "to": to_agent,
            "v": int(expected_version),
            "now": now_ms(),
            "summary": summary,
            "ids": list(subgraph_ids),
        },
    )
    if not res.result_set:
        return None
    version = int(res.result_set[0][0])
    publish(
        db,
        tenant,
        "task.handed_off",
        {
            "task_id": task_id,
            "from": from_agent,
            "to": to_agent,
            "version": version,
            "summary": summary,
            "subgraph_ids": list(subgraph_ids),
        },
    )
    return version


def complete(db: HiveDB, tenant: str, task_id: str, agent_id: str, artifact: dict | None = None) -> None:
    """Owner completes a working task, optionally PRODUCED -> Artifact `{kind, uri?, text?}`."""
    art = None
    if artifact is not None:
        art = {
            "id": artifact.get("id") or new_id("art"),
            "kind": artifact.get("kind"),
            "uri": artifact.get("uri"),
            "text": artifact.get("text"),
        }
    res = db.graph(tenant).query(
        load_cypher("complete_task"), {"id": task_id, "agent": agent_id, "now": now_ms(), "artifact": art}
    )
    if not res.result_set:
        raise NotFound(f"task {task_id!r} is not a working task owned by {agent_id!r}")
    publish(
        db,
        tenant,
        "task.completed",
        {"task_id": task_id, "agent_id": agent_id, "artifact": art, "version": int(res.result_set[0][0])},
    )


def _set_state(db: HiveDB, tenant: str, task_id: str, agent_id: str, status: str, note: str) -> int:
    res = db.graph(tenant).query(
        load_cypher("set_task_state"),
        {"id": task_id, "agent": agent_id, "status": status, "note": note, "now": now_ms()},
    )
    if not res.result_set:
        raise NotFound(f"task {task_id!r} is not owned by {agent_id!r}")
    return int(res.result_set[0][0])


def fail(db: HiveDB, tenant: str, task_id: str, agent_id: str, reason: str) -> None:
    """Owner fails a task with a reason (stored as `failure_reason`)."""
    version = _set_state(db, tenant, task_id, agent_id, "failed", reason)
    publish(
        db,
        tenant,
        "task.failed",
        {"task_id": task_id, "agent_id": agent_id, "reason": reason, "version": version},
    )


def need_input(db: HiveDB, tenant: str, task_id: str, agent_id: str, question: str) -> None:
    """Owner parks a task in `input_required` with the question for a human."""
    version = _set_state(db, tenant, task_id, agent_id, "input_required", question)
    publish(
        db,
        tenant,
        "task.input_required",
        {"task_id": task_id, "agent_id": agent_id, "question": question, "version": version},
    )


def list_tasks(db: HiveDB, tenant: str, status: str | None = None, limit: int = 50) -> CypherRows:
    """Tasks newest first (payload decoded, `requires` and `about` attached)."""
    query = load_cypher("list_tasks")
    res = db.ro(tenant).ro_query(query, {"status": status, "limit": int(limit)}, timeout=RO_TIMEOUT_MS)
    return CypherRows([_task_record(t, reqs, about) for t, reqs, about in res.result_set], query)


def list_agents(db: HiveDB, tenant: str) -> CypherRows:
    """Agents with capabilities and a derived `state` (`working` | `idle`)."""
    query = load_cypher("list_agents")
    res = db.ro(tenant).ro_query(query, timeout=RO_TIMEOUT_MS)
    rows = []
    for a, caps, working in res.result_set:
        rec = props(a) or {}
        rec["capabilities"] = [c for c in caps if c is not None]
        rec["state"] = "working" if working else "idle"
        rows.append(rec)
    return CypherRows(rows, query)


def task_trace(db: HiveDB, tenant: str, task_id: str) -> dict[str, Any]:
    """`{task, events: [...], about, cypher}` with claims, hand-offs, artifacts, skills and the terminal state in time order."""
    query = load_cypher("task_trace")
    res = db.ro(tenant).ro_query(query, {"id": task_id}, timeout=RO_TIMEOUT_MS)
    if not res.result_set:
        raise NotFound(f"task {task_id!r} does not exist in team_{tenant}")
    t, claims, handoffs, artifacts, skills, about = res.result_set[0]
    events = [dict(e) for group in (claims, handoffs, artifacts, skills) for e in group if _present(e)]
    task = _task_record(t, None, about)
    if task.get("status") in ("completed", "failed", "input_required"):
        events.append(
            {
                "t": task.get("updated_at"),
                "type": task["status"],
                "agent": task.get("owner_agent"),
                "reason": task.get("failure_reason"),
                "question": task.get("question"),
            }
        )
    events.sort(key=lambda e: e.get("t") or 0)
    return {"task": task, "events": events, "about": task["about"], "cypher": query}


def _present(event: dict) -> bool:
    """collect() over an OPTIONAL MATCH yields one all-null record when nothing matched; drop it.
    Records with a nested object (artifact, skill) count as present only when that object has data."""
    nested = [v for v in event.values() if isinstance(v, dict)]
    if nested:
        return any(x is not None for d in nested for x in d.values())
    return event.get("t") is not None or event.get("agent") is not None
