"""Procedural memory: Skills with ordered Steps, retrieval by goal embedding, outcome tracking, PageRank and
publication into the shared `commons` graph. Read paths project skills without their 768-d embedding; only
`publish_to_commons` reads the whole node (it needs the vector to copy it)."""

from __future__ import annotations

from typing import Any

from falkordb import Node

from .db import HiveDB
from .embed import validate_embedding
from .errors import NotFound
from .events import publish
from .ids import new_id
from .queries import load_cypher
from .records import CypherRows, props
from .schema import ensure_commons_schema
from .temporal import now_ms

RO_TIMEOUT_MS = 3000


def _steps(raw: list[dict]) -> list[dict]:
    steps = [dict(s) for s in raw if s.get("id") is not None]
    steps.sort(key=lambda s: (s.get("order") is None, s.get("order") or 0))
    return steps


def _skill_record(
    s: Node, steps: list[dict], learned_from: list | None = None, distance: float | None = None
) -> dict:
    rec = props(s) or {}
    rec["steps"] = _steps(steps)
    rec["learned_from"] = [x for x in (learned_from or []) if x is not None]
    if distance is not None:
        rec["distance"] = distance
        rec["similarity"] = max(0.0, min(1.0, 1.0 - distance))
    return rec


def learn_skill(
    db: HiveDB,
    tenant: str,
    goal: str,
    steps: list[dict],
    learned_from: list[str],
    embedding: list[float] | None,
    version: int = 1,
) -> str:
    """Create a Skill from `steps: [{order, tool, args_template, guard?}]`; LEARNED_FROM links to episode/task ids."""
    skill_id = new_id("skl")
    rows = [
        {
            "id": s.get("id") or new_id("stp"),
            "order": int(s.get("order", i)),
            "tool": s["tool"],
            "args_template": s.get("args_template", "{}"),
            "guard": s.get("guard"),
        }
        for i, s in enumerate(steps)
    ]
    db.graph(tenant).query(
        load_cypher("learn_skill"),
        {
            "id": skill_id,
            "goal": goal,
            "version": int(version),
            "embedding": validate_embedding(embedding),
            "steps": rows,
            "learned_from": list(learned_from),
            "now": now_ms(),
        },
    )
    publish(
        db,
        tenant,
        "skill.learned",
        {"skill_id": skill_id, "goal": goal, "steps": len(rows), "learned_from": list(learned_from)},
    )
    return skill_id


def retrieve_skill(db: HiveDB, tenant: str, goal_embedding: list[float], k: int = 3) -> CypherRows:
    """Best ACTIVE skills for a goal embedding: ordered by success_rate desc, then vector distance; steps included."""
    query = load_cypher("skill_retrieve")
    res = db.ro(tenant).ro_query(
        query,
        {"goal": validate_embedding(goal_embedding), "n": max(10, k * 4), "k": int(k)},
        timeout=RO_TIMEOUT_MS,
    )
    return CypherRows(
        [_skill_record(s, steps, None, distance) for s, distance, steps in res.result_set], query
    )


def record_outcome(
    db: HiveDB, tenant: str, skill_id: str, agent_id: str, ok: bool, task_id: str | None = None
) -> dict[str, Any]:
    """Increment runs, update the running success_rate, add Agent -[:RAN]-> Skill (and Task -[:USED]-> Skill)."""
    res = db.graph(tenant).query(
        load_cypher("skill_outcome"),
        {
            "id": skill_id,
            "agent": agent_id,
            "ok": 1.0 if ok else 0.0,
            "outcome": "ok" if ok else "failed",
            "task_id": task_id,
            "now": now_ms(),
        },
    )
    if not res.result_set:
        raise NotFound(f"skill {skill_id!r} does not exist in team_{tenant}")
    rec = props(res.result_set[0][0]) or {}
    publish(
        db,
        tenant,
        "skill.ran",
        {
            "skill_id": skill_id,
            "agent_id": agent_id,
            "ok": ok,
            "task_id": task_id,
            "runs": rec.get("runs"),
            "success_rate": rec.get("success_rate"),
        },
    )
    return rec


def deprecate_skill(db: HiveDB, tenant: str, old_id: str, new_id_: str) -> None:
    """Mark `old_id` deprecated and link DEPRECATED_BY -> `new_id_`."""
    res = db.graph(tenant).query(
        load_cypher("deprecate_skill"), {"old_id": old_id, "new_id": new_id_, "now": now_ms()}
    )
    if not res.result_set:
        raise NotFound(f"skills {old_id!r} and/or {new_id_!r} do not exist in team_{tenant}")


def skill_pagerank(db: HiveDB, tenant: str) -> CypherRows:
    """`algo.pageRank` over Task -[:USED]-> Skill; rows `{id, goal, runs, success_rate, score}` best first."""
    query = load_cypher("pagerank_skills")
    res = db.ro(tenant).ro_query(query, timeout=RO_TIMEOUT_MS)
    keys = ["id", "goal", "runs", "success_rate", "score"]
    return CypherRows([dict(zip(keys, row)) for row in res.result_set], query)


def get_skill(db: HiveDB, tenant: str, skill_id: str) -> dict[str, Any]:
    """One skill with steps and `learned_from` ids."""
    res = db.ro(tenant).ro_query(
        load_cypher("export_skill"), {"id": skill_id, "with_embedding": False}, timeout=RO_TIMEOUT_MS
    )
    if not res.result_set:
        raise NotFound(f"skill {skill_id!r} does not exist in team_{tenant}")
    s, steps, learned_from = res.result_set[0]
    return _skill_record(s, steps, learned_from)


def list_skills(db: HiveDB, tenant: str, status: str | None = None, limit: int = 500) -> CypherRows:
    """All skills (optionally by status) with steps and provenance, newest first (at most `limit`)."""
    query = load_cypher("list_skills")
    res = db.ro(tenant).ro_query(query, {"status": status, "limit": int(limit)}, timeout=RO_TIMEOUT_MS)
    return CypherRows([_skill_record(s, steps, lf) for s, steps, lf in res.result_set], query)


def publish_to_commons(db: HiveDB, tenant: str, skill_id: str) -> str:
    """Copy a Skill and its Steps into `commons` with `origin_tenant`; returns the commons skill id."""
    res = db.graph(tenant).query(load_cypher("export_skill"), {"id": skill_id, "with_embedding": True})
    if not res.result_set:
        raise NotFound(f"skill {skill_id!r} does not exist in team_{tenant}")
    s, steps, _learned_from = res.result_set[0]
    embedding = s.properties.get("embedding")
    ensure_commons_schema(db)
    commons_id = f"{skill_id}@{tenant}"
    rows = [{**step, "id": f"{step['id']}@{tenant}"} for step in _steps(steps)]
    db.commons().query(
        load_cypher("import_skill_commons"),
        {
            "id": commons_id,
            "goal": s.properties.get("goal"),
            "version": s.properties.get("version", 1),
            "origin_tenant": tenant,
            "origin_id": skill_id,
            "runs": s.properties.get("runs", 0),
            "success_rate": s.properties.get("success_rate", 0.0),
            "embedding": validate_embedding(embedding),
            "steps": rows,
            "now": now_ms(),
        },
    )
    return commons_id
