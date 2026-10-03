"""Extraction eval: precision and recall against ``data/gold/<slug>.json``.

Matching rule (docs/contracts/recorder-format.md): ``kind`` equal, speaker equal, normalized
``subject`` and ``predicate`` equal (case-insensitive, punctuation stripped), ``object`` equal
after date normalization. Run ``python -m ingest.eval --help`` for the CLI.
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

from .chunker import chunk
from .dates import normalize_date
from .extract import EpisodeContext, Extractor, GoldExtractor, LLMExtractor, select_prior_facts
from .gold import GoldFile, GoldItem, find_gold
from .models import ExtractedFact
from .recorder_format import load_export

log = logging.getLogger(__name__)

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def normalize_text(value: Any) -> str:
    """Lowercase, underscores to spaces, punctuation stripped, single spaces."""
    text = str(value or "").lower().replace("_", " ")
    return _SPACES.sub(" ", _PUNCT.sub(" ", text)).strip()


def normalize_object(value: Any, reference: date | None = None) -> str:
    """Dates become ISO; everything else goes through :func:`normalize_text`."""
    iso = normalize_date(str(value) if value is not None else None, reference)
    return iso or normalize_text(value)


def items_match(extracted: dict[str, Any], gold: GoldItem, reference: date | None = None) -> bool:
    """The contract's matching rule for one extracted/gold pair."""
    return (
        str(extracted.get("kind", "")).lower() == gold.kind
        and str(extracted.get("speaker_id", "")) == gold.speaker_id
        and normalize_text(extracted.get("subject")) == normalize_text(gold.subject)
        and normalize_text(extracted.get("predicate")) == normalize_text(gold.predicate)
        and normalize_object(extracted.get("object"), reference) == normalize_object(gold.object, reference)
    )


@dataclass
class EvalResult:
    """Scores for one meeting or thread."""

    slug: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    proposed: int = 0
    dropped: int = 0
    matched: list[dict[str, Any]] = field(default_factory=list)
    missed: list[dict[str, Any]] = field(default_factory=list)
    spurious: list[dict[str, Any]] = field(default_factory=list)

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

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "proposed": self.proposed,
            "dropped": self.dropped,
            "missed": self.missed,
            "spurious": self.spurious,
        }


def evaluate(
    extracted: list[dict[str, Any]],
    gold: list[GoldItem],
    reference: date | None = None,
    slug: str = "",
) -> EvalResult:
    """Greedy one-to-one matching of extracted items against gold items."""
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


def _extract_all(episodes: list[Any], source_title: str, day: date, speakers: list[dict[str, Any]], extractor: Extractor, result: EvalResult) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    prior: list[dict[str, Any]] = []
    for episode in episodes:
        ctx = EpisodeContext(
            episode=episode,
            container_title=source_title,
            container_date=day,
            speakers=speakers,
            prior_facts=select_prior_facts(prior, episode.text),
            source_kind=episode.source_kind,
        )
        res = extractor.extract(ctx)
        result.proposed += res.stats.proposed
        result.dropped += res.stats.dropped
        for item in res.items:
            row = fact_to_row(item)
            extracted.append(row)
            prior.append({**row, "id": f"eval_{len(prior)}", "valid_from": episode.t_occurred})
    return extracted


def run_meeting_eval(path: Path, gold: GoldFile, extractor: Extractor, *, min_seconds: int = 30, max_seconds: int = 60) -> EvalResult:
    """Extract one meeting file without a database and score it against ``gold``."""
    export = load_export(path)
    episodes = chunk(export, min_seconds=min_seconds, max_seconds=max_seconds)
    result = EvalResult(slug=path.stem)
    extracted = _extract_all(
        episodes,
        export.meeting.title,
        export.meeting.started_at.date(),
        [s.model_dump() for s in export.speakers],
        extractor,
        result,
    )
    scored = evaluate(extracted, gold.items, export.meeting.started_at.date(), slug=path.stem)
    scored.proposed, scored.dropped = result.proposed, result.dropped
    return scored


def run_thread_eval(path: Path, gold: GoldFile, extractor: Extractor, roster: list[dict[str, Any]] | None = None) -> EvalResult:
    """Extract one email thread file without a database and score it against ``gold``."""
    from .email_format import load_thread, thread_episodes

    thread = load_thread(path)
    people = thread.resolve_people(roster)
    episodes = thread_episodes(thread, people)
    result = EvalResult(slug=path.stem)
    extracted = _extract_all(
        episodes,
        thread.thread.subject,
        thread.thread.started_at.date(),
        [{"id": p["id"], "name": p["name"], "role": p.get("role")} for p in people.values()],
        extractor,
        result,
    )
    scored = evaluate(extracted, gold.items, thread.thread.started_at.date(), slug=path.stem)
    scored.proposed, scored.dropped = result.proposed, result.dropped
    return scored


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
    """Fixed-width table with a micro-averaged total row."""
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


def load_llm_factory(spec: str) -> Any:
    """Import ``module:callable`` and call it to obtain an LLM client."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError("--llm-factory must look like package.module:callable")
    sys.path.insert(0, str(Path.cwd()))
    module = importlib.import_module(module_name)
    return getattr(module, attr)()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score extraction against gold labels.")
    parser.add_argument("--meetings", default="data/meetings", help="directory with meeting/thread JSON files")
    parser.add_argument("--gold", default="data/gold", help="directory with gold label files")
    parser.add_argument("--backend", default=os.environ.get("LLM_BACKEND", "fake"), help="fake | ollama | gemini | openrouter")
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL"), help="model id for the backend")
    parser.add_argument("--llm-factory", default="apps.api.llm:llm_from_env", help="module:callable returning an LLM")
    parser.add_argument("--only", default=None, help="only this slug")
    parser.add_argument("--limit", type=int, default=None, help="stop after N files")
    parser.add_argument("--show-misses", action="store_true", help="print missed and spurious items")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    meetings_dir, gold_dir = Path(args.meetings), Path(args.gold)
    pairs = discover(meetings_dir, gold_dir)
    if args.only:
        pairs = [p for p in pairs if p[0].stem == args.only]
    if args.limit:
        pairs = pairs[: args.limit]
    if not pairs:
        print(f"no (meeting, gold) pairs found under {meetings_dir} / {gold_dir}", file=sys.stderr)
        return 1

    llm = None
    if args.backend != "fake":
        os.environ["LLM_BACKEND"] = args.backend
        if args.model:
            os.environ["LLM_MODEL"] = args.model
        llm = load_llm_factory(args.llm_factory)
    else:
        print("backend=fake: replaying gold labels through the pipeline (measures plumbing, not the model)")

    results: list[EvalResult] = []
    for path, gold, kind in pairs:
        extractor: Extractor = LLMExtractor(llm) if llm is not None else GoldExtractor(gold)
        if kind == "thread":
            results.append(run_thread_eval(path, gold, extractor, load_roster(meetings_dir, path.stem)))
        else:
            results.append(run_meeting_eval(path, gold, extractor))

    if args.json:
        print(json.dumps([r.as_dict() for r in results], indent=2))
    else:
        print(format_table(results))
        if args.show_misses:
            for r in results:
                for miss in r.missed:
                    print(f"MISSED   {r.slug}: {miss}")
                for extra in r.spurious:
                    print(f"SPURIOUS {r.slug}: {extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
