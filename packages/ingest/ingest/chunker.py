"""Merge consecutive same-speaker segments into 30 to 60 second episodes.

Segments are never split. A new episode starts whenever the speaker changes, or when
adding the next segment would push the episode past ``max_seconds`` while it already
spans at least ``min_seconds`` (or when the overshoot would be worse than the undershoot).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .recorder_format import RecorderExport


@dataclass(slots=True)
class Episode:
    """A same-speaker chunk of a meeting (``source_kind="utterance"``) or one email message."""

    id: str
    seq: int
    speaker_id: str
    text: str
    t_start: int | None
    t_end: int | None
    t_occurred: int
    segment_indices: list[int] = field(default_factory=list)
    source_kind: str = "utterance"
    container_id: str = ""
    to_ids: list[str] = field(default_factory=list)
    cc_ids: list[str] = field(default_factory=list)
    in_reply_to_episode_id: str | None = None
    message_id: str | None = None

    @property
    def duration_ms(self) -> int:
        if self.t_start is None or self.t_end is None:
            return 0
        return self.t_end - self.t_start

    def to_record(self, embedding: list[float] | None = None) -> dict[str, Any]:
        """Dict shaped for ``hiveboard.memory.remember_episodes`` / ``remember_email_episodes``."""
        rec: dict[str, Any] = {
            "id": self.id,
            "seq": self.seq,
            "text": self.text,
            "t_occurred": self.t_occurred,
            "source_kind": self.source_kind,
        }
        if self.source_kind == "email":
            rec.update(
                {
                    "sender_id": self.speaker_id,
                    "to_ids": list(self.to_ids),
                    "cc_ids": list(self.cc_ids),
                    "in_reply_to_episode_id": self.in_reply_to_episode_id,
                    "message_id": self.message_id,
                }
            )
        else:
            rec.update({"speaker_id": self.speaker_id, "t_start": self.t_start, "t_end": self.t_end})
        if embedding is not None:
            rec["embedding"] = embedding
        return rec


def episode_id(container_id: str, seq: int) -> str:
    """Deterministic episode id so re-imports MERGE instead of duplicating."""
    return f"ep_{container_id}_{seq:03d}"


def chunk(export: RecorderExport, *, min_seconds: int = 30, max_seconds: int = 60) -> list[Episode]:
    """Group the export's segments into episodes.

    Returns episodes in time order with 0-based ``seq``. ``t_start``/``t_end`` are offsets
    (ms) from the meeting start; ``t_occurred`` is absolute epoch ms.
    """
    if min_seconds <= 0 or max_seconds < min_seconds:
        raise ValueError("require 0 < min_seconds <= max_seconds")
    min_ms, max_ms = min_seconds * 1000, max_seconds * 1000
    base = export.started_at_ms
    meeting_id = export.meeting.id

    episodes: list[Episode] = []
    current: list[int] = []

    def flush() -> None:
        if not current:
            return
        segs = [export.segments[i] for i in current]
        seq = len(episodes)
        episodes.append(
            Episode(
                id=episode_id(meeting_id, seq),
                seq=seq,
                speaker_id=segs[0].speaker_id,
                text=" ".join(s.text.strip() for s in segs),
                t_start=segs[0].start_ms,
                t_end=segs[-1].end_ms,
                t_occurred=base + segs[0].start_ms,
                segment_indices=list(current),
                source_kind="utterance",
                container_id=meeting_id,
            )
        )
        current.clear()

    for index, seg in enumerate(export.segments):
        if not current:
            current.append(index)
            continue
        first = export.segments[current[0]]
        last = export.segments[current[-1]]
        if seg.speaker_id != first.speaker_id:
            flush()
            current.append(index)
            continue
        cur_dur = last.end_ms - first.start_ms
        new_dur = seg.end_ms - first.start_ms
        if new_dur <= max_ms:
            current.append(index)
            continue
        if cur_dur >= min_ms:
            flush()
            current.append(index)
            continue
        overshoot = new_dur - max_ms
        undershoot = min_ms - cur_dur
        if overshoot <= undershoot:
            current.append(index)
        else:
            flush()
            current.append(index)
    flush()
    return episodes
