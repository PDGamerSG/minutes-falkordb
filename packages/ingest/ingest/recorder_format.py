"""Pydantic models for the recorder export (docs/contracts/recorder-format.md).

Validation is strict: unknown keys are rejected, timestamps must be timezone-aware,
segments must be in time order, non-overlapping and reference declared speakers.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class RecorderFormatError(ValueError):
    """Raised when a recorder export does not satisfy the contract."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Speaker(_Strict):
    """A diarized speaker; ids are stable across meetings of a tenant."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: str | None = None


class Segment(_Strict):
    """One diarized utterance. Offsets are milliseconds from ``meeting.started_at``."""

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    speaker_id: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _end_after_start(self) -> Segment:
        if self.end_ms <= self.start_ms:
            raise ValueError(f"segment end_ms ({self.end_ms}) must be greater than start_ms ({self.start_ms})")
        return self

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class MeetingMeta(_Strict):
    """Meeting header. ``audio_uri`` is relative to the repo root when present."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    started_at: datetime
    ended_at: datetime | None = None
    audio_uri: str | None = None

    @field_validator("started_at", "ended_at")
    @classmethod
    def _tz_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must carry a timezone offset")
        return value

    @model_validator(mode="after")
    def _ended_after_started(self) -> MeetingMeta:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not be earlier than started_at")
        return self


class RecorderExport(_Strict):
    """Root of the recorder export JSON."""

    version: Literal[1]
    meeting: MeetingMeta
    speakers: list[Speaker] = Field(min_length=1)
    segments: list[Segment] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> RecorderExport:
        ids = [s.id for s in self.speakers]
        if len(set(ids)) != len(ids):
            raise ValueError("speaker ids must be unique")
        known = set(ids)
        prev_end = -1
        for index, seg in enumerate(self.segments):
            if seg.speaker_id not in known:
                raise ValueError(f"segment {index} references unknown speaker_id {seg.speaker_id!r}")
            if seg.start_ms < prev_end:
                raise ValueError(f"segment {index} overlaps or precedes the previous segment")
            prev_end = seg.end_ms
        return self

    @property
    def started_at_ms(self) -> int:
        return to_ms(self.meeting.started_at)

    @property
    def ended_at_ms(self) -> int | None:
        return to_ms(self.meeting.ended_at) if self.meeting.ended_at else None

    @property
    def speaker_map(self) -> dict[str, Speaker]:
        return {s.id: s for s in self.speakers}


def to_ms(value: datetime) -> int:
    """Epoch milliseconds for a timezone-aware datetime."""
    return int(value.timestamp() * 1000)


def parse_export(data: dict[str, Any] | str | bytes | RecorderExport) -> RecorderExport:
    """Validate raw JSON (dict, str or bytes) into a :class:`RecorderExport`."""
    if isinstance(data, RecorderExport):
        return data
    try:
        if isinstance(data, (str, bytes)):
            data = json.loads(data)
        return RecorderExport.model_validate(data)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise RecorderFormatError(str(exc)) from exc


def load_export(path: str | Path) -> RecorderExport:
    """Read and validate a recorder export file."""
    return parse_export(Path(path).read_text(encoding="utf-8"))
