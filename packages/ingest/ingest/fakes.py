"""In-memory stand-in for the ``hiveboard`` memory and event functions the pipeline calls.

Method names and argument orders mirror ``docs/contracts/hiveboard-api.md`` minus the ``db``
argument (``remember_fact(tenant, fact)`` instead of ``remember_fact(db, tenant, fact)``).
``apps/api/hive_adapter.py`` extends this class with the board, skills and analytics subset.

Event parity: like the substrate, ``MemoryHive`` publishes the memory events itself
(``publishes_memory_events = True``): ``episode.ingested`` once per stored batch, ``fact.created``
/ ``commitment.created`` from :meth:`remember_fact`, ``fact.superseded`` / ``commitment.updated``
from :meth:`supersede_fact`, with the payload shapes built by :func:`fact_created_payload` and
:func:`fact_superseded_payload`. A subclass that sets the flag to ``False`` gets the same payloads
published by the pipeline instead, so there is exactly one publisher either way.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .models import entity_id_for, fact_key, normalize_object

EventListener = Callable[[dict[str, Any]], None]


class Conflict(RuntimeError):
    """Mirror of ``hiveboard.errors.Conflict``: the write is not allowed in the node's current state
    (a no-op, backdated or cross-key supersession)."""


def now_ms() -> int:
    """Current epoch milliseconds."""
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    """Short random id with a type prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def cosine_distance(a: list[float] | None, b: list[float] | None) -> float:
    """1 - cosine similarity; 1.0 when either vector is missing or zero."""
    if not a or not b or len(a) != len(b):
        return 1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 1.0
    return max(0.0, 1.0 - dot / (na * nb))


def hive_score(valid_from: int | None, confidence: float | None, distance: float, now: int) -> float:
    """Python twin of ``hive.score``: recency * importance * similarity."""
    age_days = max(0.0, (now - (valid_from or now)) / 86_400_000)
    recency = math.exp(-age_days / 30)
    importance = confidence if confidence is not None else 0.5
    similarity = max(0.0, min(1.0, 1.0 - distance))
    return recency * importance * similarity


@dataclass
class TenantStore:
    """All nodes of one tenant, keyed by id (insertion order preserved)."""

    persons: dict[str, dict[str, Any]] = field(default_factory=dict)
    meetings: dict[str, dict[str, Any]] = field(default_factory=dict)
    threads: dict[str, dict[str, Any]] = field(default_factory=dict)
    episodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    mentions: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


#: Keys of the ``fact.superseded`` payload (``docs/contracts/hiveboard-api.md``); the substrate and
#: the pipeline publish exactly this shape.
FACT_SUPERSEDED_KEYS = frozenset(
    {
        "new_fact_id", "new_id", "old_fact_id", "old_fact_ids", "old_ids", "key", "subject", "predicate", "kind",
        "old_object", "new_object", "object", "valid_from", "due_at", "episode_id", "speaker_id", "head_changed", "tenant",
    }
)


def fact_created_payload(tenant: str, rec: dict[str, Any]) -> dict[str, Any]:
    """``fact.created`` / ``commitment.created`` payload for a stored fact record."""
    return {
        "id": rec["id"],
        "fact_id": rec["id"],
        "kind": rec.get("kind"),
        "key": rec.get("key"),
        "subject": rec.get("subject"),
        "predicate": rec.get("predicate"),
        "object": rec.get("object"),
        "text": rec.get("text"),
        "speaker_id": rec.get("speaker_id"),
        "episode_id": rec.get("episode_id"),
        "due_at": rec.get("due_at"),
        "valid_from": rec.get("valid_from"),
        "precedent_ids": list(rec.get("precedent_ids") or []),
        "tenant": tenant,
    }


def fact_superseded_payload(tenant: str, new: dict[str, Any], old: dict[str, Any], *, head_changed: bool = True) -> dict[str, Any]:
    """``fact.superseded`` payload: the full contract shape (:data:`FACT_SUPERSEDED_KEYS`)."""
    return {
        "new_fact_id": new["id"],
        "new_id": new["id"],
        "old_fact_id": old["id"],
        "old_fact_ids": [old["id"]],
        "old_ids": [old["id"]],
        "key": new.get("key"),
        "subject": new.get("subject"),
        "predicate": new.get("predicate"),
        "kind": new.get("kind"),
        "old_object": old.get("object"),
        "new_object": new.get("object"),
        "object": new.get("object"),
        "valid_from": new.get("valid_from"),
        "due_at": new.get("due_at"),
        "episode_id": new.get("episode_id"),
        "speaker_id": new.get("speaker_id"),
        "head_changed": head_changed,
        "tenant": tenant,
    }


class MemoryHive:
    """In-memory episodic + semantic memory with Redis-like pub/sub."""

    #: The hive publishes memory events itself (parity with the substrate); the pipeline stays quiet.
    publishes_memory_events = True

    def __init__(self) -> None:
        self._stores: dict[str, TenantStore] = {}
        self.events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._listeners: dict[str, list[EventListener]] = defaultdict(list)
        self._lock = threading.RLock()
        self.max_events = 500

    def _emit(self, tenant: str, event: str, payload: dict[str, Any]) -> None:
        if self.publishes_memory_events:
            self.publish(tenant, event, payload)

    # ----------------------------------------------------------------- tenants
    def store(self, tenant: str) -> TenantStore:
        """Return (and lazily create) the tenant's store."""
        with self._lock:
            if tenant not in self._stores:
                self._stores[tenant] = TenantStore()
            return self._stores[tenant]

    def has_tenant(self, tenant: str) -> bool:
        return tenant in self._stores

    def drop_tenant(self, tenant: str) -> None:
        with self._lock:
            self._stores.pop(tenant, None)
            self.events.pop(tenant, None)

    def tenants(self) -> list[str]:
        return sorted(self._stores)

    def set_tenant_meta(self, tenant: str, meta: dict[str, Any]) -> dict[str, Any]:
        """Merge ``meta`` (e.g. ``embedding_model``) into the tenant row; returns the stored meta."""
        with self._lock:
            store = self.store(tenant)
            store.meta.update({k: v for k, v in meta.items() if v is not None})
            return dict(store.meta)

    def get_tenant_meta(self, tenant: str) -> dict[str, Any]:
        """The tenant row's metadata (``{}`` when nothing was recorded)."""
        with self._lock:
            return dict(self.store(tenant).meta)

    # ----------------------------------------------------------------- memory
    def remember_person(self, tenant: str, person: dict[str, Any]) -> str:
        with self._lock:
            store = self.store(tenant)
            pid = person.get("id") or new_id("spk")
            merged = {**store.persons.get(pid, {}), **{k: v for k, v in person.items() if v is not None}, "id": pid}
            store.persons[pid] = merged
            return pid

    def remember_meeting(self, tenant: str, meeting: dict[str, Any]) -> str:
        with self._lock:
            store = self.store(tenant)
            mid = meeting.get("id") or new_id("mtg")
            store.meetings[mid] = {**store.meetings.get(mid, {}), **meeting, "id": mid}
            return mid

    def remember_thread(self, tenant: str, thread: dict[str, Any]) -> str:
        with self._lock:
            store = self.store(tenant)
            tid = thread.get("id") or new_id("thr")
            store.threads[tid] = {**store.threads.get(tid, {}), **thread, "id": tid}
            return tid

    def _store_episode(self, store: TenantStore, container_id: str, container_kind: str, episode: dict[str, Any]) -> None:
        eid = episode.get("id") or new_id("ep")
        rec = {
            **store.episodes.get(eid, {}),
            **episode,
            "id": eid,
            "container_id": container_id,
            "container_kind": container_kind,
            "source_kind": episode.get("source_kind") or ("email" if container_kind == "thread" else "utterance"),
            "t_ingested": now_ms(),
        }
        if container_kind == "thread":
            rec.setdefault("speaker_id", episode.get("sender_id"))
        store.episodes[eid] = rec

    def _remember_episode_batch(self, tenant: str, container_id: str, container_kind: str, episodes: list[dict[str, Any]]) -> int:
        with self._lock:
            store = self.store(tenant)
            for episode in episodes:
                self._store_episode(store, container_id, container_kind, episode)
        if episodes:
            source_kind = episodes[0].get("source_kind") or ("email" if container_kind == "thread" else "utterance")
            self._emit(tenant, "episode.ingested", {"container_id": container_id, "count": len(episodes), "source_kind": source_kind, "tenant": tenant})
        return len(episodes)

    def remember_episodes(self, tenant: str, meeting_id: str, episodes: list[dict[str, Any]]) -> int:
        return self._remember_episode_batch(tenant, meeting_id, "meeting", episodes)

    def remember_email_episodes(self, tenant: str, thread_id: str, episodes: list[dict[str, Any]]) -> int:
        return self._remember_episode_batch(tenant, thread_id, "thread", episodes)

    def container_episodes(self, tenant: str, container_id: str) -> list[dict[str, Any]]:
        """Stored episodes of one meeting or thread, by ``seq``, with the number of facts derived from each.

        Shape per row: the contract's ``{id, seq, t_start, t_end, speaker_id, text_hash}`` plus ``text``,
        ``t_occurred``, ``source_kind`` and ``fact_count`` (no embedding); ``text_hash`` is
        ``sha256(text)[:16]`` like the API's rows. The pipeline compares this with an incoming import to detect a changed source
        and to skip already-extracted episodes on a retry.
        """
        with self._lock:
            store = self.store(tenant)
            counts: dict[str, int] = defaultdict(int)
            for fact in store.facts.values():
                if fact.get("status") != "retracted" and fact.get("episode_id"):
                    counts[str(fact["episode_id"])] += 1
            rows = [
                {
                    "id": e["id"],
                    "seq": int(e.get("seq") or 0),
                    "t_start": e.get("t_start"),
                    "t_end": e.get("t_end"),
                    "speaker_id": e.get("speaker_id") or e.get("sender_id"),
                    "text": e.get("text") or "",
                    "text_hash": hashlib.sha256(str(e.get("text") or "").encode("utf-8")).hexdigest()[:16],
                    "t_occurred": e.get("t_occurred"),
                    "source_kind": e.get("source_kind"),
                    "fact_count": counts.get(e["id"], 0),
                }
                for e in store.episodes.values()
                if e.get("container_id") == container_id
            ]
        rows.sort(key=lambda r: r["seq"])
        return rows

    def upsert_entities(self, tenant: str, entities: list[dict[str, Any]]) -> dict[str, str]:
        """MERGE on name (case-insensitive); returns ``{name: effective_id}`` like hiveboard."""
        mapping: dict[str, str] = {}
        with self._lock:
            store = self.store(tenant)
            for entity in entities:
                name = str(entity.get("name") or "").strip()
                if not name:
                    continue
                existing = next((e for e in store.entities.values() if e["name"].lower() == name.lower()), None)
                if existing is None:
                    eid = entity.get("id") or entity_id_for(name)
                    store.entities[eid] = {**entity, "id": eid, "name": name, "type": entity.get("type") or "topic"}
                    mapping[name] = eid
                else:
                    for key, value in entity.items():
                        if value is not None and key not in {"id", "name"}:
                            existing[key] = value
                    mapping[name] = existing["id"]
        return mapping

    def remember_entities(self, tenant: str, entities: list[dict[str, Any]]) -> int:
        return len(self.upsert_entities(tenant, entities))

    def link_mentions(self, tenant: str, episode_id: str, entity_ids: list[str]) -> int:
        with self._lock:
            store = self.store(tenant)
            links = store.mentions[episode_id]
            added = 0
            for eid in entity_ids:
                if eid not in links:
                    links.append(eid)
                    added += 1
            return added

    def _new_fact(self, store: TenantStore, fact: dict[str, Any], now: int) -> dict[str, Any]:
        subject = str(fact.get("subject") or "")
        predicate = str(fact.get("predicate") or "")
        episode = store.episodes.get(str(fact.get("episode_id") or ""), {})
        rec = {
            "id": fact.get("id") or new_id("fact"),
            "kind": fact.get("kind") or "fact",
            "subject": subject,
            "predicate": predicate,
            "object": str(fact.get("object") or ""),
            "key": fact.get("key") or fact_key(subject, predicate),
            "text": fact.get("text") or f"{subject} {predicate} {fact.get('object', '')}",
            "confidence": float(fact.get("confidence", 0.8)),
            "speaker_id": fact.get("speaker_id") or episode.get("speaker_id"),
            "owner_id": fact.get("owner_id") or fact.get("speaker_id"),
            "episode_id": fact.get("episode_id"),
            "container_id": episode.get("container_id"),
            "entity_ids": list(fact.get("entity_ids") or []),
            "status": "active",
            "valid_from": int(fact.get("valid_from") or now),
            "valid_to": None,
            "created_at": now,
            "expired_at": None,
            "due_at": fact.get("due_at"),
            "embedding": fact.get("embedding"),
            "supersedes": [],
            "precedent_ids": list(fact.get("precedent_ids") or []),
        }
        return rec

    def _expire(self, old: dict[str, Any], at: int, now: int, status: str = "superseded") -> None:
        old["valid_to"] = at
        old["expired_at"] = now
        old["status"] = status

    def _publish_created(self, tenant: str, rec: dict[str, Any]) -> None:
        payload = fact_created_payload(tenant, rec)
        self._emit(tenant, "fact.created", payload)
        if rec.get("kind") == "commitment":
            self._emit(tenant, "commitment.created", {**payload, "commitment_id": rec["id"]})

    def _publish_superseded(self, tenant: str, rec: dict[str, Any], old: dict[str, Any]) -> None:
        payload = fact_superseded_payload(tenant, rec, old, head_changed=True)
        self._emit(tenant, "fact.superseded", payload)
        if rec.get("kind") == "commitment":
            self._emit(tenant, "commitment.updated", {**payload, "commitment_id": rec["id"]})

    def remember_fact(self, tenant: str, fact: dict[str, Any], supersede: bool = False) -> dict[str, Any]:
        """Store a fact atomically (one lock section); a fact id that already exists is returned as-is."""
        with self._lock:
            store = self.store(tenant)
            now = now_ms()
            fid = fact.get("id")
            if fid and fid in store.facts:
                return {"id": fid, "superseded": [], "conflicts": [], "fact": store.facts[fid], "existing": True}
            rec = self._new_fact(store, fact, now)
            superseded: list[dict[str, Any]] = []
            if supersede:
                for old in list(store.facts.values()):
                    if old["status"] == "active" and old["key"] == rec["key"] and normalize_object(old["object"]) != normalize_object(rec["object"]):
                        self._expire(old, rec["valid_from"], now)
                        superseded.append(old)
            rec["supersedes"] = [o["id"] for o in superseded]
            store.facts[rec["id"]] = rec
        self._publish_created(tenant, rec)
        for old in superseded:
            self._publish_superseded(tenant, rec, old)
        return {"id": rec["id"], "superseded": [o["id"] for o in superseded], "conflicts": [], "fact": rec, "existing": False}

    def supersede_fact(self, tenant: str, old_id: str, new_fact: dict[str, Any]) -> dict[str, Any]:
        """Expire ``old_id`` and link the new fact over it. Raises :class:`Conflict` for a no-op
        (same object), a backdated statement (``valid_from`` before the old one) or a cross-key supersession."""
        with self._lock:
            store = self.store(tenant)
            old = store.facts.get(old_id)
            if old is None:
                raise KeyError(f"fact {old_id} not found")
            if old.get("status") != "active":
                raise Conflict(f"fact {old_id!r} is {old.get('status')!r}; only active facts can be superseded")
            now = now_ms()
            rec = self._new_fact(store, new_fact, now)
            if rec["key"] != old["key"]:
                raise Conflict(f"cross-key supersession: {rec['key']!r} cannot supersede {old['key']!r}")
            if normalize_object(rec["object"]) == normalize_object(old["object"]):
                raise Conflict(f"no-op supersession: {old_id!r} already states {old['object']!r} (confirm it instead)")
            if rec["valid_from"] < int(old.get("valid_from") or 0):
                raise Conflict(f"backdated supersession: new valid_from {rec['valid_from']} is before {old_id!r} ({old.get('valid_from')})")
            self._expire(old, rec["valid_from"], now)
            rec["supersedes"] = [old_id]
            store.facts[rec["id"]] = rec
        self._publish_created(tenant, rec)
        self._publish_superseded(tenant, rec, old)
        return {"id": rec["id"], "superseded": [old_id], "fact": rec}

    def facts_by_key(self, tenant: str, key: str) -> list[dict[str, Any]]:
        """Every fact (any status) sharing the supersession key, oldest valid_from first."""
        with self._lock:
            rows = [dict(f) for f in self.store(tenant).facts.values() if f["key"] == key.lower()]
        rows.sort(key=lambda f: (f["valid_from"], f["created_at"]))
        return rows

    def insert_fact_in_chain(
        self,
        tenant: str,
        fact: dict[str, Any],
        before_id: str,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomic mid-chain insertion of a late-imported earlier statement, below ``before_id``.

        The new fact is born superseded (``valid_to = before.valid_from``) and takes over the chain
        member that ``before`` superseded (the belief at the new fact's ``valid_from``), if any.
        Refuses to self-supersede: when the statement restates ``before`` (same key and object) or the
        member it would slot over, that fact is confirmed instead. Returns
        ``{"id", "inserted", "confirmed", "before_id"}`` like ``hiveboard.memory.insert_fact_in_chain``.
        ``after_id`` is accepted for compatibility and ignored: the predecessor is derived from the chain.
        """
        with self._lock:
            store = self.store(tenant)
            before = store.facts.get(before_id)
            if before is None:
                raise KeyError(f"fact {before_id} not found")
            now = now_ms()
            rec = self._new_fact(store, fact, now)
            if rec["key"] != before["key"]:
                raise Conflict(f"cross-key insertion: {rec['key']!r} under {before['key']!r}")
            new_obj = normalize_object(rec["object"])
            if rec["id"] == before_id or new_obj == normalize_object(before["object"]):
                self.confirm_fact(tenant, before_id, str(rec.get("episode_id") or ""))
                return {"id": before_id, "inserted": False, "confirmed": True, "before_id": before_id}
            predecessor = None
            for pid in before.get("supersedes", []):
                cand = store.facts.get(pid)
                if cand is not None and int(cand.get("valid_from") or 0) <= rec["valid_from"]:
                    predecessor = cand
            if predecessor is not None and new_obj == normalize_object(predecessor["object"]):
                self.confirm_fact(tenant, predecessor["id"], str(rec.get("episode_id") or ""))
                return {"id": predecessor["id"], "inserted": False, "confirmed": True, "before_id": before_id}
            if rec["id"] in store.facts:
                return {"id": rec["id"], "inserted": False, "confirmed": False, "before_id": before_id}
            rec["valid_to"] = before["valid_from"]
            rec["expired_at"] = now
            rec["status"] = "superseded"
            if predecessor is not None:
                before["supersedes"].remove(predecessor["id"])
                predecessor["valid_to"] = rec["valid_from"]
                rec["supersedes"] = [predecessor["id"]]
            before["supersedes"].append(rec["id"])
            store.facts[rec["id"]] = rec
            return {"id": rec["id"], "inserted": True, "confirmed": False, "before_id": before_id}

    def confirm_fact(self, tenant: str, fact_id: str, episode_id: str) -> None:
        """Record that an episode restated an existing fact (extra DERIVED_FROM, no SUPERSEDES)."""
        with self._lock:
            fact = self.store(tenant).facts.get(fact_id)
            if fact is None:
                raise KeyError(f"fact {fact_id} not found")
            confirmed = fact.setdefault("confirmed_by", [])
            if episode_id and episode_id not in confirmed:
                confirmed.append(episode_id)

    def retract_fact(self, tenant: str, fact_id: str, reason: str) -> None:
        with self._lock:
            fact = self.store(tenant).facts.get(fact_id)
            if fact is None:
                raise KeyError(f"fact {fact_id} not found")
            now = now_ms()
            self._expire(fact, now, now, status="retracted")
            fact["retract_reason"] = reason

    def _matches_entity(self, store: TenantStore, fact: dict[str, Any], entity: str | None) -> bool:
        if not entity:
            return True
        if entity in fact.get("entity_ids", []):
            return True
        ent = store.entities.get(entity)
        name = (ent["name"] if ent else entity).lower()
        if fact.get("subject", "").lower() == name:
            return True
        return any(store.entities.get(eid, {}).get("name", "").lower() == name for eid in fact.get("entity_ids", []))

    def active_facts(self, tenant: str, entity_id: str | None = None, key: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            store = self.store(tenant)
            out = [
                self.enrich_fact(tenant, f)
                for f in store.facts.values()
                if f["status"] == "active"
                and (key is None or f["key"] == key.lower())
                and self._matches_entity(store, f, entity_id)
            ]
        out.sort(key=lambda f: (f["valid_from"], f["created_at"]))
        return out

    def belief_at(self, tenant: str, t: int, entity_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            store = self.store(tenant)
            out = [
                self.enrich_fact(tenant, f)
                for f in store.facts.values()
                if f["valid_from"] <= t
                and (f["valid_to"] is None or f["valid_to"] > t)
                and f["status"] != "retracted"
                and self._matches_entity(store, f, entity_id)
            ]
        out.sort(key=lambda f: -f["valid_from"])
        return out

    def episode_source(self, tenant: str, episode: dict[str, Any] | None) -> dict[str, Any] | None:
        """``why().source`` shape: kind, container {id, title|subject}, t_start | sent_at, message_id."""
        if not episode:
            return None
        store = self.store(tenant)
        if episode.get("container_kind") == "thread":
            thread = store.threads.get(episode.get("container_id", ""), {})
            return {
                "kind": "email",
                "container": {"id": thread.get("id"), "subject": thread.get("subject")},
                "sent_at": episode.get("t_occurred"),
                "message_id": episode.get("message_id") or episode.get("id"),
            }
        meeting = store.meetings.get(episode.get("container_id", ""), {})
        return {
            "kind": "utterance",
            "container": {"id": meeting.get("id"), "title": meeting.get("title")},
            "t_start": episode.get("t_start"),
            "source_uri": meeting.get("source_uri"),
        }

    def _history(self, store: TenantStore, fact: dict[str, Any]) -> list[dict[str, Any]]:
        chain: list[dict[str, Any]] = []
        seen = {fact["id"]}
        frontier = list(fact.get("supersedes", []))
        while frontier:
            fid = frontier.pop(0)
            if fid in seen:
                continue
            seen.add(fid)
            older = store.facts.get(fid)
            if older:
                chain.append(dict(older))
                frontier.extend(older.get("supersedes", []))
        return chain

    def why(self, tenant: str, node_id: str) -> dict[str, Any]:
        with self._lock:
            store = self.store(tenant)
            fact = store.facts.get(node_id)
            episode = store.episodes.get(node_id) if fact is None else store.episodes.get(fact.get("episode_id") or "")
            if fact is None and episode is None:
                raise KeyError(f"node {node_id} not found")
            node = dict(fact) if fact else dict(episode)
            speaker = store.persons.get((episode or {}).get("speaker_id") or node.get("speaker_id") or "")
            container_id = (episode or {}).get("container_id") or ""
            meeting = store.meetings.get(container_id)
            thread = store.threads.get(container_id)
            history = self._history(store, fact) if fact else []
            nodes: list[dict[str, Any]] = []
            edges: list[dict[str, Any]] = []

            def add_node(nid: str, label: str, props: dict[str, Any]) -> None:
                if not any(n["id"] == nid for n in nodes):
                    nodes.append({"id": nid, "label": label, "props": {k: v for k, v in props.items() if k != "embedding"}})

            if fact:
                add_node(fact["id"], fact["kind"].capitalize() if fact["kind"] != "fact" else "Fact", fact)
            if episode:
                add_node(episode["id"], "Episode", episode)
                if fact:
                    edges.append({"source": fact["id"], "target": episode["id"], "type": "DERIVED_FROM", "props": {}})
            if speaker:
                add_node(speaker["id"], "Person", speaker)
                if episode:
                    rel = "SENT_BY" if episode.get("source_kind") == "email" else "SPOKEN_BY"
                    edges.append({"source": episode["id"], "target": speaker["id"], "type": rel, "props": {}})
                if fact:
                    edges.append({"source": fact["id"], "target": speaker["id"], "type": "STATED_BY", "props": {}})
            if meeting:
                add_node(meeting["id"], "Meeting", meeting)
                if episode:
                    edges.append({"source": meeting["id"], "target": episode["id"], "type": "HAS_EPISODE", "props": {}})
            if thread:
                add_node(thread["id"], "EmailThread", thread)
                if episode:
                    edges.append({"source": thread["id"], "target": episode["id"], "type": "HAS_EPISODE", "props": {}})
            if fact:
                for eid in fact.get("entity_ids", []):
                    ent = store.entities.get(eid)
                    if ent:
                        add_node(eid, "Entity", ent)
                        edges.append({"source": fact["id"], "target": eid, "type": "ABOUT", "props": {}})
                newer = fact
                for older in history:
                    add_node(older["id"], "Fact", older)
                    edges.append({"source": newer["id"], "target": older["id"], "type": "SUPERSEDES", "props": {}})
                    newer = older
                for pid in fact.get("precedent_ids", []):
                    prec = store.facts.get(pid)
                    if prec:
                        add_node(pid, "Fact", prec)
                        edges.append({"source": pid, "target": fact["id"], "type": "PRECEDENT_FOR", "props": {}})
            return {
                "node": {k: v for k, v in node.items() if k != "embedding"},
                "speaker": speaker,
                "meeting": meeting,
                "thread": thread,
                "episode": (
                    {
                        "id": episode["id"],
                        "text": episode.get("text"),
                        "t_start": episode.get("t_start"),
                        "t_end": episode.get("t_end"),
                        "t_occurred": episode.get("t_occurred"),
                    }
                    if episode
                    else None
                ),
                "history": [{k: v for k, v in h.items() if k != "embedding"} for h in history],
                "source": self.episode_source(tenant, episode),
                "cypher": "-- in-memory FakeHive: no Cypher executed (32_why_path.cypher in production)",
                "subgraph": {"nodes": nodes, "edges": edges},
            }

    def recall(
        self,
        tenant: str,
        query_embedding: list[float],
        k: int = 8,
        now: int | None = None,
        label: str = "Fact",
    ) -> dict[str, Any]:
        now = now or now_ms()
        with self._lock:
            store = self.store(tenant)
            if label == "Episode":
                pool = list(store.episodes.values())
            elif label == "Skill":
                pool = list(store.extra.get("skills", {}).values())
            else:
                pool = [f for f in store.facts.values() if f["status"] == "active"]
            scored = []
            for item in pool:
                distance = cosine_distance(query_embedding, item.get("embedding"))
                if distance >= 1.0 and item.get("embedding") is None:
                    continue
                rank = hive_score(item.get("valid_from") or item.get("t_occurred"), item.get("confidence"), distance, now)
                scored.append((rank, distance, item))
            scored.sort(key=lambda row: (-row[0], row[1]))
            items = []
            nodes: list[dict[str, Any]] = []
            edges: list[dict[str, Any]] = []
            for rank, distance, item in scored[:k]:
                node = {k2: v for k2, v in item.items() if k2 != "embedding"}
                entities = [
                    {"id": eid, "name": store.entities[eid]["name"], "type": store.entities[eid]["type"]}
                    for eid in item.get("entity_ids", [])
                    if eid in store.entities
                ]
                neighbours = []
                if label == "Fact":
                    shared = set(item.get("entity_ids", []))
                    for other in store.facts.values():
                        if other["id"] != item["id"] and other["status"] == "active" and shared & set(other.get("entity_ids", [])):
                            neighbours.append({k2: v for k2, v in other.items() if k2 != "embedding"})
                            if len(neighbours) >= 5:
                                break
                items.append(
                    {
                        "node": node,
                        "id": item["id"],
                        "distance": round(distance, 6),
                        "similarity": round(max(0.0, min(1.0, 1.0 - distance)), 6),
                        "rank": round(rank, 6),
                        "entities": entities,
                        "neighbours": neighbours,
                    }
                )
                nodes.append({"id": item["id"], "label": label, "props": node})
                for ent in entities:
                    if not any(n["id"] == ent["id"] for n in nodes):
                        nodes.append({"id": ent["id"], "label": "Entity", "props": {"name": ent["name"], "type": ent["type"]}})
                    edges.append({"source": item["id"], "target": ent["id"], "type": "ABOUT", "props": {}})
                for other in neighbours:
                    if not any(n["id"] == other["id"] for n in nodes):
                        nodes.append({"id": other["id"], "label": label, "props": other})
                    for ent in entities:
                        if ent["id"] in other.get("entity_ids", []):
                            edges.append({"source": other["id"], "target": ent["id"], "type": "ABOUT", "props": {}})
        return {
            "items": items,
            "cypher": "-- in-memory FakeHive: cosine KNN + hive.score twin (30_recall_hybrid.cypher in production)",
            "subgraph": {"nodes": nodes, "edges": edges},
            "label": label,
            "k": k,
            "now": now,
        }

    def fulltext(self, tenant: str, text: str, label: str = "Episode", k: int = 10) -> list[dict[str, Any]]:
        needle = text.lower().strip()
        with self._lock:
            store = self.store(tenant)
            pool = list(store.episodes.values()) if label == "Episode" else list(store.facts.values())
            hits = [dict(item) for item in pool if needle and needle in str(item.get("text", "")).lower()]
        return hits[:k]

    # ----------------------------------------------------------------- events
    def publish(self, tenant: str, event: str, payload: dict[str, Any]) -> None:
        evt = {"event": event, "payload": payload, "ts": now_ms()}
        with self._lock:
            history = self.events[tenant]
            history.append(evt)
            if len(history) > self.max_events:
                del history[: len(history) - self.max_events]
            listeners = list(self._listeners.get(tenant, []))
        for fn in listeners:
            fn(evt)

    def add_listener(self, tenant: str, fn: EventListener) -> None:
        with self._lock:
            self._listeners[tenant].append(fn)

    def remove_listener(self, tenant: str, fn: EventListener) -> None:
        with self._lock:
            if fn in self._listeners.get(tenant, []):
                self._listeners[tenant].remove(fn)

    # ----------------------------------------------------------------- read helpers
    def list_persons(self, tenant: str) -> list[dict[str, Any]]:
        return [dict(p) for p in self.store(tenant).persons.values()]

    def get_person(self, tenant: str, person_id: str | None) -> dict[str, Any] | None:
        if not person_id:
            return None
        person = self.store(tenant).persons.get(person_id)
        return dict(person) if person else None

    def list_meetings(self, tenant: str) -> list[dict[str, Any]]:
        store = self.store(tenant)
        out = []
        for meeting in store.meetings.values():
            eps = [e for e in store.episodes.values() if e.get("container_id") == meeting["id"]]
            ep_ids = {e["id"] for e in eps}
            facts = sum(1 for f in store.facts.values() if f.get("episode_id") in ep_ids)
            out.append({**meeting, "episodes": len(eps), "facts": facts})
        out.sort(key=lambda m: m.get("started_at") or 0)
        return out

    def get_meeting(self, tenant: str, meeting_id: str) -> dict[str, Any] | None:
        meeting = self.store(tenant).meetings.get(meeting_id)
        return dict(meeting) if meeting else None

    def meeting_episodes(self, tenant: str, meeting_id: str) -> list[dict[str, Any]]:
        store = self.store(tenant)
        eps = [dict(e) for e in store.episodes.values() if e.get("container_id") == meeting_id]
        eps.sort(key=lambda e: e.get("seq", 0))
        return eps

    def list_threads(self, tenant: str) -> list[dict[str, Any]]:
        store = self.store(tenant)
        out = []
        for thread in store.threads.values():
            eps = [e for e in store.episodes.values() if e.get("container_id") == thread["id"]]
            ep_ids = {e["id"] for e in eps}
            facts = sum(1 for f in store.facts.values() if f.get("episode_id") in ep_ids)
            out.append({**thread, "messages": len(eps), "facts": facts})
        out.sort(key=lambda t: t.get("started_at") or 0)
        return out

    def get_thread(self, tenant: str, thread_id: str) -> dict[str, Any] | None:
        thread = self.store(tenant).threads.get(thread_id)
        return dict(thread) if thread else None

    def thread_messages(self, tenant: str, thread_id: str) -> list[dict[str, Any]]:
        return self.meeting_episodes(tenant, thread_id)

    def get_episode(self, tenant: str, episode_id: str) -> dict[str, Any] | None:
        episode = self.store(tenant).episodes.get(episode_id)
        return dict(episode) if episode else None

    def list_entities(self, tenant: str) -> list[dict[str, Any]]:
        return [{k: v for k, v in e.items() if k != "embedding"} for e in self.store(tenant).entities.values()]

    def get_fact(self, tenant: str, fact_id: str) -> dict[str, Any] | None:
        fact = self.store(tenant).facts.get(fact_id)
        return self.enrich_fact(tenant, fact) if fact else None

    def list_facts(
        self,
        tenant: str,
        status: str | None = "active",
        entity: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Facts with speaker and container joined in, newest valid_from last."""
        with self._lock:
            store = self.store(tenant)
            rows = []
            for fact in store.facts.values():
                if status and status != "all" and fact["status"] != status:
                    continue
                if kind and fact["kind"] != kind:
                    continue
                if not self._matches_entity(store, fact, entity):
                    continue
                rows.append(self.enrich_fact(tenant, fact))
        rows.sort(key=lambda f: (f["valid_from"], f["created_at"]))
        return rows

    def enrich_fact(self, tenant: str, fact: dict[str, Any]) -> dict[str, Any]:
        """Attach ``speaker`` and ``meeting``/``thread`` summaries to a fact dict."""
        store = self.store(tenant)
        episode = store.episodes.get(fact.get("episode_id") or "", {})
        speaker = store.persons.get(fact.get("speaker_id") or episode.get("speaker_id") or "")
        container_id = episode.get("container_id") or fact.get("container_id") or ""
        meeting = store.meetings.get(container_id)
        thread = store.threads.get(container_id)
        row = {k: v for k, v in fact.items() if k != "embedding"}
        row["has_embedding"] = fact.get("embedding") is not None
        row["speaker"] = {"id": speaker["id"], "name": speaker.get("name")} if speaker else None
        row["entities"] = [
            {"id": eid, "name": store.entities[eid]["name"], "type": store.entities[eid]["type"]}
            for eid in fact.get("entity_ids", [])
            if eid in store.entities
        ]
        row["meeting"] = {"id": meeting["id"], "title": meeting.get("title")} if meeting else None
        row["thread"] = {"id": thread["id"], "subject": thread.get("subject")} if thread else None
        row["source"] = self.episode_source(tenant, episode) if episode else None
        return row
