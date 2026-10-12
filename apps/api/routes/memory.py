"""Memory: facts (paged), why, belief-at-T, timeline, snapshots, analytics."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from ..auth import require_admin, require_tenant_key
from ..errors import ApiError
from ..state import AppContext, get_ctx

router = APIRouter(prefix="/tenants/{tenant}", tags=["memory"], dependencies=[Depends(require_tenant_key)])

STATUSES = {"active", "superseded", "retracted", "all"}
PROVENANCE_KEYS = ("speaker", "meeting", "thread", "source", "episode_id", "supersedes", "entities")
KINDS = {"fact", "decision", "commitment"}
FACTS_DEFAULT_LIMIT = 200
FACTS_MAX_LIMIT = 1000
NEXT_CURSOR_HEADER = "X-Next-Cursor"
TRUNCATED_HEADER = "X-Truncated"


@router.get("/people")
def list_people(tenant: str, ctx: Annotated[AppContext, Depends(get_ctx)]) -> list[dict[str, Any]]:
    """Recorded people are explicit owner choices, independent of who stated a fact."""
    ctx.ensure_tenant(tenant)
    people = [{k: p[k] for k in ("id", "name", "email", "role") if p.get(k) is not None}
              for p in ctx.hive.list_persons(tenant)]
    return sorted(people, key=lambda p: (str(p.get("name", "")).casefold(), p["id"]))


def fact_view(fact: dict[str, Any]) -> dict[str, Any]:
    """Contract shape for one fact row (plus ``source``, ``supersedes`` and ``entities``)."""
    supersedes = fact.get("supersedes") or []
    return {
        "id": fact.get("id"),
        "kind": fact.get("kind") or "fact",
        "subject": fact.get("subject"),
        "predicate": fact.get("predicate"),
        "object": fact.get("object"),
        "text": fact.get("text"),
        "confidence": fact.get("confidence"),
        "valid_from": fact.get("valid_from"),
        "valid_to": fact.get("valid_to"),
        "created_at": fact.get("created_at"),
        "expired_at": fact.get("expired_at"),
        "status": fact.get("status") or "active",
        "speaker": fact.get("speaker") or ({"id": fact.get("speaker_id"), "name": fact.get("speaker_id")} if fact.get("speaker_id") else None),
        "meeting": fact.get("meeting"),
        "thread": fact.get("thread"),
        "episode_id": fact.get("episode_id"),
        "due_at": fact.get("due_at"),
        "entities": fact.get("entities") or [],
        "source": fact.get("source"),
        "supersedes": supersedes[0] if supersedes else None,
        "supersedes_ids": supersedes,
        "precedent_ids": fact.get("precedent_ids") or [],
    }


@router.get("/facts")
def list_facts(
    tenant: str,
    response: Response,
    status: str = Query("active"),
    entity: str | None = Query(None),
    kind: str | None = Query(None),
    limit: int = Query(FACTS_DEFAULT_LIMIT, ge=1, le=FACTS_MAX_LIMIT),
    cursor: str | None = Query(None, description=f"opaque; the {NEXT_CURSOR_HEADER} header of the previous page"),
    ctx: AppContext = Depends(get_ctx),
) -> list[dict[str, Any]]:
    """One page of facts ordered by (valid_from, id). The body stays an array; ``X-Next-Cursor`` carries the
    next page's cursor and ``X-Truncated`` is ``true`` when more facts match."""
    ctx.ensure_tenant(tenant)
    if status not in STATUSES:
        raise ApiError(400, "bad_status", f"status must be one of {sorted(STATUSES)}")
    if kind is not None and kind not in KINDS:
        raise ApiError(400, "bad_kind", f"kind must be one of {sorted(KINDS)}")
    try:
        rows, next_cursor = ctx.hive.page_facts(tenant, status=status, entity=entity, kind=kind, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise ApiError(400, "bad_cursor", str(exc)) from exc
    response.headers[TRUNCATED_HEADER] = "true" if next_cursor else "false"
    if next_cursor:
        response.headers[NEXT_CURSOR_HEADER] = next_cursor
    return [fact_view(f) for f in rows]


@router.get("/facts/{fact_id}")
def get_fact(tenant: str, fact_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    fact = ctx.hive.get_fact(tenant, fact_id)
    if fact is None:
        raise ApiError(404, "fact_not_found", f"fact {fact_id!r} not found")
    return fact_view(fact)


@router.get("/why/{node_id}")
def why(tenant: str, node_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    info = ctx.hive.why(tenant, node_id)
    episode = info.get("episode") or {}
    return {
        "node": info.get("node"),
        "speaker": info.get("speaker"),
        "meeting": info.get("meeting"),
        "thread": info.get("thread"),
        "episode": {"id": episode.get("id"), "text": episode.get("text"), "t_start": episode.get("t_start"), "t_end": episode.get("t_end"), "t_occurred": episode.get("t_occurred")} if episode else None,
        "source": info.get("source"),
        "entities": info.get("entities") or [],
        "history": info.get("history") or [],
        "supersedes": info.get("supersedes") or [h for h in info.get("history") or [] if h.get("id") != node_id],
        "superseded_by": info.get("superseded_by") or [],
        "cypher": info.get("cypher"),
        "subgraph": info.get("subgraph") or {"nodes": [], "edges": []},
    }


@router.get("/belief")
def belief(tenant: str, t: int = Query(..., description="epoch ms"), entity: str | None = Query(None), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    result = ctx.hive.belief_at_result(tenant, int(t), entity)
    rows = result["rows"]
    if rows and any(not (f.get("meeting") or f.get("thread") or f.get("source")) for f in rows):
        # 31_belief_at_time returns the fact and its speaker only; add where it was said (meeting or thread) for display.
        # list_facts pages through every fact internally (no silent cap).
        full = {f.get("id"): f for f in ctx.hive.list_facts(tenant, status="all")}
        rows = [{**f, **{k: full[f["id"]].get(k) for k in PROVENANCE_KEYS if not f.get(k) and full.get(f.get("id"), {}).get(k)}} for f in rows]
    return {"t": int(t), "entity": entity, "facts": [fact_view(f) for f in rows], "cypher": result.get("cypher", "")}


@router.get("/timeline")
def timeline(tenant: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    events: list[dict[str, Any]] = []
    for meeting in ctx.hive.list_meetings(tenant):
        events.append({"t": meeting.get("started_at"), "type": "meeting", "id": meeting["id"], "text": meeting.get("title")})
    for thread in ctx.hive.list_threads(tenant):
        events.append({"t": thread.get("started_at"), "type": "email", "id": thread["id"], "text": thread.get("subject")})
    for fact in ctx.hive.list_facts(tenant, status="all"):
        kind = fact.get("kind") or "fact"
        label = {"decision": "decision", "commitment": "commitment"}.get(kind, "fact.created")
        text = f"{fact.get('subject')} {str(fact.get('predicate', '')).replace('_', ' ')} {fact.get('object')}"
        events.append({"t": fact.get("valid_from"), "type": label, "id": fact["id"], "text": text, "kind": kind, "status": fact.get("status")})
        if fact.get("status") == "superseded" and fact.get("valid_to") is not None:
            events.append({"t": fact.get("valid_to"), "type": "fact.superseded", "id": fact["id"], "text": f"superseded: {text}", "kind": kind})
    events = [e for e in events if e.get("t") is not None]
    events.sort(key=lambda e: (e["t"], e["type"]))
    snapshots = [{"name": s.get("name"), "taken_at": s.get("taken_at"), "label": s.get("label"), "id": s.get("id")} for s in ctx.hive.list_snapshots(tenant)]
    return {"events": events, "snapshots": snapshots}


class SnapshotBody(BaseModel):
    label: str = Field(min_length=1, max_length=120)


@router.post("/snapshots", status_code=201, dependencies=[Depends(require_admin)])
def create_snapshot(tenant: str, body: SnapshotBody, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Admin: GRAPH.COPY the tenant graph. Capped at ``MAX_SNAPSHOTS_PER_TENANT`` (default 10) -> 409 beyond."""
    ctx.ensure_tenant(tenant)
    cap = int(ctx.settings.max_snapshots_per_tenant)
    existing = ctx.hive.list_snapshots(tenant)
    if len(existing) >= cap:
        raise ApiError(409, "snapshot_quota", f"tenant {tenant!r} already has {len(existing)} snapshots (cap {cap}); delete one before taking another")
    snap = ctx.hive.snapshot(tenant, body.label)
    return {"name": snap.get("name"), "taken_at": snap.get("taken_at"), "label": snap.get("label", body.label), "id": snap.get("id")}


@router.get("/snapshots")
def list_snapshots(tenant: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return ctx.hive.list_snapshots(tenant)


@router.get("/analytics/who-knows")
def who_knows(tenant: str, entity: str = Query(...), ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return [{"person": r.get("person"), "mentions": r.get("mentions"), "last_at": r.get("last_at"), "via": r.get("via")} for r in ctx.hive.who_knows(tenant, entity)["rows"]]


@router.get("/analytics/open-commitments")
def open_commitments(tenant: str, person: str | None = Query(None), ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    rows = ctx.hive.open_commitments(tenant, person)["rows"]
    # 51_open_commitments carries no provenance; join the active commitments for speaker, source and SUPERSEDES.
    full = {f.get("id"): f for f in ctx.hive.list_facts(tenant, status="active", kind="commitment")} if rows else {}
    return [{**fact_view({**r, **full.get(r.get("id"), {})}), "owner": r.get("owner")} for r in rows]


@router.get("/analytics/contradictions")
def contradictions(tenant: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return [{"key": r.get("key"), "facts": [fact_view(f) for f in r.get("facts", []) if f]} for r in ctx.hive.contradictions(tenant)["rows"]]


@router.get("/analytics/clusters")
def clusters(tenant: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return [{"component": r.get("component"), "entities": r.get("entities", [])} for r in ctx.hive.entity_clusters(tenant)["rows"]]


@router.get("/analytics/stale-decisions")
def stale_decisions(tenant: str, older_than_days: int = Query(14, ge=1), ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return [{**fact_view(r), "age_ms": r.get("age_ms")} for r in ctx.hive.stale_decisions(tenant, older_than_days * 86_400_000)["rows"]]


@router.get("/entities")
def entities(tenant: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return [{"id": e.get("id"), "name": e.get("name"), "type": e.get("type")} for e in ctx.hive.list_entities(tenant)]
