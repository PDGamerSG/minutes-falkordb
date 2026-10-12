"""The seam between the API and the substrate.

``FakeHive`` is a complete in-memory implementation (tests, model-free demos). ``RealHive``
delegates to the ``hiveboard`` package (memory, board, skills, events, analytics, tenancy) and
adds the read-only listing queries the HTTP API needs (meetings, threads, facts with joins,
chat turns). Both expose the same method names: hiveboard's, minus the ``db`` argument.

Event conventions: the hive layer publishes ``task.*``, ``skill.*`` and (RealHive only)
``fact.*``/``episode.*`` events itself; the pipeline publishes memory events for the FakeHive.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import itertools
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from ingest.fakes import EventListener, MemoryHive, cosine_distance, new_id, now_ms

ANALYTICS_LIMIT = 5000  # hiveboard reads default to 500; belief, active facts and commitments must not be silently capped
_TRACE_SEQ = itertools.count(1)  # orders trace events inside one millisecond

log = logging.getLogger(__name__)

AGENT_SPECS: list[tuple[str, str, list[str]]] = [
    ("fact_agent", "FactAgent", ["extract"]),
    ("followup_agent", "FollowUpAgent", ["followup"]),
    ("scheduler_agent", "SchedulerAgent", ["schedule"]),
    ("standup_agent", "StandupAgent", ["standup"]),
    ("answer_agent", "AnswerAgent", ["answer"]),
]

TASK_STATES = ("submitted", "working", "input_required", "completed", "failed")


_CLOSED_STATUSES = {"completed", "complete", "done", "delivered", "shipped", "cancelled", "canceled", "dropped", "closed"}


def drop_closed_commitments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open means not yet closed: drop `<subject> | status = completed` commitments and every commitment on the
    same subject stated no later than that closing status (51_open_commitments returns all ACTIVE commitments,
    and a due date stays active after the work is reported done)."""

    def closing(row: dict[str, Any]) -> bool:
        return (row.get("predicate") or "").lower() == "status" and (row.get("object") or "").strip().lower() in _CLOSED_STATUSES

    closed_at: dict[str, int] = {}
    for row in rows:
        if closing(row):
            subject = (row.get("subject") or "").strip().lower()
            closed_at[subject] = max(closed_at.get(subject, 0), int(row.get("valid_from") or 0))
    kept = []
    for row in rows:
        if closing(row):
            continue
        subject = (row.get("subject") or "").strip().lower()
        if subject in closed_at and int(row.get("valid_from") or 0) <= closed_at[subject]:
            continue
        kept.append(row)
    return kept


class HiveNotFound(KeyError):
    """A node the caller named does not exist."""


class HiveConflict(RuntimeError):
    """The operation is not allowed in the node's current state."""


def _strip_embedding(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if d is None:
        return None
    return {k: v for k, v in d.items() if k != "embedding"}


DEFAULT_LEASE_MS = 120_000
FACT_PAGE = 500  # internal page size when a caller wants every fact


def encode_cursor(valid_from: int | None, fact_id: str) -> str:
    """Opaque cursor over the (valid_from, id) order of ``page_facts``."""
    return base64.urlsafe_b64encode(f"{int(valid_from or 0)}|{fact_id}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[int, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        vf, fid = raw.split("|", 1)
        return int(vf), fid
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid cursor") from exc


def _text_hash(text: Any) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


def _accepts(fn: Any, name: str) -> bool:
    """True when ``fn`` takes a parameter called ``name`` (contract functions land in parallel)."""
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


# =============================================================================== FakeHive
class FakeHive(MemoryHive):
    """In-memory Hive Board: memory (inherited) + tenancy, board, skills, analytics, chat turns."""

    publishes_memory_events = True  # parity with the substrate: the hive publishes fact.* / commitment.* / episode.ingested itself
    publishes_board_events = True
    kind = "fake"

    def __init__(self) -> None:
        super().__init__()
        self._tenants: dict[str, dict[str, Any]] = {}
        self._snapshots: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._agents: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._tasks: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._skills: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._turns: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        self._work_items: dict[str, dict[str, Any]] = defaultdict(dict)
        self._impact_drafts: dict[str, dict[str, Any]] = defaultdict(dict)
        self._tenant_meta: dict[str, dict[str, Any]] = defaultdict(dict)
        self._sessions: dict[str, dict[str, str | None]] = defaultdict(dict)
        self._ro_password = "fake-ro"

    def import_work_manifest(self, tenant: str, manifest: dict[str, Any]) -> int:
        from .impact_fake import import_manifest
        return import_manifest(self, tenant, manifest)

    def work_impacts(self, tenant: str) -> dict[str, Any]:
        from .impact_fake import work_impacts
        return work_impacts(self, tenant)

    def save_impact_draft(self, tenant: str, draft: dict[str, Any]) -> dict[str, Any] | None:
        from .impact_fake import save_draft
        return save_draft(self, tenant, draft)

    def list_impact_drafts(self, tenant: str) -> list[dict[str, Any]]:
        from copy import deepcopy
        return deepcopy(sorted(self._impact_drafts.get(tenant, {}).values(), key=lambda d: (-d["created_at"], d["id"]))[:200])

    # -- tenancy -----------------------------------------------------------------------------
    def ping(self) -> bool:
        return True

    def db_version(self) -> str:
        return "fake"

    def list_tenants(self) -> list[str]:
        return sorted(set(self._tenants) | set(self.tenants()))

    def create_tenant(self, slug: str, display_name: str, pw_rw: str | None = None, pw_ro: str | None = None, rotate: bool = False) -> dict[str, Any]:
        """Idempotent; an existing tenant keeps its row (mirrors tenancy.create_tenant, which no longer resets passwords)."""
        self.store(slug)
        existing = self._tenants.get(slug)
        if existing is None:
            self._tenants[slug] = {"slug": slug, "display_name": display_name, "created_at": now_ms()}
        elif rotate:
            existing["display_name"] = display_name
        return self.tenant_info(slug)

    def delete_tenant(self, slug: str) -> None:
        self.drop_tenant(slug)
        for bag in (self._tenants, self._snapshots, self._agents, self._tasks, self._skills, self._turns, self._work_items, self._impact_drafts, self._tenant_meta, self._sessions):
            bag.pop(slug, None)

    def set_tenant_meta(self, slug: str, meta: dict[str, Any]) -> dict[str, Any]:
        """Merge ``meta`` into the tenant's registry row (api_key_hash, embedding_model, embedding_dim, ...)."""
        with self._lock:
            self._tenant_meta[slug].update(meta)
            return dict(self._tenant_meta[slug])

    def get_tenant_meta(self, slug: str) -> dict[str, Any]:
        return dict(self._tenant_meta.get(slug, {}))

    def container_episodes(self, tenant: str, container_id: str) -> list[dict[str, Any]]:
        """``[{id, seq, t_start, t_end, speaker_id, text_hash}]`` of a meeting or thread, in order (ingest contract)."""
        store = self.store(tenant)
        rows = [ep for ep in store.episodes.values() if ep.get("container_id") == container_id]
        rows.sort(key=lambda ep: (ep.get("seq") or 0, ep.get("t_start") or 0))
        return [
            {"id": ep["id"], "seq": ep.get("seq"), "t_start": ep.get("t_start"), "t_end": ep.get("t_end"), "speaker_id": ep.get("speaker_id"), "text_hash": ep.get("text_hash") or _text_hash(ep.get("text"))}
            for ep in rows
        ]

    def ensure_schema(self, tenant: str) -> dict[str, int]:
        self.store(tenant)
        return {"indexes_created": 0, "indexes_existing": 33, "constraints_created": 0, "constraints_existing": 14}

    def load_udfs(self) -> None:
        return None

    def counts(self, tenant: str) -> dict[str, int]:
        store = self.store(tenant)
        facts = list(store.facts.values())
        return {
            "episodes": len(store.episodes),
            "facts": sum(1 for f in facts if f["kind"] == "fact"),
            "decisions": sum(1 for f in facts if f["kind"] == "decision"),
            "commitments": sum(1 for f in facts if f["kind"] == "commitment"),
            "tasks": len(self._tasks.get(tenant, {})),
            "skills": len(self._skills.get(tenant, {})),
            "entities": len(store.entities),
            "meetings": len(store.meetings),
            "threads": len(store.threads),
        }

    def acl_info(self, tenant: str) -> dict[str, Any]:
        rw, ro = f"team_{tenant}_rw", f"team_{tenant}_ro"
        return {
            "rw_user": rw,
            "ro_user": ro,
            "rules": [
                f"user {rw} on #<sha256> ~team_{tenant} ~commons resetchannels -@all +graph.query +graph.ro_query +ping +info",
                f"user {ro} on #<sha256> ~team_{tenant} ~commons resetchannels -@all +graph.ro_query +ping +info",
            ],
        }

    def tenant_info(self, tenant: str) -> dict[str, Any]:
        meta = self._tenants.get(tenant, {})
        counts = self.counts(tenant)
        return {
            "slug": tenant,
            "display_name": meta.get("display_name") or tenant.capitalize(),
            "graph": f"team_{tenant}",
            "usage_mb": round(0.01 * (counts["episodes"] + counts["facts"] + counts["decisions"] + counts["commitments"]), 3),
            **self.graph_size(tenant),
            "counts": counts,
            "acl": self.acl_info(tenant),
            "meta": {k: v for k, v in self._tenant_meta.get(tenant, {}).items() if k != "api_key_hash"},
        }

    def graph_size(self, tenant: str) -> dict[str, int]:
        """Approximate node and edge totals of the in-memory tenant graph (mirrors RealHive.graph_size)."""
        store = self.store(tenant)
        nodes = sum(len(bag) for bag in (store.persons, store.meetings, store.threads, store.episodes, store.entities, store.facts))
        nodes += len(self._tasks.get(tenant, {})) + len(self._skills.get(tenant, {})) + len(self._agents.get(tenant, {}))
        edges = sum(len(ids) for ids in store.mentions.values())
        edges += sum(1 for e in store.episodes.values() if e.get("container_id"))
        edges += sum(1 + len(f.get("entity_ids") or []) for f in store.facts.values())
        return {"nodes": nodes, "edges": edges}

    def acl_probe(self, tenant: str, target: str) -> dict[str, Any]:
        return {
            "allowed": tenant == target,
            "user": f"team_{tenant}_ro",
            "target_graph": f"team_{target}",
            "command": f"GRAPH.RO_QUERY team_{target} \"MATCH (n) RETURN count(n)\"",
            "error": None if tenant == target else f"NOPERM No permissions to access a key (team_{target}) as team_{tenant}_ro",
        }

    def snapshot(self, tenant: str, label: str) -> dict[str, Any]:
        taken = now_ms()
        rec = {"id": new_id("snap"), "name": f"team_{tenant}__snap_{taken}", "label": label, "taken_at": taken, "exists": True}
        self._snapshots[tenant].insert(0, rec)
        return rec

    def belief_at_result(self, tenant: str, t: int, entity_id: str | None = None) -> dict[str, Any]:
        return {"rows": self.belief_at(tenant, t, entity_id), "cypher": "-- FakeHive (31_belief_at_time.cypher in production)"}

    def list_snapshots(self, tenant: str) -> list[dict[str, Any]]:
        return [dict(s) for s in self._snapshots.get(tenant, [])]

    # -- memory lookups: missing nodes are 404s, not 500s --------------------------------------
    def why(self, tenant: str, node_id: str) -> dict[str, Any]:
        try:
            return super().why(tenant, node_id)
        except KeyError as exc:
            raise HiveNotFound(str(exc)) from exc

    def supersede_fact(self, tenant: str, old_id: str, new_fact: dict[str, Any]) -> dict[str, Any]:
        old = self.store(tenant).facts.get(old_id)
        if old is None:
            raise HiveNotFound(f"fact {old_id!r} not found")
        if old.get("status") != "active":
            raise HiveConflict(f"fact {old_id!r} is {old.get('status')!r}; only active facts can be superseded")
        # Mirrors hiveboard.memory.supersede_fact (raises Conflict on no-op, backdated and cross-key supersession).
        if new_fact.get("key") and old.get("key") and str(new_fact["key"]).lower() != str(old["key"]).lower():
            raise HiveConflict(f"fact {old_id!r} has key {old['key']!r}; the new fact has {new_fact['key']!r}")
        if str(new_fact.get("object") or "").strip().lower() == str(old.get("object") or "").strip().lower():
            raise HiveConflict(f"fact {old_id!r} already states {old.get('object')!r}; a supersession must change the value")
        new_from = new_fact.get("valid_from")
        if new_from is not None and old.get("valid_from") is not None and int(new_from) < int(old["valid_from"]):
            raise HiveConflict(f"fact {old_id!r} is newer than the proposed replacement; use insert_fact_in_chain for backdated statements")
        return super().supersede_fact(tenant, old_id, new_fact)

    def retract_fact(self, tenant: str, fact_id: str, reason: str) -> None:
        try:
            super().retract_fact(tenant, fact_id, reason)
        except KeyError as exc:
            raise HiveNotFound(str(exc)) from exc

    def insert_fact_in_chain(self, tenant: str, fact: dict[str, Any], before_id: str, after_id: str | None = None) -> dict[str, Any]:
        """Contract: ``insert_fact_in_chain(tenant, fact, before_id)``; ``after_id`` is accepted for the older pipeline."""
        parent = super().insert_fact_in_chain
        try:
            if _accepts(parent, "after_id"):
                return parent(tenant, fact, before_id, after_id)
            return parent(tenant, fact, before_id)
        except KeyError as exc:
            raise HiveNotFound(str(exc)) from exc

    def confirm_fact(self, tenant: str, fact_id: str, episode_id: str) -> None:
        try:
            super().confirm_fact(tenant, fact_id, episode_id)
        except KeyError as exc:
            raise HiveNotFound(str(exc)) from exc

    # -- extra memory writes -----------------------------------------------------------------
    def update_fact_due(self, tenant: str, fact_id: str, due_at: int | None) -> dict[str, Any]:
        with self._lock:
            fact = self.store(tenant).facts.get(fact_id)
            if fact is None:
                raise HiveNotFound(fact_id)
            fact["due_at"] = due_at
            return self.enrich_fact(tenant, fact)

    def add_turn(self, tenant: str, session_id: str, role: str, text: str, meta: dict[str, Any] | None = None, key_hash: str | None = None) -> dict[str, Any]:
        turn = {"id": new_id("turn"), "session_id": session_id, "role": role, "text": text, "t": now_ms(), "meta": meta or {}}
        with self._lock:
            self._sessions[tenant].setdefault(session_id, key_hash)
            self._turns[tenant][session_id].append(turn)
        return turn

    def get_turns(self, tenant: str, session_id: str, key_hash: str | None = None) -> list[dict[str, Any]]:
        """With ``key_hash`` only sessions created under that API key are visible (TENANT_KEYS_REQUIRED)."""
        if key_hash is not None and self._sessions.get(tenant, {}).get(session_id, None) != key_hash:
            return []
        return [dict(t) for t in self._turns.get(tenant, {}).get(session_id, [])]

    def page_facts(self, tenant: str, status: str | None = "active", entity: str | None = None, kind: str | None = None, limit: int = 200, cursor: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
        """One page of facts ordered by (valid_from, id); returns ``(rows, next_cursor)``."""
        rows = sorted(self.list_facts(tenant, status=status, entity=entity, kind=kind), key=lambda f: (int(f.get("valid_from") or 0), str(f.get("id"))))
        after = decode_cursor(cursor)
        if after is not None:
            rows = [f for f in rows if (int(f.get("valid_from") or 0), str(f.get("id"))) > after]
        page = rows[: max(1, int(limit))]
        next_cursor = encode_cursor(page[-1].get("valid_from"), str(page[-1].get("id"))) if len(rows) > len(page) else None
        return page, next_cursor

    def run_ro_cypher(self, tenant: str, query: str, params: dict[str, Any] | None = None, timeout_ms: int = 3000) -> dict[str, Any]:
        """The fake has no Cypher engine; free-form reads degrade to a full-text scan of the query words."""
        import re as _re

        words = [w for w in _re.findall(r"[A-Za-z]{4,}", query) if w.upper() != w and w not in ("Fact", "status", "active")]
        hits: list[dict[str, Any]] = []
        for word in words[:5]:
            hits.extend(_strip_embedding(h) for h in self.fulltext(tenant, word, "Fact", k=5))
        if not hits:  # the fake cannot run Cypher: show the tenant's active facts so the rows path stays exercised
            hits = [_strip_embedding(f) for f in self.list_facts(tenant, status="active")]
        return {"rows": hits[:10], "cypher": query, "note": "FakeHive: full-text approximation, no Cypher executed"}

    # -- board -------------------------------------------------------------------------------
    def register_agent(self, tenant: str, agent_id: str, name: str, capabilities: list[str], model: str) -> None:
        with self._lock:
            self.store(tenant)
            existing = self._agents[tenant].get(agent_id, {})
            self._agents[tenant][agent_id] = {
                **existing,
                "id": agent_id,
                "name": name,
                "model": model,
                "capabilities": sorted(set(existing.get("capabilities", [])) | set(capabilities)),
                "last_seen": now_ms(),
                "created_at": existing.get("created_at") or now_ms(),
            }

    def touch_agent(self, tenant: str, agent_id: str) -> None:
        agent = self._agents.get(tenant, {}).get(agent_id)
        if agent:
            agent["last_seen"] = now_ms()

    def _task_view(self, task: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in task.items() if k not in {"claims", "handoffs", "artifacts", "used_skills", "leases"}}

    def submit_task(
        self,
        tenant: str,
        kind: str,
        payload: dict[str, Any],
        requires: list[str],
        about_ids: Iterable[str] = (),
        priority: int = 5,
        owner_agent: str | None = None,
    ) -> str:
        now = now_ms()
        task = {
            "id": new_id("task"),
            "kind": kind,
            "status": "submitted",
            "version": 0,
            "owner_agent": owner_agent,
            "lease_until": None,
            "priority": int(priority),
            "payload": dict(payload or {}),
            "requires": list(requires),
            "about": list(about_ids),
            "created_at": now,
            "updated_at": now,
            "failure_reason": None,
            "question": None,
            "claims": [],
            "handoffs": [],
            "artifacts": [],
            "used_skills": [],
            "leases": [],
        }
        with self._lock:
            self._tasks[tenant][task["id"]] = task
        self.publish(tenant, "task.submitted", {"task_id": task["id"], "kind": kind, "requires": list(requires), "about": list(about_ids), "priority": priority, "owner_agent": owner_agent})
        return task["id"]

    def claim(self, tenant: str, task_id: str, agent_id: str, expected_version: int, lease_ms: int = DEFAULT_LEASE_MS) -> int | None:
        """Compare-and-set claim with a lease; a working task whose lease lapses is returned by ``reap_expired``."""
        with self._lock:
            task = self._tasks.get(tenant, {}).get(task_id)
            if task is None or agent_id not in self._agents.get(tenant, {}):
                return None
            if task["status"] != "submitted" or task["version"] != expected_version:
                return None
            if task.get("owner_agent") not in (None, agent_id):
                return None
            now = now_ms()
            task.update({"status": "working", "version": expected_version + 1, "owner_agent": agent_id, "updated_at": now, "lease_until": now + int(lease_ms)})
            task["claims"].append({"t": now, "seq": next(_TRACE_SEQ), "type": "claimed", "agent": agent_id})
            version = task["version"]
        self.publish(tenant, "task.claimed", {"task_id": task_id, "agent_id": agent_id, "version": version, "lease_until": task["lease_until"]})
        return version

    def heartbeat(self, tenant: str, task_id: str, agent_id: str, lease_ms: int = DEFAULT_LEASE_MS) -> bool:
        """Extend the owner's lease on a working task; False when the task is no longer theirs."""
        with self._lock:
            task = self._tasks.get(tenant, {}).get(task_id)
            if task is None or task["status"] != "working" or task["owner_agent"] != agent_id:
                return False
            task["lease_until"] = now_ms() + int(lease_ms)
            return True

    def reap_expired(self, tenant: str, now: int | None = None) -> list[str]:
        """Working tasks whose lease lapsed go back to ``submitted`` (version bump, owner cleared, ``lease_expired`` in the trace)."""
        now = now if now is not None else now_ms()
        expired: list[tuple[str, str | None, int]] = []
        with self._lock:
            for task in self._tasks.get(tenant, {}).values():
                if task["status"] == "working" and task.get("lease_until") is not None and task["lease_until"] < now:
                    owner = task["owner_agent"]
                    task.update({"status": "submitted", "version": task["version"] + 1, "owner_agent": None, "lease_until": None, "updated_at": now})
                    task["leases"].append({"t": now_ms(), "seq": next(_TRACE_SEQ), "type": "lease_expired", "agent": owner})
                    expired.append((task["id"], owner, task["version"]))
        for task_id, owner, version in expired:
            self.publish(tenant, "task.lease_expired", {"task_id": task_id, "agent_id": owner, "version": version})
            self.publish(tenant, "task.submitted", {"task_id": task_id, "requeued": True, "version": version})
        return [t for t, _, _ in expired]

    def next_open_task(self, tenant: str, agent_id: str) -> dict[str, Any] | None:
        """Highest priority first, then oldest; unaddressed tasks need the capabilities, addressed ones only the address."""
        agent = self._agents.get(tenant, {}).get(agent_id)
        if agent is None:
            return None
        caps = set(agent["capabilities"])
        with self._lock:
            candidates = [
                t
                for t in self._tasks.get(tenant, {}).values()
                if t["status"] == "submitted"
                and (t["owner_agent"] == agent_id or (t["owner_agent"] is None and set(t["requires"]) <= caps))
            ]
        if not candidates:
            return None
        candidates.sort(key=lambda t: (-t["priority"], t["created_at"]))
        return self._task_view(candidates[0])

    def handoff(
        self,
        tenant: str,
        task_id: str,
        from_agent: str,
        to_agent: str,
        expected_version: int,
        summary: str,
        subgraph_ids: list[str],
    ) -> int | None:
        with self._lock:
            task = self._tasks.get(tenant, {}).get(task_id)
            if task is None or task["status"] != "working" or task["owner_agent"] != from_agent or task["version"] != expected_version:
                return None
            if to_agent not in self._agents.get(tenant, {}):
                return None
            now = now_ms()
            task.update({"owner_agent": to_agent, "status": "submitted", "version": expected_version + 1, "updated_at": now, "lease_until": None})
            task["handoffs"].append({"t": now, "seq": next(_TRACE_SEQ), "type": "handed_off", "agent": from_agent, "to_agent": to_agent, "summary": summary, "subgraph_ids": list(subgraph_ids)})
            version = task["version"]
        self.publish(tenant, "task.handed_off", {"task_id": task_id, "from": from_agent, "to": to_agent, "version": version, "summary": summary, "subgraph_ids": list(subgraph_ids)})
        return version

    def complete(self, tenant: str, task_id: str, agent_id: str, artifact: dict[str, Any] | None = None) -> None:
        with self._lock:
            task = self._tasks.get(tenant, {}).get(task_id)
            if task is None or task["status"] != "working" or task["owner_agent"] != agent_id:
                raise HiveNotFound(f"task {task_id!r} is not a working task owned by {agent_id!r}")
            now = now_ms()
            art = None
            if artifact is not None:
                art = {"id": artifact.get("id") or new_id("art"), "kind": artifact.get("kind"), "uri": artifact.get("uri"), "text": artifact.get("text"), "created_at": now}
                task["artifacts"].append({"t": now, "seq": next(_TRACE_SEQ), "type": "artifact", "artifact": art})
            task.update({"status": "completed", "version": task["version"] + 1, "updated_at": now, "lease_until": None})
            version = task["version"]
        self.publish(tenant, "task.completed", {"task_id": task_id, "agent_id": agent_id, "artifact": art, "version": version})

    def _set_state(self, tenant: str, task_id: str, agent_id: str, status: str, note: str) -> int:
        with self._lock:
            task = self._tasks.get(tenant, {}).get(task_id)
            if task is None or task["owner_agent"] != agent_id or task["status"] not in ("working", "input_required"):
                raise HiveNotFound(f"task {task_id!r} is not a working task owned by {agent_id!r}")
            task.update({"status": status, "version": task["version"] + 1, "updated_at": now_ms(), "lease_until": None})
            if status == "failed":
                task["failure_reason"] = note
            else:
                task["question"] = note
            return task["version"]

    def fail(self, tenant: str, task_id: str, agent_id: str, reason: str) -> None:
        version = self._set_state(tenant, task_id, agent_id, "failed", reason)
        self.publish(tenant, "task.failed", {"task_id": task_id, "agent_id": agent_id, "reason": reason, "version": version})

    def need_input(self, tenant: str, task_id: str, agent_id: str, question: str) -> None:
        version = self._set_state(tenant, task_id, agent_id, "input_required", question)
        self.publish(tenant, "task.input_required", {"task_id": task_id, "agent_id": agent_id, "question": question, "version": version})

    def list_tasks(self, tenant: str, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        tasks = [self._task_view(t) for t in self._tasks.get(tenant, {}).values() if status in (None, "", t["status"])]
        tasks.sort(key=lambda t: -t["created_at"])
        return tasks[:limit]

    def get_task(self, tenant: str, task_id: str) -> dict[str, Any] | None:
        task = self._tasks.get(tenant, {}).get(task_id)
        return self._task_view(task) if task else None

    def list_agents(self, tenant: str) -> list[dict[str, Any]]:
        working = {t["owner_agent"] for t in self._tasks.get(tenant, {}).values() if t["status"] == "working"}
        out = []
        for agent in sorted(self._agents.get(tenant, {}).values(), key=lambda a: a["id"]):
            out.append({**agent, "state": "working" if agent["id"] in working else "idle"})
        return out

    def task_trace(self, tenant: str, task_id: str) -> dict[str, Any]:
        task = self._tasks.get(tenant, {}).get(task_id)
        if task is None:
            raise HiveNotFound(f"task {task_id!r} does not exist")
        events = [*task["claims"], *task["handoffs"], *task["artifacts"], *task["used_skills"], *task.get("leases", [])]
        if task["status"] in ("completed", "failed", "input_required"):
            events.append({"t": task["updated_at"], "seq": next(_TRACE_SEQ), "type": task["status"], "agent": task["owner_agent"], "reason": task.get("failure_reason"), "question": task.get("question")})
        events.sort(key=lambda e: e["seq"])  # appended in order; the terminal state event is stamped last
        return {"task": self._task_view(task), "events": events, "about": task["about"], "cypher": "-- FakeHive (23_task_trace.cypher in production)"}

    # -- skills ------------------------------------------------------------------------------
    def learn_skill(
        self,
        tenant: str,
        goal: str,
        steps: list[dict[str, Any]],
        learned_from: list[str],
        embedding: list[float] | None,
        version: int = 1,
    ) -> str:
        skill = {
            "id": new_id("skl"),
            "goal": goal,
            "version": int(version),
            "runs": 0,
            "success_rate": 0.0,
            "status": "active",
            "embedding": embedding,
            "created_at": now_ms(),
            "steps": [
                {"id": s.get("id") or new_id("stp"), "order": int(s.get("order", i)), "tool": s["tool"], "args_template": s.get("args_template", "{}"), "guard": s.get("guard")}
                for i, s in enumerate(steps)
            ],
            "learned_from": list(learned_from),
            "ran": [],
            "used_by": [],
        }
        with self._lock:
            self._skills[tenant][skill["id"]] = skill
            self.store(tenant).extra.setdefault("skills", {})[skill["id"]] = skill
        self.publish(tenant, "skill.learned", {"skill_id": skill["id"], "goal": goal, "steps": len(skill["steps"]), "learned_from": list(learned_from)})
        return skill["id"]

    def _skill_view(self, skill: dict[str, Any], distance: float | None = None) -> dict[str, Any]:
        view = {k: v for k, v in skill.items() if k not in {"embedding", "ran", "used_by"}}
        view["has_embedding"] = skill.get("embedding") is not None
        if distance is not None:
            view["distance"] = round(distance, 6)
            view["similarity"] = round(max(0.0, min(1.0, 1 - distance)), 6)
        return view

    def retrieve_skill(self, tenant: str, goal_embedding: list[float], k: int = 3) -> list[dict[str, Any]]:
        """Rank by ``(1 - distance) * (0.5 + 0.5 * success_rate)``: similarity first, success as a tie-breaking boost
        (mirrors 40_skill_retrieve.cypher; a new skill at 0.0 is not buried by an unrelated one with one success)."""
        scored = []
        for skill in self._skills.get(tenant, {}).values():
            if skill["status"] != "active":
                continue
            distance = cosine_distance(goal_embedding, skill.get("embedding"))
            score = (1.0 - distance) * (0.5 + 0.5 * float(skill.get("success_rate") or 0.0))
            scored.append((-score, distance, skill))
        scored.sort(key=lambda row: (row[0], row[1], row[2]["id"]))
        return [{**self._skill_view(s, d), "score": round(-neg, 6)} for neg, d, s in scored[:k]]

    def record_outcome(self, tenant: str, skill_id: str, agent_id: str, ok: bool, task_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            skill = self._skills.get(tenant, {}).get(skill_id)
            if skill is None:
                raise HiveNotFound(f"skill {skill_id!r} does not exist")
            runs = skill["runs"]
            skill["success_rate"] = (skill["success_rate"] * runs + (1.0 if ok else 0.0)) / (runs + 1)
            skill["runs"] = runs + 1
            skill["ran"].append({"agent": agent_id, "ok": ok, "at": now_ms(), "task_id": task_id})
            if task_id:
                skill["used_by"].append(task_id)
                task = self._tasks.get(tenant, {}).get(task_id)
                if task is not None:
                    task["used_skills"].append({"t": now_ms(), "seq": next(_TRACE_SEQ), "type": "skill_used", "skill": {"id": skill_id, "goal": skill["goal"]}})
            view = self._skill_view(skill)
        self.publish(tenant, "skill.ran", {"skill_id": skill_id, "agent_id": agent_id, "ok": ok, "task_id": task_id, "runs": view["runs"], "success_rate": view["success_rate"]})
        return view

    def deprecate_skill(self, tenant: str, old_id: str, new_id_: str) -> None:
        with self._lock:
            old = self._skills.get(tenant, {}).get(old_id)
            if old is None or new_id_ not in self._skills.get(tenant, {}):
                raise HiveNotFound(f"skills {old_id!r}/{new_id_!r} do not exist")
            old["status"] = "deprecated"
            old["deprecated_by"] = new_id_

    def skill_pagerank(self, tenant: str) -> list[dict[str, Any]]:
        skills = list(self._skills.get(tenant, {}).values())
        total_uses = sum(len(s["used_by"]) for s in skills) or 1
        rows = [
            {"id": s["id"], "goal": s["goal"], "runs": s["runs"], "success_rate": s["success_rate"], "score": round(0.15 + 0.85 * len(s["used_by"]) / total_uses, 6)}
            for s in skills
        ]
        rows.sort(key=lambda r: -r["score"])
        return rows

    def list_skills(self, tenant: str, status: str | None = None) -> list[dict[str, Any]]:
        skills = [self._skill_view(s) for s in self._skills.get(tenant, {}).values() if status in (None, s["status"])]
        skills.sort(key=lambda s: -s["created_at"])
        return skills

    def get_skill(self, tenant: str, skill_id: str) -> dict[str, Any]:
        skill = self._skills.get(tenant, {}).get(skill_id)
        if skill is None:
            raise HiveNotFound(f"skill {skill_id!r} does not exist")
        return self._skill_view(skill)

    def publish_to_commons(self, tenant: str, skill_id: str) -> str:
        self.get_skill(tenant, skill_id)
        return f"{skill_id}@{tenant}"

    # -- analytics ---------------------------------------------------------------------------
    def _entity_episode_ids(self, store: Any, entity_name: str) -> set[str]:
        name = entity_name.lower()
        entity_ids = {eid for eid, e in store.entities.items() if e["name"].lower() == name or name in e["name"].lower()}
        episode_ids: set[str] = set()
        for episode_id, eids in store.mentions.items():
            if entity_ids & set(eids):
                episode_ids.add(episode_id)
        for fact in store.facts.values():
            if fact["subject"].lower() == name or entity_ids & set(fact.get("entity_ids", [])):
                if fact.get("episode_id"):
                    episode_ids.add(fact["episode_id"])
        for episode in store.episodes.values():
            if name in str(episode.get("text", "")).lower():
                episode_ids.add(episode["id"])
        return episode_ids

    def owners(self, tenant: str, entity_name: str) -> dict[str, Any]:
        store = self.store(tenant)
        facts = [f for f in self.active_facts(tenant) if f["subject"].lower() == entity_name.lower()]
        assignments, assigned = self._assigned_owner(tenant, entity_name)
        if assignments:
            rows = [{"fact_id": assignments[0]["id"], "person": assigned}] if assigned else []
            return {"rows": rows, "cypher": "-- FakeHive (54_owners.cypher in production)"}
        rows = []
        for fact in facts:
            if fact.get("kind") != "commitment":
                continue
            person = store.persons.get(fact.get("owner_id"))
            if person:
                rows.append({"fact_id": fact["id"], "person": {"id": person["id"], "name": person["name"]}})
        return {"rows": rows, "cypher": "-- FakeHive (54_owners.cypher in production)"}

    def _assigned_owner(self, tenant: str, subject: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        assignments = [f for f in self.active_facts(tenant) if f["predicate"] == "owner" and f["subject"].lower() == subject.lower()]
        if len(assignments) != 1:
            return assignments, None
        value = str(assignments[0]["object"]).lower()
        people = [p for p in self.store(tenant).persons.values() if value in {str(p.get(k) or "").lower() for k in ("id", "name", "email")}]
        return assignments, people[0] if len(people) == 1 else None

    def who_knows(self, tenant: str, entity_name: str) -> dict[str, Any]:
        store = self.store(tenant)
        counts: dict[str, dict[str, Any]] = {}
        for episode_id in self._entity_episode_ids(store, entity_name):
            episode = store.episodes.get(episode_id)
            if not episode:
                continue
            participants = [(episode.get("speaker_id"), "SENT_BY" if episode.get("source_kind") == "email" else "SPOKEN_BY")]
            participants += [(pid, "SENT_TO") for pid in [*episode.get("to_ids", []), *episode.get("cc_ids", [])]]
            for pid, via in participants:
                if not pid:
                    continue
                person = store.persons.get(pid, {"id": pid, "name": pid})
                rec = counts.setdefault(pid, {"person": {"id": pid, "name": person.get("name")}, "mentions": 0, "last_at": 0, "via": set()})
                rec["mentions"] += 1
                rec["last_at"] = max(rec["last_at"], episode.get("t_occurred") or 0)
                rec["via"].add(via)
        rows = [{**r, "via": sorted(r["via"])} for r in counts.values()]
        rows.sort(key=lambda r: (-r["mentions"], -r["last_at"]))
        return {"rows": rows, "cypher": "-- FakeHive (50_who_knows.cypher in production)"}

    def open_commitments(self, tenant: str, person_id: str | None = None) -> dict[str, Any]:
        rows = []
        for fact in self.active_facts(tenant):
            if fact["kind"] != "commitment":
                continue
            owner_id = fact.get("owner_id") or fact.get("speaker_id")
            owner = self.get_person(tenant, owner_id)
            assignments, assigned = self._assigned_owner(tenant, fact["subject"])
            if assignments:
                owner = assigned
                owner_id = assigned["id"] if assigned else None
            rows.append({**fact, "owner": {"id": owner_id, "name": owner.get("name") if owner else None}})
        rows.sort(key=lambda r: (r.get("due_at") is None, r.get("due_at") or 0))
        rows = drop_closed_commitments(rows)
        if person_id:
            rows = [r for r in rows if (r.get("owner") or {}).get("id") == person_id]
        return {"rows": rows, "cypher": "-- FakeHive (51_open_commitments.cypher in production)"}

    def contradictions(self, tenant: str) -> dict[str, Any]:
        by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in self.active_facts(tenant):
            by_key[fact["key"]].append(fact)
        rows = []
        for key, facts in by_key.items():
            for i in range(len(facts)):
                for j in range(i + 1, len(facts)):
                    if facts[i]["object"] != facts[j]["object"]:
                        rows.append({"key": key, "facts": [facts[i], facts[j]]})
        return {"rows": rows, "cypher": "-- FakeHive (52_contradictions.cypher in production)"}

    def entity_clusters(self, tenant: str) -> dict[str, Any]:
        store = self.store(tenant)
        parent: dict[str, str] = {eid: eid for eid in store.entities}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for eids in store.mentions.values():
            known = [e for e in eids if e in parent]
            for a, b in zip(known, known[1:]):
                parent[find(a)] = find(b)
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for eid, entity in store.entities.items():
            groups[find(eid)].append({"id": eid, "name": entity["name"], "type": entity["type"]})
        rows = [{"component": i, "entities": sorted(ents, key=lambda e: e["name"])} for i, ents in enumerate(sorted(groups.values(), key=lambda g: -len(g)))]
        return {"rows": rows, "cypher": "-- FakeHive (61_wcc_entities.cypher in production)"}

    def stale_decisions(self, tenant: str, older_than_ms: int) -> dict[str, Any]:
        cutoff = now_ms() - int(older_than_ms)
        rows = [{**f, "age_ms": now_ms() - f["valid_from"]} for f in self.active_facts(tenant) if f["kind"] == "decision" and f["valid_from"] < cutoff]
        return {"rows": rows, "cypher": "-- FakeHive (53_stale_decisions.cypher in production)"}


# =============================================================================== RealHive
class RealHive:
    """Adapter over the ``hiveboard`` package plus the API's own read-only listing queries."""

    publishes_memory_events = True
    publishes_board_events = True
    kind = "falkordb"

    def __init__(self, db: Any, *, rw_password: str, ro_password: str) -> None:
        from hiveboard import analytics, board, events, memory, schema, skills, tenancy

        self.db = db
        self._memory, self._board, self._skills = memory, board, skills
        self._events, self._analytics, self._tenancy, self._schema = events, analytics, tenancy, schema
        self.rw_password = rw_password  # master secrets: per-tenant ACL passwords are derived from them (see _derive)
        self.ro_password = ro_password
        self._creds: dict[str, tuple[str, str]] = {}
        self._listeners: dict[str, list[EventListener]] = defaultdict(list)
        self._subscriber_threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._stopping = threading.Event()

    @classmethod
    def connect(cls, url: str, *, admin_user: str | None, admin_password: str | None, rw_password: str, ro_password: str) -> RealHive:
        from hiveboard.db import HiveDB

        db = HiveDB(url, admin_user=admin_user, admin_password=admin_password)
        hive = cls(db, rw_password=rw_password, ro_password=ro_password)
        for tenant in db.list_tenants():
            try:
                hive.credentials(tenant)  # also points db.ro(tenant) at the tenant's ro user
            except Exception as exc:  # noqa: BLE001 - a broken tenant must not stop the others
                log.warning("could not resolve ACL credentials for %s: %s", tenant, exc)
        return hive

    # -- per-tenant ACL credentials ----------------------------------------------------------
    # Tenant users get their own passwords. They are NOT stored: tenant ro/rw users can read the commons registry,
    # so a password kept there would be readable by every other tenant. Instead each password is an HMAC of the tenant
    # slug under the master secret (TENANT_RW_PASSWORD / TENANT_RO_PASSWORD), so a restart re-derives it. Tenants
    # created before this keep their old shared password until rotated; the probe below finds whichever one works.
    def _derive(self, tenant: str, role: str) -> str:
        import hashlib
        import hmac

        master = self.rw_password if role == "rw" else self.ro_password
        return hmac.new(master.encode("utf-8"), f"minutes:{tenant}:{role}".encode(), hashlib.sha256).hexdigest()

    def _accepts(self, user: str, password: str) -> bool:
        import redis

        probe = redis.Redis(host=self.db.host, port=self.db.port, username=user, password=password, socket_connect_timeout=2, socket_timeout=5)
        try:
            return bool(probe.ping())
        except redis.AuthenticationError:
            return False
        except redis.RedisError as exc:
            log.debug("password probe for %s failed: %s", user, exc)
            return False
        finally:
            probe.close()

    def credentials(self, tenant: str, *, rotate: bool = False) -> tuple[str, str]:
        """``(rw_password, ro_password)`` that work for the tenant's ACL users, and make ``db.ro(tenant)`` use the ro user."""
        if not rotate and tenant in self._creds:
            return self._creds[tenant]
        resolved: list[str] = []
        for role, user, legacy in (("rw", self.db.rw_user(tenant), self.rw_password), ("ro", self.db.ro_user(tenant), self.ro_password)):
            derived = self._derive(tenant, role)
            candidates = [derived] if rotate else [derived, legacy]
            resolved.append(next((c for c in candidates if self._accepts(user, c)), derived))  # no working one: (re)create with the derived
        creds = (resolved[0], resolved[1])
        self._creds[tenant] = creds
        self.db.configure_ro(tenant, creds[1])
        return creds

    def import_work_manifest(self, tenant: str, manifest: dict[str, Any]) -> int:
        from hiveboard.impact import import_manifest
        return import_manifest(self.db, tenant, manifest)

    def work_impacts(self, tenant: str) -> dict[str, Any]:
        from hiveboard.impact import work_impacts
        return self._with_cypher(work_impacts(self.db, tenant))

    def save_impact_draft(self, tenant: str, draft: dict[str, Any]) -> dict[str, Any] | None:
        from hiveboard.impact import save_draft
        return save_draft(self.db, tenant, draft)

    def list_impact_drafts(self, tenant: str) -> list[dict[str, Any]]:
        from hiveboard.impact import list_drafts
        return list_drafts(self.db, tenant)

    # -- helpers -----------------------------------------------------------------------------
    @staticmethod
    def _rows(result: Any) -> list[dict[str, Any]]:
        return [dict(r) if isinstance(r, dict) else r for r in result]

    @staticmethod
    def _with_cypher(result: Any) -> dict[str, Any]:
        return {"rows": [dict(r) if isinstance(r, dict) else r for r in result], "cypher": getattr(result, "cypher", "")}

    def _ro(self, tenant: str, query: str, params: dict[str, Any] | None = None) -> Any:
        return self.db.ro(tenant).ro_query(query, params or {}, timeout=3000)

    def _rw(self, tenant: str, query: str, params: dict[str, Any] | None = None) -> Any:
        return self.db.graph(tenant).query(query, params or {})

    @staticmethod
    def _props(node: Any) -> dict[str, Any] | None:
        from hiveboard.records import props

        return props(node)

    @staticmethod
    def _brief(node: Any, *fields: str) -> dict[str, Any] | None:
        from hiveboard.records import brief

        return brief(node, *fields)

    def _norm_fact(self, rec: dict[str, Any] | None) -> dict[str, Any] | None:
        """hiveboard fact record -> the API shape (adds ``speaker_id``, ``entity_ids``, ``source``)."""
        if rec is None:
            return None
        out = dict(rec)
        speaker = out.get("speaker") or {}
        out.setdefault("speaker_id", speaker.get("id"))
        out.setdefault("entity_ids", [e["id"] for e in out.get("entities") or [] if e and e.get("id")])
        out.setdefault("kind", "commitment" if "Commitment" in out.get("labels", []) else "decision" if "Decision" in out.get("labels", []) else "fact")
        return out

    # -- tenancy -----------------------------------------------------------------------------
    def ping(self) -> bool:
        return bool(self.db.ping())

    def db_version(self) -> str:
        try:
            return str(self.db.server_version())
        except Exception as exc:  # noqa: BLE001
            log.warning("server_version failed: %s", exc)
            return "unknown"

    def list_tenants(self) -> list[str]:
        return list(self.db.list_tenants())

    def create_tenant(self, slug: str, display_name: str, pw_rw: str | None = None, pw_ro: str | None = None, rotate: bool = False) -> dict[str, Any]:
        """``tenancy.create_tenant(db, slug, name, pw_rw, pw_ro, rotate)``: idempotent, passwords untouched unless ``rotate``."""
        rw, ro = self.credentials(slug, rotate=rotate)
        rw, ro = pw_rw or rw, pw_ro or ro
        info = self._tenancy.create_tenant(self.db, slug, display_name, rw, ro, rotate=rotate)
        self._creds[slug] = (rw, ro)
        self.db.configure_ro(slug, ro)
        return {**self.tenant_info(slug), "schema": info.get("schema")}

    def delete_tenant(self, slug: str) -> None:
        self._tenancy.delete_tenant(self.db, slug)
        self._creds.pop(slug, None)

    def set_tenant_meta(self, slug: str, meta: dict[str, Any]) -> dict[str, Any]:
        """``tenancy.set_tenant_meta(db, slug, meta)``: merge keys into the commons registry row (None removes a key)."""
        return dict(self._tenancy.set_tenant_meta(self.db, slug, meta) or {})

    def get_tenant_meta(self, slug: str) -> dict[str, Any]:
        """``tenancy.get_tenant_meta(db, slug)``: the registry row's metadata (api_key_hash, embedding_model, embedding_dim, ...)."""
        return dict(self._tenancy.get_tenant_meta(self.db, slug) or {})

    def container_episodes(self, tenant: str, container_id: str) -> list[dict[str, Any]]:
        """``[{id, seq, t_start, t_end, speaker_id, text_hash}]`` for a Meeting or EmailThread (ingest contract), read-only."""
        res = self._ro(
            tenant,
            "MATCH (c {id: $id})-[:HAS_EPISODE]->(ep:Episode) WHERE c:Meeting OR c:EmailThread "
            "OPTIONAL MATCH (ep)-[:SPOKEN_BY|SENT_BY]->(p:Person) "
            "RETURN ep.id, ep.seq, ep.t_start, ep.t_end, p.id, ep.text_hash, ep.text ORDER BY ep.seq, ep.t_start",
            {"id": container_id},
        )
        return [
            {"id": eid, "seq": seq, "t_start": t0, "t_end": t1, "speaker_id": pid, "text_hash": th or _text_hash(text)}
            for eid, seq, t0, t1, pid, th, text in res.result_set
        ]

    def ensure_schema(self, tenant: str) -> dict[str, int]:
        result = dict(self._schema.ensure_schema(self.db, tenant))
        rw, ro = self.credentials(tenant)
        self._tenancy.ensure_tenant_access(self.db, tenant, rw, ro)
        # Surface invalid or disabled configured credentials at startup, before workers run.
        self._ro(tenant, "RETURN 1")
        return result

    def load_udfs(self) -> None:
        self._schema.load_udfs(self.db)

    def counts(self, tenant: str) -> dict[str, int]:
        counts: dict[str, int] = {"episodes": 0, "facts": 0, "decisions": 0, "commitments": 0, "tasks": 0, "skills": 0, "entities": 0, "meetings": 0, "threads": 0}
        for key, label in (("episodes", "Episode"), ("tasks", "Task"), ("skills", "Skill"), ("entities", "Entity"), ("meetings", "Meeting"), ("threads", "EmailThread")):
            res = self._ro(tenant, f"MATCH (n:{label}) RETURN count(n)")
            counts[key] = int(res.result_set[0][0]) if res.result_set else 0
        res = self._ro(tenant, "MATCH (f:Fact) RETURN f.kind, count(f)")
        for kind, n in res.result_set:
            key = {"fact": "facts", "decision": "decisions", "commitment": "commitments"}.get(kind or "fact", "facts")
            counts[key] += int(n)
        return counts

    def graph_size(self, tenant: str) -> dict[str, int]:
        """Total nodes and edges of `team_<tenant>` via read-only Cypher.

        FalkorDB 6.0.1 answers GRAPH.MEMORY USAGE with zeros, so these counts are the size signal
        the UI shows; `usage_mb` stays for servers that do report memory.
        """
        size = {"nodes": 0, "edges": 0}
        for key, query in (("nodes", "MATCH (n) RETURN count(n)"), ("edges", "MATCH ()-[r]->() RETURN count(r)")):
            try:
                res = self._ro(tenant, query)
                size[key] = int(res.result_set[0][0]) if res.result_set else 0
            except Exception as exc:  # noqa: BLE001 - a size probe must not break the tenant list
                log.warning("%s count failed for %s: %s", key, tenant, exc)
        return size

    def tenant_info(self, tenant: str) -> dict[str, Any]:
        registry = {row["slug"]: row for row in self._tenancy.list_registered_tenants(self.db)}
        meta = registry.get(tenant, {})
        try:
            usage = float(self.db.usage(tenant).get("total_mb", 0.0))
        except Exception as exc:  # noqa: BLE001
            log.warning("usage failed for %s: %s", tenant, exc)
            usage = 0.0
        acl = self._tenancy.acl_rules(self.db, tenant)
        return {
            "slug": tenant,
            "display_name": meta.get("display_name") or tenant.capitalize(),
            "graph": acl.get("graph") or f"team_{tenant}",
            "usage_mb": round(usage, 3),
            **self.graph_size(tenant),
            "counts": self.counts(tenant),
            "acl": {"rw_user": acl.get("rw_user"), "ro_user": acl.get("ro_user"), "rules": acl.get("rules", []), "isolation": acl.get("isolation")},
            "meta": {k: v for k, v in self.get_tenant_meta(tenant).items() if k != "api_key_hash"},
        }

    def acl_probe(self, tenant: str, target: str) -> dict[str, Any]:
        from falkordb import FalkorDB

        user = self.db.ro_user(tenant)
        target_graph = self.db.graph_name(target)
        command = f'GRAPH.RO_QUERY {target_graph} "MATCH (n) RETURN count(n)"'
        try:
            client = FalkorDB(host=self.db.host, port=self.db.port, username=user, password=self.credentials(tenant)[1])
            res = client.select_graph(target_graph).ro_query("MATCH (n) RETURN count(n)", timeout=2000)
            value = res.result_set[0][0] if res.result_set else None
            return {"allowed": True, "user": user, "target_graph": target_graph, "command": command, "result": value, "error": None}
        except Exception as exc:  # noqa: BLE001 - the denial is the point
            return {"allowed": False, "user": user, "target_graph": target_graph, "command": command, "error": str(exc)}

    def snapshot(self, tenant: str, label: str) -> dict[str, Any]:
        name = self._tenancy.snapshot(self.db, tenant, label)
        snaps = [s for s in self.list_snapshots(tenant) if s.get("name") == name]
        return snaps[0] if snaps else {"name": name, "label": label, "taken_at": now_ms()}

    def list_snapshots(self, tenant: str) -> list[dict[str, Any]]:
        return [dict(s) for s in self._tenancy.list_snapshots(self.db, tenant)]

    # -- memory writes (pipeline surface) ----------------------------------------------------
    def remember_person(self, tenant: str, person: dict[str, Any]) -> str:
        return self._memory.remember_person(self.db, tenant, person)

    def remember_meeting(self, tenant: str, meeting: dict[str, Any]) -> str:
        return self._memory.remember_meeting(self.db, tenant, meeting)

    def remember_thread(self, tenant: str, thread: dict[str, Any]) -> str:
        return self._memory.remember_thread(self.db, tenant, thread)

    def remember_episodes(self, tenant: str, meeting_id: str, episodes: list[dict[str, Any]]) -> int:
        return self._memory.remember_episodes(self.db, tenant, meeting_id, episodes)

    def remember_email_episodes(self, tenant: str, thread_id: str, episodes: list[dict[str, Any]]) -> int:
        return self._memory.remember_email_episodes(self.db, tenant, thread_id, episodes)

    def upsert_entities(self, tenant: str, entities: list[dict[str, Any]]) -> dict[str, str]:
        return dict(self._memory.upsert_entities(self.db, tenant, entities))

    def remember_entities(self, tenant: str, entities: list[dict[str, Any]]) -> int:
        return self._memory.remember_entities(self.db, tenant, entities)

    def link_mentions(self, tenant: str, episode_id: str, entity_ids: list[str]) -> int:
        return self._memory.link_mentions(self.db, tenant, episode_id, entity_ids)

    def remember_fact(self, tenant: str, fact: dict[str, Any], supersede: bool = False) -> dict[str, Any]:
        from hiveboard.errors import Conflict

        try:
            result = self._memory.remember_fact(self.db, tenant, fact, supersede=supersede)
        except Conflict as exc:  # supersede=True met a later-valid active fact: the caller must insert in the chain instead
            raise HiveConflict(str(exc)) from exc
        precedents = fact.get("precedent_ids") or []
        if precedents and not result.get("existing"):
            self._rw(
                tenant,
                "MATCH (new:Fact {id: $id}) UNWIND $olds AS oid MATCH (old:Fact {id: oid}) "
                "MERGE (old)-[p:PRECEDENT_FOR]->(new) SET p.at = $now RETURN count(p)",
                {"id": result["id"], "olds": list(precedents), "now": now_ms()},
            )
        return result

    def supersede_fact(self, tenant: str, old_id: str, new_fact: dict[str, Any]) -> dict[str, Any]:
        from hiveboard.errors import Conflict, NotFound

        try:
            return self._memory.supersede_fact(self.db, tenant, old_id, new_fact)
        except NotFound as exc:
            raise HiveNotFound(str(exc)) from exc
        except Conflict as exc:
            raise HiveConflict(str(exc)) from exc

    def retract_fact(self, tenant: str, fact_id: str, reason: str) -> None:
        self._memory.retract_fact(self.db, tenant, fact_id, reason)

    def facts_by_key(self, tenant: str, key: str) -> list[dict[str, Any]]:
        res = self._ro(
            tenant,
            "MATCH (f:Fact {key: $key}) OPTIONAL MATCH (f)-[:SUPERSEDES]->(o:Fact) "
            "RETURN f, collect(o.id) ORDER BY f.valid_from ASC, f.created_at ASC",
            {"key": key.lower()},
        )
        rows = []
        for f, supersedes in res.result_set:
            rec = self._props(f) or {}
            rec["supersedes"] = [s for s in supersedes if s]
            rows.append(rec)
        return rows

    def insert_fact_in_chain(self, tenant: str, fact: dict[str, Any], before_id: str, after_id: str | None = None) -> dict[str, Any]:
        """Passthrough to ``hiveboard.memory.insert_fact_in_chain(db, tenant, fact, before_id)``
        -> ``{"id", "inserted", "confirmed", "before_id"}``. The chain surgery lives in the substrate."""
        from hiveboard.errors import Conflict, NotFound

        try:
            return dict(self._memory.insert_fact_in_chain(self.db, tenant, fact, before_id))
        except NotFound as exc:
            raise HiveNotFound(str(exc)) from exc
        except Conflict as exc:
            raise HiveConflict(str(exc)) from exc

    def confirm_fact(self, tenant: str, fact_id: str, episode_id: str) -> None:
        self._rw(
            tenant,
            "MATCH (f:Fact {id: $fid}), (ep:Episode {id: $eid}) MERGE (f)-[c:CONFIRMED_BY]->(ep) SET c.at = $now RETURN f.id",
            {"fid": fact_id, "eid": episode_id, "now": now_ms()},
        )

    def update_fact_due(self, tenant: str, fact_id: str, due_at: int | None) -> dict[str, Any]:
        res = self._rw(tenant, "MATCH (f:Fact {id: $id}) SET f.due_at = $due RETURN f", {"id": fact_id, "due": due_at})
        if not res.result_set:
            raise HiveNotFound(fact_id)
        return self.get_fact(tenant, fact_id) or {}

    # -- memory reads ------------------------------------------------------------------------
    def active_facts(self, tenant: str, entity_id: str | None = None, key: str | None = None) -> list[dict[str, Any]]:
        return [self._norm_fact(r) for r in self._memory.active_facts(self.db, tenant, entity_id=entity_id, key=key, limit=ANALYTICS_LIMIT)]

    def belief_at(self, tenant: str, t: int, entity_id: str | None = None) -> list[dict[str, Any]]:
        return self.belief_at_result(tenant, t, entity_id)["rows"]

    def belief_at_result(self, tenant: str, t: int, entity_id: str | None = None) -> dict[str, Any]:
        rows = self._memory.belief_at(self.db, tenant, t, entity_id=entity_id, limit=ANALYTICS_LIMIT)
        return {"rows": [self._norm_fact(r) for r in rows], "cypher": getattr(rows, "cypher", "")}

    def why(self, tenant: str, node_id: str) -> dict[str, Any]:
        from hiveboard.errors import NotFound

        try:
            return self._memory.why(self.db, tenant, node_id)
        except NotFound as exc:
            raise HiveNotFound(str(exc)) from exc

    def recall(self, tenant: str, query_embedding: list[float], k: int = 8, now: int | None = None, label: str = "Fact") -> dict[str, Any]:
        return self._memory.recall(self.db, tenant, query_embedding, k=k, now=now, label=label)

    def fulltext(self, tenant: str, text: str, label: str = "Episode", k: int = 10) -> list[dict[str, Any]]:
        return self._rows(self._memory.fulltext(self.db, tenant, text, label=label, k=k))

    def list_persons(self, tenant: str) -> list[dict[str, Any]]:
        res = self._ro(tenant, "MATCH (p:Person) RETURN p ORDER BY p.name")
        return [self._props(row[0]) for row in res.result_set]

    def get_person(self, tenant: str, person_id: str | None) -> dict[str, Any] | None:
        if not person_id:
            return None
        res = self._ro(tenant, "MATCH (p:Person {id: $id}) RETURN p", {"id": person_id})
        return self._props(res.result_set[0][0]) if res.result_set else None

    def list_meetings(self, tenant: str) -> list[dict[str, Any]]:
        res = self._ro(
            tenant,
            "MATCH (m:Meeting) OPTIONAL MATCH (m)-[:HAS_EPISODE]->(ep:Episode) "
            "OPTIONAL MATCH (f:Fact)-[:DERIVED_FROM]->(ep) "
            "RETURN m, count(DISTINCT ep), count(DISTINCT f) ORDER BY m.started_at",
        )
        return [{**(self._props(m) or {}), "episodes": int(eps), "facts": int(facts)} for m, eps, facts in res.result_set]

    def get_meeting(self, tenant: str, meeting_id: str) -> dict[str, Any] | None:
        res = self._ro(tenant, "MATCH (m:Meeting {id: $id}) RETURN m", {"id": meeting_id})
        return self._props(res.result_set[0][0]) if res.result_set else None

    def meeting_episodes(self, tenant: str, meeting_id: str) -> list[dict[str, Any]]:
        res = self._ro(
            tenant,
            "MATCH (m:Meeting {id: $id})-[:HAS_EPISODE]->(ep:Episode) OPTIONAL MATCH (ep)-[:SPOKEN_BY]->(p:Person) "
            "RETURN ep, p ORDER BY ep.seq",
            {"id": meeting_id},
        )
        out = []
        for ep, person in res.result_set:
            rec = self._props(ep) or {}
            rec["container_id"] = meeting_id
            rec["container_kind"] = "meeting"
            rec["speaker_id"] = person.properties.get("id") if person is not None else rec.get("speaker_id")
            rec["speaker"] = self._brief(person)
            out.append(rec)
        return out

    def list_threads(self, tenant: str) -> list[dict[str, Any]]:
        res = self._ro(
            tenant,
            "MATCH (t:EmailThread) OPTIONAL MATCH (t)-[:HAS_EPISODE]->(ep:Episode) "
            "OPTIONAL MATCH (f:Fact)-[:DERIVED_FROM]->(ep) "
            "RETURN t, count(DISTINCT ep), count(DISTINCT f) ORDER BY t.started_at",
        )
        return [{**(self._props(t) or {}), "messages": int(msgs), "facts": int(facts)} for t, msgs, facts in res.result_set]

    def get_thread(self, tenant: str, thread_id: str) -> dict[str, Any] | None:
        res = self._ro(tenant, "MATCH (t:EmailThread {id: $id}) RETURN t", {"id": thread_id})
        return self._props(res.result_set[0][0]) if res.result_set else None

    def thread_messages(self, tenant: str, thread_id: str) -> list[dict[str, Any]]:
        res = self._ro(
            tenant,
            "MATCH (t:EmailThread {id: $id})-[:HAS_EPISODE]->(ep:Episode) "
            "OPTIONAL MATCH (ep)-[:SENT_BY]->(s:Person) "
            "OPTIONAL MATCH (ep)-[r:SENT_TO]->(p:Person) "
            "OPTIONAL MATCH (ep)-[:REPLIES_TO]->(prev:Episode) "
            "RETURN ep, s, collect({id: p.id, name: p.name, email: p.email, cc: r.cc}), prev.id ORDER BY ep.seq",
            {"id": thread_id},
        )
        out = []
        for ep, sender, recipients, prev_id in res.result_set:
            rec = self._props(ep) or {}
            rec["container_id"] = thread_id
            rec["container_kind"] = "thread"
            rec["speaker_id"] = sender.properties.get("id") if sender is not None else rec.get("sender_id")
            rec["sender"] = self._brief(sender, "id", "name", "email")
            people = [r for r in recipients if r and r.get("id")]
            rec["to_ids"] = [r["id"] for r in people if not r.get("cc")]
            rec["cc_ids"] = [r["id"] for r in people if r.get("cc")]
            rec["to"] = [{"id": r["id"], "name": r.get("name"), "email": r.get("email")} for r in people if not r.get("cc")]
            rec["cc"] = [{"id": r["id"], "name": r.get("name"), "email": r.get("email")} for r in people if r.get("cc")]
            rec["in_reply_to_episode_id"] = prev_id
            out.append(rec)
        return out

    def get_episode(self, tenant: str, episode_id: str) -> dict[str, Any] | None:
        res = self._ro(
            tenant,
            "MATCH (ep:Episode {id: $id}) OPTIONAL MATCH (c)-[:HAS_EPISODE]->(ep) "
            "OPTIONAL MATCH (ep)-[:SPOKEN_BY|SENT_BY]->(p:Person) RETURN ep, c, p",
            {"id": episode_id},
        )
        if not res.result_set:
            return None
        ep, container, person = res.result_set[0]
        rec = self._props(ep) or {}
        if container is not None:
            rec["container_id"] = container.properties.get("id")
            rec["container_kind"] = "thread" if "EmailThread" in container.labels else "meeting"
        rec["speaker_id"] = person.properties.get("id") if person is not None else rec.get("speaker_id") or rec.get("sender_id")
        return rec

    def list_entities(self, tenant: str) -> list[dict[str, Any]]:
        res = self._ro(tenant, "MATCH (e:Entity) RETURN e ORDER BY e.name")
        return [self._props(row[0]) for row in res.result_set]

    _FACT_QUERY = (
        "MATCH (f:Fact) WHERE ($id IS NULL OR f.id = $id) AND ($status IS NULL OR f.status = $status) "
        "AND ($kind IS NULL OR f.kind = $kind) "
        "AND ($cursor_vf IS NULL OR coalesce(f.valid_from, 0) > $cursor_vf OR (coalesce(f.valid_from, 0) = $cursor_vf AND f.id > $cursor_id)) "
        "OPTIONAL MATCH (f)-[:ABOUT]->(en:Entity) WITH f, collect(DISTINCT en) AS entities "
        "WHERE $entity IS NULL OR any(x IN entities WHERE x.id = $entity OR toLower(x.name) = toLower($entity)) "
        "OPTIONAL MATCH (f)-[:STATED_BY]->(p:Person) OPTIONAL MATCH (f)-[:DERIVED_FROM]->(ep0:Episode) "
        # a fact confirmed by later episodes has several DERIVED_FROM edges: keep the earliest, one row per fact
        "WITH f, entities, p, ep0 ORDER BY ep0.t_start ASC WITH f, entities, p, head(collect(ep0)) AS ep "
        "OPTIONAL MATCH (c)-[:HAS_EPISODE]->(ep) OPTIONAL MATCH (f)-[:SUPERSEDES]->(o:Fact) "
        "RETURN f, entities, p, ep, c, collect(DISTINCT o.id) ORDER BY coalesce(f.valid_from, 0) ASC, f.id ASC LIMIT $limit"
    )

    def _fact_rows(self, tenant: str, **params: Any) -> list[dict[str, Any]]:
        from hiveboard.memory import _source

        args = {"id": None, "status": "active", "kind": None, "entity": None, "limit": FACT_PAGE, "cursor_vf": None, "cursor_id": None, **params}
        res = self._ro(tenant, self._FACT_QUERY, args)
        rows = []
        for f, entities, speaker, ep, container, supersedes in res.result_set:
            rec = self._props(f) or {}
            rec["entities"] = [self._brief(e, "id", "name", "type") for e in entities]
            rec["entity_ids"] = [e["id"] for e in rec["entities"] if e]
            rec["speaker"] = self._brief(speaker)
            rec["speaker_id"] = speaker.properties.get("id") if speaker is not None else None
            rec["episode_id"] = ep.properties.get("id") if ep is not None else None
            is_meeting = container is not None and "Meeting" in container.labels
            is_thread = container is not None and "EmailThread" in container.labels
            rec["meeting"] = self._brief(container, "id", "title") if is_meeting else None
            rec["thread"] = self._brief(container, "id", "subject") if is_thread else None
            rec["source"] = _source(ep, container if is_meeting else None, container if is_thread else None)
            rec["supersedes"] = [s for s in supersedes if s]
            rows.append(self._norm_fact(rec))
        return rows

    def page_facts(self, tenant: str, status: str | None = "active", entity: str | None = None, kind: str | None = None, limit: int = 200, cursor: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
        """One page ordered by (valid_from, id) plus the cursor of the next page (None when exhausted)."""
        after = decode_cursor(cursor)
        limit = max(1, int(limit))
        rows = self._fact_rows(
            tenant,
            status=None if status in (None, "all") else status,
            entity=entity,
            kind=kind,
            limit=limit + 1,
            cursor_vf=after[0] if after else None,
            cursor_id=after[1] if after else None,
        )
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1].get("valid_from"), str(page[-1].get("id"))) if len(rows) > limit else None
        return page, next_cursor

    def list_facts(self, tenant: str, status: str | None = "active", entity: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        """Every matching fact: pages through ``page_facts`` so timeline, belief and impact never hit a silent cap."""
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page, cursor = self.page_facts(tenant, status=status, entity=entity, kind=kind, limit=FACT_PAGE, cursor=cursor)
            out.extend(page)
            if cursor is None or not page:
                return out

    def get_fact(self, tenant: str, fact_id: str) -> dict[str, Any] | None:
        rows = self._fact_rows(tenant, id=fact_id, status=None, limit=1)
        return rows[0] if rows else None

    def add_turn(self, tenant: str, session_id: str, role: str, text: str, meta: dict[str, Any] | None = None, key_hash: str | None = None) -> dict[str, Any]:
        import json

        turn = {"id": new_id("turn"), "session_id": session_id, "role": role, "text": text, "t": now_ms(), "meta": json.dumps(meta or {}, default=str)}
        self._rw(
            tenant,
            "MERGE (s:ChatSession {id: $sid}) ON CREATE SET s.created_at = $t, s.key_hash = $key_hash "
            "CREATE (t:Turn {id: $id, session_id: $sid, role: $role, text: $text, t: $t, meta: $meta}) "
            "MERGE (s)-[:HAS_TURN]->(t) RETURN t.id",
            {"sid": session_id, "key_hash": key_hash, **turn},
        )
        turn["meta"] = meta or {}
        return turn

    def get_turns(self, tenant: str, session_id: str, key_hash: str | None = None) -> list[dict[str, Any]]:
        """With ``key_hash`` only a session stamped with that key at creation is visible (TENANT_KEYS_REQUIRED)."""
        import json

        if key_hash is not None:
            owner = self._ro(tenant, "MATCH (s:ChatSession {id: $sid}) RETURN s.key_hash", {"sid": session_id})
            if not owner.result_set or owner.result_set[0][0] != key_hash:
                return []
        res = self._ro(tenant, "MATCH (t:Turn {session_id: $sid}) RETURN t ORDER BY t.t", {"sid": session_id})
        out = []
        for (node,) in res.result_set:
            rec = self._props(node) or {}
            if isinstance(rec.get("meta"), str):
                try:
                    rec["meta"] = json.loads(rec["meta"])
                except json.JSONDecodeError:
                    rec["meta"] = {}
            out.append(rec)
        return out

    def run_ro_cypher(self, tenant: str, query: str, params: dict[str, Any] | None = None, timeout_ms: int = 3000) -> dict[str, Any]:
        from hiveboard.records import row_value

        res = self.db.ro(tenant).ro_query(query, params or {}, timeout=timeout_ms)
        header = [h[1] if isinstance(h, (list, tuple)) and len(h) > 1 else str(h) for h in (res.header or [])]
        rows = []
        for row in res.result_set:
            values = [row_value(v) for v in row]
            rows.append(dict(zip(header, values)) if header and len(header) == len(values) else {"row": values})
        return {"rows": rows, "cypher": query}

    # -- events ------------------------------------------------------------------------------
    def publish(self, tenant: str, event: str, payload: dict[str, Any]) -> None:
        self._events.publish(self.db, tenant, event, payload)

    def add_listener(self, tenant: str, fn: EventListener) -> None:
        with self._lock:
            self._listeners[tenant].append(fn)
            if tenant not in self._subscriber_threads:
                thread = threading.Thread(target=self._pump, args=(tenant,), name=f"events-{tenant}", daemon=True)
                self._subscriber_threads[tenant] = thread
                thread.start()

    def remove_listener(self, tenant: str, fn: EventListener) -> None:
        with self._lock:
            if fn in self._listeners.get(tenant, []):
                self._listeners[tenant].remove(fn)

    def _dispatch(self, tenant: str, event: dict[str, Any]) -> None:
        with self._lock:
            listeners = list(self._listeners.get(tenant, []))
        for fn in listeners:
            try:
                fn(event)
            except Exception as exc:  # noqa: BLE001
                log.warning("event listener failed: %s", exc)

    def _pump(self, tenant: str) -> None:
        """One long-lived SUBSCRIBE per tenant. ``get_message(timeout=1.0)`` is polled so the stop flag is checked
        between messages; the subscription is only re-opened after a connection error (never on idle), so an
        event published at any moment is delivered."""
        import orjson

        channel = self._events.channel(tenant)
        while not self._stopping.is_set():
            pubsub = None
            try:
                pubsub = self.db.connection.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(channel)
                while not self._stopping.is_set():
                    message = pubsub.get_message(timeout=1.0)
                    if message is None or message.get("type") != "message":
                        continue
                    try:
                        event = orjson.loads(message["data"])
                    except (orjson.JSONDecodeError, TypeError) as exc:
                        log.warning("undecodable event on %s: %s", channel, exc)
                        continue
                    self._dispatch(tenant, event)
            except Exception as exc:  # noqa: BLE001 - connection trouble: resubscribe after a short pause
                if self._stopping.is_set():
                    return
                log.warning("event subscription for %s dropped (%s); reconnecting", tenant, exc)
                self._stopping.wait(1.0)
            finally:
                if pubsub is not None:
                    try:
                        pubsub.close()
                    except Exception:  # noqa: BLE001
                        pass

    def close(self) -> None:
        self._stopping.set()
        self.db.close()

    # -- board -------------------------------------------------------------------------------
    def register_agent(self, tenant: str, agent_id: str, name: str, capabilities: list[str], model: str) -> None:
        self._board.register_agent(self.db, tenant, agent_id, name, capabilities, model)

    def touch_agent(self, tenant: str, agent_id: str) -> None:
        self._rw(tenant, "MATCH (a:Agent {id: $id}) SET a.last_seen = $now RETURN a.id", {"id": agent_id, "now": now_ms()})

    def submit_task(self, tenant: str, kind: str, payload: dict[str, Any], requires: list[str], about_ids: Iterable[str] = (), priority: int = 5, owner_agent: str | None = None) -> str:
        submit = self._board.submit_task
        if owner_agent and _accepts(submit, "owner_agent"):
            return submit(self.db, tenant, kind, payload, list(requires), list(about_ids), priority, owner_agent=owner_agent)
        task_id = submit(self.db, tenant, kind, payload, list(requires), list(about_ids), priority)
        if owner_agent:
            # Addressed submission: the board's submit_task has no owner parameter (yet); stamp it so only that agent claims.
            self._rw(tenant, "MATCH (t:Task {id: $id}) SET t.owner_agent = $agent RETURN t.id", {"id": task_id, "agent": owner_agent})
        return task_id

    def claim(self, tenant: str, task_id: str, agent_id: str, expected_version: int, lease_ms: int = DEFAULT_LEASE_MS) -> int | None:
        """``board.claim(db, tenant, task_id, agent_id, expected_version, lease_ms=120000)``."""
        return self._board.claim(self.db, tenant, task_id, agent_id, expected_version, lease_ms=lease_ms)

    def heartbeat(self, tenant: str, task_id: str, agent_id: str, lease_ms: int = DEFAULT_LEASE_MS) -> bool:
        """``board.heartbeat(db, tenant, task_id, agent_id, lease_ms=120000) -> bool``."""
        return bool(self._board.heartbeat(self.db, tenant, task_id, agent_id, lease_ms=lease_ms))

    def reap_expired(self, tenant: str, now: int | None = None) -> list[str]:
        """``board.reap_expired(db, tenant, now=None) -> list[str]`` of task ids returned to ``submitted``."""
        return list(self._board.reap_expired(self.db, tenant, now=now) or [])

    def next_open_task(self, tenant: str, agent_id: str) -> dict[str, Any] | None:
        return self._board.next_open_task(self.db, tenant, agent_id)

    def handoff(self, tenant: str, task_id: str, from_agent: str, to_agent: str, expected_version: int, summary: str, subgraph_ids: list[str]) -> int | None:
        return self._board.handoff(self.db, tenant, task_id, from_agent, to_agent, expected_version, summary, list(subgraph_ids))

    def complete(self, tenant: str, task_id: str, agent_id: str, artifact: dict[str, Any] | None = None) -> None:
        from hiveboard.errors import NotFound

        try:
            self._board.complete(self.db, tenant, task_id, agent_id, artifact)
        except NotFound as exc:
            raise HiveNotFound(str(exc)) from exc

    def fail(self, tenant: str, task_id: str, agent_id: str, reason: str) -> None:
        from hiveboard.errors import NotFound

        try:
            self._board.fail(self.db, tenant, task_id, agent_id, reason)
        except NotFound as exc:
            raise HiveNotFound(str(exc)) from exc

    def need_input(self, tenant: str, task_id: str, agent_id: str, question: str) -> None:
        self._board.need_input(self.db, tenant, task_id, agent_id, question)

    def list_tasks(self, tenant: str, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self._rows(self._board.list_tasks(self.db, tenant, status=status or None, limit=limit))

    def get_task(self, tenant: str, task_id: str) -> dict[str, Any] | None:
        from hiveboard.errors import NotFound

        try:
            return self._board.task_trace(self.db, tenant, task_id)["task"]
        except NotFound:
            return None

    def list_agents(self, tenant: str) -> list[dict[str, Any]]:
        return self._rows(self._board.list_agents(self.db, tenant))

    def task_trace(self, tenant: str, task_id: str) -> dict[str, Any]:
        from hiveboard.errors import NotFound

        try:
            return self._board.task_trace(self.db, tenant, task_id)
        except NotFound as exc:
            raise HiveNotFound(str(exc)) from exc

    # -- skills ------------------------------------------------------------------------------
    def learn_skill(self, tenant: str, goal: str, steps: list[dict[str, Any]], learned_from: list[str], embedding: list[float] | None, version: int = 1) -> str:
        return self._skills.learn_skill(self.db, tenant, goal, steps, list(learned_from), embedding, version)

    def retrieve_skill(self, tenant: str, goal_embedding: list[float], k: int = 3) -> list[dict[str, Any]]:
        return self._rows(self._skills.retrieve_skill(self.db, tenant, goal_embedding, k=k))

    def record_outcome(self, tenant: str, skill_id: str, agent_id: str, ok: bool, task_id: str | None = None) -> dict[str, Any]:
        from hiveboard.errors import NotFound

        try:
            self._skills.record_outcome(self.db, tenant, skill_id, agent_id, ok, task_id)
            return self.get_skill(tenant, skill_id)
        except NotFound as exc:
            raise HiveNotFound(str(exc)) from exc

    def deprecate_skill(self, tenant: str, old_id: str, new_id_: str) -> None:
        self._skills.deprecate_skill(self.db, tenant, old_id, new_id_)

    def skill_pagerank(self, tenant: str) -> list[dict[str, Any]]:
        try:
            return self._rows(self._skills.skill_pagerank(self.db, tenant))
        except Exception as exc:  # noqa: BLE001 - algo.pageRank needs at least one edge on some builds
            log.warning("skill_pagerank failed: %s", exc)
            return []

    def list_skills(self, tenant: str, status: str | None = None) -> list[dict[str, Any]]:
        return self._rows(self._skills.list_skills(self.db, tenant, status=status))

    def get_skill(self, tenant: str, skill_id: str) -> dict[str, Any]:
        from hiveboard.errors import NotFound

        try:
            return dict(self._skills.get_skill(self.db, tenant, skill_id))
        except NotFound as exc:
            raise HiveNotFound(str(exc)) from exc

    def publish_to_commons(self, tenant: str, skill_id: str) -> str:
        return self._skills.publish_to_commons(self.db, tenant, skill_id)

    # -- analytics ---------------------------------------------------------------------------
    def owners(self, tenant: str, entity_name: str) -> dict[str, Any]:
        return self._with_cypher(self._analytics.owners(self.db, tenant, entity_name))

    def who_knows(self, tenant: str, entity_name: str) -> dict[str, Any]:
        return self._with_cypher(self._analytics.who_knows(self.db, tenant, entity_name))

    def open_commitments(self, tenant: str, person_id: str | None = None) -> dict[str, Any]:
        # Closing statuses may be stated by someone other than the owner, so filter closures over all rows first.
        result = self._analytics.open_commitments(self.db, tenant, None, limit=ANALYTICS_LIMIT)
        rows = drop_closed_commitments([self._norm_fact(r) for r in result])
        if person_id:
            rows = [r for r in rows if (r.get("owner") or {}).get("id") == person_id]
        return {"rows": rows, "cypher": getattr(result, "cypher", "")}

    def contradictions(self, tenant: str) -> dict[str, Any]:
        return self._with_cypher(self._analytics.contradictions(self.db, tenant))

    def entity_clusters(self, tenant: str) -> dict[str, Any]:
        try:
            return self._with_cypher(self._analytics.entity_clusters(self.db, tenant))
        except Exception as exc:  # noqa: BLE001
            log.warning("entity_clusters failed: %s", exc)
            return {"rows": [], "cypher": "", "error": str(exc)}

    def stale_decisions(self, tenant: str, older_than_ms: int) -> dict[str, Any]:
        return self._with_cypher(self._analytics.stale_decisions(self.db, tenant, older_than_ms))


def build_hive(settings: Any) -> Any:
    """Connect the real substrate (or the fake when ``HIVE_BACKEND=fake``)."""
    import os

    if os.environ.get("HIVE_BACKEND", "").lower() == "fake":
        return FakeHive()
    return RealHive.connect(
        settings.falkordb_url,
        admin_user=settings.falkordb_admin_user,
        admin_password=settings.falkordb_admin_password,
        rw_password=settings.tenant_rw_password,
        ro_password=settings.tenant_ro_password,
    )


def register_default_agents(hive: Any, tenant: str, model: str) -> None:
    """Register the five agents (idempotent)."""
    for agent_id, name, caps in AGENT_SPECS:
        hive.register_agent(tenant, agent_id, name, caps, model)


ListenerFn = Callable[[dict[str, Any]], None]
