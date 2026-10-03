"""Episodic memory (Meeting/EmailThread -> Episode) and semantic memory (bi-temporal Fact/Decision/Commitment),
with provenance edges, supersession, belief-at-T, Why paths, hybrid recall and full-text lookup."""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from falkordb import Graph
from redis.exceptions import ResponseError

from .db import HiveDB
from .errors import Conflict, NotFound
from .events import publish
from .ids import new_id, slugify
from .queries import load_cypher
from .records import CypherRows, Record, Subgraph, brief, compact, get, labels_of, props
from .temporal import now_ms, to_ms
from .udf.loader import load_udfs

RO_TIMEOUT_MS = 3000
RECALL_LABELS = ("Fact", "Episode", "Skill", "Entity")
FULLTEXT_LABELS = ("Episode", "Fact", "Decision")
FACT_KINDS = ("fact", "decision", "commitment")
_BATCH = 200
_FT_CLEAN = re.compile(r"[^A-Za-z0-9 ]+")


def _vec(embedding: list[float] | None) -> list[float] | None:
    return None if embedding is None else [float(x) for x in embedding]


def _first(res) -> Any:
    return res.result_set[0][0] if res.result_set else None


# -- people and containers -------------------------------------------------------------------
def remember_person(db: HiveDB, tenant: str, person: dict) -> str:
    """Upsert `{id?, name, role?, email?}`; without an id the id is `per_<slug(name)>`."""
    return remember_people(db, tenant, [person])[0]


def remember_people(db: HiveDB, tenant: str, people: list[dict]) -> list[str]:
    """Batch form of remember_person (one UNWIND)."""
    rows = [
        {
            "id": p.get("id") or f"per_{slugify(p['name'])}",
            "name": p.get("name"),
            "role": p.get("role"),
            "email": p.get("email"),
        }
        for p in people
    ]
    if rows:
        db.graph(tenant).query(load_cypher("upsert_person"), {"rows": rows})
    return [r["id"] for r in rows]


def remember_meeting(db: HiveDB, tenant: str, meeting: dict) -> str:
    """Upsert `{id?, title, started_at, ended_at?, source_uri?}` (timestamps: epoch ms or ISO)."""
    mid = meeting.get("id") or new_id("mtg")
    row = {
        "id": mid,
        "title": meeting.get("title"),
        "started_at": to_ms(meeting.get("started_at")),
        "ended_at": to_ms(meeting.get("ended_at")),
        "source_uri": meeting.get("source_uri"),
    }
    db.graph(tenant).query(load_cypher("upsert_meeting"), {"rows": [row]})
    return mid


def remember_thread(db: HiveDB, tenant: str, thread: dict) -> str:
    """Upsert an EmailThread `{id?, subject, started_at}`."""
    tid = thread.get("id") or new_id("thr")
    row = {"id": tid, "subject": thread.get("subject"), "started_at": to_ms(thread.get("started_at"))}
    db.graph(tenant).query(load_cypher("upsert_thread"), {"rows": [row]})
    return tid


# -- episodes ----------------------------------------------------------------------------------
def _episode_row(ep: dict, source_kind: str) -> dict:
    now = now_ms()
    return {
        "id": ep.get("id") or new_id("ep"),
        "seq": int(ep["seq"]),
        "text": ep["text"],
        "t_start": to_ms(ep.get("t_start")),
        "t_end": to_ms(ep.get("t_end")),
        "t_occurred": to_ms(ep.get("t_occurred")) or now,
        "source_kind": ep.get("source_kind") or source_kind,
        "speaker_id": ep.get("speaker_id"),
        "sender_id": ep.get("sender_id"),
        "recipients": [{"id": x, "cc": False} for x in ep.get("to_ids") or []]
        + [{"id": x, "cc": True} for x in ep.get("cc_ids") or []],
        "in_reply_to_id": ep.get("in_reply_to_episode_id"),
        "message_id": ep.get("message_id"),
        "embedding": _vec(ep.get("embedding")),
    }


def _ingest_episode_rows(db: HiveDB, tenant: str, container_id: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    graph = db.graph(tenant)
    rows.sort(key=lambda r: r["seq"])
    prev = _first(graph.query(load_cypher("last_episode"), {"container_id": container_id}))
    for row in rows:
        row["prev_id"] = prev
        prev = row["id"]
    now = now_ms()
    total = 0
    for i in range(0, len(rows), _BATCH):
        res = graph.query(
            load_cypher("ingest_episode"),
            {"container_id": container_id, "rows": rows[i : i + _BATCH], "now": now},
        )
        total += int(_first(res) or 0)
    if total == 0:
        raise NotFound(f"container {container_id!r} does not exist in team_{tenant}")
    publish(
        db,
        tenant,
        "episode.ingested",
        {"container_id": container_id, "count": total, "source_kind": rows[0]["source_kind"]},
    )
    return total


def remember_episodes(db: HiveDB, tenant: str, meeting_id: str, episodes: list[dict]) -> int:
    """Utterance episodes `{id?, seq, speaker_id, text, t_start, t_end, t_occurred, embedding?}` under a Meeting.
    Creates HAS_EPISODE, SPOKEN_BY, ATTENDED and the NEXT chain (continuing any earlier batch)."""
    return _ingest_episode_rows(db, tenant, meeting_id, [_episode_row(ep, "utterance") for ep in episodes])


def remember_email_episodes(db: HiveDB, tenant: str, thread_id: str, episodes: list[dict]) -> int:
    """Email episodes `{id?, seq, sender_id, to_ids, cc_ids, in_reply_to_episode_id?, text, t_occurred, message_id?, embedding?}`
    under an EmailThread. Creates HAS_EPISODE, SENT_BY, SENT_TO{cc}, REPLIES_TO and NEXT; source_kind = 'email'."""
    rows = []
    for ep in episodes:
        row = _episode_row(ep, "email")
        row["message_id"] = row["message_id"] or row["id"]
        rows.append(row)
    return _ingest_episode_rows(db, tenant, thread_id, rows)


# -- entities ----------------------------------------------------------------------------------
def upsert_entities(db: HiveDB, tenant: str, entities: list[dict]) -> dict[str, str]:
    """MERGE on name; returns `{name: effective_id}` (an existing entity keeps its id)."""
    rows = [
        {
            "id": e.get("id") or f"ent_{slugify(e['name'])}",
            "name": e["name"].strip(),
            "type": e.get("type"),
            "embedding": _vec(e.get("embedding")),
        }
        for e in entities
    ]
    if not rows:
        return {}
    res = db.graph(tenant).query(load_cypher("upsert_entity"), {"rows": rows, "now": now_ms()})
    return {name: eid for name, eid in res.result_set}


def remember_entities(db: HiveDB, tenant: str, entities: list[dict]) -> int:
    """`{id?, name, type, embedding?}` MERGEd on name; returns how many were upserted."""
    return len(upsert_entities(db, tenant, entities))


def link_mentions(db: HiveDB, tenant: str, episode_id: str, entity_ids: list[str]) -> int:
    """Episode -[:MENTIONS]-> Entity edges (plus CO_MENTIONED between the entities); returns the mention count."""
    if not entity_ids:
        return 0
    res = db.graph(tenant).query(
        load_cypher("link_mentions"), {"episode_id": episode_id, "entity_ids": list(entity_ids)}
    )
    return int(_first(res) or 0)


# -- facts -------------------------------------------------------------------------------------
def fact_key(subject: str, predicate: str) -> str:
    """`subject|predicate`, lower-cased and trimmed: the supersession key."""
    return f"{subject.strip()}|{predicate.strip()}".lower()


def _fact_row(fact: dict, fid: str) -> dict:
    kind = fact.get("kind") or "fact"
    if kind not in FACT_KINDS:
        raise ValueError(f"kind must be one of {FACT_KINDS}, got {kind!r}")
    return {
        "id": fid,
        "kind": kind,
        "subject": fact["subject"],
        "predicate": fact["predicate"],
        "object": fact["object"],
        "key": fact_key(fact["subject"], fact["predicate"]),
        "text": fact.get("text") or f"{fact['subject']} {fact['predicate']} {fact['object']}",
        "confidence": float(fact.get("confidence", 0.5)),
        "valid_from": to_ms(fact.get("valid_from")),
        "due_at": to_ms(fact.get("due_at")),
        "speaker_id": fact.get("speaker_id"),
        "owner_id": fact.get("owner_id"),
        "episode_id": fact.get("episode_id"),
        "entity_ids": list(fact.get("entity_ids") or []),
        "embedding": _vec(fact.get("embedding")),
    }


_FACT_KEYS = (
    "id",
    "kind",
    "subject",
    "predicate",
    "object",
    "key",
    "text",
    "confidence",
    "status",
    "valid_from",
    "valid_to",
    "created_at",
    "expired_at",
    "due_at",
)


def fact_props(f: Record) -> dict:
    """Fact props (Node or projection) with every bi-temporal key present: FalkorDB drops properties set to
    NULL, so `valid_to`, `expired_at` and `due_at` are filled with None for a stable record shape."""
    rec = props(f) or {}
    for key in _FACT_KEYS:
        rec.setdefault(key, None)
    return rec


def _fact_record(
    f: Record,
    entities: list,
    speaker: Record | None = None,
    episode_id: str | None = None,
    container: Record | None = None,
) -> dict:
    rec = fact_props(f)
    rec["entities"] = [brief(e, "id", "name", "type") for e in entities]
    rec["speaker"] = brief(speaker)
    rec["episode_id"] = episode_id
    labels = labels_of(container)
    rec["meeting"] = brief(container, "id", "title") if "Meeting" in labels else None
    rec["thread"] = brief(container, "id", "subject") if "EmailThread" in labels else None
    return rec


def _active_by_key(graph: Graph, key: str) -> list[dict]:
    res = graph.query(load_cypher("active_facts"), {"entity": None, "key": key, "limit": 100})
    return [_fact_record(*row) for row in res.result_set]


def _link_supersedes(graph: Graph, new_id_: str, old_ids: list[str], now: int) -> list[str]:
    res = graph.query(load_cypher("supersede_fact"), {"new_id": new_id_, "old_ids": old_ids, "now": now})
    return list(_first(res) or [])


def _publish_fact_events(db: HiveDB, tenant: str, fid: str, row: dict, superseded: list[str]) -> None:
    body = {
        "id": fid,
        "kind": row["kind"],
        "key": row["key"],
        "subject": row["subject"],
        "predicate": row["predicate"],
        "object": row["object"],
        "text": row["text"],
        "speaker_id": row["speaker_id"],
        "episode_id": row["episode_id"],
        "due_at": row["due_at"],
    }
    publish(db, tenant, "fact.created", body)
    if row["kind"] == "commitment":
        publish(db, tenant, "commitment.created", body)
    if superseded:
        publish(
            db,
            tenant,
            "fact.superseded",
            {
                "new_id": fid,
                "old_ids": superseded,
                "key": row["key"],
                "kind": row["kind"],
                "object": row["object"],
            },
        )
        if row["kind"] == "commitment":
            publish(
                db, tenant, "commitment.updated", {"id": fid, "replaces": superseded, "due_at": row["due_at"]}
            )


def remember_fact(db: HiveDB, tenant: str, fact: dict, supersede: bool = False) -> dict[str, Any]:
    """Ingest `{id?, subject, predicate, object, text, confidence, speaker_id, episode_id, entity_ids, kind, due_at?, valid_from?, embedding?}`.

    key = `subject|predicate` lower-cased. An identical ACTIVE fact (same key and object) is returned as-is
    (`existing: True`). ACTIVE facts with the same key and a different object are returned under `conflicts`,
    or expired and linked with SUPERSEDES when `supersede=True` (`superseded`)."""
    graph = db.graph(tenant)
    now = now_ms()
    fid = fact.get("id") or new_id("fact")
    row = _fact_row(fact, fid)
    existing = _active_by_key(graph, row["key"])
    same = [f["id"] for f in existing if f.get("object") == row["object"] and f["id"] != fid]
    if same and not fact.get("id"):
        return {"id": same[0], "superseded": [], "conflicts": [], "existing": True}
    conflicts = [f["id"] for f in existing if f.get("object") != row["object"] and f["id"] != fid]
    graph.query(load_cypher("ingest_fact"), {"rows": [row], "now": now})
    superseded = _link_supersedes(graph, fid, conflicts, now) if supersede and conflicts else []
    _publish_fact_events(db, tenant, fid, row, superseded)
    return {
        "id": fid,
        "superseded": superseded,
        "conflicts": [] if supersede else conflicts,
        "existing": False,
    }


def supersede_fact(db: HiveDB, tenant: str, old_id: str, new_fact: dict) -> dict[str, Any]:
    """Explicit supersession: ingest `new_fact`, expire `old_id` (valid_to = new.valid_from) and link new -[:SUPERSEDES]-> old."""
    graph = db.graph(tenant)
    status = graph.query(load_cypher("fact_status"), {"id": old_id}).result_set
    if not status:
        raise NotFound(f"fact {old_id!r} does not exist in team_{tenant}")
    if status[0][1] != "active":
        raise Conflict(f"fact {old_id!r} is {status[0][1]!r}, only ACTIVE facts can be superseded")
    now = now_ms()
    fid = new_fact.get("id") or new_id("fact")
    row = _fact_row(new_fact, fid)
    graph.query(load_cypher("ingest_fact"), {"rows": [row], "now": now})
    superseded = _link_supersedes(graph, fid, [old_id], now)
    _publish_fact_events(db, tenant, fid, row, superseded)
    return {"id": fid, "superseded": superseded}


def retract_fact(db: HiveDB, tenant: str, fact_id: str, reason: str) -> None:
    """Mark a fact `retracted` (never true); it disappears from belief_at for every T."""
    res = db.graph(tenant).query(
        load_cypher("retract_fact"), {"id": fact_id, "reason": reason, "now": now_ms()}
    )
    if not res.result_set:
        raise NotFound(f"fact {fact_id!r} does not exist in team_{tenant}")


def active_facts(
    db: HiveDB, tenant: str, entity_id: str | None = None, key: str | None = None, limit: int = 200
) -> CypherRows:
    """ACTIVE facts (optionally for one entity id and/or key) with speaker, entities and source container."""
    query = load_cypher("active_facts")
    res = db.ro(tenant).ro_query(
        query, {"entity": entity_id, "key": key, "limit": limit}, timeout=RO_TIMEOUT_MS
    )
    return CypherRows([_fact_record(*row) for row in res.result_set], query)


def belief_at(
    db: HiveDB, tenant: str, t: int, entity_id: str | None = None, known_by: int | None = None
) -> CypherRows:
    """Facts true at valid time `t` (`valid_from <= t < valid_to`), optionally only those ingested by `known_by`."""
    query = load_cypher("belief_at_time")
    res = db.ro(tenant).ro_query(
        query, {"t": int(t), "entity": entity_id, "known_by": known_by}, timeout=RO_TIMEOUT_MS
    )
    return CypherRows([_fact_record(f, entities, speaker) for f, entities, speaker in res.result_set], query)


# -- why ---------------------------------------------------------------------------------------
def _source(ep: Record | None, meeting: Record | None, thread: Record | None) -> dict | None:
    """`{kind, episode_id, container: {id, title|subject, ...}, t_start/t_end | sent_at/message_id}` for the Why panel."""
    if ep is None:
        return None
    kind = get(ep, "source_kind") or "utterance"
    source: dict[str, Any] = {"kind": kind, "episode_id": get(ep, "id"), "container": None}
    if meeting is not None:
        source["container"] = {
            "id": get(meeting, "id"),
            "title": get(meeting, "title"),
            "source_uri": get(meeting, "source_uri"),
            "label": "Meeting",
        }
    elif thread is not None:
        source["container"] = {
            "id": get(thread, "id"),
            "subject": get(thread, "subject"),
            "label": "EmailThread",
        }
    if kind == "email":
        source["sent_at"] = get(ep, "t_occurred")
        source["message_id"] = get(ep, "message_id")
    else:
        source["t_start"] = get(ep, "t_start")
        source["t_end"] = get(ep, "t_end")
    return source


def why(db: HiveDB, tenant: str, node_id: str) -> dict[str, Any]:
    """Provenance of a Fact/Decision/Commitment: speaker, meeting or email thread, episode, SUPERSEDES chain, subgraph."""
    query = load_cypher("why_path")
    res = db.ro(tenant).ro_query(query, {"id": node_id}, timeout=RO_TIMEOUT_MS)
    if not res.result_set:
        raise NotFound(f"no Fact/Decision/Commitment with id {node_id!r} in team_{tenant}")
    f, ep, speaker, meeting, thread, entities, older, newer = res.result_set[0]

    def by_time(n: Record) -> int:
        return get(n, "valid_from") or 0

    older = sorted(older, key=by_time, reverse=True)
    newer = sorted(newer, key=by_time, reverse=True)
    chain = newer + [f] + older

    sub = Subgraph()
    fid = sub.add_node(f)
    ep_id = sub.add_node(ep)
    sub.add_edge(fid, ep_id, "DERIVED_FROM")
    sp_id = sub.add_node(speaker)
    if ep is not None:
        sub.add_edge(ep_id, sp_id, "SENT_BY" if get(ep, "source_kind") == "email" else "SPOKEN_BY")
    else:
        sub.add_edge(fid, sp_id, "STATED_BY")
    sub.add_edge(sub.add_node(meeting), ep_id, "HAS_EPISODE")
    sub.add_edge(sub.add_node(thread), ep_id, "HAS_EPISODE")
    for en in entities:
        sub.add_edge(fid, sub.add_node(en), "ABOUT")
    for a, b in pairwise(chain):
        sub.add_edge(sub.add_node(a), sub.add_node(b), "SUPERSEDES")

    return {
        "node": fact_props(f),
        "speaker": props(speaker),
        "meeting": props(meeting),
        "thread": props(thread),
        "episode": props(ep),
        "source": _source(ep, meeting, thread),
        "entities": [brief(e, "id", "name", "type") for e in entities],
        "history": [fact_props(n) for n in chain],
        "superseded_by": [fact_props(n) for n in newer],
        "supersedes": [fact_props(n) for n in older],
        "cypher": query,
        "subgraph": sub.to_dict(),
    }


# -- recall ------------------------------------------------------------------------------------
def recall(
    db: HiveDB,
    tenant: str,
    query_embedding: list[float],
    k: int = 8,
    now: int | None = None,
    label: str = "Fact",
) -> dict[str, Any]:
    """Hybrid recall: vector KNN over `label` -> 1-hop expansion through shared entities -> `hive.score` ranking."""
    if label not in RECALL_LABELS:
        raise ValueError(f"label must be one of {RECALL_LABELS}, got {label!r}")
    query = load_cypher("recall_hybrid")
    now = now or now_ms()
    params = {"label": label, "q": _vec(query_embedding), "n": max(20, k * 3), "k": int(k), "now": now}
    try:
        res = db.ro(tenant).ro_query(query, params, timeout=RO_TIMEOUT_MS)
    except ResponseError as exc:
        if "hive" not in str(exc).lower():
            raise
        load_udfs(db)
        res = db.ro(tenant).ro_query(query, params, timeout=RO_TIMEOUT_MS)

    sub = Subgraph()
    items = []
    for f, distance, entities, neighbours, rank in res.result_set:
        fid = sub.add_node(f)
        entity_ids = [sub.add_node(e) for e in entities]
        for eid in entity_ids:
            sub.add_edge(fid, eid, "ABOUT")
        for g in neighbours:
            gid = sub.add_node(g)
            for eid in entity_ids:
                sub.add_edge(gid, eid, "ABOUT")
        items.append(
            {
                "node": fact_props(f) if "Fact" in labels_of(f) else compact(props(f)),
                "id": get(f, "id"),
                "distance": distance,
                "similarity": max(0.0, min(1.0, 1.0 - distance)),
                "rank": rank,
                "entities": [brief(e, "id", "name", "type") for e in entities],
                "neighbours": [compact(props(g)) for g in neighbours],
            }
        )
    return {"items": items, "cypher": query, "subgraph": sub.to_dict(), "label": label, "k": k, "now": now}


# -- full-text ---------------------------------------------------------------------------------
def sanitize_fulltext(text: str) -> str:
    """Keep `[A-Za-z0-9]` tokens only (a bare underscore or operator breaks the RediSearch tokenizer) and OR them,
    so a query matches episodes containing any of the words; RediSearch scores multi-word matches higher."""
    return "|".join(_FT_CLEAN.sub(" ", text).split())


def fulltext(db: HiveDB, tenant: str, text: str, label: str = "Episode", k: int = 10) -> CypherRows:
    """Full-text search over `label`.text (Episode, Fact or Decision); rows are node props plus `score`."""
    if label not in FULLTEXT_LABELS:
        raise ValueError(f"label must be one of {FULLTEXT_LABELS}, got {label!r}")
    query = load_cypher("fulltext")
    clean = sanitize_fulltext(text)
    if not clean:
        return CypherRows([], query)
    res = db.ro(tenant).ro_query(query, {"label": label, "q": clean, "k": int(k)}, timeout=RO_TIMEOUT_MS)
    rows = []
    for node, score in res.result_set:
        rec = props(node) or {}
        rec["score"] = score
        rows.append(rec)
    return CypherRows(rows, query)
