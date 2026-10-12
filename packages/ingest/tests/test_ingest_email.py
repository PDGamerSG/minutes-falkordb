"""Email threads: JSON model, .eml/.mbox parsing, HTML bodies, quote stripping, identities, episodes and cross-source supersession."""

from __future__ import annotations

import copy
import json

import pytest
from ingest.email_format import (
    EmailFormatError,
    html_to_text,
    parse_thread,
    strip_quoted,
    synthesize_person,
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
RAHUL_EXT = synthesize_person("rahul@orbit.example")["id"]

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

HTML_EML = b"""From: Aditya <aditya@orbit.example>
To: Priya <priya@orbit.example>
Subject: Re: UPI flow timeline
Date: Wed, 16 Sep 2026 15:10:00 +0530
Message-ID: <html1@orbit.example>
In-Reply-To: <abc123@orbit.example>
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<html><head><style>.gmail_quote { color: #500050; } p { margin: 0 }</style>
<script>var tracking = 1;</script></head>
<body><div dir="ltr">Understood &amp; agreed, Friday the 26th works.<br>We ship the &lt;receipts&gt; screen after.</div>
<div dir="ltr">Regards,<br>Aditya</div><br>
<div class="gmail_quote"><div dir="ltr" class="gmail_attr">On Wed, Sep 16, 2026 at 2:02 PM Priya &lt;priya@orbit.example&gt; wrote:<br></div>
<blockquote class="gmail_quote" style="margin:0 0 0 .8ex;border-left:1px #ccc solid"><div>Quick heads-up: the UPI flow now lands on Friday the 26th.</div>
<blockquote><div>Where are we on the UPI flow?</div></blockquote></blockquote></div></body></html>
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


def test_strip_quoted_needs_a_date_token_allows_three_line_headers_and_keeps_bare_dashes():
    # "wrote:" mid-sentence without a date is body text, not a quote header
    prose = "On balance I agree with what Rahul wrote:\nthe sandbox keys come first."
    assert strip_quoted(prose) == prose
    # a Gmail header wrapped over three lines is still detected
    three = "Agreed.\nOn Wed, 16 Sep 2026 at 14:02, Priya\n<priya@orbit.example>\nwrote:\n> old"
    assert strip_quoted(three) == "Agreed."
    # only the RFC 3676 "-- " separator is a signature; a bare "--" is a dash in prose
    assert strip_quoted("First point\n--\nSecond point") == "First point\n--\nSecond point"
    assert strip_quoted("First point\n-- \nSignature") == "First point"


def test_html_to_text_drops_style_decodes_entities_and_marks_blockquotes():
    text = html_to_text(HTML_EML.split(b"\n\n", 1)[1].decode())
    assert "color" not in text and "tracking" not in text
    assert "Understood & agreed, Friday the 26th works." in text
    assert "We ship the <receipts> screen after." in text
    assert "> Quick heads-up: the UPI flow now lands on Friday the 26th." in text
    assert "> > Where are we on the UPI flow?" in text


def test_html_only_eml_keeps_only_the_new_text():
    thread = thread_from_eml(HTML_EML, thread_id="thr_html")
    episodes = thread_episodes(thread, thread.resolve_people(ROSTER))
    assert episodes[0].speaker_id == "spk_aditya"
    assert episodes[0].text == "Understood & agreed, Friday the 26th works.\nWe ship the <receipts> screen after.\n\nRegards,\nAditya"
    assert "26th." not in episodes[0].text.split("Regards")[1]


def test_synthesized_people_never_collide_with_roster_ids(sample_thread):
    thread = parse_thread(sample_thread)
    people = thread.resolve_people(ROSTER)
    assert set(people) == {"spk_priya", "spk_aditya", "spk_rahul"}
    assert people["spk_priya"]["role"] == "backend"
    # without a roster the cc'd address is synthesized from the full address, not its local part
    people = thread.resolve_people(None)
    assert set(people) == {"spk_priya", "spk_aditya", RAHUL_EXT}
    assert RAHUL_EXT.startswith("ext_") and len(RAHUL_EXT) == 14
    assert people[RAHUL_EXT]["name"] == "Rahul" and people[RAHUL_EXT]["email"] == "rahul@orbit.example"
    # an outside sender with the roster's local part stays a distinct person
    outside = synthesize_person("priya@gmail.com")
    assert outside["id"] != "spk_priya" and outside["id"] != synthesize_person("priya@orbit.example")["id"]
    assert outside["email"] == "priya@gmail.com"
    external = copy.deepcopy(sample_thread)
    external["messages"][0]["from"] = "priya@gmail.com"
    thread = parse_thread(external)
    episodes = thread_episodes(thread, thread.resolve_people(ROSTER))
    assert episodes[0].speaker_id == outside["id"] and episodes[1].speaker_id == "spk_aditya"


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
    assert all(p.id.startswith("ext_") for p in thread.people)
    episodes = thread_episodes(thread, thread.resolve_people(ROSTER))
    assert episodes[0].text == "Quick heads-up: the UPI flow now lands on Friday the 26th."


def _mbox(*messages: bytes) -> bytes:
    return b"".join(b"From someone@orbit.example Wed Sep 16 15:10:00 2026\n" + m + b"\n" for m in messages)


def _reply(date: bytes, msgid: bytes, parent: bytes | None, subject: bytes = b"Re: UPI flow timeline", refs: bytes | None = None) -> bytes:
    msg = EML.replace(b"Date: Wed, 16 Sep 2026 14:02:00 +0530", b"Date: " + date).replace(b"Message-ID: <abc123@orbit.example>", b"Message-ID: <" + msgid + b">")
    msg = msg.replace(b"Subject: Re: UPI flow timeline", b"Subject: " + subject)
    if parent:
        msg = msg.replace(b"Message-ID: <" + msgid + b">", b"Message-ID: <" + msgid + b">\nIn-Reply-To: <" + parent + b">")
    if refs:
        msg = msg.replace(b"Message-ID: <" + msgid + b">", b"Message-ID: <" + msgid + b">\nReferences: " + refs)
    return msg


def test_mbox_parsing_orders_by_date():
    second = _reply(b"Wed, 16 Sep 2026 15:10:00 +0530", b"def456@orbit.example", b"abc123@orbit.example")
    threads = thread_from_mbox(_mbox(second, EML))
    assert len(threads) == 1
    thread = threads[0]
    assert [m.id for m in thread.messages] == ["abc123@orbit.example", "def456@orbit.example"]
    assert thread.messages[1].in_reply_to == "abc123@orbit.example"
    assert thread.thread.id.startswith("thr_")


def test_mbox_dedupes_message_ids_and_nulls_skewed_replies():
    # the sent copy and the received copy of the same message: one message, first copy kept
    threads = thread_from_mbox(_mbox(EML, EML.replace(b"Friday the 26th", b"Saturday")), thread_id="thr_dup")
    assert len(threads) == 1 and len(threads[0].messages) == 1
    assert "Friday the 26th" in threads[0].messages[0].body_text and threads[0].thread.id == "thr_dup"
    # a reply whose Date sorts before its parent (clock skew) keeps its place but loses the reply link
    early_reply = _reply(b"Wed, 16 Sep 2026 13:50:00 +0530", b"def456@orbit.example", b"abc123@orbit.example")
    [thread] = thread_from_mbox(_mbox(EML, early_reply))
    assert [m.id for m in thread.messages] == ["def456@orbit.example", "abc123@orbit.example"]
    assert thread.messages[0].in_reply_to is None and thread.messages[1].in_reply_to is None


def test_mbox_groups_conversations_by_references_then_subject():
    reply = _reply(b"Wed, 16 Sep 2026 15:10:00 +0530", b"def456@orbit.example", None, refs=b"<abc123@orbit.example>")
    other = _reply(b"Thu, 17 Sep 2026 09:00:00 +0530", b"kyc1@orbit.example", None, subject=b"Razorpay merchant KYC")
    other_followup = _reply(b"Thu, 17 Sep 2026 11:00:00 +0530", b"kyc2@orbit.example", None, subject=b"RE: Razorpay merchant KYC")
    threads = thread_from_mbox(_mbox(other_followup, reply, other, EML), thread_id="thr_box")
    assert len(threads) == 2
    upi, kyc = threads
    assert upi.thread.id == "thr_box" and upi.thread.subject == "UPI flow timeline"
    assert [m.id for m in upi.messages] == ["abc123@orbit.example", "def456@orbit.example"]
    assert kyc.thread.id == "thr_box_2" and kyc.thread.subject == "Razorpay merchant KYC"
    assert [m.id for m in kyc.messages] == ["kyc1@orbit.example", "kyc2@orbit.example"]
    assert {p.email for p in kyc.people} <= {"priya@orbit.example", "aditya@orbit.example", "rahul@orbit.example"}


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
    events = [e["event"] for e in hive.events["orbit"]]
    assert events.count("episode.ingested") == 2  # one per import, not one per message


def test_run_thread_with_fake_llm(sample_thread):
    hive = MemoryHive()
    llm = FakeLLM([{"items": [{"kind": "fact", "subject": "UPI flow", "predicate": "status", "object": "delayed", "text": "keys late"}]}, {"items": []}])
    stats = run_thread(json.dumps(sample_thread), "orbit", hive, llm, Embedder(backend="fake"))
    assert stats["facts"] == 1 and stats["episodes"] == 2
    assert "Email thread: UPI flow timeline" in llm.calls[0]["user"]
    assert "Sent at:" in llm.calls[0]["user"]
    assert "ONE email message" in llm.calls[0]["system"]
