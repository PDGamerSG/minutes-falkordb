"""Track 3 queries: who knows about X, open commitments, contradictions, entity clusters (WCC), stale decisions."""

from __future__ import annotations

from .db import HiveDB
from .queries import load_cypher
from .records import CypherRows, brief, props
from .temporal import now_ms

RO_TIMEOUT_MS = 3000


def owners(db: HiveDB, tenant: str, entity_name: str) -> CypherRows:
    """Explicit assignments (or commitment owners when absent), with citable fact ids."""
    query = load_cypher("owners")
    res = db.ro(tenant).ro_query(query, {"name": entity_name}, timeout=RO_TIMEOUT_MS)
    return CypherRows([
        {"fact_id": fid, "person": {"id": pid, "name": name}}
        for fid, pid, name in res.result_set
    ], query)


def who_knows(db: HiveDB, tenant: str, entity_name: str) -> CypherRows:
    """People ranked by how many episodes mentioning the entity they spoke, sent or received."""
    query = load_cypher("who_knows")
    res = db.ro(tenant).ro_query(query, {"name": entity_name}, timeout=RO_TIMEOUT_MS)
    rows = [
        {"person": {"id": pid, "name": name}, "mentions": mentions, "last_at": last_at, "via": via}
        for pid, name, mentions, last_at, via in res.result_set
    ]
    return CypherRows(rows, query)


def open_commitments(db: HiveDB, tenant: str, person_id: str | None = None) -> CypherRows:
    """ACTIVE commitments (optionally one owner), soonest due first, with `owner`, `speaker` and `entities`."""
    query = load_cypher("open_commitments")
    res = db.ro(tenant).ro_query(query, {"person": person_id}, timeout=RO_TIMEOUT_MS)
    rows = []
    for c, owner, speaker, entities in res.result_set:
        rec = props(c) or {}
        rec["owner"] = brief(owner)
        rec["speaker"] = brief(speaker)
        rec["entities"] = [brief(e, "id", "name", "type") for e in entities]
        rows.append(rec)
    return CypherRows(rows, query)


def contradictions(db: HiveDB, tenant: str) -> CypherRows:
    """Pairs of ACTIVE facts sharing a key with different objects: `[{key, facts: [a, b]}]`."""
    query = load_cypher("contradictions")
    res = db.ro(tenant).ro_query(query, timeout=RO_TIMEOUT_MS)
    return CypherRows([{"key": key, "facts": [props(a), props(b)]} for key, a, b in res.result_set], query)


def entity_clusters(db: HiveDB, tenant: str) -> CypherRows:
    """`algo.WCC` over Entity nodes linked by CO_MENTIONED: `[{component, entities: [{id, name, type}]}]`."""
    query = load_cypher("wcc_entities")
    res = db.ro(tenant).ro_query(query, timeout=RO_TIMEOUT_MS)
    return CypherRows(
        [{"component": comp, "entities": [dict(e) for e in ents]} for comp, ents in res.result_set], query
    )


def stale_decisions(db: HiveDB, tenant: str, older_than_ms: int) -> CypherRows:
    """ACTIVE decisions older than `older_than_ms` (an age, not a timestamp) with decider, entities and `age_ms`."""
    query = load_cypher("stale_decisions")
    now = now_ms()
    res = db.ro(tenant).ro_query(query, {"cutoff": now - int(older_than_ms)}, timeout=RO_TIMEOUT_MS)
    rows = []
    for d, decider, entities in res.result_set:
        rec = props(d) or {}
        rec["decider"] = brief(decider)
        rec["entities"] = [brief(e, "id", "name", "type") for e in entities]
        rec["age_ms"] = now - int(rec.get("decided_at") or rec.get("valid_from") or now)
        rows.append(rec)
    return CypherRows(rows, query)
