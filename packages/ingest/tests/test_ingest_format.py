"""Recorder export validation."""

from __future__ import annotations

import json

import pytest
from ingest.recorder_format import RecorderFormatError, load_export, parse_export


def test_valid_export_parses(sample_meeting):
    export = parse_export(sample_meeting)
    assert export.meeting.id == "mtg_orbit_001"
    assert export.started_at_ms == 1788755400000
    assert export.ended_at_ms == 1788755910000
    assert set(export.speaker_map) == {"spk_aditya", "spk_priya"}
    assert export.segments[1].duration_ms == 8800


def test_parse_accepts_str_and_bytes(sample_meeting):
    text = json.dumps(sample_meeting)
    assert parse_export(text).meeting.title == "Orbit kickoff"
    assert parse_export(text.encode()).meeting.title == "Orbit kickoff"


def test_naive_timestamp_rejected(sample_meeting):
    sample_meeting["meeting"]["started_at"] = "2026-09-07T10:00:00"
    with pytest.raises(RecorderFormatError, match="timezone"):
        parse_export(sample_meeting)


def test_unknown_speaker_rejected(sample_meeting):
    sample_meeting["segments"][0]["speaker_id"] = "spk_ghost"
    with pytest.raises(RecorderFormatError, match="unknown speaker_id"):
        parse_export(sample_meeting)


def test_overlapping_segments_rejected(sample_meeting):
    sample_meeting["segments"][1]["start_ms"] = 5000
    with pytest.raises(RecorderFormatError, match="overlaps"):
        parse_export(sample_meeting)


def test_blank_and_zero_length_segments_are_dropped_with_a_warning(sample_meeting, caplog):
    sample_meeting["segments"][0]["end_ms"] = 0
    sample_meeting["segments"].insert(2, {"start_ms": 15200, "end_ms": 15200, "speaker_id": "spk_priya", "text": "   "})
    sample_meeting["segments"].insert(2, {"start_ms": 15200, "end_ms": 15300, "speaker_id": "spk_priya", "text": ""})
    with caplog.at_level("WARNING"):
        export = parse_export(sample_meeting)
    assert len(export.segments) == 3 and [s.start_ms for s in export.segments] == [6400, 15200, 20000]
    assert "dropped 3 blank or zero-length segment(s)" in caplog.text and "[0, 2, 3]" in caplog.text


def test_only_empty_segments_is_still_an_error(sample_meeting):
    sample_meeting["segments"] = [{"start_ms": 0, "end_ms": 0, "speaker_id": "spk_aditya", "text": "x"}]
    with pytest.raises(RecorderFormatError):
        parse_export(sample_meeting)


def test_extra_keys_rejected(sample_meeting):
    sample_meeting["meeting"]["mood"] = "tense"
    with pytest.raises(RecorderFormatError, match="extra"):
        parse_export(sample_meeting)


def test_duplicate_speaker_ids_rejected(sample_meeting):
    sample_meeting["speakers"].append({"id": "spk_priya", "name": "Priya 2"})
    with pytest.raises(RecorderFormatError, match="unique"):
        parse_export(sample_meeting)


def test_wrong_version_rejected(sample_meeting):
    sample_meeting["version"] = 2
    with pytest.raises(RecorderFormatError):
        parse_export(sample_meeting)


def test_invalid_json_rejected():
    with pytest.raises(RecorderFormatError):
        parse_export("{not json")


def test_load_export_from_file(tmp_path, sample_meeting):
    path = tmp_path / "orbit_001.json"
    path.write_text(json.dumps(sample_meeting), encoding="utf-8")
    assert load_export(path).meeting.id == "mtg_orbit_001"
