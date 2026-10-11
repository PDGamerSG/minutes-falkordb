"""Deterministic counterpart of the graph impact queries for API unit tests."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import Any


def import_manifest(hive: Any, tenant: str, data: dict[str, Any]) -> int:
    items = data["items"]
    if not items or len(items) > 200 or len({i["id"] for i in items}) != len(items):
        raise ValueError("manifest needs 1–200 distinct work items")
    if any(not hive.get_fact(tenant, i["baseline_fact_id"]) or not hive.get_person(tenant, i["owner_id"]) for i in items):
        raise ValueError("manifest reference not found in this tenant")
    for item in items:
        hive._work_items[tenant][item["id"]] = deepcopy({**item, "document": data["document"]})
    return len(items)


def work_impacts(hive: Any, tenant: str) -> dict[str, Any]:
    facts = hive.store(tenant).facts

    def path(start: str, target: str) -> list[str]:
        frontier = deque([[start]])
        while frontier:
            route = frontier.popleft()
            if route[-1] == target:
                return route
            if len(route) > 24:
                continue
            for previous in (facts.get(route[-1]) or {}).get("supersedes", []):
                if previous not in route:
                    frontier.append([*route, previous])
        return []

    rows = []
    for item in sorted(hive._work_items.get(tenant, {}).values(), key=lambda i: i["id"])[:200]:
        baseline = facts.get(item["baseline_fact_id"])
        if not baseline:
            continue
        candidates = [{"fact": deepcopy(f), "via": path(f["id"], baseline["id"])}
                      for f in facts.values() if f["status"] == "active" and f["key"] == baseline["key"]]
        rows.append({"item": {k: item[k] for k in ("id", "title", "status", "rationale")},
                     "baseline": deepcopy(baseline), "owner": deepcopy(hive.get_person(tenant, item["owner_id"])),
                     "document": deepcopy(item["document"]), "candidates": candidates})
    return {"rows": rows, "cypher": "-- Explicit dependency traversal (81_work_impacts.cypher in FalkorDB)"}


def save_draft(hive: Any, tenant: str, draft: dict[str, Any]) -> dict[str, Any] | None:
    from .impact_service import assessment

    row = next((r for r in work_impacts(hive, tenant)["rows"] if r["item"]["id"] == draft["work_item_id"]), None)
    if not row:
        return None
    state, _, chosen = assessment(row)
    if (state != "needs_review" or chosen["fact"]["id"] != draft["current_fact_id"]
            or row["baseline"]["id"] != draft["baseline_fact_id"]
            or row["owner"]["id"] != draft["owner_id"] or row["document"]["id"] != draft["document_id"]):
        return None
    return deepcopy(hive._impact_drafts[tenant].setdefault(draft["id"], deepcopy(draft)))
