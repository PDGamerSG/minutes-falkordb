"""Gold labels (``data/gold/<slug>.json``) and helpers to replay them as extraction output."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .chunker import Episode
from .models import ExtractedFact, Kind, fact_key

log = logging.getLogger(__name__)


class GoldItem(BaseModel):
    """One hand-labelled statement. ``segment_index`` for meetings, ``message_index`` for threads."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    kind: Kind
    subject: str
    predicate: str
    object: str
    speaker_id: str
    segment_index: int | None = None
    message_index: int | None = None
    supersedes: dict[str, Any] | None = None
    follows_precedent: dict[str, Any] | None = None
    confirms: dict[str, Any] | None = None
    text: str | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, value: Any) -> str:
        return str(value).strip().lower()

    @property
    def index(self) -> int | None:
        return self.segment_index if self.segment_index is not None else self.message_index

    def as_text(self) -> str:
        return self.text or f"{self.subject} {self.predicate.replace('_', ' ')} {self.object}"


class GoldFile(BaseModel):
    """A gold label file for one meeting or one email thread."""

    model_config = ConfigDict(extra="ignore")

    meeting_id: str | None = None
    thread_id: str | None = None
    items: list[GoldItem] = Field(default_factory=list)

    @property
    def container_id(self) -> str | None:
        return self.meeting_id or self.thread_id


def load_gold(path: str | Path) -> GoldFile:
    """Read and validate a gold file."""
    return GoldFile.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def find_gold(gold_dir: str | Path, *, container_id: str | None = None, slug: str | None = None) -> GoldFile | None:
    """Locate the gold file for a meeting/thread by file slug or by its ``meeting_id``/``thread_id``."""
    directory = Path(gold_dir)
    if not directory.is_dir():
        return None
    if slug:
        candidate = directory / f"{slug}.json"
        if candidate.is_file():
            try:
                return load_gold(candidate)
            except (ValidationError, json.JSONDecodeError) as exc:
                log.warning("gold file %s is invalid: %s", candidate, exc)
    if container_id:
        for path in sorted(directory.glob("*.json")):
            try:
                gold = load_gold(path)
            except (ValidationError, json.JSONDecodeError):
                continue
            if gold.container_id == container_id:
                return gold
    return None


def gold_items_for_episode(gold: GoldFile, episode: Episode) -> list[ExtractedFact]:
    """Gold items whose segment (or message) falls inside ``episode``, as validated facts."""
    is_email = episode.source_kind == "email"
    indices = {episode.seq} if is_email else set(episode.segment_indices)
    out: list[ExtractedFact] = []
    for item in gold.items:
        index = item.message_index if is_email else item.segment_index
        if index is None or index not in indices:
            continue
        precedent = item.follows_precedent or {}
        out.append(
            ExtractedFact(
                kind=item.kind,
                subject=item.subject,
                predicate=item.predicate,
                object=item.object,
                text=item.as_text(),
                speaker=item.speaker_id,
                confidence=0.95,
                episode_id=episode.id,
                supersedes_hint=json.dumps(item.supersedes) if item.supersedes else None,
                precedent_key=(
                    fact_key(str(precedent.get("subject", "")), str(precedent.get("predicate", "")))
                    if precedent.get("subject") and precedent.get("predicate")
                    else None
                ),
            )
        )
    return out
