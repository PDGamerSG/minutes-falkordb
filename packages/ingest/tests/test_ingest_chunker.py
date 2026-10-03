"""Chunker boundaries: speaker changes, 30-60 s window, never split a segment."""

from __future__ import annotations

from ingest.chunker import chunk, episode_id
from ingest.recorder_format import parse_export


def _export(segments, started="2026-09-07T10:00:00+00:00"):
    return parse_export(
        {
            "version": 1,
            "meeting": {"id": "mtg_t", "title": "t", "started_at": started},
            "speakers": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
            "segments": segments,
        }
    )


def _seg(start_s, end_s, speaker="a", text="x"):
    return {"start_ms": start_s * 1000, "end_ms": end_s * 1000, "speaker_id": speaker, "text": text}


def test_sample_meeting_merges_same_speaker(sample_meeting):
    episodes = chunk(parse_export(sample_meeting))
    assert [e.speaker_id for e in episodes] == ["spk_aditya", "spk_priya", "spk_aditya"]
    assert episodes[1].segment_indices == [1, 2]
    assert episodes[1].text.startswith("Payments go first.") and episodes[1].text.endswith("before then.")
    assert episodes[1].t_start == 6400 and episodes[1].t_end == 20000
    assert episodes[1].t_occurred == 1788755400000 + 6400
    assert [e.seq for e in episodes] == [0, 1, 2]
    assert episodes[0].id == episode_id("mtg_orbit_001", 0) == "ep_mtg_orbit_001_000"
    assert all(e.source_kind == "utterance" for e in episodes)


def test_speaker_change_always_splits():
    export = _export([_seg(0, 5, "a"), _seg(5, 10, "b"), _seg(10, 15, "a")])
    episodes = chunk(export)
    assert [e.speaker_id for e in episodes] == ["a", "b", "a"]
    assert all(e.duration_ms == 5000 for e in episodes)


def test_merges_until_window_then_closes():
    # 10 s segments by the same speaker: 6 fit in 60 s, the 7th opens a new episode.
    export = _export([_seg(i * 10, (i + 1) * 10) for i in range(8)])
    episodes = chunk(export)
    assert [e.duration_ms for e in episodes] == [60000, 20000]
    assert episodes[0].segment_indices == list(range(6))
    assert episodes[1].segment_indices == [6, 7]


def test_never_splits_a_long_segment():
    # A 90 s segment is one episode (never split); it is already past the window, so the next
    # same-speaker segment opens a new episode.
    export = _export([_seg(0, 90), _seg(90, 95)])
    episodes = chunk(export)
    assert [e.duration_ms for e in episodes] == [90000, 5000]
    assert episodes[0].segment_indices == [0] and episodes[1].segment_indices == [1]


def test_short_episode_prefers_small_overshoot_over_large_undershoot():
    # 25 s so far; adding 40 s gives 65 s (overshoot 5) versus staying at 25 s (undershoot 5): add.
    export = _export([_seg(0, 25), _seg(25, 65)])
    assert [e.duration_ms for e in chunk(export)] == [65000]
    # 10 s so far; adding 70 s gives 80 s (overshoot 20) versus undershoot 20: tie adds too.
    export = _export([_seg(0, 10), _seg(10, 80)])
    assert [e.duration_ms for e in chunk(export)] == [80000]
    # 10 s so far; adding 75 s gives 85 s (overshoot 25) worse than undershoot 20: split.
    export = _export([_seg(0, 10), _seg(10, 85)])
    assert [e.duration_ms for e in chunk(export)] == [10000, 75000]


def test_gap_between_segments_counts_toward_duration():
    export = _export([_seg(0, 10), _seg(50, 60), _seg(61, 70)])
    episodes = chunk(export)
    assert [e.duration_ms for e in episodes] == [60000, 9000]


def test_custom_window():
    export = _export([_seg(i * 10, (i + 1) * 10) for i in range(4)])
    assert [e.duration_ms for e in chunk(export, min_seconds=10, max_seconds=20)] == [20000, 20000]


def test_episode_record_shape():
    export = _export([_seg(0, 5)])
    rec = chunk(export)[0].to_record([0.0] * 3)
    assert rec["speaker_id"] == "a" and rec["t_start"] == 0 and rec["t_end"] == 5000
    assert rec["source_kind"] == "utterance" and rec["embedding"] == [0.0, 0.0, 0.0]
    assert "sender_id" not in rec
