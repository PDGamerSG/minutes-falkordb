"""Evidence assembly for the AnswerAgent: fact dossiers (full supersession history, source, speaker,
rationale) and raw-Episode recall fused with fact recall by reciprocal-rank fusion.

Everything here reads through the hive adapter's public methods (``list_facts``, ``get_episode``,
``meeting_episodes``/``thread_messages``, ``recall(label="Episode")``, ``fulltext(label="Episode")``)
so it runs the same on the in-memory FakeHive and on FalkorDB. The only FalkorDB-specific read is
the PRECEDENT_FOR / CONFIRMED_BY neighbourhood, a parameterised read-only query (``LINKS_CYPHER``).
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

RRF_K = 60
RATIONALE_PREDICATES = {"decided", "lesson", "requires", "rationale", "reason", "because", "mandates", "constraint"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by", "can", "did", "do", "does", "for", "from", "had", "has",
    "have", "how", "i", "if", "in", "into", "is", "it", "its", "it's", "me", "my", "no", "not", "of", "on", "or", "our", "so",
    "that", "the", "their", "them", "then", "there", "they", "this", "to", "us", "was", "we", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "you", "your", "now", "about", "any", "all", "get", "got", "going", "just", "okay",
    "yes", "yeah", "one", "would", "could", "should", "been", "being", "than", "also", "out", "over", "down", "using", "change", "changed",
}

LINKS_CYPHER = (
    "UNWIND $ids AS fid MATCH (f:Fact {id: fid}) "
    "OPTIONAL MATCH (p:Fact)-[:PRECEDENT_FOR]->(f) WITH f, collect(DISTINCT p.id) AS precedents "
    "OPTIONAL MATCH (f)-[:PRECEDENT_FOR]->(n:Fact) WITH f, precedents, collect(DISTINCT n.id) AS precedent_for "
    "OPTIONAL MATCH (f)-[:CONFIRMED_BY]->(ep:Episode) "
    "RETURN f.id AS id, precedents, precedent_for, collect(DISTINCT ep.id) AS confirmed_by"
)

# Projections without the 768-float embedding: returning whole nodes costs ~0.5 ms per node on the wire.
FACTS_CYPHER = (
    "MATCH (f:Fact) "
    "OPTIONAL MATCH (f)-[:ABOUT]->(en:Entity) WITH f, collect(DISTINCT en {.id, .name, .type}) AS entities "
    "OPTIONAL MATCH (f)-[:STATED_BY]->(p:Person) "
    "OPTIONAL MATCH (f)-[:DERIVED_FROM]->(ep:Episode) "
    "OPTIONAL MATCH (c)-[:HAS_EPISODE]->(ep) "
    "OPTIONAL MATCH (f)-[:SUPERSEDES]->(o:Fact) "
    "RETURN f {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to, "
    ".created_at, .expired_at, .due_at} AS f, labels(f) AS labels, entities, p {.id, .name} AS speaker, "
    "ep {.id, .seq, .source_kind, .t_start, .t_end, .t_occurred, .message_id} AS ep, c {.id, .title, .subject, .source_uri} AS c, "
    "labels(c) AS clabels, collect(DISTINCT o.id) AS supersedes"
)
CONTAINER_CYPHER = (
    "MATCH (c)-[:HAS_EPISODE]->(ep:Episode) WHERE c.id = $id "
    "OPTIONAL MATCH (ep)-[:SPOKEN_BY|SENT_BY]->(p:Person) "
    "RETURN ep {.id, .seq, .text, .t_start, .t_occurred, .source_kind, .message_id} AS ep, p {.id, .name} AS speaker, "
    "c {.id, .title, .subject, .started_at} AS c, labels(c) AS clabels ORDER BY ep.seq"
)
EPISODE_CONTAINER_CYPHER = "UNWIND $ids AS eid MATCH (c)-[:HAS_EPISODE]->(ep:Episode {id: eid}) RETURN eid AS id, c.id AS container_id"


def _fact_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """FACTS_CYPHER row -> the adapter's fact shape (speaker, meeting|thread, source, supersedes, entity_ids)."""
    fact = dict(row.get("f") or {})
    labels = row.get("labels") or []
    if not fact.get("kind"):
        fact["kind"] = "commitment" if "Commitment" in labels else "decision" if "Decision" in labels else "fact"
    entities = [e for e in row.get("entities") or [] if e and e.get("id")]
    fact["entities"] = entities
    fact["entity_ids"] = [e["id"] for e in entities]
    speaker = row.get("speaker")
    fact["speaker"] = speaker if speaker and speaker.get("id") else None
    fact["speaker_id"] = (speaker or {}).get("id")
    ep = row.get("ep") or None
    container = row.get("c") or None
    clabels = row.get("clabels") or []
    fact["episode_id"] = (ep or {}).get("id")
    is_thread = "EmailThread" in clabels
    fact["meeting"] = {"id": container.get("id"), "title": container.get("title")} if container and not is_thread else None
    fact["thread"] = {"id": container.get("id"), "subject": container.get("subject")} if container and is_thread else None
    if ep:
        kind = ep.get("source_kind") or ("email" if is_thread else "utterance")
        source: dict[str, Any] = {"kind": kind, "episode_id": ep.get("id"), "container": None}
        if container:
            source["container"] = (
                {"id": container.get("id"), "subject": container.get("subject"), "label": "EmailThread"}
                if is_thread
                else {"id": container.get("id"), "title": container.get("title"), "source_uri": container.get("source_uri"), "label": "Meeting"}
            )
        if kind == "email":
            source["sent_at"] = ep.get("t_occurred")
            source["message_id"] = ep.get("message_id")
        else:
            source["t_start"] = ep.get("t_start")
            source["t_end"] = ep.get("t_end")
        fact["source"] = source
    else:
        fact["source"] = None
    fact["supersedes"] = [x for x in row.get("supersedes") or [] if x]
    return fact


# --------------------------------------------------------------------------- formatting helpers
def iso_date(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).date().isoformat()
    except (TypeError, ValueError, OSError):
        return "?"


def pretty_object(value: Any) -> str:
    """ISO dates get their weekday (``2026-09-25 (Friday)``) so "move it to Friday" lines up with the date."""
    text = str(value if value is not None else "")
    if _DATE.match(text):
        try:
            return f"{text} ({datetime.fromisoformat(text).strftime('%A')})"
        except ValueError:
            return text
    return text


def clip(text: Any, limit: int = 320) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 3].rstrip() + "..."


def tokens(text: Any) -> set[str]:
    return {t for t in _TOKEN.findall(str(text or "").lower()) if t not in _STOP and len(t) > 2}


def keywords(message: str, limit: int = 8) -> list[str]:
    seen: list[str] = []
    for tok in _TOKEN.findall(message.lower()):
        if tok not in _STOP and len(tok) > 2 and tok not in seen:
            seen.append(tok)
    return seen[:limit]


def rrf(*ranked_lists: list[str], weights: list[float] | None = None) -> dict[str, float]:
    """Reciprocal-rank fusion: ``sum_l w_l / (K + rank_l(item))`` with 1-based ranks."""
    scores: dict[str, float] = defaultdict(float)
    for i, ranked in enumerate(ranked_lists):
        w = weights[i] if weights else 1.0
        for rank, item in enumerate(ranked, start=1):
            if item:
                scores[item] += w / (RRF_K + rank)
    return dict(scores)


# --------------------------------------------------------------------------- the index
class EvidenceIndex:
    """Per-answer cache over one tenant: every fact (all statuses), supersession links, episodes by container."""

    def __init__(self, hive: Any, tenant: str) -> None:
        self.hive = hive
        self.tenant = tenant
        self._facts: dict[str, dict[str, Any]] | None = None
        self._newer: dict[str, list[str]] = defaultdict(list)
        self._by_episode: dict[str, list[str]] = defaultdict(list)
        self._containers: dict[str, dict[str, Any]] = {}
        self._episode_container: dict[str, str] = {}
        self._persons: dict[str, dict[str, Any] | None] = {}
        self._links: dict[str, dict[str, list[str]]] = {}
        self._common: set[str] | None = None
        self.cypher: list[str] = []
        self.is_falkordb = getattr(hive, "kind", "") == "falkordb"

    # -- facts ------------------------------------------------------------------------------
    @property
    def facts(self) -> dict[str, dict[str, Any]]:
        if self._facts is None:
            try:
                if self.is_falkordb:
                    rows = [_fact_from_row(r) for r in self.hive.run_ro_cypher(self.tenant, FACTS_CYPHER, {}).get("rows", [])]
                    self.cypher.append(FACTS_CYPHER)
                else:
                    rows = self.hive.list_facts(self.tenant, status="all")
            except Exception as exc:  # noqa: BLE001 - evidence is best effort, the route's facts still answer
                log.warning("evidence index: list_facts failed: %s", exc)
                rows = []
            self._facts = {r["id"]: r for r in rows if r.get("id")}
            for fact in self._facts.values():
                for old in fact.get("supersedes") or []:
                    self._newer[old].append(fact["id"])
                if fact.get("episode_id"):
                    self._by_episode[fact["episode_id"]].append(fact["id"])
        return self._facts

    def fact(self, fact_id: str | None, fallback: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not fact_id:
            return fallback
        found = self.facts.get(fact_id)
        if found is None and fallback is not None:
            return fallback
        return found

    def add_fact(self, fact: dict[str, Any]) -> None:
        """Register a fact the route returned that the index does not know (e.g. a free-form row)."""
        if fact.get("id") and fact["id"] not in self.facts:
            self.facts[fact["id"]] = fact
            for old in fact.get("supersedes") or []:
                self._newer[old].append(fact["id"])

    def chain(self, fact_id: str) -> list[dict[str, Any]]:
        """Every version connected to ``fact_id`` through SUPERSEDES (both directions), oldest to newest."""
        facts = self.facts
        if fact_id not in facts:
            return []
        seen = {fact_id}
        frontier = [fact_id]
        while frontier:
            fid = frontier.pop()
            fact = facts.get(fid) or {}
            for nid in list(fact.get("supersedes") or []) + self._newer.get(fid, []):
                if nid in facts and nid not in seen and len(seen) < 12:
                    seen.add(nid)
                    frontier.append(nid)
        return sorted((facts[i] for i in seen), key=lambda f: (f.get("valid_from") or 0, f.get("created_at") or 0))

    def active_about(self, entity_id: str) -> list[dict[str, Any]]:
        """Active facts ABOUT an entity, oldest first (same rows as ``list_facts(entity=...)``)."""
        rows = [f for f in self.facts.values() if f.get("status") == "active" and entity_id in (f.get("entity_ids") or [])]
        return sorted(rows, key=lambda f: (f.get("valid_from") or 0, f.get("created_at") or 0))

    def facts_from_episode(self, episode_id: str) -> list[str]:
        _ = self.facts
        return list(self._by_episode.get(episode_id, []))

    def common_tokens(self) -> set[str]:
        """Tokens in more than 15 percent of fact texts carry no signal for rationale matching."""
        if self._common is None:
            counts: dict[str, int] = defaultdict(int)
            facts = list(self.facts.values())
            for fact in facts:
                for tok in tokens(f"{fact.get('subject')} {fact.get('object')} {fact.get('text')}"):
                    counts[tok] += 1
            limit = max(3, math.ceil(0.15 * len(facts)))
            self._common = {t for t, c in counts.items() if c > limit}
        return self._common

    # -- links (PRECEDENT_FOR / CONFIRMED_BY) ------------------------------------------------
    def links(self, fact_ids: list[str]) -> dict[str, dict[str, list[str]]]:
        missing = [f for f in dict.fromkeys(fact_ids) if f and f not in self._links]
        if missing:
            if self.is_falkordb:
                try:
                    result = self.hive.run_ro_cypher(self.tenant, LINKS_CYPHER, {"ids": missing})
                    self.cypher.append(LINKS_CYPHER)
                    for row in result.get("rows", []):
                        self._links[row["id"]] = {
                            "precedents": [x for x in row.get("precedents") or [] if x],
                            "precedent_for": [x for x in row.get("precedent_for") or [] if x],
                            "confirmed_by": [x for x in row.get("confirmed_by") or [] if x],
                        }
                except Exception as exc:  # noqa: BLE001
                    log.warning("evidence links query failed: %s", exc)
            else:
                for fid in missing:
                    fact = self.facts.get(fid) or {}
                    self._links[fid] = {
                        "precedents": list(fact.get("precedent_ids") or []),
                        "precedent_for": [o["id"] for o in self.facts.values() if fid in (o.get("precedent_ids") or [])],
                        "confirmed_by": list(fact.get("confirmed_by") or []),
                    }
            for fid in missing:
                self._links.setdefault(fid, {"precedents": [], "precedent_for": [], "confirmed_by": []})
        return {f: self._links.get(f, {"precedents": [], "precedent_for": [], "confirmed_by": []}) for f in fact_ids}

    # -- episodes ---------------------------------------------------------------------------
    def person(self, person_id: str | None) -> dict[str, Any] | None:
        if not person_id:
            return None
        if person_id not in self._persons:
            try:
                self._persons[person_id] = self.hive.get_person(self.tenant, person_id)
            except Exception:  # noqa: BLE001
                self._persons[person_id] = None
        return self._persons[person_id]

    def _load_container_falkordb(self, container_id: str) -> dict[str, Any]:
        rows = []
        try:
            rows = self.hive.run_ro_cypher(self.tenant, CONTAINER_CYPHER, {"id": container_id}).get("rows", [])
        except Exception as exc:  # noqa: BLE001
            log.warning("evidence: episodes of %s failed: %s", container_id, exc)
        meta: dict[str, Any] = {}
        kind = "meeting"
        by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            ep = dict(row.get("ep") or {})
            if not ep.get("id"):
                continue
            meta = row.get("c") or meta
            kind = "thread" if "EmailThread" in (row.get("clabels") or []) else "meeting"
            ep["speaker"] = row.get("speaker") or {}
            by_id[ep["id"]] = ep
            self._episode_container[ep["id"]] = container_id
        ordered = sorted(by_id.values(), key=lambda e: e.get("seq") or 0)
        entry = {"id": container_id, "kind": kind, "meta": meta, "episodes": by_id, "ordered": ordered}
        self._containers[container_id] = entry
        return entry

    def prefetch(self, episode_ids: list[str]) -> None:
        """Resolve the containers of many episodes in one query (FalkorDB) so later lookups hit the cache."""
        wanted = [e for e in dict.fromkeys(episode_ids) if e and e not in self._episode_container]
        if not wanted or not self.is_falkordb:
            return
        try:
            rows = self.hive.run_ro_cypher(self.tenant, EPISODE_CONTAINER_CYPHER, {"ids": wanted}).get("rows", [])
        except Exception as exc:  # noqa: BLE001
            log.warning("evidence: episode containers failed: %s", exc)
            return
        for cid in dict.fromkeys(r.get("container_id") for r in rows if r.get("container_id")):
            if cid not in self._containers:
                self._load_container_falkordb(cid)

    def _load_container(self, container_id: str, kind_hint: str | None = None) -> dict[str, Any]:
        if container_id in self._containers:
            return self._containers[container_id]
        if self.is_falkordb:
            return self._load_container_falkordb(container_id)
        meta: dict[str, Any] | None = None
        kind = kind_hint
        try:
            if kind != "thread":
                meta = self.hive.get_meeting(self.tenant, container_id)
                if meta:
                    kind = "meeting"
            if meta is None:
                meta = self.hive.get_thread(self.tenant, container_id)
                kind = "thread" if meta else kind
        except Exception:  # noqa: BLE001
            meta = None
        episodes: list[dict[str, Any]] = []
        try:
            if kind == "thread":
                episodes = self.hive.thread_messages(self.tenant, container_id)
            elif kind == "meeting":
                episodes = self.hive.meeting_episodes(self.tenant, container_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("evidence: episodes of %s failed: %s", container_id, exc)
        by_id = {}
        for ep in episodes:
            if ep.get("id"):
                by_id[ep["id"]] = ep
                self._episode_container[ep["id"]] = container_id
        ordered = sorted(by_id.values(), key=lambda e: e.get("seq") or 0)
        entry = {"id": container_id, "kind": kind or "meeting", "meta": meta or {}, "episodes": by_id, "ordered": ordered}
        self._containers[container_id] = entry
        return entry

    def _container_of(self, episode_id: str, container_id: str | None = None) -> dict[str, Any] | None:
        if container_id:
            return self._load_container(container_id)
        if episode_id in self._episode_container:
            return self._containers[self._episode_container[episode_id]]
        if self.is_falkordb:
            self.prefetch([episode_id])
            cid = self._episode_container.get(episode_id)
            return self._containers.get(cid) if cid else None
        try:
            raw = self.hive.get_episode(self.tenant, episode_id)
        except Exception:  # noqa: BLE001
            raw = None
        if not raw or not raw.get("container_id"):
            return None
        return self._load_container(raw["container_id"], raw.get("container_kind"))

    def episode(self, episode_id: str | None, container_id: str | None = None) -> dict[str, Any] | None:
        """Display record: ``{id, seq, kind, text, t, t_start, speaker, container: {id, kind, name}}``."""
        if not episode_id:
            return None
        container = self._container_of(episode_id, container_id)
        if container is None or episode_id not in container["episodes"]:
            return None
        ep = container["episodes"][episode_id]
        speaker = ep.get("speaker") or ep.get("sender") or {}
        if not speaker.get("name"):
            speaker = self.person(ep.get("speaker_id") or ep.get("sender_id")) or speaker
        meta = container["meta"]
        is_email = container["kind"] == "thread" or ep.get("source_kind") == "email"
        return {
            "id": episode_id,
            "seq": ep.get("seq"),
            "kind": "email" if is_email else "utterance",
            "text": ep.get("text") or "",
            "t": ep.get("t_occurred") or ep.get("t_start"),
            "t_start": None if is_email else ep.get("t_start"),
            "speaker": {"id": speaker.get("id") or ep.get("speaker_id"), "name": speaker.get("name") or ep.get("speaker_id") or "unknown"},
            "container": {
                "id": container["id"],
                "kind": "thread" if is_email else "meeting",
                "name": meta.get("subject") if is_email else meta.get("title"),
            },
        }

    def neighbours(self, episode_id: str, before: int = 1, after: int = 1) -> list[dict[str, Any]]:
        """Adjacent episodes in the same meeting or thread (by ``seq``), excluding the episode itself."""
        container = self._container_of(episode_id)
        if container is None:
            return []
        ordered = container["ordered"]
        idx = next((i for i, e in enumerate(ordered) if e.get("id") == episode_id), None)
        if idx is None:
            return []
        out = []
        for j in list(range(max(0, idx - before), idx)) + list(range(idx + 1, min(len(ordered), idx + 1 + after))):
            rec = self.episode(ordered[j]["id"], container["id"])
            if rec:
                out.append(rec)
        return out


# --------------------------------------------------------------------------- source wording
def fact_source(index: EvidenceIndex, fact: dict[str, Any]) -> dict[str, Any]:
    """``{kind, speaker, container, date, episode}`` for a fact, from its joins (and the episode when known)."""
    src = fact.get("source") or {}
    container = src.get("container") or {}
    meeting = fact.get("meeting") or {}
    thread = fact.get("thread") or {}
    kind = src.get("kind") or ("email" if thread.get("id") else "utterance")
    speaker = (fact.get("speaker") or {}).get("name") or fact.get("speaker_id") or "unknown"
    if kind == "email":
        name = thread.get("subject") or container.get("subject")
        cid = thread.get("id") or container.get("id")
    else:
        name = meeting.get("title") or container.get("title")
        cid = meeting.get("id") or container.get("id")
    episode = index.episode(fact.get("episode_id"), cid) if fact.get("episode_id") else None
    if episode and speaker == "unknown":
        speaker = episode["speaker"]["name"]
    return {"kind": kind, "speaker": speaker, "container_id": cid, "container": name, "date": iso_date(fact.get("valid_from")), "episode": episode}


def where_phrase(kind: str, container: str | None, speaker: str) -> str:
    """The one wording the model sees: meetings are spoken, emails are written. Never mixed."""
    if kind == "email":
        return f'written in the email thread "{container or "?"}" (email sent by {speaker})'
    return f'spoken in the meeting "{container or "?"}"'


def episode_phrase(ep: dict[str, Any]) -> str:
    name = ep["container"]["name"] or "?"
    who = ep["speaker"]["name"]
    if ep["kind"] == "email":
        return f'{iso_date(ep["t"])}, email from {who} in the email thread "{name}"'
    return f'{iso_date(ep["t"])}, {who} speaking in the meeting "{name}"'


# --------------------------------------------------------------------------- dossiers
def rationale_for(index: EvidenceIndex, chain: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """Facts that state a reason for (or a lesson about) the chain: ``decided``/``lesson``/``requires`` facts whose
    subject or object names the chain's subject or value, or that share at least two uncommon words with it."""
    chain_ids = {f["id"] for f in chain}
    names = set()
    words: set[str] = set()
    entity_ids: set[str] = set()
    for f in chain:
        names.update({str(f.get("subject") or "").lower(), str(f.get("object") or "").lower()})
        words |= tokens(f"{f.get('subject')} {f.get('object')} {f.get('text')}")
        entity_ids.update(f.get("entity_ids") or [])
    names.discard("")
    words -= index.common_tokens()
    scored = []
    for other in index.facts.values():
        if other["id"] in chain_ids or str(other.get("predicate") or "").lower() not in RATIONALE_PREDICATES:
            continue
        subj = str(other.get("subject") or "").lower()
        obj = str(other.get("object") or "").lower()
        score = 0.0
        if subj in names:
            score += 3
        if any(n and len(n) > 2 and (n == obj or re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", obj)) for n in names):
            score += 3
        overlap = len(words & (tokens(f"{subj} {obj} {other.get('text')}") - index.common_tokens()))
        if overlap >= 2:
            score += overlap
        if score >= 2:
            scored.append((score, other.get("status") == "active", other.get("valid_from") or 0, other))
    scored.sort(key=lambda row: (-row[0], not row[1], -row[2]))
    return [row[3] for row in scored[:limit]]


def build_dossiers(index: EvidenceIndex, facts: list[dict[str, Any]], *, max_blocks: int = 8) -> list[dict[str, Any]]:
    """One dossier per supersession chain touched by ``facts`` (in their order): versions oldest to newest with source,
    speaker and source text, later confirmations, precedents and rationale facts."""
    dossiers: list[dict[str, Any]] = []
    covered: set[str] = set()
    for fact in facts:
        fid = fact.get("id")
        if not fid or fid in covered:
            continue
        index.add_fact(fact)
        chain = index.chain(fid) or [fact]
        covered.update(f["id"] for f in chain)
        dossiers.append({"focus": fid, "chain": chain})
        if len(dossiers) >= max_blocks:
            break
    all_ids = [f["id"] for d in dossiers for f in d["chain"]]
    links = index.links(all_ids)
    for rank, dossier in enumerate(dossiers):
        chain = dossier["chain"]
        versions = []
        for i, f in enumerate(chain):
            src = fact_source(index, f)
            context: list[dict[str, Any]] = []
            # the words around a change usually carry its reason ("the sandbox doesn't fire callbacks... so move it")
            change_point = i > 0 or (f.get("kind") == "decision" and len(chain) == 1)
            if src["episode"] and change_point and rank < 3 and i >= len(chain) - 2:  # keep the prompt small
                context = index.neighbours(src["episode"]["id"], before=1, after=1)
            versions.append({"fact": f, "source": src, "context": context})
        dossier["versions"] = versions
        confirmations = []
        precedents = []
        for f in chain:
            link = links.get(f["id"]) or {}
            for ep_id in link.get("confirmed_by", [])[:3]:
                ep = index.episode(ep_id)
                if ep:
                    confirmations.append({"fact_id": f["id"], "episode": ep})
            for pid in link.get("precedents", []):
                if index.fact(pid):
                    precedents.append({"relation": "follows precedent", "fact": index.fact(pid)})
            for nid in link.get("precedent_for", []):
                if index.fact(nid):
                    precedents.append({"relation": "set a precedent for", "fact": index.fact(nid)})
        dossier["confirmations"] = confirmations[:2]
        dossier["precedents"] = precedents[:3]
        dossier["rationale"] = rationale_for(index, chain, limit=3)
    # quote each related fact once: drop precedents/rationale that another block already shows
    shown = {f["id"] for d in dossiers for f in d["chain"]}
    for dossier in dossiers:
        dossier["precedents"] = [p for p in dossier["precedents"] if p["fact"]["id"] not in shown]
        shown.update(p["fact"]["id"] for p in dossier["precedents"])
        dossier["rationale"] = [f for f in dossier["rationale"] if f["id"] not in shown][:2]
        shown.update(f["id"] for f in dossier["rationale"])
    return dossiers


def _version_status(i: int, n: int, fact: dict[str, Any]) -> str:
    status = str(fact.get("status") or "active")
    if status == "active" and i == n - 1:
        return "ACTIVE, current value"
    if status == "superseded" and i < n - 1:
        return f"superseded by version {i + 2}"
    return status


def _fact_line(index: EvidenceIndex, fact: dict[str, Any]) -> str:
    src = fact_source(index, fact)
    return (
        f"[{fact.get('id')}] {fact.get('subject')} {str(fact.get('predicate') or '').replace('_', ' ')} {pretty_object(fact.get('object'))} "
        f"({fact.get('kind') or 'fact'}, {fact.get('status') or 'active'}; stated {src['date']} by {src['speaker']}, {where_phrase(src['kind'], src['container'], src['speaker'])})"
        + (f': "{clip(src["episode"]["text"], 200)}"' if src["episode"] else "")
    )


def render_dossier(index: EvidenceIndex, dossier: dict[str, Any], number: int) -> str:
    chain = dossier["chain"]
    head = chain[-1]
    predicate = str(head.get("predicate") or "").replace("_", " ")
    lines = [f"FACT {number}: {head.get('subject')} / {predicate}" + (f" ({len(chain)} versions, oldest first)" if len(chain) > 1 else "")]
    for i, version in enumerate(dossier["versions"]):
        f, src = version["fact"], version["source"]
        verb = "wrote" if src["kind"] == "email" else "said"
        lines.append(
            f"  v{i + 1}. [{f.get('id')}] {f.get('subject')} {predicate} = {pretty_object(f.get('object'))}; {f.get('kind') or 'fact'}; "
            f"stated {src['date']} by {src['speaker']}, {where_phrase(src['kind'], src['container'], src['speaker'])}; status: {_version_status(i, len(chain), f)}"
        )
        if src["episode"]:
            lines.append(f'      {src["speaker"]} {verb}: "{clip(src["episode"]["text"], 300)}"')
        elif f.get("text"):
            lines.append(f'      fact text: "{clip(f.get("text"), 200)}"')
        for ctx in version["context"]:
            rel = "earlier in the same" if (ctx.get("seq") or 0) < ((src["episode"] or {}).get("seq") or 0) else "next in the same"
            medium = "email thread" if ctx["kind"] == "email" else "meeting"
            lines.append(f'      ({rel} {medium}, {ctx["speaker"]["name"]} [{ctx["id"]}]: "{clip(ctx["text"], 180)}")')
    if len(chain) > 1:
        order = ["first", *(["then"] * (len(chain) - 2)), "now" if str(head.get("status") or "active") == "active" else "last"]
        story = ", ".join(f"{word} {pretty_object(v['fact'].get('object'))} ({v['source']['date']}, {v['source']['speaker']}, {'email' if v['source']['kind'] == 'email' else 'meeting'})" for word, v in zip(order, dossier["versions"]))
        lines.append(f"  chronology: {story}")
    for conf in dossier["confirmations"]:
        lines.append(f'  later confirmed [{conf["fact_id"]}] by {episode_phrase(conf["episode"])} [{conf["episode"]["id"]}]: "{clip(conf["episode"]["text"], 200)}"')
    for prec in dossier["precedents"]:
        lines.append(f"  {prec['relation']}: {_fact_line(index, prec['fact'])}")
    for fact in dossier["rationale"]:
        lines.append(f"  stated rationale / related: {_fact_line(index, fact)}")
    return "\n".join(lines)


def dossier_fact_ids(dossiers: list[dict[str, Any]]) -> list[str]:
    """Every fact id a dossier shows (chain versions, then precedents and rationale), deduplicated in order."""
    out: list[str] = []
    for d in dossiers:
        out.extend(f["id"] for f in d["chain"])
    for d in dossiers:
        out.extend(p["fact"]["id"] for p in d["precedents"])
        out.extend(f["id"] for f in d["rationale"])
    return list(dict.fromkeys(i for i in out if i))


# --------------------------------------------------------------------------- episode recall
def recall_episodes(hive: Any, tenant: str, message: str, vec: list[float] | None, k: int = 8) -> dict[str, Any]:
    """Vector KNN over Episode (hybrid recall with label="Episode") plus full-text over Episode.text.

    Returns ``{knn: [ids], fulltext: [ids], nodes: {id: props}, cypher: [str]}``; ranks are list positions."""
    out: dict[str, Any] = {"knn": [], "fulltext": [], "nodes": {}, "cypher": []}
    if vec is not None:
        try:
            # hive.score folds in recency, which buries the utterance where a change was explained under the most
            # recent meeting; for raw episodes we over-fetch and rank by cosine similarity alone.
            result = hive.recall(tenant, vec, k=max(20, 2 * k), label="Episode")
            out["cypher"].append(result.get("cypher", ""))
            items = sorted(result.get("items", []), key=lambda i: -(i.get("similarity") or 0.0))[:k]
            for item in items:
                node = item.get("node") or {}
                eid = item.get("id") or node.get("id")
                if eid:
                    out["knn"].append(eid)
                    out["nodes"][eid] = node
        except Exception as exc:  # noqa: BLE001 - keyword search still runs
            log.warning("episode KNN failed: %s", exc)
    words = keywords(message)
    if words:
        try:
            if getattr(hive, "kind", "") == "falkordb":
                rows = hive.fulltext(tenant, " ".join(words), label="Episode", k=k)
                out["cypher"].append("CALL db.idx.fulltext.queryNodes($label, $q) YIELD node, score RETURN node, score ORDER BY score DESC LIMIT $k")
            else:  # the fake's full-text is a substring match: one keyword at a time, merged by first hit
                rows = []
                for word in words:
                    rows.extend(hive.fulltext(tenant, word, label="Episode", k=k))
            for row in rows:
                eid = row.get("id")
                if eid and eid not in out["fulltext"]:
                    out["fulltext"].append(eid)
                    out["nodes"].setdefault(eid, {k2: v for k2, v in row.items() if k2 != "embedding"})
            out["fulltext"] = out["fulltext"][:k]
        except Exception as exc:  # noqa: BLE001
            log.warning("episode full-text failed: %s", exc)
    return out


def fuse(
    index: EvidenceIndex,
    fact_lists: list[list[str]],
    episode_hits: dict[str, Any],
    *,
    fact_weights: list[float] | None = None,
    window: int = 1,
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """RRF over fact rankings and episode rankings. An episode's score flows to the facts derived from it (full weight)
    and from its neighbours within ``window`` (half weight), so an utterance that explains a change surfaces the change.
    Returns ``(facts ranked, episodes ranked)`` as ``(id, score)`` pairs."""
    ep_scores = rrf(episode_hits.get("knn", []), episode_hits.get("fulltext", []), weights=[1.0, 0.6])
    index.prefetch(list(ep_scores))
    fact_scores = rrf(*fact_lists, weights=fact_weights) if fact_lists else {}
    fact_scores = defaultdict(float, fact_scores)
    for eid, score in ep_scores.items():
        for fid in index.facts_from_episode(eid):
            fact_scores[fid] += score
        if window:
            for nb in index.neighbours(eid, before=window, after=window):
                for fid in index.facts_from_episode(nb["id"]):
                    fact_scores[fid] += score * 0.5
    facts_ranked = sorted(fact_scores.items(), key=lambda kv: -kv[1])
    eps_ranked = sorted(ep_scores.items(), key=lambda kv: -kv[1])
    return facts_ranked, eps_ranked


def quoted_episode_ids(dossiers: list[dict[str, Any]]) -> set[str]:
    """Episodes whose text a dossier already quotes (sources, context lines, confirmations)."""
    out: set[str] = set()
    for d in dossiers:
        for v in d.get("versions", []):
            if v["source"]["episode"]:
                out.add(v["source"]["episode"]["id"])
            out.update(c["id"] for c in v.get("context", []))
        out.update(c["episode"]["id"] for c in d.get("confirmations", []))
    return out


def render_episodes(episodes: list[dict[str, Any]], shown_fact_sources: dict[str, str]) -> list[str]:
    lines = []
    for ep in episodes:
        note = f" (source of [{shown_fact_sources[ep['id']]}])" if ep["id"] in shown_fact_sources else ""
        lines.append(f'- [{ep["id"]}] {episode_phrase(ep)}{note}: "{clip(ep["text"], 280)}"')
    return lines


def episode_source_item(ep: dict[str, Any], score: float | None = None) -> dict[str, Any]:
    """Item for the response's ``episodes[]`` list (UI: play at timestamp / open email)."""
    item: dict[str, Any] = {
        "episode_id": ep["id"],
        "kind": ep["kind"],
        "speaker": ep["speaker"]["name"],
        "container_id": ep["container"]["id"],
        "text": ep["text"],
        "t": ep["t"],
    }
    if ep["kind"] == "email":
        item["thread"] = ep["container"]["name"]
        item["sent_at"] = ep["t"]
    else:
        item["meeting"] = ep["container"]["name"]
        item["t_start"] = ep["t_start"]
    if score is not None:
        item["score"] = round(score, 5)
    return item


# --------------------------------------------------------------------------- subgraph
def merge_subgraph(base: dict[str, Any], index: EvidenceIndex, dossiers: list[dict[str, Any]], episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Add chain versions, their source episodes, speakers, containers and the retrieved episodes to ``base``."""
    nodes = {n["id"]: n for n in base.get("nodes", []) if n.get("id")}
    edges = list(base.get("edges", []))
    seen_edges = {(e.get("source"), e.get("target"), e.get("type")) for e in edges}

    def add_node(nid: str | None, label: str, props: dict[str, Any]) -> None:
        if nid and nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "props": {k: v for k, v in props.items() if k not in {"embedding", "entities", "speaker", "meeting", "thread", "source", "supersedes"} and not isinstance(v, (dict, list))}}

    def add_edge(a: str | None, b: str | None, kind: str) -> None:
        if a and b and (a, b, kind) not in seen_edges:
            seen_edges.add((a, b, kind))
            edges.append({"source": a, "target": b, "type": kind, "props": {}})

    def add_episode(ep: dict[str, Any]) -> None:
        add_node(ep["id"], "Episode", {"text": ep["text"], "seq": ep["seq"], "source_kind": ep["kind"], "t_occurred": ep["t"], "t_start": ep["t_start"]})
        if ep["speaker"].get("id"):
            add_node(ep["speaker"]["id"], "Person", {"name": ep["speaker"]["name"]})
            add_edge(ep["id"], ep["speaker"]["id"], "SENT_BY" if ep["kind"] == "email" else "SPOKEN_BY")
        cont = ep["container"]
        add_node(cont["id"], "EmailThread" if cont["kind"] == "thread" else "Meeting", {"subject" if cont["kind"] == "thread" else "title": cont["name"]})
        add_edge(cont["id"], ep["id"], "HAS_EPISODE")

    def add_fact(f: dict[str, Any]) -> None:
        label = {"decision": "Decision", "commitment": "Commitment"}.get(str(f.get("kind")), "Fact")
        add_node(f["id"], label, f)
        src = fact_source(index, f)
        if src["episode"]:
            add_episode(src["episode"])
            add_edge(f["id"], src["episode"]["id"], "DERIVED_FROM")

    for d in dossiers:
        for f in d["chain"]:
            add_fact(f)
        chain_ids = {f["id"] for f in d["chain"]}
        for newer in d["chain"]:
            for old in newer.get("supersedes") or []:
                if old in chain_ids:
                    add_edge(newer["id"], old, "SUPERSEDES")
        for conf in d["confirmations"]:
            add_episode(conf["episode"])
            add_edge(conf["fact_id"], conf["episode"]["id"], "CONFIRMED_BY")
        for prec in d["precedents"]:
            add_fact(prec["fact"])
            if prec["relation"] == "follows precedent":
                add_edge(prec["fact"]["id"], d["focus"], "PRECEDENT_FOR")
            else:
                add_edge(d["focus"], prec["fact"]["id"], "PRECEDENT_FOR")
        for f in d["rationale"]:
            add_fact(f)
    for ep in episodes:
        add_episode(ep)
        for fid in index.facts_from_episode(ep["id"]):
            if fid in nodes:
                add_edge(fid, ep["id"], "DERIVED_FROM")
    return {"nodes": list(nodes.values()), "edges": edges}
