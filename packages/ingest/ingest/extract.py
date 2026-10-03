"""Gemma 4 extraction of facts, decisions and commitments from one episode.

``LLMExtractor`` is the production path (``complete_json`` with one retry inside the client).
``GoldExtractor`` replays gold labels for model-free demos and plumbing tests.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from .chunker import Episode
from .dates import calendar_table, looks_like_date, normalize_date, resolve_day_of_month
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
from .vocab import canonicalize_object, canonicalize_predicate, canonicalize_subject, known_subjects, render_subjects

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
    tenant: str = ""
    #: earlier episodes of the same meeting/thread, oldest first: ``{"speaker", "text"}`` (context only)
    context_before: list[dict[str, Any]] = field(default_factory=list)
    #: items already extracted from earlier episodes of the same meeting/thread (read-back filter)
    container_items: list[dict[str, Any]] = field(default_factory=list)
    #: extra known entity names (e.g. from the tenant graph) on top of the vocabulary list
    known_entities: list[str] = field(default_factory=list)


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


_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MARK_NON_WORD = re.compile(r"[^a-z0-9]+")


def build_user_prompt_v2(ctx: EpisodeContext, *, context_episodes: int = 3, context_chars: int = 400) -> str:
    """User turn for the v2 prompts: calendar, participants, known entities, recorded facts, context, episode."""
    is_email = ctx.source_kind == "email"
    day = ctx.container_date
    lines = [
        f"# {'Email thread' if is_email else 'Meeting'}: {ctx.container_title}",
        f"Date: {day.isoformat()} ({_WEEKDAY_NAMES[day.weekday()]})",
        "",
        "## Calendar (copy ISO dates from here; never compute weekdays yourself)",
        calendar_table(day, weeks_after=3),
        "",
        "## Participants",
    ]
    for s in ctx.speakers:
        role = f" ({s['role']})" if s.get("role") else (" (external)" if is_email else "")
        lines.append(f"- {s.get('id')}: {s.get('name')}{role}")
    lines += ["", "## Known entities (reuse these exact subject names)", render_subjects(ctx.tenant, ctx.known_entities)]
    lines += ["", "## Facts already recorded"]
    if ctx.prior_facts:
        for f in ctx.prior_facts:
            lines.append(
                f"- [{f.get('kind', 'fact')}] {f.get('subject')} | {f.get('predicate')} | {f.get('object')}"
                f" (by {f.get('speaker_id', '?')})"
            )
    else:
        lines.append("- none")
    names = {str(s.get("id")): str(s.get("name") or s.get("id")) for s in ctx.speakers}
    heading = "Earlier messages in this thread" if is_email else "Lines just before this episode"
    lines += ["", f"## {heading} (context only; do NOT extract from these)"]
    before = ctx.context_before[-context_episodes:] if context_episodes else []
    if before:
        for prev in before:
            who = names.get(str(prev.get("speaker")), str(prev.get("speaker")))
            text = " ".join(str(prev.get("text") or "").split())
            if len(text) > context_chars:
                text = text[: context_chars - 3] + "..."
            lines.append(f"{who}: {text}")
    else:
        lines.append("- none (this is the first)")
    ep = ctx.episode
    role = next((s.get("role") for s in ctx.speakers if s.get("id") == ep.speaker_id), None)
    lines += ["", "## " + ("Message to extract from" if is_email else "Episode to extract from")]
    lines.append(f"{'Sender' if is_email else 'Speaker'}: {_speaker_name(ctx)} ({ep.speaker_id}{', ' + role if role else ''})")
    if is_email:
        sent = datetime.fromtimestamp(ep.t_occurred / 1000, tz=UTC).isoformat()
        lines.append(f"Sent at: {sent}")
    lines += ["Text:", ep.text, "", "Return the JSON object now."]
    return "\n".join(lines)


def _mark_norm(value: Any) -> str:
    return " ".join(_MARK_NON_WORD.sub(" ", str(value or "").lower()).split())


def _item_marker(subject: Any, predicate: Any, obj: Any) -> tuple[str, str, str]:
    text = str(obj or "")
    return _mark_norm(subject), _mark_norm(predicate), _mark_norm(normalize_date(text) or text)


_LEAD_ROLES = ("lead", "editor", "manager", "head", "chair", "director")
_WEEKDAY_RE = re.compile(r"(?<![a-z])(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?![a-z])", re.IGNORECASE)
_ORDINAL_RE = re.compile(r"(?<![0-9])[0-9]{1,2}(st|nd|rd|th)?(?![0-9])")


def correct_weekday(iso: str, ctx: EpisodeContext) -> str:
    """Fix a model-computed date when the episode names exactly one weekday and no day number.

    "for Wednesday's design review" said on Monday 2026-09-14 must be 2026-09-16 whatever the model
    computed; the date becomes the next such weekday on or after the episode's own date (or the one
    in the week after when the text says "next"). Dates with a spoken day number are left alone.
    """
    text = ctx.episode.text
    days = {m.group(1).lower() for m in _WEEKDAY_RE.finditer(text)}
    if len(days) != 1 or _ORDINAL_RE.search(text):
        return iso
    try:
        current = date.fromisoformat(iso)
    except ValueError:
        return iso
    target = _WEEKDAY_NAMES.index(days.pop().capitalize())
    if current.weekday() == target:
        return iso
    spoken_on = datetime.fromtimestamp(ctx.episode.t_occurred / 1000, tz=UTC).date() if ctx.episode.t_occurred else ctx.container_date
    delta = (target - spoken_on.weekday()) % 7
    if re.search(r"(?<![a-z])next(?![a-z])", text, re.IGNORECASE):
        delta += 7
    return (spoken_on + timedelta(days=delta)).isoformat()


def is_lead(ctx: EpisodeContext, speaker_id: str) -> bool:
    """Whether a participant chairs the team (role contains lead, editor, manager, head, chair)."""
    role = next((str(s.get("role") or "") for s in ctx.speakers if s.get("id") == speaker_id), "")
    return any(word in role.lower() for word in _LEAD_ROLES)


def postprocess_v2(extraction: EpisodeExtraction, ctx: EpisodeContext, version: str = "v2") -> EpisodeExtraction:
    """Controlled-vocabulary pass: closed predicates, canonical subjects, kind conventions, read-back filter.

    From v3 on, three schema rules are enforced as well: a commitment is a dated promise (``due``) or a
    completion (``status = completed``); in a meeting only the lead decides (a member's "decision" is a
    fact: a restated or proposed choice); the read-back filter compares kind as well.
    """
    v3 = version >= "v3"
    v4 = version >= "v4"
    stats = extraction.stats
    asked_why = any("why" in _mark_norm(prev.get("text")).split() for prev in ctx.context_before[-3:])

    def marker_of(kind: Any, subject: Any, predicate: Any, obj: Any) -> tuple[str, ...]:
        base = _item_marker(subject, predicate, obj)
        return (str(kind), *base) if v3 else base

    seen_before = {marker_of(i.get("kind"), i.get("subject"), i.get("predicate"), i.get("object")) for i in ctx.container_items}
    kept: list[ExtractedFact] = []
    keys: list[tuple[str, ...]] = []
    for item in extraction.items:
        predicate = canonicalize_predicate(item.predicate)
        if predicate is None:
            stats.dropped += 1
            stats.errors.append(f"predicate {item.predicate!r} outside the vocabulary")
            continue
        subject = canonicalize_subject(item.subject, ctx.tenant, ctx.known_entities, fuzzy=v3)
        obj = canonicalize_object(predicate, item.object, numbers=v4)
        if predicate == "due":
            iso = normalize_date(obj, ctx.container_date) or resolve_day_of_month(obj, ctx.container_date)
            if iso is None:
                stats.dropped += 1
                stats.errors.append(f"due without a date: {obj!r}")
                continue
            obj = correct_weekday(iso, ctx) if v4 else iso
        if v4 and predicate == "decided" and _mark_norm(obj).startswith("because") and not asked_why:
            stats.dropped += 1
            stats.errors.append("rationale without a why-question")
            continue
        kind = item.kind
        if predicate == "status" and obj.lower() == "completed":
            kind = "commitment"
        elif predicate == "lesson":
            kind = "decision"
        elif predicate == "customer":
            kind = "fact"
        if v3:
            if kind == "commitment" and predicate not in ("due", "status"):
                stats.dropped += 1
                stats.errors.append(f"commitment without a date or completion: {subject}|{predicate}")
                continue
            if kind == "commitment" and predicate == "status" and obj.lower() != "completed":
                stats.dropped += 1
                stats.errors.append(f"commitment status other than completed: {obj!r}")
                continue
            if kind == "decision" and ctx.source_kind != "email" and not is_lead(ctx, ctx.episode.speaker_id):
                kind = "fact"
        if version >= "v5" and predicate == "status" and obj.lower() == "completed":
            tracked = {_mark_norm(n) for n in known_subjects(ctx.tenant)} | {_mark_norm(n) for n in ctx.known_entities}
            tracked |= {_mark_norm(f.get("subject")) for f in [*ctx.prior_facts, *ctx.container_items]}
            if _mark_norm(subject) not in tracked:
                stats.dropped += 1
                stats.errors.append(f"completion of an untracked subject: {subject!r}")
                continue
        marker = marker_of(kind, subject, predicate, obj)
        if ctx.source_kind != "email" and marker in seen_before:
            stats.dropped += 1
            stats.errors.append(f"restatement of {subject}|{predicate}|{obj} from earlier in the meeting")
            continue
        if marker in keys:
            stats.dropped += 1
            continue
        keys.append(marker)
        update: dict[str, Any] = {"subject": subject, "predicate": predicate, "object": obj, "kind": kind}
        if predicate == "due":
            update["due_at"] = obj
        kept.append(item.model_copy(update=update))
    stats.kept = len(kept)
    return EpisodeExtraction(items=kept, entities=extraction.entities, stats=stats)


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


_SIGNAL_WORDS = frozenset({"done", "finished", "complete", "completed", "shipped", "decision", "decided", "deferred", "cut"})


def is_trivial_utterance(ctx: EpisodeContext, min_words: int = 6) -> bool:
    """Short meeting utterances with no digit and no completion/decision word ("Got it.", "Bye.").

    v2 skips the model call for them (about a fifth of all episodes; none of them carries a gold
    label, the shortest labelled episode has 9 words). Email messages are always sent to the model.
    """
    if ctx.source_kind == "email":
        return False
    words = _MARK_NON_WORD.sub(" ", ctx.episode.text.lower()).split()
    if len(words) >= min_words or any(ch.isdigit() for ch in ctx.episode.text):
        return False
    return not (_SIGNAL_WORDS & set(words))


_READBACK_CUES = ("read it back", "read that back", "let me recap", "to recap", "decisions since", "to summarise", "to summarize")


def is_readback(ctx: EpisodeContext) -> bool:
    """An end-of-meeting read-back or recap ("Let me read it back. Scope: ..."); v5 skips the model call.

    The owners' own statements earlier in the meeting carry the facts; a read-back only restates them,
    and its compressed phrasing ("Vendor: PayU replaces Razorpay. New customer: Kestrel") produced most
    of the spurious items in the v4 dev run. Emails are never skipped.
    """
    if ctx.source_kind == "email":
        return False
    text = " ".join(ctx.episode.text.lower().split())
    return any(cue in text for cue in _READBACK_CUES)


class LLMExtractor:
    """Extraction through the LLM client (temperature 0.1; the client retries once on bad JSON).

    ``version="v1"`` (default) is the original open-vocabulary prompt; ``version="v2"`` and later use
    the controlled vocabulary, the known-entity list, context lines and :func:`postprocess_v2`.
    """

    def __init__(
        self,
        llm: LLMProtocol,
        *,
        prompt_name: str | None = None,
        email_prompt_name: str | None = None,
        temperature: float = 0.1,
        version: str = "v1",
    ) -> None:
        self.llm = llm
        self.version = version
        self.prompt_name = prompt_name or f"extract_{version}"
        self.email_prompt_name = email_prompt_name or f"extract_email_{version}"
        self.temperature = temperature

    def extract(self, ctx: EpisodeContext) -> EpisodeExtraction:
        if self.version != "v1" and is_trivial_utterance(ctx):
            return EpisodeExtraction()
        if self.version >= "v5" and is_readback(ctx):
            return EpisodeExtraction(stats=ExtractionStats(errors=[f"{ctx.episode.id}: read-back skipped"]))
        system = load_prompt(self.email_prompt_name if ctx.source_kind == "email" else self.prompt_name)
        user = build_user_prompt(ctx) if self.version == "v1" else build_user_prompt_v2(ctx)
        try:
            raw = self.llm.complete_json(system, user, RawExtraction, temperature=self.temperature)
        except RuntimeError as exc:  # LLMFormatError after the retry, or a transport failure
            log.error("extraction failed for %s: %s", ctx.episode.id, exc)
            return EpisodeExtraction(stats=ExtractionStats(errors=[f"{ctx.episode.id}: {exc}"], failed=True))
        result = coerce_extraction(raw, ctx)
        if self.version != "v1":
            result = postprocess_v2(result, ctx, self.version)
        return result


#: The prompt version the seed (``--extract real``) and the eval use by default.
CURRENT_VERSION = "v5"


def make_extractor(llm: LLMProtocol, version: str | None = None) -> LLMExtractor:
    """The production extractor for a prompt version (``v1`` keeps the original behaviour)."""
    return LLMExtractor(llm, version=version or CURRENT_VERSION)


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
