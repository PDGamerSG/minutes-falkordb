"""End-to-end ingestion: validate -> chunk -> embed -> remember -> extract -> supersede.

``run`` handles recorder exports (meetings); ``run_thread`` handles email threads. Both share
``_extract_and_store`` so facts from either source go through the same supersession path.
The ``hive`` argument is any object with the ``hiveboard`` memory/event methods minus ``db``
(see ``apps/api/hive_adapter.py`` for the real adapter and ``ingest.fakes.MemoryHive``).

Events: the hive publishes memory events itself when ``hive.publishes_memory_events`` is true
(the substrate and ``MemoryHive`` do); otherwise the pipeline publishes the same payload shapes
(``ingest.fakes.fact_created_payload`` / ``fact_superseded_payload``), so there is exactly one
publisher and ``episode.ingested`` is published once per stored batch, never per episode.

Re-imports: fact ids are content-derived (``fact_<episode>_<sha1(key|object)[:8]>``) and episode ids
positional (``ep_<container>_<seq>``). Before storing, the incoming episodes are compared with the
container's stored ones; a differing source fails with :class:`SourceChangedError` (``source_changed``)
instead of silently rewriting the chain: a changed recording or mailbox must be imported under a new
container id. On an identical re-import, episodes that already have facts are skipped (a retry after a
partial failure only re-runs the model for the episodes that lost their facts).
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Protocol

from .chunker import Episode, chunk
from .dates import DEFAULT_DAYFIRST, DEFAULT_TZ, date_to_ms
from .embed import Embedder
from .extract import (
    EpisodeContext,
    Extractor,
    LLMExtractor,
    hinted_supersession,
    judge_supersession,
    plan_windows,
    select_prior_facts,
)
from .fakes import fact_created_payload, fact_superseded_payload
from .llm_protocol import LLMProtocol
from .models import ExtractedFact, SupersessionVerdict, canonical_entity_name, entity_id_for, fact_id_for, fact_key, normalize_object
from .recorder_format import RecorderExport, parse_export
from .vocab import known_spelling

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]
Judge = Callable[[dict[str, Any], ExtractedFact], SupersessionVerdict]

#: Predicates with one current value per subject: a new object supersedes the old one. Every other
#: predicate (lesson, requires, scope_includes, customer, decided, ...) is multi-valued and only
#: supersedes when the extracted item carries a ``supersedes_hint``.
SINGLE_VALUED_PREDICATES = frozenset({"due", "owner", "uses_vendor", "uses_pattern", "status"})

__all__ = [
    "EmbeddingModelMismatch",
    "HiveLike",
    "IngestError",
    "PipelineStats",
    "SINGLE_VALUED_PREDICATES",
    "SourceChangedError",
    "SourceContext",
    "ingest_episode_record",
    "mentioned_known_entities",
    "normalize_object",
    "run",
    "run_thread",
]


class IngestError(ValueError):
    """An import was refused; ``code`` is the machine-readable reason for API error envelopes."""

    code = "ingest_error"


class SourceChangedError(IngestError):
    """The container already holds episodes and the incoming export differs from them."""

    code = "source_changed"


class EmbeddingModelMismatch(IngestError):
    """The tenant's vectors come from a different embedding model than the one in use."""

    code = "embedding_model_mismatch"


class HiveLike(Protocol):
    """The subset of the hiveboard surface the pipeline calls (tenant first, no ``db``)."""

    def remember_person(self, tenant: str, person: dict[str, Any]) -> str: ...

    def remember_meeting(self, tenant: str, meeting: dict[str, Any]) -> str: ...

    def remember_thread(self, tenant: str, thread: dict[str, Any]) -> str: ...

    def remember_episodes(self, tenant: str, meeting_id: str, episodes: list[dict[str, Any]]) -> int: ...

    def remember_email_episodes(self, tenant: str, thread_id: str, episodes: list[dict[str, Any]]) -> int: ...

    def container_episodes(self, tenant: str, container_id: str) -> list[dict[str, Any]]:
        """Stored episodes of a container: ``[{id, seq, t_start, t_end, speaker_id, text_hash}]`` (the contract shape);
        ``text`` may stand in for ``text_hash`` and ``fact_count`` is optional (MemoryHive supplies both)."""
        ...

    def remember_entities(self, tenant: str, entities: list[dict[str, Any]]) -> int: ...

    def upsert_entities(self, tenant: str, entities: list[dict[str, Any]]) -> dict[str, str]: ...

    def list_entities(self, tenant: str) -> list[dict[str, Any]]: ...

    def link_mentions(self, tenant: str, episode_id: str, entity_ids: list[str]) -> int: ...

    def remember_fact(self, tenant: str, fact: dict[str, Any]) -> dict[str, Any]: ...

    def supersede_fact(self, tenant: str, old_id: str, new_fact: dict[str, Any]) -> dict[str, Any]: ...

    def active_facts(self, tenant: str, entity_id: str | None = None, key: str | None = None) -> list[dict[str, Any]]: ...

    def facts_by_key(self, tenant: str, key: str) -> list[dict[str, Any]]: ...

    def insert_fact_in_chain(self, tenant: str, fact: dict[str, Any], before_id: str) -> dict[str, Any]:
        """Atomic mid-chain insertion; returns ``{"id", "inserted", "confirmed", "before_id"}``."""
        ...

    def confirm_fact(self, tenant: str, fact_id: str, episode_id: str) -> None: ...

    def list_facts(self, tenant: str, status: str | None = "active", entity: str | None = None, kind: str | None = None) -> list[dict[str, Any]]: ...

    def set_tenant_meta(self, tenant: str, meta: dict[str, Any]) -> dict[str, Any]: ...

    def get_tenant_meta(self, tenant: str) -> dict[str, Any]: ...

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
    #: episodes already carrying facts from an earlier import of this container (not re-extracted)
    skipped_episodes: int = 0
    #: model calls made (dialogue windows count once)
    extraction_calls: int = 0
    errors: list[str] = field(default_factory=list)
    #: episodes whose extraction or storage failed (nothing or only part extracted); callers surface these
    failed_episodes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["items"] = self.facts + self.decisions + self.commitments
        data["drop_rate"] = round(self.dropped / self.proposed, 3) if self.proposed else 0.0
        return data

    def fail_episode(self, episode_id: str, message: str | None = None) -> None:
        if episode_id not in self.failed_episodes:
            self.failed_episodes.append(episode_id)
        if message and len(self.errors) < 50:
            self.errors.append(message)


@dataclass(slots=True)
class SourceContext:
    """Container-level context shared by every episode of one import."""

    container_id: str
    container_kind: str
    title: str
    day: date
    speakers: list[dict[str, Any]]
    #: tenant conventions: ambiguous numeric dates and the zone of calendar dates (due_at midnight)
    dayfirst: bool = DEFAULT_DAYFIRST
    timezone: str = DEFAULT_TZ


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


# --------------------------------------------------------------------------- guards


def check_embedding_model(hive: HiveLike, tenant: str, embedder: Embedder) -> str:
    """Record the embedding model on the first ingest; refuse a different one afterwards.

    Returns the recorded identity. Hives without ``get_tenant_meta`` (an adapter not yet updated) are
    logged and skipped so the import still runs.
    """
    identity = getattr(embedder, "identity", None) or f"{embedder.name}:{embedder.model}"
    getter = getattr(hive, "get_tenant_meta", None)
    setter = getattr(hive, "set_tenant_meta", None)
    if not callable(getter) or not callable(setter):
        log.warning("hive %s has no tenant meta; embedding model %s not recorded", type(hive).__name__, identity)
        return identity
    meta = getter(tenant) or {}
    recorded = meta.get("embedding_model")
    if not recorded:
        setter(tenant, {"embedding_model": identity, "embedding_dim": int(getattr(embedder, "dim", 768))})
        return identity
    if str(recorded) != identity:
        raise EmbeddingModelMismatch(
            f"embedding_model_mismatch: tenant {tenant!r} was embedded with {recorded!r} but this process uses "
            f"{identity!r}; recall over mixed vector spaces returns noise. Re-seed the tenant with --reset or "
            f"set EMBED_BACKEND/EMBED_MODEL to match."
        )
    return identity


def _text_digest(text: Any) -> str:
    """Digest of an episode's text, the same function the API's ``container_episodes`` rows use for ``text_hash``."""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


def _episode_signature(seq: Any, t_start: Any, t_end: Any, speaker: Any, text: Any = None, text_hash: Any = None) -> tuple[int, Any, Any, str, str]:
    """Comparable identity of an episode; ``text_hash`` (RealHive rows) wins over ``text`` (MemoryHive rows)."""
    return (int(seq or 0), t_start, t_end, str(speaker or ""), str(text_hash) if text_hash else _text_digest(text))


def existing_episodes(hive: HiveLike, tenant: str, container_id: str) -> list[dict[str, Any]]:
    """The container's stored episodes (``[]`` for a first import or a hive without the read)."""
    reader = getattr(hive, "container_episodes", None)
    if not callable(reader):
        log.warning("hive %s has no container_episodes; re-import checks are skipped", type(hive).__name__)
        return []
    return list(reader(tenant, container_id) or [])


def extracted_episode_ids(hive: HiveLike, tenant: str, stored: list[dict[str, Any]]) -> set[str]:
    """Ids of the stored episodes that already carry facts (not re-extracted on a retry).

    Rows with ``fact_count`` (MemoryHive) answer directly; the contract's ``container_episodes`` rows
    do not, so the tenant's facts are listed once and grouped by ``episode_id``.
    """
    if not stored:
        return set()
    if any("fact_count" in r for r in stored):
        return {str(r["id"]) for r in stored if int(r.get("fact_count") or 0) > 0}
    lister = getattr(hive, "list_facts", None)
    if not callable(lister):
        return set()
    ids = {str(r["id"]) for r in stored}
    try:
        facts = lister(tenant, status=None)
    except Exception:  # noqa: BLE001 - without the list a retry just re-extracts, which is safe (content-hash ids)
        log.warning("could not list facts to find already-extracted episodes; re-extracting", exc_info=True)
        return set()
    return {str(f["episode_id"]) for f in facts if f.get("episode_id") in ids and f.get("status") != "retracted"}


def assert_same_source(container_id: str, stored: list[dict[str, Any]], incoming: list[Episode]) -> None:
    """Raise :class:`SourceChangedError` when a re-import's episodes differ from the stored ones."""
    if not stored:
        return
    old = {_episode_signature(r.get("seq"), r.get("t_start"), r.get("t_end"), r.get("speaker_id"), r.get("text"), r.get("text_hash")) for r in stored}
    new = {_episode_signature(e.seq, e.t_start, e.t_end, e.speaker_id, e.text) for e in incoming}
    if old == new:
        return
    by_seq_old = {sig[0]: sig for sig in old}
    by_seq_new = {sig[0]: sig for sig in new}
    for seq in sorted(set(by_seq_old) | set(by_seq_new)):
        if by_seq_old.get(seq) != by_seq_new.get(seq):
            if seq not in by_seq_old:
                detail = "a new episode not in the stored import"
            elif seq not in by_seq_new:
                detail = "a stored episode missing from this import"
            else:
                detail = "different speaker, timing or text"
            raise SourceChangedError(
                f"source_changed: container {container_id!r} already has {len(stored)} stored episode(s) and the "
                f"incoming export differs at seq {seq} ({detail}). A changed recording, transcript or mailbox must be "
                f"imported under a new container id; identical re-imports are idempotent."
            )


# --------------------------------------------------------------------------- entity cache


class _EntityCache:
    """The tenant's entities, read once per import and extended with the entities this import creates."""

    def __init__(self, hive: HiveLike, tenant: str) -> None:
        self.rows: dict[str, str] = {}
        self._patterns: dict[str, re.Pattern[str]] = {}
        for entity in hive.list_entities(tenant):
            if entity.get("id") and entity.get("name"):
                self.add(str(entity["name"]), str(entity["id"]))

    def add(self, name: str, entity_id: str) -> None:
        name = name.strip()
        if entity_id in self.rows or not name:
            return
        self.rows[entity_id] = name
        lowered = name.lower()
        if len(lowered) >= 3:
            self._patterns[entity_id] = re.compile(r"(?<![a-z0-9])" + re.escape(lowered) + r"(?![a-z0-9])")

    def names(self) -> list[str]:
        return list(self.rows.values())

    def mentioned(self, text: str) -> list[str]:
        lowered = f" {text.lower()} "
        if not lowered.strip():
            return []
        return [eid for eid, pattern in self._patterns.items() if pattern.search(lowered)]


def mentioned_known_entities(hive: HiveLike, tenant: str, text: str) -> list[str]:
    """Ids of already-known entities whose name occurs in ``text`` as a whole word (case-insensitive).

    This is what makes "who knows about PayU" count every utterance and email that names PayU,
    not only the episodes where the extractor returned it as an entity.
    """
    return _EntityCache(hive, tenant).mentioned(text)


def _display_name(name: str, tenant: str, cache: _EntityCache) -> str:
    """Vocabulary or graph spelling for known names ("payments service"); Title Case only for new ones."""
    return known_spelling(name, tenant, cache.names()) or canonical_entity_name(name)


def _prior_facts(hive: HiveLike, tenant: str, cache: _EntityCache, text: str) -> list[dict[str, Any]]:
    """Active facts about the entities the episode names (every key, however many facts the tenant has)."""
    mentioned = cache.mentioned(text)
    if mentioned:
        pool: dict[str, dict[str, Any]] = {}
        for eid in mentioned:
            for fact in hive.active_facts(tenant, entity_id=eid):
                pool.setdefault(str(fact.get("id")), fact)
        facts = list(pool.values())
    else:
        facts = hive.active_facts(tenant)
    return select_prior_facts(facts, text)


# --------------------------------------------------------------------------- entry points


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
    dayfirst: bool = DEFAULT_DAYFIRST,
    timezone: str = DEFAULT_TZ,
    window_episodes: int | None = None,
    skip_extracted: bool = True,
) -> dict[str, Any]:
    """Ingest one recorder export into the tenant graph and return :class:`PipelineStats` as a dict.

    ``window_episodes`` overrides the extractor's dialogue-window size (``None``: the extractor's own
    default, 3 for :class:`LLMExtractor`, 1 for gold replay). ``skip_extracted`` leaves episodes that
    already carry facts alone on a re-import of the same container.
    """
    report = progress or _noop_progress
    report("validating", 0.02)
    export = parse_export(meeting_json)
    episodes = chunk(export, min_seconds=min_seconds, max_seconds=max_seconds)
    stats = PipelineStats(container_id=export.meeting.id, source_kind="utterance", episodes=len(episodes))
    check_embedding_model(hive, tenant, embedder)
    stored = existing_episodes(hive, tenant, export.meeting.id)
    assert_same_source(export.meeting.id, stored, episodes)

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
    _emit(hive, tenant, "episode.ingested", {"container_id": meeting_id, "count": len(episodes), "source_kind": "utterance", "tenant": tenant})
    report("episodes stored", 0.25)

    source = SourceContext(
        container_id=meeting_id,
        container_kind="meeting",
        title=export.meeting.title,
        day=export.meeting.started_at.date(),
        speakers=[s.model_dump() for s in export.speakers],
        dayfirst=dayfirst,
        timezone=timezone,
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
        window_episodes=window_episodes,
        already_extracted=extracted_episode_ids(hive, tenant, stored) if skip_extracted else set(),
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
    dayfirst: bool = DEFAULT_DAYFIRST,
    timezone: str = DEFAULT_TZ,
    window_episodes: int | None = None,
    skip_extracted: bool = True,
) -> dict[str, Any]:
    """Ingest one email thread: one Episode per message, then the same extraction path as meetings."""
    from .email_format import parse_thread, thread_episodes

    report = progress or _noop_progress
    report("validating", 0.02)
    thread = parse_thread(thread_json)
    people = thread.resolve_people(roster)
    episodes = thread_episodes(thread, people)
    stats = PipelineStats(container_id=thread.thread.id, source_kind="email", episodes=len(episodes))
    check_embedding_model(hive, tenant, embedder)
    stored = existing_episodes(hive, tenant, thread.thread.id)
    assert_same_source(thread.thread.id, stored, episodes)

    thread_id = hive.remember_thread(
        tenant,
        {"id": thread.thread.id, "subject": thread.thread.subject, "started_at": thread.started_at_ms},
    )
    for person in people.values():
        hive.remember_person(tenant, {"id": person["id"], "name": person["name"], "email": person.get("email"), "role": person.get("role")})

    report("embedding messages", 0.08)
    vectors = embedder.embed([e.text for e in episodes], "document")
    hive.remember_email_episodes(tenant, thread_id, [e.to_record(v) for e, v in zip(episodes, vectors)])
    _emit(hive, tenant, "episode.ingested", {"container_id": thread_id, "count": len(episodes), "source_kind": "email", "tenant": tenant})
    report("messages stored", 0.25)

    source = SourceContext(
        container_id=thread_id,
        container_kind="thread",
        title=thread.thread.subject,
        day=thread.thread.started_at.date(),
        speakers=[{"id": p["id"], "name": p["name"], "role": p.get("role"), "email": p.get("email")} for p in people.values()],
        dayfirst=dayfirst,
        timezone=timezone,
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
        window_episodes=window_episodes,
        already_extracted=extracted_episode_ids(hive, tenant, stored) if skip_extracted else set(),
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
    check_embedding_model(hive, tenant, embedder)
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
        window_episodes=1,
        already_extracted=set(),
    )
    return stats.as_dict()


# --------------------------------------------------------------------------- extraction


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
    window_episodes: int | None = None,
    already_extracted: set[str] | None = None,
) -> None:
    total = len(episodes) or 1
    done = already_extracted or set()
    cache = _EntityCache(hive, tenant)
    context: list[dict[str, Any]] = []
    container_items: list[dict[str, Any]] = []
    size = window_episodes if window_episodes is not None else int(getattr(extractor, "window_episodes", 1) or 1)
    supports_windows = callable(getattr(extractor, "extract_window", None))
    processed = 0

    todo = [e for e in episodes if e.id not in done]
    stats.skipped_episodes = len(episodes) - len(todo)
    if stats.skipped_episodes:
        log.info("%s: %d episode(s) already carry facts; not re-extracted", source.container_id, stats.skipped_episodes)
    skipped_iter = iter(sorted((e for e in episodes if e.id in done), key=lambda e: e.seq))
    next_skipped = next(skipped_iter, None)

    for window in plan_windows(todo, size if supports_windows else 1):
        # keep skipped episodes in the dialogue context in their original order
        while next_skipped is not None and next_skipped.seq < window[0].seq:
            context.append({"speaker": next_skipped.speaker_id, "text": next_skipped.text})
            next_skipped = next(skipped_iter, None)
        ctxs = [
            EpisodeContext(
                episode=episode,
                container_title=source.title,
                container_date=source.day,
                speakers=source.speakers,
                prior_facts=_prior_facts(hive, tenant, cache, episode.text),
                source_kind=episode.source_kind,
                tenant=tenant,
                context_before=list(context),
                container_items=list(container_items),
                known_entities=cache.names(),
                dayfirst=source.dayfirst,
            )
            for episode in window
        ]
        try:
            if len(ctxs) > 1 and supports_windows:
                results = extractor.extract_window(ctxs)  # type: ignore[attr-defined]
            else:
                results = [extractor.extract(ctxs[0])]
            stats.extraction_calls += 1
        except Exception as exc:  # noqa: BLE001 - one bad window must not abort the import
            log.exception("extraction raised for %s", [c.episode.id for c in ctxs])
            for ctx in ctxs:
                stats.fail_episode(ctx.episode.id, f"{ctx.episode.id}: {type(exc).__name__}: {exc}")
            for ctx in ctxs:
                context.append({"speaker": ctx.episode.speaker_id, "text": ctx.episode.text})
            processed += len(ctxs)
            report(f"episode {processed}/{total}", start + (1.0 - start) * processed / total)
            continue

        for ctx, result in zip(ctxs, results):
            episode = ctx.episode
            context.append({"speaker": episode.speaker_id, "text": episode.text})
            container_items.extend(
                {"subject": i.subject, "predicate": i.predicate, "object": i.object, "kind": i.kind, "speaker_id": episode.speaker_id}
                for i in result.items
            )
            stats.proposed += result.stats.proposed
            stats.dropped += result.stats.dropped
            stats.errors.extend(result.stats.errors[:5])
            if result.stats.failed:
                stats.fail_episode(episode.id)  # the extractor's own error is already in stats.errors
                log.warning("extraction failed for episode %s: %s", episode.id, "; ".join(result.stats.errors[:1]))
            try:
                _store_episode_results(tenant, hive, embedder, episode, result, source, judge, stats, cache)
            except Exception as exc:  # noqa: BLE001 - storing one episode must not abort the import
                log.exception("storing results of %s failed", episode.id)
                stats.fail_episode(episode.id, f"{episode.id}: {type(exc).__name__}: {exc}")
            processed += 1
            report(f"episode {processed}/{total}", start + (1.0 - start) * processed / total)

    # Retro pass: entities first named late in the import also get MENTIONS from earlier episodes
    # of the same import that talk about them (link_mentions MERGEs, so this is idempotent).
    for episode in episodes:
        late = cache.mentioned(episode.text)
        if late:
            hive.link_mentions(tenant, episode.id, late)


def _store_episode_results(
    tenant: str,
    hive: HiveLike,
    embedder: Embedder,
    episode: Episode,
    result: Any,
    source: SourceContext,
    judge: Judge,
    stats: PipelineStats,
    cache: _EntityCache,
) -> None:
    entity_types: dict[str, str] = {}
    for entity in result.entities:
        entity_types.setdefault(_display_name(entity.name, tenant, cache), entity.type)
    for item in result.items:
        entity_types.setdefault(_display_name(item.subject, tenant, cache), "topic")
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
        for name, eid in entity_ids.items():
            cache.add(name, eid)
        stats.entities += len(entity_ids)
    mentioned = list(dict.fromkeys([*entity_ids.values(), *cache.mentioned(episode.text)]))
    if mentioned:
        hive.link_mentions(tenant, episode.id, mentioned)

    if not result.items:
        return
    item_vectors = embedder.embed([item.text for item in result.items], "document")
    for item, vec in zip(result.items, item_vectors):
        try:
            _store_item(tenant, hive, episode, item, vec, entity_ids, judge, stats, source=source, cache=cache)
        except Exception as exc:  # noqa: BLE001 - a conflict on one key must not lose the other items
            log.exception("storing %s|%s from %s failed", item.subject, item.predicate, episode.id)
            stats.fail_episode(episode.id, f"{episode.id}: {item.key}: {type(exc).__name__}: {exc}")


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
    source: SourceContext | None = None,
    cache: _EntityCache | None = None,
) -> None:
    subject = _display_name(item.subject, tenant, cache) if cache is not None else canonical_entity_name(item.subject)
    text_lower = item.text.lower()
    entity_ids = [entity_map.get(subject, entity_id_for(subject))]
    for name, eid in entity_map.items():
        if name != subject and name.lower() in text_lower and eid not in entity_ids:
            entity_ids.append(eid)

    key = fact_key(subject, item.predicate)
    fact: dict[str, Any] = {
        "id": fact_id_for(episode.id, key, item.object),
        "kind": item.kind,
        "subject": subject,
        "predicate": item.predicate,
        "object": item.object,
        "key": key,
        "text": item.text,
        "confidence": item.confidence,
        "speaker_id": episode.speaker_id,
        "episode_id": episode.id,
        "entity_ids": entity_ids,
        "valid_from": episode.t_occurred,
        "embedding": vector,
    }
    due_ms = date_to_ms(item.due_at, source.timezone if source is not None else None) if item.due_at else None
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

    if head is None or t >= int(head.get("valid_from") or 0):
        # Normal path: the new statement is the latest thing said about this key.
        if head is not None:
            verdict = judge(head, item)
            if verdict.verdict == "contradiction":
                result = hive.supersede_fact(tenant, head["id"], fact)
                stats.superseded += 1
                stored = {**fact, "id": result["id"]}
                _emit(hive, tenant, "fact.created", fact_created_payload(tenant, stored))
                if item.kind == "commitment":
                    _emit(hive, tenant, "commitment.created", {**fact_created_payload(tenant, stored), "commitment_id": result["id"]})
                payload = fact_superseded_payload(tenant, stored, head, head_changed=True)
                _emit(hive, tenant, "fact.superseded", payload)
                if item.kind == "commitment":
                    _emit(hive, tenant, "commitment.updated", {**payload, "commitment_id": result["id"]})
                _count(stats, item.kind)
                return
            if verdict.verdict == "refinement":
                fact["precedent_ids"] = [*fact.get("precedent_ids", []), head["id"]]
                stats.refinements += 1
        result = hive.remember_fact(tenant, fact)
        if result.get("existing"):
            stats.duplicates += 1
            hive.confirm_fact(tenant, result["id"], episode.id)
            return
        stored = {**fact, "id": result["id"]}
        payload = fact_created_payload(tenant, stored)
        _emit(hive, tenant, "fact.created", payload)
        if item.kind == "commitment":
            _emit(hive, tenant, "commitment.created", {**payload, "commitment_id": result["id"]})
        _count(stats, item.kind)
        return

    # Mid-chain insertion: the statement occurred before the current head (late import of an
    # earlier meeting). The substrate slots it in by valid_from atomically and refuses to
    # self-supersede (a restatement of the member it would slot over is confirmed instead). The
    # current belief does not change, so nothing is published (the Scheduler must not wake).
    following = next(f for f in chain if int(f.get("valid_from") or 0) > t)
    verdict = judge(prior, item) if prior is not None else SupersessionVerdict(verdict="contradiction", reason="first statement in chain")
    if prior is not None and verdict.verdict == "refinement":
        fact["precedent_ids"] = [*fact.get("precedent_ids", []), prior["id"]]
    result = hive.insert_fact_in_chain(tenant, fact, before_id=following["id"])
    if result.get("confirmed"):
        stats.duplicates += 1
        return
    if not result.get("inserted", True):
        stats.duplicates += 1
        return
    if prior is not None and verdict.verdict == "contradiction":
        stats.superseded += 1
    elif prior is not None:
        stats.refinements += 1
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
    """The active fact a supersedes hint names, else the latest one.

    Accepts the live format ``"replaces: <subject> <predicate> <old object>"`` and the gold JSON form
    ``{"subject": ..., "predicate": ..., "object"?: ...}``: the fact whose object appears in the hint
    text (or equals the JSON ``object``) wins; a hint that names only the key falls back to the latest.
    """
    if not active:
        return None
    text = hint
    stripped = hint.strip()
    if stripped.startswith("{"):
        try:
            import json

            data = json.loads(stripped)
            text = " ".join(str(v) for v in data.values() if v is not None) if isinstance(data, dict) else hint
        except ValueError:
            text = hint
    normalized = normalize_object(text)
    named = [f for f in active if normalize_object(f.get("object")) and normalize_object(f.get("object")) in normalized]
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
