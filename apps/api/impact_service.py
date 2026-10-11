"""Grounded decision impact: explicit dependency + supersession path + accountable work."""

from __future__ import annotations

import hashlib
import json
from itertools import pairwise
from typing import Any

from ingest.fakes import now_ms

from .errors import ApiError
from .routes.memory import fact_view


def assessment(row: dict[str, Any]) -> tuple[str, str, dict[str, Any] | None]:
    candidates = {c["fact"]["id"]: c for c in row["candidates"]}
    chosen = next(iter(candidates.values())) if len(candidates) == 1 else None
    current = chosen["fact"] if chosen else None
    if row["item"]["status"] != "open":
        reachable = chosen if chosen and chosen.get("via") else None
        return "closed", "This work is already closed; no follow-up is needed.", reachable
    if row["baseline"]["status"] == "retracted" or not chosen or not chosen.get("via") or not row.get("owner"):
        return "unresolved", "The graph cannot establish one current decision and owner for this dependency.", None
    if current["id"] == row["baseline"]["id"] or current["object"] == row["baseline"]["object"]:
        return "aligned", "This work still matches the current recorded decision.", chosen
    return "needs_review", "The decision this open work depends on has changed.", chosen


def draft_identity(tenant: str, row: dict[str, Any], current: dict[str, Any]) -> str:
    values = [tenant, row["item"]["id"], row["baseline"]["id"], current["id"],
              row["document"]["id"], row["owner"]["id"]]
    return "draft_" + hashlib.sha256(json.dumps(values).encode()).hexdigest()[:24]


def impact_report(hive: Any, tenant: str) -> dict[str, Any]:
    result = hive.work_impacts(tenant)
    drafts = {d["id"]: d for d in hive.list_impact_drafts(tenant)}
    facts = {f["id"]: f for f in hive.list_facts(tenant, status="all")} if result["rows"] else {}
    summary = {"tracked": len(result["rows"]), "needs_review": 0, "aligned": 0, "closed": 0, "unresolved": 0}
    items = []
    for row in result["rows"]:
        state, reason, chosen = assessment(row)
        summary[state] += 1
        baseline = fact_view(facts.get(row["baseline"]["id"]) or row["baseline"])
        current = fact_view(facts.get(chosen["fact"]["id"]) or chosen["fact"]) if chosen else None
        item, owner, document = row["item"], row["owner"], row["document"]
        ids = chosen["via"] if chosen else [baseline["id"]]
        nodes = [{"id": fid, "label": "Fact", "props": fact_view(facts.get(fid) or {"id": fid})} for fid in ids]
        nodes.extend([{"id": item["id"], "label": "WorkItem", "props": item},
                      {"id": document["id"], "label": "Document", "props": document}])
        edges = [{"source": a, "target": b, "type": "SUPERSEDES", "props": {}} for a, b in pairwise(ids)]
        edges.extend([{"source": item["id"], "target": baseline["id"], "type": "DEPENDS_ON", "props": {}},
                      {"source": item["id"], "target": document["id"], "type": "DOCUMENTED_IN", "props": {}}])
        if owner:
            nodes.append({"id": owner["id"], "label": "Person", "props": owner})
            edges.append({"source": item["id"], "target": owner["id"], "type": "OWNED_BY", "props": {}})
        draft_id = draft_identity(tenant, row, current) if current and owner and state == "needs_review" else None
        items.append({**item, "owner": owner, "assessment": state, "reason": reason, "baseline": baseline,
                      "current": current, "document": document, "path": {"nodes": nodes, "edges": edges},
                      "draft": drafts.get(draft_id)})
    order = {"needs_review": 0, "unresolved": 1, "aligned": 2, "closed": 3}
    items.sort(key=lambda i: (order[i["assessment"]], i["id"]))
    return {"summary": summary, "items": items, "cypher": result.get("cypher", "")}


def prepare_draft(hive: Any, tenant: str, work_id: str, current_fact_id: str) -> dict[str, Any]:
    row = next((r for r in hive.work_impacts(tenant)["rows"] if r["item"]["id"] == work_id), None)
    if row is None:
        raise ApiError(404, "work_not_found", "Work item not found in this team.")
    state, _, chosen = assessment(row)
    if state != "needs_review" or chosen["fact"]["id"] != current_fact_id:
        raise ApiError(409, "impact_changed", "This dependency changed or no longer needs review. Refresh the impact list.")
    current = hive.get_fact(tenant, current_fact_id) or chosen["fact"]
    baseline, item, owner, doc = row["baseline"], row["item"], row["owner"], row["document"]
    source = (current.get("meeting") or {}).get("title") or (current.get("thread") or {}).get("subject") or "recorded source"
    body = (f"{owner['name']}, please review “{item['title']}”.\n\n"
            f"{baseline['subject']} · {baseline['predicate'].replace('_', ' ')} changed from "
            f"{baseline['object']} to {current['object']}.\n"
            f"Previous evidence: [{baseline['id']}]. Current evidence: [{current['id']}] in {source}.\n\n"
            f"Why this work is affected: {item['rationale']}\n"
            f"Dependency recorded in {doc['title']} [{doc['id']}].\n\n"
            "Please confirm whether the work or its delivery plan needs updating. This is a local draft; nothing has been sent.")
    draft = {"id": draft_identity(tenant, row, current), "status": "draft", "created_at": now_ms(),
             "title": f"Review {item['title']}", "body": body, "work_item_id": work_id,
             "baseline_fact_id": baseline["id"], "current_fact_id": current_fact_id,
             "owner_id": owner["id"], "document_id": doc["id"]}
    saved = hive.save_impact_draft(tenant, draft)
    if saved is None:
        raise ApiError(409, "impact_changed", "The graph changed while preparing the draft. Refresh and try again.")
    return saved
