"""Pydantic models for extraction output (implementation plan section 5)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .dates import looks_like_date, normalize_date

Kind = Literal["fact", "decision", "commitment"]

_KIND_SYNONYMS = {
    "fact": "fact",
    "facts": "fact",
    "statement": "fact",
    "decision": "decision",
    "decisions": "decision",
    "decided": "decision",
    "commitment": "commitment",
    "commitments": "commitment",
    "promise": "commitment",
    "action_item": "commitment",
    "action item": "commitment",
    "todo": "commitment",
    "task": "commitment",
}

_NON_WORD = re.compile(r"[^a-z0-9]+")
_SPACES = re.compile(r"\s+")


def normalize_predicate(value: str) -> str:
    """snake_case, lowercase, alphanumerics only: "Due Date" -> "due_date"."""
    return _NON_WORD.sub("_", value.strip().lower()).strip("_")


def canonical_entity_name(value: str) -> str:
    """Canonical display form of an entity name: trimmed, single-spaced, Title Case for lowercase words."""
    name = _SPACES.sub(" ", value.strip().strip(".,;:!?\"'"))
    words = []
    for word in name.split(" "):
        if word.islower() and len(word) > 2:
            words.append(word[0].upper() + word[1:])
        else:
            words.append(word)
    return " ".join(words)


def entity_id_for(name: str) -> str:
    """Deterministic id for a canonical entity name."""
    slug = _NON_WORD.sub("_", name.strip().lower()).strip("_") or "unnamed"
    return f"ent_{slug}"


def fact_key(subject: str, predicate: str) -> str:
    """The supersession key: ``subject|predicate`` lowercased."""
    return f"{_SPACES.sub(' ', subject.strip()).lower()}|{normalize_predicate(predicate)}"


class ExtractedEntity(BaseModel):
    """An entity mentioned in an episode (project, system, customer, topic, person)."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(min_length=1)
    type: str = "topic"

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, value: Any) -> str:
        return str(value or "topic").strip().lower() or "topic"

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return canonical_entity_name(value)


class ExtractedFact(BaseModel):
    """One extracted statement; ``kind`` distinguishes facts, decisions and commitments."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    kind: Kind = "fact"
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str = Field(min_length=1)
    text: str = Field(min_length=1)
    speaker: str = ""
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    due_at: str | None = None
    supersedes_hint: str | None = None
    precedent_key: str | None = None
    episode_id: str = ""

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, value: Any) -> str:
        key = str(value or "fact").strip().lower()
        if key not in _KIND_SYNONYMS:
            raise ValueError(f"unknown kind {value!r}")
        return _KIND_SYNONYMS[key]

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> float:
        if value is None or value == "":
            return 0.8
        return float(value)

    @field_validator("predicate")
    @classmethod
    def _predicate(cls, value: str) -> str:
        normalized = normalize_predicate(value)
        if not normalized:
            raise ValueError("predicate is empty after normalisation")
        return normalized

    @field_validator("subject", "object")
    @classmethod
    def _collapse(cls, value: str) -> str:
        return _SPACES.sub(" ", value)

    @field_validator("object", mode="before")
    @classmethod
    def _object_str(cls, value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value)
        if isinstance(value, (int, float, bool)):
            return str(value)
        return value

    @field_validator("supersedes_hint", "due_at", "precedent_key", mode="before")
    @classmethod
    def _none_strings(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "n/a"}:
            return None
        return value

    @model_validator(mode="after")
    def _dates(self) -> ExtractedFact:
        if self.due_at is not None:
            self.due_at = normalize_date(self.due_at) or (self.due_at if looks_like_date(self.due_at) else None)
        if self.kind == "commitment" and self.due_at is None and looks_like_date(self.object):
            self.due_at = normalize_date(self.object)
        if looks_like_date(self.object):
            normalized = normalize_date(self.object)
            if normalized:
                self.object = normalized
        return self

    @property
    def key(self) -> str:
        return fact_key(self.subject, self.predicate)


class ExtractedDecision(ExtractedFact):
    kind: Literal["decision"] = "decision"  # type: ignore[assignment]


class ExtractedCommitment(ExtractedFact):
    kind: Literal["commitment"] = "commitment"  # type: ignore[assignment]


class RawExtraction(BaseModel):
    """Lenient container for what the model returns; items are validated one by one later."""

    model_config = ConfigDict(extra="ignore")

    entities: list[dict[str, Any]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("entities", "items", mode="before")
    @classmethod
    def _list(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        return list(value)


class ExtractionStats(BaseModel):
    """Counts for one extraction call; ``drop_rate`` is logged by the extractor."""

    proposed: int = 0
    kept: int = 0
    dropped: int = 0
    errors: list[str] = Field(default_factory=list)

    @property
    def drop_rate(self) -> float:
        return self.dropped / self.proposed if self.proposed else 0.0


class EpisodeExtraction(BaseModel):
    """Validated extraction result for one episode."""

    items: list[ExtractedFact] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    stats: ExtractionStats = Field(default_factory=ExtractionStats)


class SupersessionVerdict(BaseModel):
    """Answer to "contradiction or refinement?" for two facts sharing a key."""

    model_config = ConfigDict(extra="ignore")

    verdict: Literal["contradiction", "refinement", "unrelated"]
    reason: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, value: Any) -> str:
        key = str(value or "").strip().lower()
        if key.startswith("contra") or key in {"replace", "replaces", "supersede", "supersedes", "change"}:
            return "contradiction"
        if key.startswith("refin") or key in {"adds", "addition", "detail", "elaboration", "complement"}:
            return "refinement"
        if key.startswith("unrel") or key in {"different", "none", "no"}:
            return "unrelated"
        raise ValueError(f"unknown verdict {value!r}")
