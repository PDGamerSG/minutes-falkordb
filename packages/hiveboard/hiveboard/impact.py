"""Explicit work dependencies and persistent local follow-up drafts in a tenant graph."""

from __future__ import annotations

from typing import Any

from .db import HiveDB
from .queries import load_cypher
from .records import CypherRows


def import_manifest(db: HiveDB, tenant: str, manifest: dict[str, Any]) -> int:
    """One atomic query: any unresolved fact/person prevents the entire import."""
    items = manifest["items"]
    if not items or len(items) > 200 or len({item["id"] for item in items}) != len(items):
        raise ValueError("manifest needs 1–200 distinct work items")
    result = db.graph(tenant).query(load_cypher("import_work_manifest"), manifest)
    imported = result.result_set[0][0] if result.result_set else 0
    if imported != len(items):
        raise ValueError("manifest reference not found in this tenant")
    return imported


def work_impacts(db: HiveDB, tenant: str) -> CypherRows:
    query = load_cypher("work_impacts")
    result = db.ro(tenant).ro_query(query, timeout=3000)
    rows = []
    for item, baseline, owner, document, candidates in result.result_set:
        rows.append({"item": item, "baseline": baseline, "owner": owner, "document": document,
                     "candidates": [c for c in candidates if c and (c.get("fact") or {}).get("id")]})
    return CypherRows(rows, query)


def save_draft(db: HiveDB, tenant: str, draft: dict[str, Any]) -> dict[str, Any] | None:
    import json

    params = {**draft, "payload": json.dumps(draft, sort_keys=True)}
    rows = db.graph(tenant).query(load_cypher("save_impact_draft"), params).result_set
    return json.loads(rows[0][0]) if rows else None


def list_drafts(db: HiveDB, tenant: str) -> list[dict[str, Any]]:
    import json

    rows = db.ro(tenant).ro_query(load_cypher("impact_drafts"), timeout=3000).result_set
    return [json.loads(row[0]) for row in rows]
