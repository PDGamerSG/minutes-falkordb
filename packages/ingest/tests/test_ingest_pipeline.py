"""Pipeline end to end with FakeLLM + MemoryHive + FakeEmbedder."""

from __future__ import annotations

import copy

from ingest.embed import Embedder
from ingest.extract import GoldExtractor, heuristic_supersession
from ingest.fakes import MemoryHive
from ingest.gold import GoldFile
from ingest.llm_protocol import FakeLLM
from ingest.models import ExtractedFact, SupersessionVerdict
from ingest.pipeline import run

EP0 = {
    "entities": [{"name": "October release", "type": "project"}],
    "items": [
        {
            "kind": "decision",
            "subject": "October release",
            "predicate": "scope_includes",
            "object": "payments",
            "text": "Aditya locked payments into the October release scope",
            "confidence": 0.9,
        }
    ],
}
EP1 = {
    "entities": [{"name": "UPI flow", "type": "feature"}, {"name": "Rahul", "type": "person"}],
    "items": [
        {
            "kind": "commitment",
            "subject": "UPI flow",
            "predicate": "due",
            "object": "the 24th",
            "due_at": "2026-09-24",
            "text": "Priya will have the UPI flow done by the 24th",
            "confidence": 0.9,
        },
        {"kind": "fact", "subject": "UPI flow", "predicate": "blocked_by", "object": "sandbox keys", "text": "needs keys from Rahul"},
        {"kind": "fact", "subject": "", "predicate": "", "object": "", "text": "invalid item dropped"},
    ],
}
EP2 = {
    "entities": [{"name": "Payment gateway", "type": "system"}],
    "items": [
        {"kind": "decision", "subject": "Payment gateway", "predicate": "decided", "object": "Razorpay", "text": "We go with Razorpay", "confidence": 0.95}
    ],
}


def _run(hive, llm, meeting, **kwargs):
    return run(meeting, "orbit", hive, llm, Embedder(backend="fake"), **kwargs)


def test_pipeline_stores_episodes_entities_and_facts(sample_meeting):
    hive = MemoryHive()
    llm = FakeLLM([EP0, EP1, EP2])
    stats = _run(hive, llm, sample_meeting)

    assert stats["episodes"] == 3
    assert stats["facts"] == 1 and stats["decisions"] == 2 and stats["commitments"] == 1
    assert stats["proposed"] == 5 and stats["dropped"] == 1 and stats["drop_rate"] == 0.2
    assert stats["superseded"] == 0 and stats["errors"]

    assert hive.get_meeting("orbit", "mtg_orbit_001")["source_uri"] == "data/meetings/orbit_001.wav"
    assert {p["id"] for p in hive.list_persons("orbit")} == {"spk_aditya", "spk_priya"}
    episodes = hive.meeting_episodes("orbit", "mtg_orbit_001")
    assert len(episodes) == 3 and len(episodes[0]["embedding"]) == 768

    names = {e["name"] for e in hive.list_entities("orbit")}
    assert {"October Release", "UPI Flow", "Rahul", "Payment Gateway"} <= names

    facts = hive.active_facts("orbit")
    assert len(facts) == 4
    commitment = next(f for f in facts if f["kind"] == "commitment")
    assert commitment["object"] == "the 24th" and commitment["due_at"] == 1790208000000
    assert commitment["valid_from"] == episodes[1]["t_occurred"]
    assert commitment["speaker_id"] == "spk_priya" and commitment["episode_id"] == episodes[1]["id"]
    assert "ent_upi_flow" in commitment["entity_ids"]
    assert commitment["id"] == "fact_ep_mtg_orbit_001_001_00"

    events = [e["event"] for e in hive.events["orbit"]]
    assert events.count("episode.ingested") == 3
    assert events.count("fact.created") == 4 and events.count("commitment.created") == 1
    assert all(len(llm.calls[i]["system"]) > 100 for i in range(3))
    assert "Calendar" in llm.calls[0]["user"] and "Mon 2026-09-07" in llm.calls[0]["user"]


def test_prior_facts_are_offered_to_the_model(sample_meeting):
    hive = MemoryHive()
    llm = FakeLLM([EP0, EP1, EP2])
    _run(hive, llm, sample_meeting)
    first_prompt = llm.calls[0]["user"]
    assert "Prior active facts" in first_prompt and "- none" in first_prompt
    # the second episode says "Payments go first": the scope decision about payments is offered
    second_prompt = llm.calls[1]["user"]
    assert "October Release | scope_includes | payments" in second_prompt
    # the third episode (Razorpay gateway) shares no words with the stored facts
    assert "- none" in llm.calls[2]["user"]


def test_supersession_contradiction_expires_old_fact(sample_meeting):
    hive = MemoryHive()
    _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    old = next(f for f in hive.active_facts("orbit") if f["kind"] == "commitment")

    later = copy.deepcopy(sample_meeting)
    later["meeting"].update({"id": "mtg_orbit_002", "title": "Orbit standup 1", "started_at": "2026-09-14T10:00:00+05:30", "ended_at": None})
    later["segments"] = [
        {"start_ms": 0, "end_ms": 9000, "speaker_id": "spk_priya", "text": "The UPI flow slips, move it to Friday the 26th."}
    ]
    moved = {
        "entities": [{"name": "UPI flow", "type": "feature"}],
        "items": [
            {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-26", "text": "Priya moved the UPI flow to Friday the 26th", "supersedes_hint": "replaces: UPI flow due 2026-09-24"}
        ],
    }
    llm = FakeLLM([moved, SupersessionVerdict(verdict="contradiction", reason="date moved")])
    stats = _run(hive, llm, later)

    assert stats["superseded"] == 1 and stats["commitments"] == 1
    assert llm.calls[1]["schema"] == "SupersessionVerdict"
    active = hive.active_facts("orbit", key="upi flow|due")
    assert len(active) == 1 and active[0]["object"] == "2026-09-26"
    assert active[0]["supersedes"] == [old["id"]]
    expired = hive.get_fact("orbit", old["id"])
    assert expired["status"] == "superseded" and expired["valid_to"] == active[0]["valid_from"]

    # belief at time T: before the standup the old date held, after it the new one
    before = hive.belief_at("orbit", active[0]["valid_from"] - 1, entity_id="ent_upi_flow")
    after = hive.belief_at("orbit", active[0]["valid_from"] + 1, entity_id="ent_upi_flow")
    assert {f["object"] for f in before if f["predicate"] == "due"} == {"the 24th"}
    assert {f["object"] for f in after if f["predicate"] == "due"} == {"2026-09-26"}

    why = hive.why("orbit", active[0]["id"])
    assert [h["id"] for h in why["history"]] == [old["id"]]
    assert why["speaker"]["name"] == "Priya" and why["meeting"]["title"] == "Orbit standup 1"
    assert why["source"]["kind"] == "utterance" and why["source"]["t_start"] == 0
    assert any(e["type"] == "SUPERSEDES" for e in why["subgraph"]["edges"])

    events = [e for e in hive.events["orbit"] if e["event"] == "fact.superseded"]
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["old_fact_id"] == old["id"] and payload["new_fact_id"] == active[0]["id"]
    assert payload["predicate"] == "due" and payload["new_object"] == "2026-09-26"
    assert any(e["event"] == "commitment.updated" for e in hive.events["orbit"])


def _later(sample_meeting, meeting_id: str, started_at: str):
    later = copy.deepcopy(sample_meeting)
    later["meeting"].update({"id": meeting_id, "started_at": started_at, "ended_at": None})
    later["segments"] = later["segments"][:1]
    return later


def test_multi_valued_predicate_adds_a_value_without_the_judge(sample_meeting):
    hive = MemoryHive()
    _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    more = {"items": [{"kind": "decision", "subject": "October release", "predicate": "scope_includes", "object": "refunds", "text": "scope also includes refunds"}]}
    llm = FakeLLM([more])
    stats = _run(hive, llm, _later(sample_meeting, "mtg_orbit_003", "2026-09-21T10:00:00+05:30"))
    assert stats["superseded"] == 0 and stats["decisions"] == 1
    assert [c["kind"] for c in llm.calls] == ["complete_json"]  # extraction only, no supersession judge
    active = hive.active_facts("orbit", key="october release|scope_includes")
    assert sorted(f["object"] for f in active) == ["payments", "refunds"]


def test_lessons_and_requirements_do_not_supersede_each_other(sample_meeting):
    hive = MemoryHive()
    lessons = {
        "items": [
            {"kind": "decision", "subject": "Orbit", "predicate": "lesson", "object": "confirm vendor constraints first", "text": "l1"},
            {"kind": "decision", "subject": "Orbit", "predicate": "requires", "object": "Meridian accessibility checklist", "text": "r1"},
        ]
    }
    more = {
        "items": [
            {"kind": "decision", "subject": "Orbit", "predicate": "lesson", "object": "record the rationale", "text": "l2"},
            {"kind": "fact", "subject": "Orbit", "predicate": "requires", "object": "data residency in India", "text": "r2"},
        ]
    }
    _run(hive, FakeLLM([lessons, {"items": []}, {"items": []}]), sample_meeting)
    stats = _run(hive, FakeLLM([more]), _later(sample_meeting, "mtg_orbit_005", "2026-09-23T10:00:00+05:30"))
    assert stats["superseded"] == 0
    assert len(hive.active_facts("orbit", key="orbit|lesson")) == 2
    assert len(hive.active_facts("orbit", key="orbit|requires")) == 2


def test_multi_valued_predicate_supersedes_only_with_a_hint(sample_meeting):
    hive = MemoryHive()
    first = {"items": [{"kind": "decision", "subject": "newsletter", "predicate": "decided", "object": "weekly on Thursdays", "text": "Thursdays"}]}
    _run(hive, FakeLLM([first, {"items": []}, {"items": []}]), sample_meeting)
    moved = {
        "items": [
            {"kind": "decision", "subject": "newsletter", "predicate": "decided", "object": "weekly on Tuesdays", "text": "Tuesdays", "supersedes_hint": "replaces: newsletter decided weekly on Thursdays"},
            {"kind": "decision", "subject": "newsletter", "predicate": "decided", "object": "no sponsors until 5000 subscribers", "text": "no sponsors"},
        ]
    }
    stats = _run(hive, FakeLLM([moved, {"verdict": "contradiction", "reason": "day moved"}]), _later(sample_meeting, "mtg_quill_002", "2026-09-16T10:00:00+05:30"))
    assert stats["superseded"] == 1
    active = sorted(f["object"] for f in hive.active_facts("orbit", key="newsletter|decided"))
    assert active == ["no sponsors until 5000 subscribers", "weekly on Tuesdays"]


def test_refinement_keeps_both_with_precedent(sample_meeting):
    hive = MemoryHive()
    first = {"items": [{"kind": "decision", "subject": "offline mode", "predicate": "uses_pattern", "object": "SQLite cache", "text": "SQLite cache"}]}
    _run(hive, FakeLLM([first, {"items": []}, {"items": []}]), sample_meeting)
    refine = {"items": [{"kind": "decision", "subject": "offline mode", "predicate": "uses_pattern", "object": "SQLite cache with sync queue", "text": "adds the sync queue"}]}
    stats = _run(hive, FakeLLM([refine, {"verdict": "refinement"}]), _later(sample_meeting, "mtg_orbit_003", "2026-09-21T10:00:00+05:30"))
    assert stats["refinements"] == 1 and stats["superseded"] == 0
    active = hive.active_facts("orbit", key="offline mode|uses_pattern")
    assert len(active) == 2
    newer = max(active, key=lambda f: f["valid_from"])
    assert newer["precedent_ids"] == [min(active, key=lambda f: f["valid_from"])["id"]]


def test_reimport_is_idempotent(sample_meeting):
    hive = MemoryHive()
    _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    stats = _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    assert stats["duplicates"] == 4 and stats["items"] == 0
    assert len(hive.active_facts("orbit")) == 4
    assert len(hive.meeting_episodes("orbit", "mtg_orbit_001")) == 3


def test_model_failure_is_logged_not_fatal(sample_meeting, caplog):
    hive = MemoryHive()
    with caplog.at_level("ERROR"):
        stats = _run(hive, FakeLLM([]), sample_meeting)
    assert stats["items"] == 0 and len(stats["errors"]) == 3
    assert stats["failed_episodes"] == [e["id"] for e in hive.meeting_episodes("orbit", "mtg_orbit_001")]
    assert "extraction failed" in caplog.text
    assert len(hive.meeting_episodes("orbit", "mtg_orbit_001")) == 3


def test_gold_extractor_and_heuristic_judge(sample_meeting, sample_gold):
    hive = MemoryHive()
    stats = _run(hive, None, sample_meeting, extractor=GoldExtractor(GoldFile.model_validate(sample_gold)), judge=heuristic_supersession)
    assert stats["decisions"] == 2 and stats["commitments"] == 1 and stats["dropped"] == 0
    facts = hive.active_facts("orbit")
    assert {f["subject"] for f in facts} == {"October Release", "UPI Flow", "Payment Gateway"}


def test_heuristic_judge_rules():
    new_date = ExtractedFact(kind="commitment", subject="x", predicate="due", object="2026-09-26", text="t")
    assert heuristic_supersession({"object": "2026-09-24"}, new_date).verdict == "contradiction"
    wider = ExtractedFact(subject="x", predicate="scope", object="payments and refunds", text="t")
    assert heuristic_supersession({"object": "payments"}, wider).verdict == "refinement"
    other = ExtractedFact(subject="x", predicate="owner", object="Priya", text="t")
    assert heuristic_supersession({"object": "Aditya"}, other).verdict == "contradiction"


def test_progress_callback_reports_stages(sample_meeting):
    seen = []
    _run(MemoryHive(), FakeLLM([EP0, EP1, EP2]), sample_meeting, progress=lambda stage, p: seen.append((stage, p)))
    assert seen[0][0] == "validating" and seen[-1] == ("done", 1.0)
    assert all(0 <= p <= 1 for _, p in seen)
