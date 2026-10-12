"""Shared import logic for the HTTP routes and the seed script.

Dispatches a data file on its top-level key (``meeting`` vs ``thread``), loads the tenant roster,
picks the gold-replay extractor when the model backend is fake, runs the pipeline and, after a
meeting import, triggers StandupAgent's skill learning when a title prefix has two meetings.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ingest import pipeline
from ingest.email_format import EmailThread, parse_thread
from ingest.extract import GoldExtractor, hinted_supersession
from ingest.gold import find_gold
from ingest.recorder_format import RecorderExport, parse_export

from .agents.standup_agent import StandupAgent, meetings_by_prefix, title_prefix
from .errors import ApiError

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]

# Tenant meta keys shared with the ingest pipeline (which records the same two on first ingest).
EMBEDDING_MODEL_KEY = "embedding_model"
EMBEDDING_DIM_KEY = "embedding_dim"


class EmbeddingMismatch(ApiError):
    """The tenant's vectors were produced by a different embedding model than the API runs (409)."""

    def __init__(self, tenant: str, expected: str, actual: str) -> None:
        super().__init__(
            409,
            "embedding_model_mismatch",
            f"tenant {tenant!r} was embedded with {expected!r} but this API runs {actual!r}; "
            "set EMBED_BACKEND/EMBED_MODEL to match or re-seed the tenant",
            expected=expected,
            actual=actual,
        )


def embedding_identity(embedder: Any) -> str:
    """``Embedder.identity`` when the ingest package provides it, else ``<backend>:<model>``."""
    identity = getattr(embedder, "identity", None)
    if identity:
        return str(identity)
    return f"{getattr(embedder, 'name', 'unknown')}:{getattr(embedder, 'model', 'unknown')}"


def check_embedding_space(ctx: Any, tenant: str) -> dict[str, Any] | None:
    """Compare the API's embedder with the tenant meta; returns the mismatch (and records it on ``ctx``) or None."""
    try:
        meta = ctx.hive.get_tenant_meta(tenant) or {}
    except Exception as exc:  # noqa: BLE001 - a missing meta surface must not block startup
        log.debug("get_tenant_meta(%s) failed: %s", tenant, exc)
        return None
    expected = meta.get(EMBEDDING_MODEL_KEY)
    actual = embedding_identity(ctx.embedder)
    if expected and str(expected) != actual:
        mismatch = {"expected": str(expected), "actual": actual, "expected_dim": meta.get(EMBEDDING_DIM_KEY), "actual_dim": getattr(ctx.embedder, "dim", None)}
        ctx.embedding_mismatch[tenant] = mismatch
        log.error("embedding model mismatch for %s: graph %s, API %s", tenant, expected, actual)
        return mismatch
    ctx.embedding_mismatch.pop(tenant, None)
    return None


def ensure_embedding_space(ctx: Any, tenant: str) -> None:
    """Before an import: refuse (409) on a mismatch, record the embedding space on the first ingest."""
    mismatch = check_embedding_space(ctx, tenant)
    if mismatch:
        raise EmbeddingMismatch(tenant, mismatch["expected"], mismatch["actual"])
    try:
        meta = ctx.hive.get_tenant_meta(tenant) or {}
        if not meta.get(EMBEDDING_MODEL_KEY):
            ctx.hive.set_tenant_meta(tenant, {EMBEDDING_MODEL_KEY: embedding_identity(ctx.embedder), EMBEDDING_DIM_KEY: int(getattr(ctx.embedder, "dim", 768))})
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.debug("could not record the embedding space for %s: %s", tenant, exc)


def source_kind_of(data: dict[str, Any]) -> str | None:
    """``"meeting"`` or ``"thread"`` from the top-level key; None for rosters, gold and other JSON."""
    if isinstance(data.get("meeting"), dict):
        return "meeting"
    if isinstance(data.get("thread"), dict):
        return "thread"
    return None


def load_roster(data_dir: Path, tenant: str) -> list[dict[str, Any]] | None:
    """``data/meetings/<tenant>_roster.json`` when present."""
    path = data_dir / "meetings" / f"{tenant}_roster.json"
    if not path.is_file():
        return None
    try:
        roster = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.warning("roster %s is invalid: %s", path, exc)
        return None
    return roster if isinstance(roster, list) else None


class _EmptyExtractor:
    """Fake backend without gold labels: episodes are stored, nothing is extracted."""

    def extract(self, ctx: Any) -> Any:
        from ingest.models import EpisodeExtraction

        return EpisodeExtraction()


def _fake_strategy(llm: Any, data_dir: Path, container_id: str, slug: str | None) -> tuple[Any, Any]:
    """(extractor, judge) overrides: gold replay when the LLM is the fake, else the model path."""
    if getattr(llm, "backend", "") != "fake":
        from ingest.extract import make_extractor

        return make_extractor(llm), None  # current prompt version (v5); judge stays the pipeline default
    gold = find_gold(data_dir / "gold", container_id=container_id, slug=slug)
    if gold is None:
        log.warning("fake LLM and no gold labels for %s; nothing will be extracted", container_id)
        return _EmptyExtractor(), hinted_supersession
    return GoldExtractor(gold), hinted_supersession


def import_meeting(
    export: dict[str, Any] | RecorderExport,
    tenant: str,
    ctx: Any,
    *,
    slug: str | None = None,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Run the meeting pipeline, then schedule skill learning for repeated meeting titles."""
    parsed = parse_export(export)
    ensure_embedding_space(ctx, tenant)
    extractor, judge = _fake_strategy(ctx.llm, ctx.settings.data_path, parsed.meeting.id, slug)
    stats = pipeline.run(parsed, tenant, ctx.hive, ctx.llm, ctx.embedder, extractor=extractor, judge=judge, progress=progress)
    stats["skill_learned"] = maybe_learn_standup(tenant, ctx, parsed.meeting.title)
    return stats


def import_thread(
    thread: dict[str, Any] | EmailThread,
    tenant: str,
    ctx: Any,
    *,
    slug: str | None = None,
    roster: list[dict[str, Any]] | None = None,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Run the email-thread pipeline with the tenant roster as the identity join."""
    parsed = parse_thread(thread)
    ensure_embedding_space(ctx, tenant)
    roster = roster if roster is not None else load_roster(ctx.settings.data_path, tenant)
    extractor, judge = _fake_strategy(ctx.llm, ctx.settings.data_path, parsed.thread.id, slug)
    return pipeline.run_thread(parsed, tenant, ctx.hive, ctx.llm, ctx.embedder, roster=roster, extractor=extractor, judge=judge, progress=progress)


def maybe_learn_standup(tenant: str, ctx: Any, title: str) -> str | None:
    """After an import: if the title prefix now has >= N meetings and no Skill, submit a learn task.

    Submitting through the board (rather than learning inline) keeps the Standup worker the only
    writer of skills and shows the learning step on the board. Without workers (tests, seed) the
    skill is learned inline so the demo data is complete.
    """
    prefix = title_prefix(title)
    if not prefix:
        return None
    groups = meetings_by_prefix(ctx.hive.list_meetings(tenant))
    meetings = groups.get(prefix, [])
    if len(meetings) < int(ctx.settings.standup_min_meetings):
        return None
    agent = StandupAgent(tenant, ctx.hive, ctx.llm, ctx.embedder, ctx.settings)
    if agent.has_skill_for(prefix):
        return None
    if getattr(ctx, "workers", None) is not None and ctx.settings.workers_enabled:
        return ctx.hive.submit_task(tenant, "learn_standup", {"prefix": prefix, "meeting_ids": [m["id"] for m in meetings]}, ["standup"], [], 4)
    return agent.maybe_learn(prefix, meetings)


def import_file(path: Path, tenant: str, ctx: Any, *, progress: ProgressFn | None = None) -> dict[str, Any] | None:
    """Import one data file by its top-level key; returns None when the file is not a source."""
    data = json.loads(path.read_text(encoding="utf-8"))
    kind = source_kind_of(data) if isinstance(data, dict) else None
    if kind == "meeting":
        return import_meeting(data, tenant, ctx, slug=path.stem, progress=progress)
    if kind == "thread":
        return import_thread(data, tenant, ctx, slug=path.stem, progress=progress)
    return None
