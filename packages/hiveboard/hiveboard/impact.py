"""Explicit work dependencies and persistent local follow-up drafts in a tenant graph."""

from __future__ import annotations

from typing import Any

import orjson
from redis.exceptions import ResponseError

from .db import HiveDB
from .errors import Conflict
from .queries import load_cypher
from .records import CypherRows

RO_TIMEOUT_MS = 3000
DRAFT_REQUIRED_KEYS = (
    "id",
    "work_item_id",
    "baseline_fact_id",
    "current_fact_id",
    "owner_id",
    "document_id",
    "created_at",
)
ITEM_REQUIRED_KEYS = ("id", "title", "status", "owner_id", "baseline_fact_id")


def import_manifest(db: HiveDB, tenant: str, manifest: dict[str, Any]) -> int:
    """One atomic query: any unresolved fact/person prevents the entire import. Raises ValueError on a malformed manifest."""
    items = manifest.get("items") or []
    document = manifest.get("document") or {}
    if not items or len(items) > 200 or len({item.get("id") for item in items}) != len(items):
        raise ValueError("manifest needs 1-200 distinct work items")
    if not document.get("id"):
        raise ValueError("manifest needs a document with an id")
    for item in items:
        missing = [k for k in ITEM_REQUIRED_KEYS if item.get(k) in (None, "")]
        if missing:
            raise ValueError(f"work item {item.get('id')!r} is missing {missing}")
    result = db.graph(tenant).query(
        load_cypher("import_work_manifest"), {"items": items, "document": document}
    )
    imported = result.result_set[0][0] if result.result_set else 0
    if imported != len(items):
        raise ValueError("manifest reference not found in this tenant")
    return imported


def _distinct_candidates(candidates: list) -> list[dict]:
    """One candidate per current fact id, keeping the shortest SUPERSEDES path: a DAG chain yields one path row per route."""
    best: dict[str, dict] = {}
    for c in candidates:
        fid = (c.get("fact") or {}).get("id") if c else None
        if fid and (fid not in best or len(c.get("via") or []) < len(best[fid].get("via") or [])):
            best[fid] = c
    return list(best.values())


def work_impacts(db: HiveDB, tenant: str) -> CypherRows:
    """Every work item with its baseline fact, owner, document and the ACTIVE facts on the same key (`candidates`)."""
    query = load_cypher("work_impacts")
    result = db.ro(tenant).ro_query(query, timeout=RO_TIMEOUT_MS)
    rows = []
    for item, baseline, owner, document, candidates in result.result_set:
        rows.append(
            {
                "item": item,
                "baseline": baseline,
                "owner": owner,
                "document": document,
                "candidates": _distinct_candidates(candidates),
            }
        )
    return CypherRows(rows, query)


def save_draft(db: HiveDB, tenant: str, draft: dict[str, Any]) -> dict[str, Any] | None:
    """Persist a follow-up draft after re-validating the work item, owner, document and current fact inside the write.
    Returns the stored payload, or None when the graph moved on (stale draft). Raises ValueError when a required key is
    missing and Conflict when the draft id is already used for another work item."""
    missing = [k for k in DRAFT_REQUIRED_KEYS if draft.get(k) in (None, "")]
    if missing:
        raise ValueError(f"draft is missing {missing}")
    params = {key: draft[key] for key in DRAFT_REQUIRED_KEYS}
    params["payload"] = orjson.dumps(draft, option=orjson.OPT_SORT_KEYS, default=str).decode()
    try:
        rows = db.graph(tenant).query(load_cypher("save_impact_draft"), params).result_set
    except ResponseError as exc:
        if "unique constraint" in str(exc).lower():
            raise Conflict(f"draft id {draft['id']!r} is already used for another work item") from exc
        raise
    return orjson.loads(rows[0][0]) if rows else None


def list_drafts(db: HiveDB, tenant: str) -> list[dict[str, Any]]:
    """Stored draft payloads, newest first."""
    rows = db.ro(tenant).ro_query(load_cypher("impact_drafts"), timeout=RO_TIMEOUT_MS).result_set
    return [orjson.loads(row[0]) for row in rows]
