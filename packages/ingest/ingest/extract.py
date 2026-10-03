"""Gemma 4 extraction of facts, decisions and commitments from one episode.

``LLMExtractor`` is the production path (``complete_json`` with one retry inside the client).
``GoldExtractor`` replays gold labels for model-free demos and plumbing tests.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from .chunker import Episode
from .dates import calendar_table, looks_like_date
from .gold import GoldFile, gold_items_for_episode
from .llm_protocol import LLMFormatError, LLMProtocol
from .models import (
    EpisodeExtraction,
    ExtractedEntity,
    ExtractedFact,
    ExtractionStats,
    RawExtraction,
    SupersessionVerdict,
)

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    ["a", "an", "the", "and", "or", "but", "if", "then", "so", "to", "of", "in", "on", "at", "for", "by", "with", "from", "as", "is", "are", "was", "were", "be", "been", "being", "it", "its", "this", "that", "these", "those", "we", "you", "they", "he", "she", "i", "me", "my", "our", "your", "their", "them", "us", "do", "does", "did", "done", "have", "has", "had", "will", "would", "can", "could", "should", "may", "might", "must", "not", "no", "yes", "ok", "okay", "let", "lets", "just", "about", "into", "out", "up", "down", "over", "under", "again", "also", "very", "really", "there", "here", "what", "when", "where", "who", "which", "how"]
)

SUPERSESSION_SYSTEM = (
    "You compare two statements about the same subject and relation and decide how the newer one "
    "relates to the earlier one. Answer with ONE JSON object: "
    '{"verdict": "contradiction" | "refinement" | "unrelated", "reason": "<one sentence>"}. '
    "contradiction: the new value replaces the old one (a date moved, an owner changed, a choice reversed); "
    "the old statement is no longer true. refinement: both remain true and the new statement adds detail "
    "or narrows the old one. unrelated: they are about different things despite the shared words. "
    "Output JSON only."
)


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Read ``prompts/<name>.md``."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


@dataclass(slots=True)
class EpisodeContext:
    """Everything the extractor needs about one episode."""

    episode: Episode
    container_title: str
    container_date: date
    speakers: list[dict[str, Any]]
    prior_facts: list[dict[str, Any]] = field(default_factory=list)
    source_kind: str = "utterance"


class Extractor(Protocol):
    """Strategy interface used by the pipeline."""

    def extract(self, ctx: EpisodeContext) -> EpisodeExtraction: ...


def _speaker_name(ctx: EpisodeContext) -> str:
    for s in ctx.speakers:
        if s.get("id") == ctx.episode.speaker_id:
            return str(s.get("name") or ctx.episode.speaker_id)
    return ctx.episode.speaker_id


def build_user_prompt(ctx: EpisodeContext) -> str:
    """Render the user turn: header, calendar, participants, prior facts, episode."""
    is_email = ctx.source_kind == "email"
    lines = [
        f"# {'Email thread' if is_email else 'Meeting'}: {ctx.container_title}",
        f"Date: {ctx.container_date.isoformat()}",
        "",
        "## Calendar (copy ISO dates from here; never compute weekdays yourself)",
        calendar_table(ctx.container_date),
        "",
        "## Participants",
    ]
    for s in ctx.speakers:
        role = f" ({s['role']})" if s.get("role") else ""
        lines.append(f"- {s.get('id')}: {s.get('name')}{role}")
    lines += ["", "## Prior active facts about mentioned entities (use for supersedes_hint)"]
    if ctx.prior_facts:
        for f in ctx.prior_facts:
            lines.append(
                f"- [{f.get('kind', 'fact')}] {f.get('subject')} | {f.get('predicate')} | {f.get('object')}"
                f" (by {f.get('speaker_id', '?')}, fact_id={f.get('id')})"
            )
    else:
        lines.append("- none")
    ep = ctx.episode
    lines += ["", "## " + ("Message" if is_email else "Episode")]
    lines.append(f"{'Sender' if is_email else 'Speaker'}: {_speaker_name(ctx)} ({ep.speaker_id})")
    if is_email:
        sent = datetime.fromtimestamp(ep.t_occurred / 1000, tz=UTC).isoformat()
        lines.append(f"Sent at: {sent}")
    elif ep.t_start is not None and ep.t_end is not None:
        lines.append(f"Time offset: {ep.t_start / 1000:.0f}s to {ep.t_end / 1000:.0f}s")
    lines += ["Text:", ep.text, "", "Return the JSON object now."]
    return "\n".join(lines)


def coerce_extraction(raw: RawExtraction, ctx: EpisodeContext) -> EpisodeExtraction:
    """Validate raw model items one by one; invalid items are dropped and counted."""
    stats = ExtractionStats(proposed=len(raw.items))
    items: list[ExtractedFact] = []
    seen: set[tuple[str, str]] = set()
    for raw_item in raw.items:
        if not isinstance(raw_item, dict):
            stats.dropped += 1
            stats.errors.append("item is not an object")
            continue
        data = dict(raw_item)
        data["episode_id"] = ctx.episode.id
        data["speaker"] = ctx.episode.speaker_id
        try:
            item = ExtractedFact.model_validate(data)
        except ValidationError as exc:
            stats.dropped += 1
            stats.errors.append(str(exc).splitlines()[0][:160])
            continue
        marker = (item.key, item.object.lower())
        if marker in seen:
            stats.dropped += 1
            stats.errors.append(f"duplicate item {item.key}")
            continue
        seen.add(marker)
        items.append(item)
    entities: list[ExtractedEntity] = []
    names: set[str] = set()
    for raw_entity in raw.entities:
        try:
            entity = ExtractedEntity.model_validate(raw_entity if isinstance(raw_entity, dict) else {"name": raw_entity})
        except ValidationError:
            continue
        if entity.name.lower() in names:
            continue
        names.add(entity.name.lower())
        entities.append(entity)
    stats.kept = len(items)
    if stats.proposed:
        log.info(
            "extraction %s: proposed=%d kept=%d drop_rate=%.2f",
            ctx.episode.id,
            stats.proposed,
            stats.kept,
            stats.drop_rate,
        )
    return EpisodeExtraction(items=items, entities=entities, stats=stats)


class LLMExtractor:
    """Extraction through the LLM client (temperature 0.1; the client retries once on bad JSON)."""

    def __init__(
        self,
        llm: LLMProtocol,
        *,
        prompt_name: str = "extract_v1",
        email_prompt_name: str = "extract_email_v1",
        temperature: float = 0.1,
    ) -> None:
        self.llm = llm
        self.prompt_name = prompt_name
        self.email_prompt_name = email_prompt_name
        self.temperature = temperature

    def extract(self, ctx: EpisodeContext) -> EpisodeExtraction:
        system = load_prompt(self.email_prompt_name if ctx.source_kind == "email" else self.prompt_name)
        user = build_user_prompt(ctx)
        try:
            raw = self.llm.complete_json(system, user, RawExtraction, temperature=self.temperature)
        except LLMFormatError as exc:
            log.error("extraction failed for %s after retry: %s", ctx.episode.id, exc)
            return EpisodeExtraction(stats=ExtractionStats(errors=[f"{ctx.episode.id}: {exc}"]))
        return coerce_extraction(raw, ctx)


class GoldExtractor:
    """Model-free extractor that replays gold labels for the episode's segments/messages."""

    def __init__(self, gold: GoldFile) -> None:
        self.gold = gold

    def extract(self, ctx: EpisodeContext) -> EpisodeExtraction:
        items = gold_items_for_episode(self.gold, ctx.episode)
        entities: list[ExtractedEntity] = []
        seen: set[str] = set()
        for item in items:
            if item.subject.lower() not in seen:
                seen.add(item.subject.lower())
                entities.append(ExtractedEntity(name=item.subject, type="topic"))
            if looks_like_proper_noun(item.object) and item.object.lower() not in seen:
                seen.add(item.object.lower())
                entities.append(ExtractedEntity(name=item.object, type="vendor" if "vendor" in item.predicate else "topic"))
        return EpisodeExtraction(items=items, entities=entities, stats=ExtractionStats(proposed=len(items), kept=len(items)))


_PROPER_NOUN = re.compile(r"^[A-Z][A-Za-z0-9&.-]*(\s+[A-Z][A-Za-z0-9&.-]*){0,3}$")


def looks_like_proper_noun(value: str) -> bool:
    """Short capitalised phrase that is not a date or a status word: "PayU", "Meridian Bank", "Razorpay"."""
    text = value.strip()
    if not text or looks_like_date(text) or len(text) > 40:
        return False
    if text.lower() in {"completed", "done", "open", "blocked", "none", "yes", "no", "true", "false"}:
        return False
    return bool(_PROPER_NOUN.match(text))


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


def select_prior_facts(active: list[dict[str, Any]], text: str, limit: int = 25) -> list[dict[str, Any]]:
    """Active facts whose subject/predicate/object share words with the episode text, best first."""
    words = _tokens(text)
    if not words:
        return []
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for fact in active:
        blob = " ".join(
            str(fact.get(k) or "").replace("_", " ") for k in ("subject", "predicate", "object")
        )
        overlap = len(words & _tokens(blob))
        if overlap:
            scored.append((overlap, int(fact.get("valid_from") or 0), fact))
    scored.sort(key=lambda row: (-row[0], -row[1]))
    return [fact for _, _, fact in scored[:limit]]


def heuristic_supersession(old: dict[str, Any], new: ExtractedFact) -> SupersessionVerdict:
    """Rule-based verdict used by the fake backend and as a fallback when the model fails."""
    old_obj = str(old.get("object") or "")
    if looks_like_date(old_obj) and looks_like_date(new.object):
        return SupersessionVerdict(verdict="contradiction", reason="date changed")
    old_tokens, new_tokens = _tokens(old_obj), _tokens(new.object)
    if old_tokens and old_tokens < new_tokens:
        return SupersessionVerdict(verdict="refinement", reason="new object extends the old one")
    return SupersessionVerdict(verdict="contradiction", reason="object changed")


def hinted_supersession(old: dict[str, Any], new: ExtractedFact) -> SupersessionVerdict:
    """Judge for the model-free path: gold hints first (supersedes / follows_precedent), then the heuristic."""
    if new.supersedes_hint:
        return SupersessionVerdict(verdict="contradiction", reason="labelled as superseding an earlier statement")
    if new.precedent_key:
        return SupersessionVerdict(verdict="refinement", reason="labelled as following a precedent")
    return heuristic_supersession(old, new)


def judge_supersession(llm: LLMProtocol, old: dict[str, Any], new: ExtractedFact) -> SupersessionVerdict:
    """Ask the model "contradiction or refinement?"; fall back to the heuristic on format errors."""
    user = (
        f"Earlier statement ({old.get('kind', 'fact')}): subject={old.get('subject')!r} "
        f"predicate={old.get('predicate')!r} object={old.get('object')!r}\n"
        f"Earlier text: {old.get('text', '')}\n\n"
        f"New statement ({new.kind}): subject={new.subject!r} predicate={new.predicate!r} object={new.object!r}\n"
        f"New text: {new.text}\n\n"
        "Does the new statement replace the earlier one (contradiction), add detail while both stay true "
        "(refinement), or talk about something else (unrelated)?"
    )
    try:
        return llm.complete_json(SUPERSESSION_SYSTEM, user, SupersessionVerdict, temperature=0.0)
    except LLMFormatError as exc:
        log.warning("supersession judge failed (%s); using heuristic", exc)
        return heuristic_supersession(old, new)
