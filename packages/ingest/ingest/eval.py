"""Extraction eval: precision and recall against ``data/gold/<slug>.json``.

Strict matching rule (docs/contracts/recorder-format.md): ``kind`` equal, speaker equal, normalized
``subject`` and ``predicate`` equal (case-insensitive, punctuation stripped), ``object`` equal after
the pipeline's own object canonicalisation (:func:`ingest.vocab.canonicalize_object`: number words to
digits, completion words, articles) and date normalization. Both sides are normalised the same way,
so gold "three cards" matches extracted "3 cards".

``--partial`` adds a secondary, partial-credit view: an extracted item gets credit when it sits in the
same episode as a gold item, has the same canonical subject, an equivalent predicate
(``{decided, status}``, ``{requires, uses_pattern, scope_includes}``) and an object with token-F1 >= 0.5
(dates must be equal); plus slot-wise precision and recall per field. ``--rescore <json>`` re-scores an
earlier run's saved items offline with the current matcher (no model calls).

Run ``python -m ingest.eval --help`` for the CLI.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .chunker import chunk, episode_id
from .dates import DEFAULT_DAYFIRST, normalize_date
from .extract import CURRENT_VERSION, EpisodeContext, Extractor, GoldExtractor, LLMExtractor, plan_windows, select_prior_facts
from .gold import GoldFile, GoldItem, find_gold
from .models import ExtractedFact
from .recorder_format import load_export
from .vocab import FEWSHOT_SOURCE, canonicalize_object, canonicalize_predicate, canonicalize_subject, tenant_of

log = logging.getLogger(__name__)

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Predicates the gold uses interchangeably for the same kind of statement (partial credit only).
PREDICATE_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"decided", "status"}),
    frozenset({"requires", "uses_pattern", "scope_includes"}),
)
SLOTS = ("kind", "speaker_id", "subject", "predicate", "object")


def normalize_text(value: Any) -> str:
    """Lowercase, underscores to spaces, punctuation stripped, single spaces."""
    text = str(value or "").lower().replace("_", " ")
    return _SPACES.sub(" ", _PUNCT.sub(" ", text)).strip()


def normalize_object(value: Any, reference: date | None = None, predicate: str | None = None, *, dayfirst: bool = DEFAULT_DAYFIRST) -> str:
    """Pipeline canonicalisation first (when ``predicate`` is known), then dates become ISO, else text."""
    text = str(value) if value is not None else ""
    if predicate:
        text = canonicalize_object(canonicalize_predicate(predicate) or normalize_text(predicate).replace(" ", "_"), text, numbers=True)
    iso = normalize_date(text or None, reference, dayfirst=dayfirst)
    return iso or normalize_text(text)


def items_match(extracted: dict[str, Any], gold: GoldItem, reference: date | None = None) -> bool:
    """The contract's strict matching rule for one extracted/gold pair."""
    return (
        str(extracted.get("kind", "")).lower() == gold.kind
        and str(extracted.get("speaker_id", "")) == gold.speaker_id
        and normalize_text(extracted.get("subject")) == normalize_text(gold.subject)
        and normalize_text(extracted.get("predicate")) == normalize_text(gold.predicate)
        and normalize_object(extracted.get("object"), reference, str(extracted.get("predicate") or ""))
        == normalize_object(gold.object, reference, gold.predicate)
    )


def predicates_equivalent(a: str, b: str) -> bool:
    """Equal predicates, or both in one :data:`PREDICATE_GROUPS` group."""
    pa, pb = normalize_text(a).replace(" ", "_"), normalize_text(b).replace(" ", "_")
    if pa == pb:
        return True
    return any(pa in group and pb in group for group in PREDICATE_GROUPS)


def token_f1(a: str, b: str) -> float:
    """Token-level F1 between two normalised strings (bag of words)."""
    ta, tb = a.split(), b.split()
    if not ta or not tb:
        return 1.0 if ta == tb else 0.0
    common = 0
    pool = list(tb)
    for tok in ta:
        if tok in pool:
            pool.remove(tok)
            common += 1
    if common == 0:
        return 0.0
    p, r = common / len(ta), common / len(tb)
    return 2 * p * r / (p + r)


def canonical_subject_text(subject: Any, tenant: str) -> str:
    return normalize_text(canonicalize_subject(str(subject or ""), tenant, fuzzy=True))


def partial_match(
    extracted: dict[str, Any],
    gold: GoldItem,
    gold_episode: str | None,
    tenant: str,
    reference: date | None = None,
) -> bool:
    """Same episode, same canonical subject, equivalent predicate, object token-F1 >= 0.5 (dates equal)."""
    if gold_episode is not None and extracted.get("episode_id") and str(extracted["episode_id"]) != gold_episode:
        return False
    if canonical_subject_text(extracted.get("subject"), tenant) != canonical_subject_text(gold.subject, tenant):
        return False
    if not predicates_equivalent(str(extracted.get("predicate") or ""), gold.predicate):
        return False
    a = normalize_object(extracted.get("object"), reference, str(extracted.get("predicate") or ""))
    b = normalize_object(gold.object, reference, gold.predicate)
    if _ISO.match(a) or _ISO.match(b):
        return a == b
    return token_f1(a, b) >= 0.5


@dataclass
class SlotScore:
    """Slot-wise agreement for one field: how often the extracted value appears in the episode's gold."""

    hits: int = 0
    extracted: int = 0
    gold: int = 0

    @property
    def precision(self) -> float:
        return self.hits / self.extracted if self.extracted else 0.0

    @property
    def recall(self) -> float:
        return self.hits / self.gold if self.gold else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"hits": self.hits, "extracted": self.extracted, "gold": self.gold, "precision": round(self.precision, 3), "recall": round(self.recall, 3)}


@dataclass
class EvalResult:
    """Scores for one meeting or thread (strict, plus partial credit when computed)."""

    slug: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    proposed: int = 0
    dropped: int = 0
    errors: int = 0
    calls: int = 0
    matched: list[dict[str, Any]] = field(default_factory=list)
    missed: list[dict[str, Any]] = field(default_factory=list)
    spurious: list[dict[str, Any]] = field(default_factory=list)
    partial_tp: int | None = None
    partial_fp: int | None = None
    partial_fn: int | None = None
    slots: dict[str, SlotScore] = field(default_factory=dict)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def partial_precision(self) -> float:
        tp, fp = self.partial_tp or 0, self.partial_fp or 0
        return tp / (tp + fp) if (tp + fp) else 0.0

    @property
    def partial_recall(self) -> float:
        tp, fn = self.partial_tp or 0, self.partial_fn or 0
        return tp / (tp + fn) if (tp + fn) else 0.0

    @property
    def partial_f1(self) -> float:
        p, r = self.partial_precision, self.partial_recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "slug": self.slug,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "proposed": self.proposed,
            "dropped": self.dropped,
            "errors": self.errors,
            "calls": self.calls,
            "matched": self.matched,
            "missed": self.missed,
            "spurious": self.spurious,
        }
        if self.partial_tp is not None:
            data["partial"] = {
                "tp": self.partial_tp,
                "fp": self.partial_fp,
                "fn": self.partial_fn,
                "precision": round(self.partial_precision, 3),
                "recall": round(self.partial_recall, 3),
                "f1": round(self.partial_f1, 3),
                "slots": {name: score.as_dict() for name, score in self.slots.items()},
            }
        return data


def evaluate(
    extracted: list[dict[str, Any]],
    gold: list[GoldItem],
    reference: date | None = None,
    slug: str = "",
) -> EvalResult:
    """Greedy one-to-one strict matching of extracted items against gold items."""
    result = EvalResult(slug=slug)
    unmatched = list(range(len(gold)))
    for item in extracted:
        hit = next((i for i in unmatched if items_match(item, gold[i], reference)), None)
        if hit is None:
            result.fp += 1
            result.spurious.append(item)
        else:
            unmatched.remove(hit)
            result.tp += 1
            result.matched.append(item)
    for i in unmatched:
        result.fn += 1
        result.missed.append(gold[i].model_dump())
    return result


def _slot_value(row: dict[str, Any], slot: str, tenant: str, reference: date | None) -> str:
    if slot == "subject":
        return canonical_subject_text(row.get("subject"), tenant)
    if slot == "object":
        return normalize_object(row.get("object"), reference, str(row.get("predicate") or ""))
    if slot == "predicate":
        return normalize_text(canonicalize_predicate(str(row.get("predicate") or "")) or row.get("predicate"))
    return normalize_text(row.get(slot))


def evaluate_partial(
    result: EvalResult,
    extracted: list[dict[str, Any]],
    gold: list[GoldItem],
    gold_episodes: list[str | None],
    tenant: str,
    reference: date | None = None,
) -> EvalResult:
    """Add partial-credit triple counts and slot-wise P/R to ``result`` (greedy one-to-one)."""
    unmatched = list(range(len(gold)))
    tp = fp = 0
    for item in extracted:
        hit = next((i for i in unmatched if partial_match(item, gold[i], gold_episodes[i], tenant, reference)), None)
        if hit is None:
            fp += 1
        else:
            unmatched.remove(hit)
            tp += 1
    result.partial_tp, result.partial_fp, result.partial_fn = tp, fp, len(unmatched)

    gold_rows = [{**g.model_dump(), "episode_id": ep} for g, ep in zip(gold, gold_episodes)]
    for slot in SLOTS:
        score = SlotScore(extracted=len(extracted), gold=len(gold))
        free = list(range(len(gold_rows)))
        for item in extracted:
            value = _slot_value(item, slot, tenant, reference)
            episode = str(item.get("episode_id") or "")
            hit = next(
                (
                    i
                    for i in free
                    if (gold_rows[i]["episode_id"] is None or not episode or gold_rows[i]["episode_id"] == episode)
                    and _slot_value(gold_rows[i], slot, tenant, reference) == value
                ),
                None,
            )
            if hit is not None:
                free.remove(hit)
                score.hits += 1
        result.slots[slot] = score
    return result


def fact_to_row(item: ExtractedFact) -> dict[str, Any]:
    """Flatten an :class:`ExtractedFact` into the dict shape :func:`items_match` expects."""
    return {
        "kind": item.kind,
        "subject": item.subject,
        "predicate": item.predicate,
        "object": item.object,
        "speaker_id": item.speaker,
        "text": item.text,
        "episode_id": item.episode_id,
    }


def _extract_all(
    episodes: list[Any],
    source_title: str,
    day: date,
    speakers: list[dict[str, Any]],
    extractor: Extractor,
    result: EvalResult,
    tenant: str = "",
    window_episodes: int | None = None,
) -> list[dict[str, Any]]:
    """Run the extractor over the episodes the way the pipeline does (dialogue windows included)."""
    extracted: list[dict[str, Any]] = []
    prior: list[dict[str, Any]] = []
    context: list[dict[str, Any]] = []
    size = window_episodes if window_episodes is not None else int(getattr(extractor, "window_episodes", 1) or 1)
    supports_windows = callable(getattr(extractor, "extract_window", None))
    for window in plan_windows(episodes, size if supports_windows else 1):
        ctxs = [
            EpisodeContext(
                episode=episode,
                container_title=source_title,
                container_date=day,
                speakers=speakers,
                prior_facts=select_prior_facts(prior, episode.text),
                source_kind=episode.source_kind,
                tenant=tenant,
                context_before=list(context),
                container_items=list(prior),
            )
            for episode in window
        ]
        if len(ctxs) > 1 and supports_windows:
            results = extractor.extract_window(ctxs)  # type: ignore[attr-defined]
        else:
            results = [extractor.extract(ctxs[0])]
        result.calls += 1
        for ctx, res in zip(ctxs, results):
            episode = ctx.episode
            result.proposed += res.stats.proposed
            result.dropped += res.stats.dropped
            result.errors += int(res.stats.failed)
            for item in res.items:
                row = fact_to_row(item)
                extracted.append(row)
                prior.append({**row, "id": f"eval_{len(prior)}", "valid_from": episode.t_occurred})
            context.append({"speaker": episode.speaker_id, "text": episode.text})
    return extracted


def gold_episode_ids(gold: GoldFile, episodes: list[Any], kind: str, container_id: str) -> list[str | None]:
    """The episode id each gold item falls into (segment index -> chunked episode; message index -> seq)."""
    out: list[str | None] = []
    by_segment: dict[int, str] = {}
    for ep in episodes:
        for index in ep.segment_indices:
            by_segment[index] = ep.id
    for item in gold.items:
        if kind == "thread":
            out.append(episode_id(container_id, item.message_index) if item.message_index is not None else None)
        else:
            out.append(by_segment.get(item.segment_index) if item.segment_index is not None else None)
    return out


def run_meeting_eval(
    path: Path,
    gold: GoldFile,
    extractor: Extractor,
    *,
    min_seconds: int = 30,
    max_seconds: int = 60,
    partial: bool = False,
    window_episodes: int | None = None,
) -> EvalResult:
    """Extract one meeting file without a database and score it against ``gold``."""
    export = load_export(path)
    episodes = chunk(export, min_seconds=min_seconds, max_seconds=max_seconds)
    result = EvalResult(slug=path.stem)
    tenant = tenant_of(path.stem)
    extracted = _extract_all(
        episodes,
        export.meeting.title,
        export.meeting.started_at.date(),
        [s.model_dump() for s in export.speakers],
        extractor,
        result,
        tenant,
        window_episodes,
    )
    day = export.meeting.started_at.date()
    scored = evaluate(extracted, gold.items, day, slug=path.stem)
    scored.proposed, scored.dropped, scored.errors, scored.calls = result.proposed, result.dropped, result.errors, result.calls
    if partial:
        evaluate_partial(scored, extracted, gold.items, gold_episode_ids(gold, episodes, "meeting", export.meeting.id), tenant, day)
    return scored


def run_thread_eval(
    path: Path,
    gold: GoldFile,
    extractor: Extractor,
    roster: list[dict[str, Any]] | None = None,
    *,
    partial: bool = False,
    window_episodes: int | None = None,
) -> EvalResult:
    """Extract one email thread file without a database and score it against ``gold``."""
    from .email_format import load_thread, thread_episodes

    thread = load_thread(path)
    people = thread.resolve_people(roster)
    episodes = thread_episodes(thread, people)
    result = EvalResult(slug=path.stem)
    tenant = tenant_of(path.stem)
    extracted = _extract_all(
        episodes,
        thread.thread.subject,
        thread.thread.started_at.date(),
        [{"id": p["id"], "name": p["name"], "role": p.get("role")} for p in people.values()],
        extractor,
        result,
        tenant,
        window_episodes,
    )
    day = thread.thread.started_at.date()
    scored = evaluate(extracted, gold.items, day, slug=path.stem)
    scored.proposed, scored.dropped, scored.errors, scored.calls = result.proposed, result.dropped, result.errors, result.calls
    if partial:
        evaluate_partial(scored, extracted, gold.items, gold_episode_ids(gold, episodes, "thread", thread.thread.id), tenant, day)
    return scored


def rescore_saved(saved: dict[str, Any], meetings_dir: Path, gold_dir: Path, *, partial: bool = True) -> list[EvalResult]:
    """Re-score an earlier ``--out`` JSON with the current matcher, offline (no model calls).

    The saved ``matched`` and ``spurious`` rows are the extracted items; gold comes from ``gold_dir``;
    the meeting files are chunked again only to map gold indices onto episode ids.
    """
    results: list[EvalResult] = []
    for entry in saved.get("results", []):
        slug = str(entry.get("slug") or "")
        extracted = [*entry.get("matched", []), *entry.get("spurious", [])]
        path = meetings_dir / f"{slug}.json"
        source = peek_source(path) if path.is_file() else None
        gold = find_gold(gold_dir, slug=slug, container_id=source[1] if source else None)
        if gold is None or source is None:
            log.warning("rescore: no gold or source file for %s; skipped", slug)
            continue
        kind, container_id = source
        tenant = tenant_of(slug)
        if kind == "thread":
            from .email_format import load_thread, thread_episodes

            thread = load_thread(path)
            episodes = thread_episodes(thread, thread.resolve_people(load_roster(meetings_dir, slug)))
            day = thread.thread.started_at.date()
        else:
            export = load_export(path)
            episodes = chunk(export)
            day = export.meeting.started_at.date()
        scored = evaluate(extracted, gold.items, day, slug=slug)
        scored.proposed, scored.dropped, scored.errors = int(entry.get("proposed") or 0), int(entry.get("dropped") or 0), int(entry.get("errors") or 0)
        if partial:
            evaluate_partial(scored, extracted, gold.items, gold_episode_ids(gold, episodes, kind, container_id or ""), tenant, day)
        results.append(scored)
    return results


def peek_source(path: Path) -> tuple[str, str | None] | None:
    """(kind, container id) for a data file by its top-level key: ``meeting`` or ``thread``.

    Returns None for anything else (rosters, gold files, unrelated JSON).
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("meeting", "thread"):
        inner = data.get(key)
        if isinstance(inner, dict):
            return key, (str(inner["id"]) if inner.get("id") else None)
    return None


def discover(meetings_dir: Path, gold_dir: Path) -> list[tuple[Path, GoldFile, str]]:
    """Pair every meeting/thread JSON with its gold file. Returns (path, gold, kind)."""
    pairs: list[tuple[Path, GoldFile, str]] = []
    if not meetings_dir.is_dir():
        return pairs
    for path in sorted(meetings_dir.glob("*.json")):
        source = peek_source(path)
        if source is None:
            continue
        kind, container_id = source
        gold = find_gold(gold_dir, slug=path.stem, container_id=container_id)
        if gold is None:
            log.info("no gold file for %s; skipped", path.name)
            continue
        pairs.append((path, gold, kind))
    return pairs


def load_roster(meetings_dir: Path, slug: str) -> list[dict[str, Any]] | None:
    """``data/meetings/<tenant>_roster.json`` for the tenant prefix of ``slug``."""
    tenant = slug.split("_", 1)[0]
    roster_path = meetings_dir / f"{tenant}_roster.json"
    if roster_path.is_file():
        return json.loads(roster_path.read_text(encoding="utf-8"))
    return None


def format_table(results: list[EvalResult]) -> str:
    """Fixed-width strict table with a micro-averaged total row."""
    header = f"{'slug':<28}{'gold':>6}{'extr':>6}{'tp':>5}{'fp':>5}{'fn':>5}{'P':>8}{'R':>8}{'F1':>8}{'drop':>7}"
    lines = [header, "-" * len(header)]
    tp = fp = fn = proposed = dropped = 0
    for r in results:
        lines.append(
            f"{r.slug:<28}{r.tp + r.fn:>6}{r.tp + r.fp:>6}{r.tp:>5}{r.fp:>5}{r.fn:>5}"
            f"{r.precision:>8.2f}{r.recall:>8.2f}{r.f1:>8.2f}{r.dropped:>7}"
        )
        tp, fp, fn = tp + r.tp, fp + r.fp, fn + r.fn
        proposed, dropped = proposed + r.proposed, dropped + r.dropped
    total = EvalResult(slug="TOTAL", tp=tp, fp=fp, fn=fn, proposed=proposed, dropped=dropped)
    lines.append("-" * len(header))
    lines.append(
        f"{'TOTAL':<28}{tp + fn:>6}{tp + fp:>6}{tp:>5}{fp:>5}{fn:>5}"
        f"{total.precision:>8.2f}{total.recall:>8.2f}{total.f1:>8.2f}{dropped:>7}"
    )
    return "\n".join(lines)


def format_partial_table(results: list[EvalResult]) -> str:
    """Partial-credit table (same episode, canonical subject, predicate group, object token-F1 >= 0.5) and slot-wise P/R."""
    rows = [r for r in results if r.partial_tp is not None]
    header = f"{'slug':<28}{'gold':>6}{'extr':>6}{'ptp':>5}{'pfp':>5}{'pfn':>5}{'P':>8}{'R':>8}{'F1':>8}"
    lines = ["Partial credit:", header, "-" * len(header)]
    tp = fp = fn = 0
    slots: dict[str, SlotScore] = {slot: SlotScore() for slot in SLOTS}
    for r in rows:
        ptp, pfp, pfn = r.partial_tp or 0, r.partial_fp or 0, r.partial_fn or 0
        lines.append(f"{r.slug:<28}{ptp + pfn:>6}{ptp + pfp:>6}{ptp:>5}{pfp:>5}{pfn:>5}{r.partial_precision:>8.2f}{r.partial_recall:>8.2f}{r.partial_f1:>8.2f}")
        tp, fp, fn = tp + ptp, fp + pfp, fn + pfn
        for slot, score in r.slots.items():
            slots[slot].hits += score.hits
            slots[slot].extracted += score.extracted
            slots[slot].gold += score.gold
    total = EvalResult(slug="TOTAL", partial_tp=tp, partial_fp=fp, partial_fn=fn)
    lines.append("-" * len(header))
    lines.append(f"{'TOTAL':<28}{tp + fn:>6}{tp + fp:>6}{tp:>5}{fp:>5}{fn:>5}{total.partial_precision:>8.2f}{total.partial_recall:>8.2f}{total.partial_f1:>8.2f}")
    lines.append("")
    lines.append(f"{'slot':<14}{'hits':>6}{'extr':>6}{'gold':>6}{'P':>8}{'R':>8}")
    for slot, score in slots.items():
        lines.append(f"{slot:<14}{score.hits:>6}{score.extracted:>6}{score.gold:>6}{score.precision:>8.2f}{score.recall:>8.2f}")
    return "\n".join(lines)


def load_llm_factory(spec: str) -> Any:
    """Import ``module:callable`` and call it to obtain an LLM client."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError("--llm-factory must look like package.module:callable")
    sys.path.insert(0, str(Path.cwd()))
    module = importlib.import_module(module_name)
    return getattr(module, attr)()


def _split(values: list[str] | None) -> list[str]:
    return [v.strip() for chunk in values or [] for v in chunk.split(",") if v.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score extraction against gold labels.")
    parser.add_argument("--meetings", default="data/meetings", help="directory with meeting/thread JSON files")
    parser.add_argument("--gold", default="data/gold", help="directory with gold label files")
    parser.add_argument("--backend", default=os.environ.get("LLM_BACKEND", "fake"), help="fake | gemini | ollama (built in) | anything --llm-factory supports")
    parser.add_argument("--model", default=None, help="model id for the backend (default: LLM_MODEL, or gemma4:e4b for ollama)")
    parser.add_argument("--llm-factory", default=None, help="module:callable returning an LLM (e.g. apps.api.llm:llm_from_env); default: built-in client")
    parser.add_argument("--prompt-version", default=CURRENT_VERSION, help="extraction prompt version: v1, v2, v3 ... (prompts/extract_<v>.md)")
    parser.add_argument("--window", type=int, default=None, help="dialogue window size (episodes per model call); default: the extractor's (3 for v2+, 1 for gold)")
    parser.add_argument("--files", action="append", default=None, help="only these slugs (comma-separated, repeatable)")
    parser.add_argument("--only", default=None, help="only this slug (same as --files with one slug)")
    parser.add_argument("--exclude", action="append", default=None, help="slugs to leave out (comma-separated, repeatable)")
    parser.add_argument("--include-fewshot-source", action="store_true", help=f"also score {FEWSHOT_SOURCE}, the source of the v2+ few-shot examples")
    parser.add_argument("--limit", type=int, default=None, help="stop after N files")
    parser.add_argument("--rpm", type=float, default=None, help="per-key request budget for the gemini client (default LLM_RPM or 15)")
    parser.add_argument("--tpm", type=float, default=None, help="per-key input-token budget per minute (default LLM_TPM or 15000; 0 disables)")
    parser.add_argument("--partial", action="store_true", help="also report partial-credit triples and slot-wise P/R")
    parser.add_argument("--rescore", default=None, help="re-score a saved --out JSON offline with the current matcher (no model calls)")
    parser.add_argument("--show-misses", action="store_true", help="print missed and spurious items")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--out", default=None, help="also write the full JSON results (matched, missed, spurious) to this path")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "google_genai", "google_genai.models"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    meetings_dir, gold_dir = Path(args.meetings), Path(args.gold)
    llm = None
    results: list[EvalResult] = []
    if args.rescore:
        saved = json.loads(Path(args.rescore).read_text(encoding="utf-8"))
        results = rescore_saved(saved, meetings_dir, gold_dir, partial=True)
        if not results:
            print(f"nothing to rescore in {args.rescore}", file=sys.stderr)
            return 1
        print(f"rescored {args.rescore}: backend={saved.get('backend')} model={saved.get('model')} prompt={saved.get('prompt_version')} files={len(results)}")
        args.partial = True
    else:
        pairs = discover(meetings_dir, gold_dir)
        wanted = set(_split(args.files)) | ({args.only} if args.only else set())
        if wanted:
            pairs = [p for p in pairs if p[0].stem in wanted]
        excluded = set(_split(args.exclude))
        uses_fewshot = args.backend != "fake" and args.prompt_version != "v1"
        if uses_fewshot and not args.include_fewshot_source:
            excluded.add(FEWSHOT_SOURCE)
        if excluded:
            pairs = [p for p in pairs if p[0].stem not in excluded]
        if args.limit:
            pairs = pairs[: args.limit]
        if not pairs:
            print(f"no (meeting, gold) pairs found under {meetings_dir} / {gold_dir}", file=sys.stderr)
            return 1

        if args.backend != "fake":
            if args.llm_factory:
                os.environ["LLM_BACKEND"] = args.backend
                if args.model:
                    os.environ["LLM_MODEL"] = args.model
                llm = load_llm_factory(args.llm_factory)
            else:
                from .llm_client import make_llm

                llm = make_llm(args.backend, args.model, rpm=args.rpm, tpm=args.tpm)
            print(f"backend={args.backend} model={getattr(llm, 'model', '?')} prompt={args.prompt_version} files={len(pairs)}"
                  + (f" (excluded: {', '.join(sorted(excluded))})" if excluded else ""))
        else:
            print("backend=fake: replaying gold labels through the pipeline (measures plumbing, not the model)")

        for path, gold, kind in pairs:
            extractor: Extractor = LLMExtractor(llm, version=args.prompt_version) if llm is not None else GoldExtractor(gold)
            if kind == "thread":
                results.append(run_thread_eval(path, gold, extractor, load_roster(meetings_dir, path.stem), partial=args.partial, window_episodes=args.window))
            else:
                results.append(run_meeting_eval(path, gold, extractor, partial=args.partial, window_episodes=args.window))
            if llm is not None:
                r = results[-1]
                log.info("%s: P=%.2f R=%.2f F1=%.2f (tp=%d fp=%d fn=%d errors=%d calls=%d)", r.slug, r.precision, r.recall, r.f1, r.tp, r.fp, r.fn, r.errors, r.calls)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "backend": args.backend if not args.rescore else "rescore",
            "model": getattr(llm, "model", "fake"),
            "prompt_version": args.prompt_version,
            "results": [r.as_dict() for r in results],
            "client": getattr(getattr(llm, "stats", None), "summary", lambda: "")(),
        }
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    if args.json:
        print(json.dumps([r.as_dict() for r in results], indent=2, default=str))
    else:
        print(format_table(results))
        if args.partial:
            print()
            print(format_partial_table(results))
        if args.show_misses:
            for r in results:
                for miss in r.missed:
                    print(f"MISSED   {r.slug}: [{miss.get('segment_index') if miss.get('segment_index') is not None else miss.get('message_index')}] {miss['kind']} {miss['speaker_id']} | {miss['subject']} | {miss['predicate']} | {miss['object']}")
                for extra in r.spurious:
                    print(f"SPURIOUS {r.slug}: {extra.get('episode_id', '')[-3:]} {extra['kind']} {extra['speaker_id']} | {extra['subject']} | {extra['predicate']} | {extra['object']}")
    stats = getattr(llm, "stats", None)
    if stats is not None and hasattr(stats, "summary"):
        print(f"client: {stats.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
