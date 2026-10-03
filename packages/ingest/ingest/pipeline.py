"""End-to-end ingestion: validate -> chunk -> embed -> remember -> extract -> supersede -> publish.

``run`` handles recorder exports (meetings); ``run_thread`` handles email threads. Both share
``_extract_and_store`` so facts from either source go through the same supersession path.
The ``hive`` argument is any object with the ``hiveboard`` memory/event methods minus ``db``
(see ``apps/api/hive_adapter.py`` for the real adapter and ``ingest.fakes.MemoryHive``).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Protocol

from .chunker import Episode, chunk
from .dates import date_to_ms
from .embed import Embedder
from .extract import (
    EpisodeContext,
    Extractor,
    LLMExtractor,
    hinted_supersession,
    judge_supersession,
    select_prior_facts,
)
from .llm_protocol import LLMProtocol
from .models import ExtractedFact, SupersessionVerdict, canonical_entity_name, entity_id_for, fact_key
from .recorder_format import RecorderExport, parse_export

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]
Judge = Callable[[dict[str, Any], ExtractedFact], SupersessionVerdict]

#: Predicates with one current value per subject: a new object supersedes the old one. Every other
#: predicate (lesson, requires, scope_includes, customer, decided, ...) is multi-valued and only
#: supersedes when the extracted item carries a ``supersedes_hint``.
SINGLE_VALUED_PREDICATES = frozenset({"due", "owner", "uses_vendor", "uses_pattern", "status"})

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


class HiveLike(Protocol):
    """The subset of the hiveboard surface the pipeline calls (tenant first, no ``db``)."""

    def remember_person(self, tenant: str, person: dict[str, Any]) -> str: ...

    def remember_meeting(self, tenant: str, meeting: dict[str, Any]) -> str: ...

    def remember_thread(self, tenant: str, thread: dict[str, Any]) -> str: ...

    def remember_episodes(self, tenant: str, meeting_id: str, episodes: list[dict[str, Any]]) -> int: ...

    def remember_email_episodes(self, tenant: str, thread_id: str, episodes: list[dict[str, Any]]) -> int: ...

    def remember_entities(self, tenant: str, entities: list[dict[str, Any]]) -> int: ...

    def upsert_entities(self, tenant: str, entities: list[dict[str, Any]]) -> dict[str, str]: ...

    def list_entities(self, tenant: str) -> list[dict[str, Any]]: ...

    def link_mentions(self, tenant: str, episode_id: str, entity_ids: list[str]) -> int: ...

    def remember_fact(self, tenant: str, fact: dict[str, Any]) -> dict[str, Any]: ...

    def supersede_fact(self, tenant: str, old_id: str, new_fact: dict[str, Any]) -> dict[str, Any]: ...

    def active_facts(self, tenant: str, entity_id: str | None = None, key: str | None = None) -> list[dict[str, Any]]: ...

    def facts_by_key(self, tenant: str, key: str) -> list[dict[str, Any]]: ...

    def insert_fact_in_chain(self, tenant: str, fact: dict[str, Any], before_id: str, after_id: str | None) -> dict[str, Any]: ...

    def confirm_fact(self, tenant: str, fact_id: str, episode_id: str) -> None: ...

    def publish(self, tenant: str, event: str, payload: dict[str, Any]) -> None: ...


@dataclass
class PipelineStats:
    """Counts returned by :func:`run` / :func:`run_thread` (also the job ``stats`` in the API)."""

    container_id: str
    source_kind: str
    episodes: int = 0
    entities: int = 0
    facts: int = 0
    decisions: int = 0
    commitments: int = 0
    superseded: int = 0
    refinements: int = 0
    duplicates: int = 0
    proposed: int = 0
    dropped: int = 0
    errors: list[str] = field(default_factory=list)
    #: episodes whose extraction call failed outright (nothing extracted); callers should surface these
    failed_episodes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["items"] = self.facts + self.decisions + self.commitments
        data["drop_rate"] = round(self.dropped / self.proposed, 3) if self.proposed else 0.0
        return data


@dataclass(slots=True)
class SourceContext:
    """Container-level context shared by every episode of one import."""

    container_id: str
    container_kind: str
    title: str
    day: date
    speakers: list[dict[str, Any]]


def _noop_progress(stage: str, fraction: float) -> None:
    return None


def _emit(hive: HiveLike, tenant: str, event: str, payload: dict[str, Any]) -> None:
    """Publish from the pipeline only when the hive does not already publish memory events itself."""
    if not getattr(hive, "publishes_memory_events", False):
        hive.publish(tenant, event, payload)


def _resolve_extractor(extractor: Extractor | None, llm: LLMProtocol | None) -> Extractor:
    if extractor is not None:
        return extractor
    if llm is None:
        raise ValueError("pipeline.run needs an llm or an explicit extractor")
    return LLMExtractor(llm)


def _resolve_judge(judge: Judge | None, llm: LLMProtocol | None) -> Judge:
    if judge is not None:
        return judge
    if llm is None:
        return hinted_supersession
    return lambda old, new: judge_supersession(llm, old, new)


def normalize_object(value: Any) -> str:
    """Loose equality for fact objects: lowercase, punctuation and double spaces removed."""
    text = _PUNCT.sub(" ", str(value or "").lower())
    return _SPACES.sub(" ", text).strip()


def run(
    meeting_json: dict[str, Any] | str | bytes | RecorderExport,
    tenant: str,
    hive: HiveLike,
    llm: LLMProtocol | None,
    embedder: Embedder,
    *,
    extractor: Extractor | None = None,
    judge: Judge | None = None,
    progress: ProgressFn | None = None,
    min_seconds: int = 30,
    max_seconds: int = 60,
) -> dict[str, Any]:
    """Ingest one recorder export into the tenant graph and return :class:`PipelineStats` as a dict."""
    report = progress or _noop_progress
    report("validating", 0.02)
    export = parse_export(meeting_json)
    episodes = chunk(export, min_seconds=min_seconds, max_seconds=max_seconds)
    stats = PipelineStats(container_id=export.meeting.id, source_kind="utterance", episodes=len(episodes))

    meeting_id = hive.remember_meeting(
        tenant,
        {
            "id": export.meeting.id,
            "title": export.meeting.title,
            "started_at": export.started_at_ms,
            "ended_at": export.ended_at_ms,
            "source_uri": export.meeting.audio_uri,
        },
    )
    for speaker in export.speakers:
        hive.remember_person(tenant, {"id": speaker.id, "name": speaker.name, "role": speaker.role})

    report("embedding episodes", 0.08)
    vectors = embedder.embed([e.text for e in episodes], "document")
    hive.remember_episodes(tenant, meeting_id, [e.to_record(v) for e, v in zip(episodes, vectors)])
    for episode in episodes:
        hive.publish(
            tenant,
            "episode.ingested",
            {
                "episode_id": episode.id,
                "meeting_id": meeting_id,
                "seq": episode.seq,
                "speaker_id": episode.speaker_id,
                "t_occurred": episode.t_occurred,
                "source_kind": "utterance",
            },
        )
    report("episodes stored", 0.25)

    source = SourceContext(
        container_id=meeting_id,
        container_kind="meeting",
        title=export.meeting.title,
        day=export.meeting.started_at.date(),
        speakers=[s.model_dump() for s in export.speakers],
    )
    _extract_and_store(
        tenant,
        hive,
        embedder,
        episodes,
        source,
        _resolve_extractor(extractor, llm),
        _resolve_judge(judge, llm),
        stats,
        report,
        start=0.25,
    )
    report("done", 1.0)
    log.info("ingested %s for %s: %s", meeting_id, tenant, stats.as_dict())
    return stats.as_dict()


def run_thread(
    thread_json: dict[str, Any] | str | bytes | Any,
    tenant: str,
    hive: HiveLike,
    llm: LLMProtocol | None,
    embedder: Embedder,
    *,
    roster: list[dict[str, Any]] | None = None,
    extractor: Extractor | None = None,
    judge: Judge | None = None,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Ingest one email thread: one Episode per message, then the same extraction path as meetings."""
    from .email_format import parse_thread, thread_episodes

    report = progress or _noop_progress
    report("validating", 0.02)
    thread = parse_thread(thread_json)
    people = thread.resolve_people(roster)
    episodes = thread_episodes(thread, people)
    stats = PipelineStats(container_id=thread.thread.id, source_kind="email", episodes=len(episodes))

    thread_id = hive.remember_thread(
        tenant,
        {"id": thread.thread.id, "subject": thread.thread.subject, "started_at": thread.started_at_ms},
    )
    for person in people.values():
        hive.remember_person(tenant, {"id": person["id"], "name": person["name"], "email": person.get("email"), "role": person.get("role")})

    report("embedding messages", 0.08)
    vectors = embedder.embed([e.text for e in episodes], "document")
    hive.remember_email_episodes(tenant, thread_id, [e.to_record(v) for e, v in zip(episodes, vectors)])
    for episode in episodes:
        hive.publish(
            tenant,
            "episode.ingested",
            {
                "episode_id": episode.id,
                "thread_id": thread_id,
                "seq": episode.seq,
                "speaker_id": episode.speaker_id,
                "t_occurred": episode.t_occurred,
                "source_kind": "email",
            },
        )
    report("messages stored", 0.25)

    source = SourceContext(
        container_id=thread_id,
        container_kind="thread",
        title=thread.thread.subject,
        day=thread.thread.started_at.date(),
        speakers=[{"id": p["id"], "name": p["name"], "role": p.get("role"), "email": p.get("email")} for p in people.values()],
    )
    _extract_and_store(
        tenant,
        hive,
        embedder,
        episodes,
        source,
        _resolve_extractor(extractor, llm),
        _resolve_judge(judge, llm),
        stats,
        report,
        start=0.25,
    )
    report("done", 1.0)
    log.info("ingested thread %s for %s: %s", thread_id, tenant, stats.as_dict())
    return stats.as_dict()


def ingest_episode_record(
    tenant: str,
    hive: HiveLike,
    embedder: Embedder,
    episode_record: dict[str, Any],
    source: SourceContext,
    *,
    llm: LLMProtocol | None = None,
    extractor: Extractor | None = None,
    judge: Judge | None = None,
) -> dict[str, Any]:
    """Re-run extraction and supersession for one already-stored episode (used by the FactAgent)."""
    is_email = episode_record.get("source_kind") == "email"
    episode = Episode(
        id=str(episode_record["id"]),
        seq=int(episode_record.get("seq") or 0),
        speaker_id=str(episode_record.get("speaker_id") or episode_record.get("sender_id") or ""),
        text=str(episode_record.get("text") or ""),
        t_start=episode_record.get("t_start"),
        t_end=episode_record.get("t_end"),
        t_occurred=int(episode_record.get("t_occurred") or 0),
        segment_indices=[int(episode_record.get("seq") or 0)],
        source_kind="email" if is_email else "utterance",
        container_id=source.container_id,
        message_id=episode_record.get("message_id"),
    )
    stats = PipelineStats(container_id=source.container_id, source_kind=episode.source_kind, episodes=1)
    _extract_and_store(
        tenant,
        hive,
        embedder,
        [episode],
        source,
        _resolve_extractor(extractor, llm),
        _resolve_judge(judge, llm),
        stats,
        _noop_progress,
        start=0.0,
    )
    return stats.as_dict()


def _extract_and_store(
    tenant: str,
    hive: HiveLike,
    embedder: Embedder,
    episodes: list[Episode],
    source: SourceContext,
    extractor: Extractor,
    judge: Judge,
    stats: PipelineStats,
    report: ProgressFn,
    *,
    start: float,
) -> None:
    total = len(episodes) or 1
    context: list[dict[str, Any]] = []
    container_items: list[dict[str, Any]] = []
    for index, episode in enumerate(episodes):
        active = hive.active_facts(tenant)
        ctx = EpisodeContext(
            episode=episode,
            container_title=source.title,
            container_date=source.day,
            speakers=source.speakers,
            prior_facts=select_prior_facts(active, episode.text),
            source_kind=episode.source_kind,
            tenant=tenant,
            context_before=list(context),
            container_items=list(container_items),
        )
        result = extractor.extract(ctx)
        context.append({"speaker": episode.speaker_id, "text": episode.text})
        container_items.extend(
            {"subject": i.subject, "predicate": i.predicate, "object": i.object, "kind": i.kind, "speaker_id": episode.speaker_id}
            for i in result.items
        )
        stats.proposed += result.stats.proposed
        stats.dropped += result.stats.dropped
        stats.errors.extend(result.stats.errors[:5])
        if result.stats.failed:
            stats.failed_episodes.append(episode.id)
            log.warning("extraction failed for episode %s: %s", episode.id, "; ".join(result.stats.errors[:1]))

        entity_types: dict[str, str] = {}
        for entity in result.entities:
            entity_types.setdefault(entity.name, entity.type)
        for item in result.items:
            entity_types.setdefault(canonical_entity_name(item.subject), "topic")
        names = list(entity_types)
        entity_ids: dict[str, str] = {}
        if names:
            vectors = embedder.embed(names, "document")
            rows = [
                {"id": entity_id_for(name), "name": name, "type": entity_types[name], "embedding": vec}
                for name, vec in zip(names, vectors)
            ]
            entity_ids = hive.upsert_entities(tenant, rows)
            for name in names:
                entity_ids.setdefault(name, entity_id_for(name))
            stats.entities += len(entity_ids)
        mentioned = list(dict.fromkeys([*entity_ids.values(), *mentioned_known_entities(hive, tenant, episode.text)]))
        if mentioned:
            hive.link_mentions(tenant, episode.id, mentioned)

        if result.items:
            item_vectors = embedder.embed([item.text for item in result.items], "document")
            for n, (item, vec) in enumerate(zip(result.items, item_vectors)):
                _store_item(tenant, hive, episode, item, vec, entity_ids, judge, stats, index=n)
        report(f"episode {index + 1}/{total}", start + (1.0 - start) * (index + 1) / total)

    # Retro pass: entities first named late in the import also get MENTIONS from earlier episodes
    # of the same import that talk about them (link_mentions MERGEs, so this is idempotent).
    for episode in episodes:
        late = mentioned_known_entities(hive, tenant, episode.text)
        if late:
            hive.link_mentions(tenant, episode.id, late)


def mentioned_known_entities(hive: HiveLike, tenant: str, text: str) -> list[str]:
    """Ids of already-known entities whose name occurs in ``text`` as a whole word (case-insensitive).

    This is what makes "who knows about PayU" count every utterance and email that names PayU,
    not only the episodes where the extractor returned it as an entity.
    """
    lowered = f" {text.lower()} "
    if not lowered.strip():
        return []
    ids: list[str] = []
    for entity in hive.list_entities(tenant):
        name = str(entity.get("name") or "").strip().lower()
        if len(name) < 3 or not entity.get("id"):
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", lowered):
            ids.append(str(entity["id"]))
    return ids


def _count(stats: PipelineStats, kind: str) -> None:
    if kind == "decision":
        stats.decisions += 1
    elif kind == "commitment":
        stats.commitments += 1
    else:
        stats.facts += 1


def _store_item(
    tenant: str,
    hive: HiveLike,
    episode: Episode,
    item: ExtractedFact,
    vector: list[float],
    entity_map: dict[str, str],
    judge: Judge,
    stats: PipelineStats,
    *,
    index: int,
) -> None:
    subject = canonical_entity_name(item.subject)
    text_lower = item.text.lower()
    entity_ids = [entity_map.get(subject, entity_id_for(subject))]
    for name, eid in entity_map.items():
        if name != subject and name.lower() in text_lower and eid not in entity_ids:
            entity_ids.append(eid)

    fact: dict[str, Any] = {
        "id": f"fact_{episode.id}_{index:02d}",
        "kind": item.kind,
        "subject": subject,
        "predicate": item.predicate,
        "object": item.object,
        "key": fact_key(subject, item.predicate),
        "text": item.text,
        "confidence": item.confidence,
        "speaker_id": episode.speaker_id,
        "episode_id": episode.id,
        "entity_ids": entity_ids,
        "valid_from": episode.t_occurred,
        "embedding": vector,
    }
    due_ms = date_to_ms(item.due_at) if item.due_at else None
    if due_ms is not None:
        fact["due_at"] = due_ms
    if item.supersedes_hint:
        fact["supersedes_hint"] = item.supersedes_hint

    t = fact["valid_from"]
    chain = [f for f in hive.facts_by_key(tenant, fact["key"]) if f.get("status") != "retracted"]
    chain.sort(key=lambda f: (int(f.get("valid_from") or 0), int(f.get("created_at") or 0)))
    prior = _belief_in_chain(chain, t)
    head = next((f for f in reversed(chain) if f.get("status") == "active"), None)
    new_object = normalize_object(item.object)

    if item.predicate not in SINGLE_VALUED_PREDICATES:
        # Multi-valued key (lessons, requirements, scope items, customers, decided rules): a different
        # object is a new value next to the others, not a replacement, unless the item says it supersedes.
        believed = _beliefs_in_chain(chain, t)
        same = next((f for f in believed if normalize_object(f.get("object")) == new_object), None)
        if same is not None:
            prior = same
        elif item.supersedes_hint:
            active = [f for f in chain if f.get("status") == "active"]
            head = _hinted_target(active, item.supersedes_hint) or head
        else:
            head = None

    if prior is not None and normalize_object(prior.get("object")) == new_object:
        # A restatement of what was already believed at that time: confirmation, never SUPERSEDES.
        stats.duplicates += 1
        hive.confirm_fact(tenant, prior["id"], episode.id)
        return

    if item.precedent_key:
        precedents = hive.active_facts(tenant, key=item.precedent_key)
        if precedents:
            best = max(precedents, key=lambda f: (f.get("valid_from") or 0, f.get("created_at") or 0))
            fact["precedent_ids"] = [best["id"]]

    base_payload = {
        "key": fact["key"],
        "kind": item.kind,
        "subject": subject,
        "predicate": item.predicate,
        "object": item.object,
        "speaker_id": episode.speaker_id,
        "episode_id": episode.id,
        "due_at": fact.get("due_at"),
        "source_kind": episode.source_kind,
    }

    if head is None or t >= int(head.get("valid_from") or 0):
        # Normal path: the new statement is the latest thing said about this key.
        if head is not None:
            verdict = judge(head, item)
            if verdict.verdict == "contradiction":
                result = hive.supersede_fact(tenant, head["id"], fact)
                stats.superseded += 1
                payload = {
                    **base_payload,
                    "old_fact_id": head["id"],
                    "new_fact_id": result["id"],
                    "old_object": head.get("object"),
                    "new_object": item.object,
                    "reason": verdict.reason,
                    "head_changed": True,
                }
                _emit(hive, tenant, "fact.superseded", payload)
                if item.kind == "commitment":
                    _emit(hive, tenant, "commitment.updated", {**payload, "commitment_id": result["id"]})
                _count(stats, item.kind)
                return
            if verdict.verdict == "refinement":
                fact["precedent_ids"] = [*fact.get("precedent_ids", []), head["id"]]
                stats.refinements += 1
        result = hive.remember_fact(tenant, fact)
        payload = {**base_payload, "fact_id": result["id"], "precedent_ids": fact.get("precedent_ids", [])}
        _emit(hive, tenant, "fact.created", payload)
        if item.kind == "commitment":
            _emit(hive, tenant, "commitment.created", {**payload, "commitment_id": result["id"]})
        _count(stats, item.kind)
        return

    # Mid-chain insertion: the statement occurred before the current head (late import of an
    # earlier meeting). It slots in by valid_from; the current belief does not change, so no
    # fact.superseded is published (the Scheduler must not wake).
    following = next(f for f in chain if int(f.get("valid_from") or 0) > t)
    verdict = judge(prior, item) if prior is not None else SupersessionVerdict(verdict="contradiction", reason="first statement in chain")
    after_id: str | None = None
    if prior is not None and verdict.verdict == "contradiction":
        after_id = prior["id"]
        stats.superseded += 1
    elif prior is not None and verdict.verdict == "refinement":
        fact["precedent_ids"] = [*fact.get("precedent_ids", []), prior["id"]]
        stats.refinements += 1
    result = hive.insert_fact_in_chain(tenant, fact, before_id=following["id"], after_id=after_id)
    payload = {
        **base_payload,
        "fact_id": result["id"],
        "precedent_ids": fact.get("precedent_ids", []),
        "chain_position": "mid",
        "superseded_by": following["id"],
        "supersedes": after_id,
        "head_changed": False,
    }
    _emit(hive, tenant, "fact.created", payload)
    _count(stats, item.kind)


def _beliefs_in_chain(chain: list[dict[str, Any]], t: int) -> list[dict[str, Any]]:
    """Every chain member believed at time ``t`` (several for multi-valued predicates)."""
    out = []
    for fact in chain:
        valid_from = int(fact.get("valid_from") or 0)
        valid_to = fact.get("valid_to")
        if valid_from <= t and (valid_to is None or int(valid_to) > t):
            out.append(fact)
    return out


def _hinted_target(active: list[dict[str, Any]], hint: str) -> dict[str, Any] | None:
    """The active fact a supersedes hint names (its object appears in the hint), else the latest one."""
    if not active:
        return None
    text = normalize_object(hint)
    named = [f for f in active if normalize_object(f.get("object")) and normalize_object(f.get("object")) in text]
    pool = named or active
    return max(pool, key=lambda f: (int(f.get("valid_from") or 0), int(f.get("created_at") or 0)))


def _belief_in_chain(chain: list[dict[str, Any]], t: int) -> dict[str, Any] | None:
    """The chain member that was believed at time ``t`` (valid_from <= t < valid_to)."""
    for fact in reversed(chain):
        valid_from = int(fact.get("valid_from") or 0)
        valid_to = fact.get("valid_to")
        if valid_from <= t and (valid_to is None or int(valid_to) > t):
            return fact
    return None
