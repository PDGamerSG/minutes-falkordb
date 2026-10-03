"""Shared fixtures for the ingest tests (no database, no models)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

SAMPLE_MEETING: dict[str, Any] = {
    "version": 1,
    "meeting": {
        "id": "mtg_orbit_001",
        "title": "Orbit kickoff",
        "started_at": "2026-09-07T10:00:00+05:30",
        "ended_at": "2026-09-07T10:08:30+05:30",
        "audio_uri": "data/meetings/orbit_001.wav",
    },
    "speakers": [
        {"id": "spk_aditya", "name": "Aditya", "role": "lead"},
        {"id": "spk_priya", "name": "Priya", "role": "backend"},
    ],
    "segments": [
        {"start_ms": 0, "end_ms": 6400, "speaker_id": "spk_aditya", "text": "Alright, let's lock the scope for the October release."},
        {"start_ms": 6400, "end_ms": 15200, "speaker_id": "spk_priya", "text": "Payments go first. I can have the UPI flow done by the 24th."},
        {"start_ms": 15200, "end_ms": 20000, "speaker_id": "spk_priya", "text": "I will need the sandbox keys from Rahul before then."},
        {"start_ms": 20000, "end_ms": 24000, "speaker_id": "spk_aditya", "text": "Good. We go with Razorpay for the gateway."},
    ],
}

SAMPLE_GOLD: dict[str, Any] = {
    "meeting_id": "mtg_orbit_001",
    "items": [
        {"kind": "decision", "subject": "October release", "predicate": "scope_includes", "object": "payments", "speaker_id": "spk_aditya", "segment_index": 0},
        {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "speaker_id": "spk_priya", "segment_index": 1},
        {"kind": "decision", "subject": "Payment gateway", "predicate": "decided", "object": "Razorpay", "speaker_id": "spk_aditya", "segment_index": 3},
    ],
}

SAMPLE_THREAD: dict[str, Any] = {
    "version": 1,
    "thread": {"id": "thr_orbit_001", "subject": "UPI flow timeline", "started_at": "2026-09-16T14:02:00+05:30"},
    "people": [
        {"id": "spk_priya", "name": "Priya", "email": "priya@orbit.example"},
        {"id": "spk_aditya", "name": "Aditya", "email": "aditya@orbit.example"},
    ],
    "messages": [
        {
            "id": "msg_orbit_001_1",
            "sent_at": "2026-09-16T14:02:00+05:30",
            "from": "priya@orbit.example",
            "to": ["aditya@orbit.example"],
            "cc": ["rahul@orbit.example"],
            "in_reply_to": None,
            "subject": "UPI flow timeline",
            "body_text": "Aditya, quick heads-up on the UPI flow: the sandbox keys arrived late, so it now lands on Friday the 26th.",
        },
        {
            "id": "msg_orbit_001_2",
            "sent_at": "2026-09-16T15:10:00+05:30",
            "from": "aditya@orbit.example",
            "to": ["priya@orbit.example"],
            "cc": [],
            "in_reply_to": "msg_orbit_001_1",
            "subject": "Re: UPI flow timeline",
            "body_text": "Understood, Friday works.\n\nOn Tue, Sep 16, 2026 at 2:02 PM Priya <priya@orbit.example> wrote:\n> Aditya, quick heads-up on the UPI flow\n> it now lands on Friday the 26th.",
        },
    ],
}

SAMPLE_THREAD_GOLD: dict[str, Any] = {
    "thread_id": "thr_orbit_001",
    "items": [
        {
            "kind": "commitment",
            "subject": "UPI flow",
            "predicate": "due",
            "object": "2026-09-26",
            "speaker_id": "spk_priya",
            "message_index": 0,
            "supersedes": {"subject": "UPI flow", "predicate": "due"},
        }
    ],
}


@pytest.fixture
def sample_meeting() -> dict[str, Any]:
    return copy.deepcopy(SAMPLE_MEETING)


@pytest.fixture
def sample_gold() -> dict[str, Any]:
    return copy.deepcopy(SAMPLE_GOLD)


@pytest.fixture
def sample_thread() -> dict[str, Any]:
    return copy.deepcopy(SAMPLE_THREAD)


@pytest.fixture
def sample_thread_gold() -> dict[str, Any]:
    return copy.deepcopy(SAMPLE_THREAD_GOLD)
