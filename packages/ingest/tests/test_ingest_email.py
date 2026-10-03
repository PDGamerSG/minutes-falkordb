"""Email threads: JSON model, .eml/.mbox parsing, quote stripping, episodes and cross-source supersession."""

from __future__ import annotations

import copy
import json

import pytest
from ingest.email_format import (
    EmailFormatError,
    parse_thread,
    strip_quoted,
    thread_episodes,
    thread_from_eml,
    thread_from_mbox,
)
from ingest.embed import Embedder
from ingest.extract import GoldExtractor, heuristic_supersession
from ingest.fakes import MemoryHive
from ingest.gold import GoldFile
from ingest.llm_protocol import FakeLLM
from ingest.pipeline import run, run_thread

ROSTER = [
    {"id": "spk_priya", "name": "Priya", "role": "backend", "email": "priya@orbit.example"},
    {"id": "spk_aditya", "name": "Aditya", "role": "lead", "email": "aditya@orbit.example"},
    {"id": "spk_rahul", "name": "Rahul", "role": "infra", "email": "rahul@orbit.example"},
]

EML = b"""From: Priya <priya@orbit.example>
To: Aditya <aditya@orbit.example>
Cc: rahul@orbit.example
Subject: Re: UPI flow timeline
Date: Wed, 16 Sep 2026 14:02:00 +0530
Message-ID: <abc123@orbit.example>
Content-Type: text/plain; charset="utf-8"

Quick heads-up: the UPI flow now lands on Friday the 26th.

On Tue, Sep 15, 2026 at 9:00 AM Aditya <aditya@orbit.example> wrote:
> Where are we on the UPI flow?
"""


def test_thread_json_parses(sample_thread):
    thread = parse_thread(sample_thread)
    assert thread.thread.id == "thr_orbit_001" and thread.started_at_ms == 1789547520000
    assert thread.messages[1].from_ == "aditya@orbit.example"
    assert thread.messages[1].in_reply_to == "msg_orbit_001_1"


def test_thread_validation_errors(sample_thread):
    bad = copy.deepcopy(sample_thread)
    bad["messages"][1]["in_reply_to"] = "msg_missing"
    with pytest.raises(EmailFormatError, match="replies to unknown"):
        parse_thread(bad)
    bad = copy.deepcopy(sample_thread)
    bad["messages"][0]["sent_at"] = "2026-09-17T14:02:00+05:30"
    with pytest.raises(EmailFormatError, match="out of sent_at order"):
        parse_thread(bad)
    bad = copy.deepcopy(sample_thread)
    bad["messages"][0]["sent_at"] = "2026-09-16T14:02:00"
    with pytest.raises(EmailFormatError, match="timezone"):
        parse_thread(bad)
    bad = copy.deepcopy(sample_thread)
    bad["thread"]["colour"] = "blue"
    with pytest.raises(EmailFormatError):
        parse_thread(bad)


def test_strip_quoted_replies():
    body = "Understood, Friday works.\n\nOn Tue, Sep 16, 2026 at 2:02 PM Priya <p@x> wrote:\n> old\n> text"
    assert strip_quoted(body) == "Understood, Friday works."
    assert strip_quoted("line one\n> quoted\nline two") == "line one\nline two"
    wrapped = "Thanks.\nOn Tue, Sep 16, 2026 at 2:02 PM Priya\nwrote:\n> old"
    assert strip_quoted(wrapped) == "Thanks."
    assert strip_quoted("Yes.\n-----Original Message-----\nFrom: a\nSent: b") == "Yes."
    assert strip_quoted("Body\n-- \nPriya\nBackend") == "Body"


def test_resolve_people_prefers_roster_then_people_then_synthesizes(sample_thread):
    thread = parse_thread(sample_thread)
    people = thread.resolve_people(ROSTER)
    assert set(people) == {"spk_priya", "spk_aditya", "spk_rahul"}
    assert people["spk_priya"]["role"] == "backend"
    people = thread.resolve_people(None)
    assert set(people) == {"spk_priya", "spk_aditya", "spk_rahul"}
    assert people["spk_rahul"]["name"] == "Rahul" and people["spk_rahul"]["email"] == "rahul@orbit.example"


def test_thread_episodes_shape(sample_thread):
    thread = parse_thread(sample_thread)
    episodes = thread_episodes(thread, thread.resolve_people(ROSTER))
    assert [e.id for e in episodes] == ["ep_thr_orbit_001_000", "ep_thr_orbit_001_001"]
    first, second = episodes
    assert first.source_kind == "email" and first.t_start is None and first.t_occurred == 1789547520000
    assert first.speaker_id == "spk_priya" and first.to_ids == ["spk_aditya"] and first.cc_ids == ["spk_rahul"]
    assert second.in_reply_to_episode_id == first.id and second.text == "Understood, Friday works."
    rec = second.to_record([0.1])
    assert rec["sender_id"] == "spk_aditya" and rec["in_reply_to_episode_id"] == first.id and rec["message_id"] == "msg_orbit_001_2"
    assert "speaker_id" not in rec


def test_eml_parsing():
    thread = thread_from_eml(EML, thread_id="thr_test")
    assert thread.thread.subject == "UPI flow timeline"
    msg = thread.messages[0]
    assert msg.id == "abc123@orbit.example" and msg.from_ == "priya@orbit.example"
    assert msg.to == ["aditya@orbit.example"] and msg.cc == ["rahul@orbit.example"]
    assert msg.in_reply_to is None
    assert {p.email for p in thread.people} == {"priya@orbit.example", "aditya@orbit.example", "rahul@orbit.example"}
    episodes = thread_episodes(thread, thread.resolve_people(ROSTER))
    assert episodes[0].text == "Quick heads-up: the UPI flow now lands on Friday the 26th."


def test_mbox_parsing_orders_by_date():
    second = EML.replace(b"Date: Wed, 16 Sep 2026 14:02:00 +0530", b"Date: Wed, 16 Sep 2026 15:10:00 +0530").replace(
        b"Message-ID: <abc123@orbit.example>", b"Message-ID: <def456@orbit.example>\nIn-Reply-To: <abc123@orbit.example>"
    )
    mbox = b"From priya@orbit.example Wed Sep 16 15:10:00 2026\n" + second + b"\nFrom priya@orbit.example Wed Sep 16 14:02:00 2026\n" + EML
    thread = thread_from_mbox(mbox)
    assert [m.id for m in thread.messages] == ["abc123@orbit.example", "def456@orbit.example"]
    assert thread.messages[1].in_reply_to == "abc123@orbit.example"
    assert thread.thread.id.startswith("thr_")


def test_run_thread_supersedes_meeting_commitment(sample_meeting, sample_gold, sample_thread, sample_thread_gold):
    hive = MemoryHive()
    embedder = Embedder(backend="fake")
    run(sample_meeting, "orbit", hive, None, embedder, extractor=GoldExtractor(GoldFile.model_validate(sample_gold)))
    old = hive.active_facts("orbit", key="upi flow|due")[0]

    gold = GoldFile.model_validate(sample_thread_gold)
    stats = run_thread(sample_thread, "orbit", hive, None, embedder, roster=ROSTER, extractor=GoldExtractor(gold), judge=heuristic_supersession)
    assert stats["source_kind"] == "email" and stats["episodes"] == 2
    assert stats["superseded"] == 1 and stats["commitments"] == 1

    active = hive.active_facts("orbit", key="upi flow|due")
    assert len(active) == 1 and active[0]["object"] == "2026-09-26" and active[0]["supersedes"] == [old["id"]]
    assert hive.get_fact("orbit", old["id"])["status"] == "superseded"

    why = hive.why("orbit", active[0]["id"])
    assert why["source"]["kind"] == "email"
    assert why["source"]["container"] == {"id": "thr_orbit_001", "subject": "UPI flow timeline"}
    assert why["source"]["message_id"] == "msg_orbit_001_1" and why["source"]["sent_at"] == 1789547520000
    assert why["thread"]["subject"] == "UPI flow timeline" and why["meeting"] is None

    threads = hive.list_threads("orbit")
    assert threads[0]["messages"] == 2 and threads[0]["facts"] == 1
    messages = hive.thread_messages("orbit", "thr_orbit_001")
    assert messages[1]["in_reply_to_episode_id"] == messages[0]["id"]
    assert hive.get_person("orbit", "spk_priya")["email"] == "priya@orbit.example"


def test_run_thread_with_fake_llm(sample_thread):
    hive = MemoryHive()
    llm = FakeLLM([{"items": [{"kind": "fact", "subject": "UPI flow", "predicate": "status", "object": "delayed", "text": "keys late"}]}, {"items": []}])
    stats = run_thread(json.dumps(sample_thread), "orbit", hive, llm, Embedder(backend="fake"))
    assert stats["facts"] == 1 and stats["episodes"] == 2
    assert "Email thread: UPI flow timeline" in llm.calls[0]["user"]
    assert "Sent at:" in llm.calls[0]["user"]
    assert "ONE email message" in llm.calls[0]["system"]
