"""Episodic memory (Meeting/EmailThread -> Episode) and semantic memory (bi-temporal Fact/Decision/Commitment),
with provenance edges, supersession, belief-at-T, Why paths, hybrid recall and full-text lookup.

Every fact write (`remember_fact`, `supersede_fact`, `insert_fact_in_chain`) is ONE Cypher statement, so FalkorDB's
per-graph write serialisation makes it atomic: concurrent writers cannot leave two active facts on a key, insert the
same fact twice, or let a chain supersede itself."""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from redis.exceptions import ResponseError

from .db import HiveDB
from .embed import validate_embedding
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
DEFAULT_LIMIT = 500
_BATCH = 200
_FT_CLEAN = re.compile(r"[^A-Za-z0-9 ]+")
_UDF_MISSING = "unknown function 'hive.score'"


def _vec(embedding: list[float] | None) -> list[float] | None:
    """Floats or None; raises ValueError unless the vector has exactly 768 dimensions (finding 10)."""
    return validate_embedding(embedding)


def _first(res) -> Any:
    return res.result_set[0][0] if res.result_set else None


def normalize_object(value: Any) -> str:
    """Comparison form of a fact object: trimmed and lower-cased (finding 27). Mirrors `toLower(trim(x))` in Cypher."""
    return "" if value is None else str(value).strip().lower()


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


def _relink_next(graph, container_id: str, from_seq: int) -> None:
    """Make the NEXT chain linear over the window of episodes from `from_seq` on (finding 7). Read the window in seq order,
    drop NEXT edges that leave a window node for anything but its successor, then MERGE the intended edges. Two statements
    on purpose: FalkorDB runs FOREACH writes only after a whole batch has matched, so one per-row statement cannot see
    the edges its own earlier rows rewired."""
    ids = [r[0] for r in graph.query(
        load_cypher("episode_window"), {"container_id": container_id, "from_seq": from_seq}
    ).result_set]
    nodes = [{"id": a, "next": b} for a, b in zip(ids, ids[1:])] + ([{"id": ids[-1], "next": None}] if ids else [])
    if not nodes:
        return
    graph.query(load_cypher("relink_next"), {"nodes": nodes})
    graph.query(load_cypher("link_next"), {"nodes": [n for n in nodes if n["next"]]})


def _ingest_episode_rows(db: HiveDB, tenant: str, container_id: str, rows: list[dict]) -> int:
    """Write one batch of episodes and publish exactly one `episode.ingested` for the batch (see EVENTS.md)."""
    if not rows:
        return 0
    graph = db.graph(tenant)
    rows.sort(key=lambda r: r["seq"])
    prev = graph.query(
        load_cypher("last_episode"), {"container_id": container_id, "before_seq": rows[0]["seq"]}
    ).result_set
    from_seq = prev[0][1] if prev else 0
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
    _relink_next(graph, container_id, from_seq)
    publish(
        db,
        tenant,
        "episode.ingested",
        {
            "container_id": container_id,
            "count": total,
            "source_kind": rows[0]["source_kind"],
            "first_episode_id": rows[0]["id"],
            "last_episode_id": rows[-1]["id"],
            "t_first": rows[0]["t_occurred"],
            "t_last": rows[-1]["t_occurred"],
            "tenant": tenant,
        },
    )
    return total


def remember_episodes(db: HiveDB, tenant: str, meeting_id: str, episodes: list[dict]) -> int:
    """Utterance episodes `{id?, seq, speaker_id, text, t_start, t_end, t_occurred, embedding?}` under a Meeting.
    Creates HAS_EPISODE, SPOKEN_BY, ATTENDED and the NEXT chain (continuing any earlier batch; an out-of-order batch
    is spliced in so the chain stays linear). Publishes one `episode.ingested` per call."""
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
def entity_name_key(name: str) -> str:
    """`lower(trim(name))`: the MERGE key of Entity nodes (finding 6); `name` keeps the first display form."""
    return name.strip().lower()


def upsert_entities(db: HiveDB, tenant: str, entities: list[dict]) -> dict[str, str]:
    """MERGE on the normalised name (`name_key`); returns `{input name: effective_id}` (an existing entity keeps its id
    and its display name, so "UPI flow" and "UPI Flow" are one node)."""
    rows = [
        {
            "id": e.get("id") or f"ent_{slugify(e['name'])}",
            "name": e["name"].strip(),
            "name_key": entity_name_key(e["name"]),
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
    """`{id?, name, type, embedding?}` MERGEd on the normalised name; returns how many were upserted."""
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
    for required in ("subject", "predicate", "object"):
        if fact.get(required) is None:
            raise ValueError(f"fact needs a {required!r}")
    return {
        "id": fid,
        "kind": kind,
        "subject": fact["subject"],
        "predicate": fact["predicate"],
        "object": fact["object"],
        "object_norm": normalize_object(fact["object"]),
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


def _superseded_payload(
    tenant: str,
    row: dict,
    valid_from: int | None,
    old_facts: list[dict],
    head_changed: bool,
) -> dict:
    """The `fact.superseded` payload (superset schema, documented in events.py and EVENTS.md)."""
    old_ids = [o["id"] for o in old_facts]
    old_object = old_facts[0].get("object") if old_facts else None
    return {
        "new_fact_id": row["id"],
        "new_id": row["id"],
        "old_fact_id": old_ids[0] if old_ids else None,
        "old_fact_ids": old_ids,
        "old_ids": old_ids,
        "key": row["key"],
        "subject": row["subject"],
        "predicate": row["predicate"],
        "kind": row["kind"],
        "old_object": old_object,
        "new_object": row["object"],
        "object": row["object"],
        "valid_from": valid_from,
        "due_at": row["due_at"],
        "episode_id": row["episode_id"],
        "speaker_id": row["speaker_id"],
        "head_changed": head_changed,
        "tenant": tenant,
    }


def _publish_fact_events(
    db: HiveDB,
    tenant: str,
    row: dict,
    valid_from: int | None,
    superseded: list[dict],
    *,
    created: bool,
    head_changed: bool = True,
) -> None:
    """`fact.created` (+ `commitment.created`) when a fact was born ACTIVE; `fact.superseded` (+ `commitment.updated`)
    when something was expired. Facts born superseded by chain insertion never fire the created events."""
    if created:
        body = {
            "id": row["id"],
            "fact_id": row["id"],
            "kind": row["kind"],
            "key": row["key"],
            "subject": row["subject"],
            "predicate": row["predicate"],
            "object": row["object"],
            "text": row["text"],
            "speaker_id": row["speaker_id"],
            "episode_id": row["episode_id"],
            "due_at": row["due_at"],
            "valid_from": valid_from,
            "tenant": tenant,
        }
        publish(db, tenant, "fact.created", body)
        if row["kind"] == "commitment":
            publish(db, tenant, "commitment.created", {**body, "commitment_id": row["id"]})
    if superseded:
        payload = _superseded_payload(tenant, row, valid_from, superseded, head_changed)
        publish(db, tenant, "fact.superseded", payload)
        if row["kind"] == "commitment":
            publish(
                db,
                tenant,
                "commitment.updated",
                {
                    **payload,
                    "id": row["id"],
                    "commitment_id": row["id"],
                    "replaces": [o["id"] for o in superseded],
                },
            )


def remember_fact(db: HiveDB, tenant: str, fact: dict, supersede: bool = False) -> dict[str, Any]:
    """Ingest `{id?, subject, predicate, object, text, confidence, speaker_id, episode_id, entity_ids, kind, due_at?, valid_from?, embedding?}`
    in one atomic statement (18_remember_fact).

    key = `subject|predicate` lower-cased. An identical ACTIVE fact (same key, same trimmed lower-cased object) is returned
    as-is (`existing: True`, nothing written) unless an explicit `id` is given. ACTIVE facts with the same key and a different
    object are returned under `conflicts`, or expired and linked with SUPERSEDES when `supersede=True` (`superseded`).
    Raises Conflict when `supersede=True` and a conflicting fact is valid from LATER than this one: that is a late import
    of an earlier statement, use `insert_fact_in_chain`. Returns `{id, superseded, conflicts, existing}`."""
    fid = fact.get("id") or new_id("fact")
    row = _fact_row(fact, fid)
    res = db.graph(tenant).query(
        load_cypher("remember_fact"),
        {"row": row, "now": now_ms(), "supersede": bool(supersede), "explicit_id": bool(fact.get("id"))},
    )
    rid, existing, backdated, conflicts, valid_from, written = res.result_set[0]
    conflicts = [dict(c) for c in conflicts]
    if backdated:
        raise Conflict(
            f"fact {row['key']!r} is valid from {valid_from} but an active fact on that key is valid from later "
            f"({[c['id'] for c in conflicts]}); use insert_fact_in_chain for a late import of an earlier statement"
        )
    if existing:
        return {"id": rid, "superseded": [], "conflicts": [], "existing": True}
    superseded = conflicts if supersede else []
    _publish_fact_events(db, tenant, row, valid_from, superseded, created=bool(written))
    return {
        "id": fid,
        "superseded": [c["id"] for c in superseded],
        "conflicts": [] if supersede else [c["id"] for c in conflicts],
        "existing": False,
    }


def supersede_fact(db: HiveDB, tenant: str, old_id: str, new_fact: dict) -> dict[str, Any]:
    """Explicit supersession in one atomic statement (12_supersede_fact): ingest `new_fact`, expire `old_id`
    (valid_to = new.valid_from, expired_at = now) and link new -[:SUPERSEDES]-> old.

    Raises NotFound when `old_id` does not exist and Conflict when nothing was superseded: the old fact is not ACTIVE
    (a concurrent writer won), the keys differ, or `new.valid_from < old.valid_from` (use `insert_fact_in_chain`).
    Returns `{id, superseded: [old_id]}`."""
    fid = new_fact.get("id") or new_id("fact")
    row = _fact_row(new_fact, fid)
    res = db.graph(tenant).query(
        load_cypher("supersede_fact"), {"old_id": old_id, "row": row, "now": now_ms()}
    )
    if not res.result_set:
        raise NotFound(f"fact {old_id!r} does not exist in team_{tenant}")
    _rid, error, oid, old_object, old_due_at, old_valid_from, valid_from, _written = res.result_set[0]
    if error == "not_active":
        raise Conflict(f"fact {old_id!r} is no longer ACTIVE; only ACTIVE facts can be superseded")
    if error == "key_mismatch":
        raise Conflict(f"fact {old_id!r} has a different key than {row['key']!r}; supersession needs the same key")
    if error == "backdated":
        raise Conflict(
            f"new fact is valid from {valid_from}, before {old_id!r} ({old_valid_from}); use insert_fact_in_chain"
        )
    if error == "self":
        raise Conflict(f"fact {old_id!r} cannot supersede itself")
    if error:
        raise Conflict(f"supersede_fact refused: {error}")
    _publish_fact_events(
        db, tenant, row, valid_from, [{"id": oid, "object": old_object, "due_at": old_due_at}], created=True
    )
    return {"id": fid, "superseded": [oid]}


def insert_fact_in_chain(db: HiveDB, tenant: str, fact: dict, before_id: str) -> dict[str, Any]:
    """Late import of an EARLIER statement about a key, in one atomic statement (19_insert_fact_in_chain).

    The new fact is born `superseded` between the predecessor(s) of `before_id` and `before_id` (valid_from = its own,
    valid_to = before.valid_from, expired_at = now); SUPERSEDES edges are re-wired around it and the chain head is unchanged.
    If the statement restates a chain member (same key, same normalised object) or its id equals `before_id`, nothing is
    inserted: the existing fact gets DERIVED_FROM/CONFIRMED_BY links to the episode and `confirmed` is True.
    Publishes `fact.superseded` with `head_changed=False` when a predecessor was re-wired; never `fact.created`.
    Raises NotFound when `before_id` is missing and Conflict when the keys differ or `before` is not actually later.
    Returns `{id, inserted, confirmed, before_id, superseded}`."""
    fid = fact.get("id") or new_id("fact")
    row = _fact_row(fact, fid)
    res = db.graph(tenant).query(
        load_cypher("insert_fact_in_chain"), {"row": row, "before_id": before_id, "now": now_ms()}
    )
    if not res.result_set:
        raise NotFound(f"fact {before_id!r} does not exist in team_{tenant}")
    rid, inserted, confirmed, error, superseded, old_objects, bid, valid_from = res.result_set[0]
    if error == "key_mismatch":
        raise Conflict(f"fact {before_id!r} has a different key than {row['key']!r}")
    if error == "not_before":
        raise Conflict(
            f"fact {before_id!r} is not later than the new statement ({valid_from}); use remember_fact or supersede_fact"
        )
    if error:
        raise Conflict(f"insert_fact_in_chain refused: {error}")
    if inserted and superseded:
        olds = [{"id": oid, "object": obj} for oid, obj in zip(superseded, old_objects)]
        _publish_fact_events(db, tenant, row, valid_from, olds, created=False, head_changed=False)
    return {
        "id": rid,
        "inserted": bool(inserted),
        "confirmed": bool(confirmed),
        "before_id": bid,
        "superseded": list(superseded) if inserted else [],
    }


def retract_fact(db: HiveDB, tenant: str, fact_id: str, reason: str) -> None:
    """Mark a fact `retracted` (never true); it disappears from belief_at for every T (except views with `known_by`
    before the retraction)."""
    res = db.graph(tenant).query(
        load_cypher("retract_fact"), {"id": fact_id, "reason": reason, "now": now_ms()}
    )
    if not res.result_set:
        raise NotFound(f"fact {fact_id!r} does not exist in team_{tenant}")


def active_facts(
    db: HiveDB, tenant: str, entity_id: str | None = None, key: str | None = None, limit: int = DEFAULT_LIMIT
) -> CypherRows:
    """ACTIVE facts (optionally for one entity id and/or key) with speaker, entities and source container.
    With an entity the query starts from the Entity index (1A_active_facts_for_entity)."""
    if entity_id is not None:
        query = load_cypher("active_facts_for_entity")
        params = {"entity": entity_id, "key": key, "limit": int(limit)}
    else:
        query = load_cypher("active_facts")
        params = {"key": key, "limit": int(limit)}
    res = db.ro(tenant).ro_query(query, params, timeout=RO_TIMEOUT_MS)
    return CypherRows([_fact_record(*row) for row in res.result_set], query)


def belief_at(
    db: HiveDB,
    tenant: str,
    t: int,
    entity_id: str | None = None,
    known_by: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> CypherRows:
    """Facts true at valid time `t` (`valid_from <= t < valid_to`), optionally only those known by transaction time
    `known_by` (a fact superseded or retracted after `known_by` still counts as believed then)."""
    query = load_cypher("belief_at_time")
    res = db.ro(tenant).ro_query(
        query,
        {"t": int(t), "entity": entity_id, "known_by": known_by, "limit": int(limit)},
        timeout=RO_TIMEOUT_MS,
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
    """Provenance of a Fact/Decision/Commitment: speaker, meeting or email thread, the primary (earliest) episode plus
    every DERIVED_FROM episode under `episodes`, the SUPERSEDES chain and a subgraph for the UI."""
    query = load_cypher("why_path")
    res = db.ro(tenant).ro_query(query, {"id": node_id}, timeout=RO_TIMEOUT_MS)
    if not res.result_set:
        raise NotFound(f"no Fact/Decision/Commitment with id {node_id!r} in team_{tenant}")
    f, ep, speaker, meeting, thread, entities, older, newer, episodes = res.result_set[0]

    def by_time(n: Record) -> int:
        return get(n, "valid_from") or 0

    older = sorted(older, key=by_time, reverse=True)
    newer = sorted(newer, key=by_time, reverse=True)
    chain = newer + [f] + older
    episodes = sorted(
        (e for e in episodes if e is not None), key=lambda e: (get(e, "t_occurred") or 0, get(e, "seq") or 0)
    )

    sub = Subgraph()
    fid = sub.add_node(f)
    ep_id = sub.add_node(ep)
    sub.add_edge(fid, ep_id, "DERIVED_FROM")
    for extra in episodes[1:]:
        sub.add_edge(fid, sub.add_node(extra), "DERIVED_FROM")
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
        "episodes": [props(e) for e in episodes],
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
    """Hybrid recall: vector KNN over `label` -> 1-hop expansion through shared entities -> `hive.score` ranking.
    When the server reports `Unknown function 'hive.score'` (UDF library not loaded) it is loaded once and the query retried."""
    if label not in RECALL_LABELS:
        raise ValueError(f"label must be one of {RECALL_LABELS}, got {label!r}")
    query = load_cypher("recall_hybrid")
    now = now or now_ms()
    params = {"label": label, "q": _vec(query_embedding), "n": max(20, k * 3), "k": int(k), "now": now}
    try:
        res = db.ro(tenant).ro_query(query, params, timeout=RO_TIMEOUT_MS)
    except ResponseError as exc:
        if _UDF_MISSING not in str(exc).lower():
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
    """Full-text search over `label`.text (Episode, Fact or Decision); rows are node props (no embedding) plus `score`."""
    if label not in FULLTEXT_LABELS:
        raise ValueError(f"label must be one of {FULLTEXT_LABELS}, got {label!r}")
    query = load_cypher("fulltext")
    clean = sanitize_fulltext(text)
    if not clean:
        return CypherRows([], query)
    res = db.ro(tenant).ro_query(query, {"label": label, "q": clean, "k": int(k)}, timeout=RO_TIMEOUT_MS)
    rows = []
    for node, score in res.result_set:
        rec = compact(props(node)) or {}
        rec["score"] = score
        rows.append(rec)
    return CypherRows(rows, query)
