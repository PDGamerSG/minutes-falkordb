"""Pipeline end to end with FakeLLM + MemoryHive + FakeEmbedder."""

from __future__ import annotations

import copy
import json

import pytest
from ingest.embed import Embedder
from ingest.extract import GoldExtractor, heuristic_supersession, make_extractor
from ingest.fakes import FACT_SUPERSEDED_KEYS, MemoryHive
from ingest.gold import GoldFile
from ingest.llm_protocol import FakeLLM
from ingest.models import ExtractedFact, SupersessionVerdict, fact_id_for
from ingest.pipeline import EmbeddingModelMismatch, SourceChangedError, _hinted_target, run

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

IST_MIDNIGHT_SEP_24 = 1790208000000 - 19_800_000  # 2026-09-24T00:00+05:30


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
    assert stats["extraction_calls"] == 3 and stats["skipped_episodes"] == 0

    assert hive.get_meeting("orbit", "mtg_orbit_001")["source_uri"] == "data/meetings/orbit_001.wav"
    assert {p["id"] for p in hive.list_persons("orbit")} == {"spk_aditya", "spk_priya"}
    episodes = hive.meeting_episodes("orbit", "mtg_orbit_001")
    assert len(episodes) == 3 and len(episodes[0]["embedding"]) == 768

    # known vocabulary names keep their spelling; unknown names are title-cased
    names = {e["name"] for e in hive.list_entities("orbit")}
    assert {"October release", "UPI flow", "Rahul", "Payment Gateway"} <= names

    facts = hive.active_facts("orbit")
    assert len(facts) == 4
    commitment = next(f for f in facts if f["kind"] == "commitment")
    assert commitment["object"] == "the 24th" and commitment["due_at"] == IST_MIDNIGHT_SEP_24
    assert commitment["valid_from"] == episodes[1]["t_occurred"]
    assert commitment["speaker_id"] == "spk_priya" and commitment["episode_id"] == episodes[1]["id"]
    assert "ent_upi_flow" in commitment["entity_ids"]
    assert commitment["id"] == fact_id_for("ep_mtg_orbit_001_001", "upi flow|due", "the 24th")
    assert commitment["id"].startswith("fact_ep_mtg_orbit_001_001_") and len(commitment["id"].rsplit("_", 1)[1]) == 8

    events = [e["event"] for e in hive.events["orbit"]]
    assert events.count("episode.ingested") == 1  # once per stored batch, never per episode
    assert events.count("fact.created") == 4 and events.count("commitment.created") == 1
    assert all(len(llm.calls[i]["system"]) > 100 for i in range(3))
    assert "Calendar" in llm.calls[0]["user"] and "Mon 2026-09-07" in llm.calls[0]["user"]


def test_due_dates_use_the_tenant_timezone(sample_meeting):
    hive = MemoryHive()
    _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting, timezone="UTC")
    commitment = next(f for f in hive.active_facts("orbit") if f["kind"] == "commitment")
    assert commitment["due_at"] == 1790208000000


def test_prior_facts_are_offered_to_the_model(sample_meeting):
    hive = MemoryHive()
    llm = FakeLLM([EP0, EP1, EP2])
    _run(hive, llm, sample_meeting)
    first_prompt = llm.calls[0]["user"]
    assert "Prior active facts" in first_prompt and "- none" in first_prompt
    # the second episode says "Payments go first": the scope decision about payments is offered
    second_prompt = llm.calls[1]["user"]
    assert "October release | scope_includes | payments" in second_prompt
    # the third episode (Razorpay gateway) shares no words with the stored facts
    assert "- none" in llm.calls[2]["user"]


class _CappedHive(MemoryHive):
    """Like the real adapter: an unfiltered active_facts read is capped, entity-scoped reads are not."""

    def active_facts(self, tenant, entity_id=None, key=None):
        rows = super().active_facts(tenant, entity_id, key)
        return rows[:200] if entity_id is None and key is None else rows


def test_prior_facts_are_key_scoped_beyond_the_read_cap(sample_meeting):
    hive = _CappedHive()
    hive.upsert_entities("orbit", [{"id": "ent_upi_flow", "name": "UPI flow", "type": "feature"}])
    hive.remember_fact("orbit", {"id": "f_upi", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "entity_ids": ["ent_upi_flow"], "valid_from": 1, "speaker_id": "spk_priya"})
    for n in range(250):
        hive.remember_fact("orbit", {"id": f"f_{n}", "subject": f"filler {n}", "predicate": "status", "object": "active", "entity_ids": [f"ent_filler_{n}"], "valid_from": 2 + n})
    llm = FakeLLM([EP0, EP1, EP2])
    _run(hive, llm, sample_meeting, window_episodes=1)
    assert "UPI flow | due | 2026-09-24" in llm.calls[1]["user"]


def test_known_entities_come_from_the_graph(sample_meeting):
    hive = MemoryHive()
    hive.upsert_entities("orbit", [{"id": "ent_zephyr_portal", "name": "Zephyr portal", "type": "topic"}])
    llm = FakeLLM([{"items": []}])
    _run(hive, llm, sample_meeting, extractor=make_extractor(llm))
    assert "- Zephyr portal" in llm.calls[0]["user"]


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
    assert set(payload) == FACT_SUPERSEDED_KEYS
    assert payload["old_fact_id"] == old["id"] and payload["new_fact_id"] == active[0]["id"]
    assert payload["old_fact_ids"] == [old["id"]] and payload["old_object"] == "the 24th"
    assert payload["predicate"] == "due" and payload["new_object"] == "2026-09-26" and payload["head_changed"] is True
    assert payload["tenant"] == "orbit" and payload["episode_id"] == active[0]["episode_id"]
    assert any(e["event"] == "commitment.updated" for e in hive.events["orbit"])


class _QuietHive(MemoryHive):
    """A hive that does not publish memory events itself (the pipeline publishes for it)."""

    publishes_memory_events = False


def _supersession_scenario(hive, sample_meeting):
    _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    later = copy.deepcopy(sample_meeting)
    later["meeting"].update({"id": "mtg_orbit_002", "started_at": "2026-09-14T10:00:00+05:30", "ended_at": None})
    later["segments"] = [{"start_ms": 0, "end_ms": 9000, "speaker_id": "spk_priya", "text": "The UPI flow slips, move it to Friday the 26th."}]
    moved = {"items": [{"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-26", "text": "moved"}]}
    _run(hive, FakeLLM([moved, {"verdict": "contradiction"}]), later)
    return [(e["event"], tuple(sorted(e["payload"]))) for e in hive.events["orbit"]]


def test_event_parity_between_hive_and_pipeline_publishers(sample_meeting):
    """Exactly one publisher either way, same event sequence, same payload shapes."""
    own = _supersession_scenario(MemoryHive(), sample_meeting)
    via_pipeline = _supersession_scenario(_QuietHive(), sample_meeting)
    assert own == via_pipeline
    names = [name for name, _ in own]
    assert names.count("episode.ingested") == 2 and names.count("fact.superseded") == 1
    superseded_keys = next(keys for name, keys in own if name == "fact.superseded")
    assert set(superseded_keys) == FACT_SUPERSEDED_KEYS


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


def test_hinted_target_picks_the_named_old_object():
    active = [
        {"id": "a", "object": "weekly on Thursdays", "valid_from": 1},
        {"id": "b", "object": "no sponsors until 5000 subscribers", "valid_from": 2},
        {"id": "c", "object": "weekly on Tuesdays", "valid_from": 3},
    ]
    assert _hinted_target(active, "replaces: newsletter decided weekly on Thursdays")["id"] == "a"
    assert _hinted_target(active, json.dumps({"subject": "newsletter", "predicate": "decided", "object": "weekly on Thursdays"}))["id"] == "a"
    # a hint that names only the key falls back to the latest active fact
    assert _hinted_target(active, "replaces: newsletter decided")["id"] == "c"
    assert _hinted_target(active, json.dumps({"subject": "newsletter", "predicate": "decided"}))["id"] == "c"
    assert _hinted_target([], "anything") is None


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


def test_reimport_skips_episodes_that_already_have_facts(sample_meeting):
    hive = MemoryHive()
    _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    before = {f["id"]: dict(f) for f in hive.active_facts("orbit")}
    llm = FakeLLM([])  # no model call may happen for the three already-extracted episodes
    stats = _run(hive, llm, sample_meeting)
    assert llm.calls == [] and stats["skipped_episodes"] == 3 and stats["items"] == 0 and stats["failed_episodes"] == []
    assert {f["id"]: dict(f) for f in hive.active_facts("orbit")} == before
    assert len(hive.meeting_episodes("orbit", "mtg_orbit_001")) == 3
    assert [e["event"] for e in hive.events["orbit"]].count("episode.ingested") == 2


def test_reimport_without_skipping_confirms_instead_of_duplicating(sample_meeting):
    hive = MemoryHive()
    _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    stats = _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting, skip_extracted=False)
    assert stats["duplicates"] == 4 and stats["items"] == 0
    assert len(hive.active_facts("orbit")) == 4


def test_reimport_with_a_different_extraction_never_rewrites_a_fact(sample_meeting):
    """Content-derived ids: a different triple from the same episode gets a new node, the old one stays."""
    hive = MemoryHive()
    _run(hive, FakeLLM([EP0, {"items": []}, {"items": []}]), sample_meeting)
    original = hive.active_facts("orbit")[0]
    other = {"items": [{"kind": "decision", "subject": "October release", "predicate": "owner", "object": "Aditya", "text": "Aditya owns the release"}]}
    _run(hive, FakeLLM([other, {"items": []}, {"items": []}]), sample_meeting, skip_extracted=False)
    kept = hive.get_fact("orbit", original["id"])
    assert kept["key"] == "october release|scope_includes" and kept["object"] == "payments" and kept["status"] == "active"
    new = [f for f in hive.active_facts("orbit") if f["id"] != original["id"]]
    assert len(new) == 1 and new[0]["key"] == "october release|owner" and new[0]["episode_id"] == original["episode_id"]
    assert new[0]["id"] != original["id"] and new[0]["id"].startswith("fact_ep_mtg_orbit_001_000_")


def test_changed_source_is_refused(sample_meeting):
    hive = MemoryHive()
    _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    changed = copy.deepcopy(sample_meeting)
    changed["segments"][3]["text"] = "Good. We go with PayU for the gateway."
    with pytest.raises(SourceChangedError, match=r"source_changed.*seq 2.*new container id") as info:
        _run(hive, FakeLLM([EP0, EP1, EP2]), changed)
    assert info.value.code == "source_changed"
    # re-chunking (a segment split differently) is a changed source too
    rechunked = copy.deepcopy(sample_meeting)
    rechunked["segments"][1:3] = [{"start_ms": 6400, "end_ms": 20000, "speaker_id": "spk_priya", "text": "Payments go first. I can have the UPI flow done by the 24th. I will need the sandbox keys from Rahul before then."}]
    _run(hive, FakeLLM([]), rechunked)  # same episodes after chunking: still idempotent
    rechunked["segments"].append({"start_ms": 24000, "end_ms": 30000, "speaker_id": "spk_aditya", "text": "One more thing."})
    with pytest.raises(SourceChangedError, match="seq 2"):
        _run(hive, FakeLLM([]), rechunked)
    assert len(hive.meeting_episodes("orbit", "mtg_orbit_001")) == 3 and len(hive.active_facts("orbit")) == 4


class _ContractHive(MemoryHive):
    """Serves ``container_episodes`` exactly in the contract shape (the API's RealHive): no text, no fact_count."""

    def container_episodes(self, tenant, container_id):
        keys = ("id", "seq", "t_start", "t_end", "speaker_id", "text_hash")
        return [{k: row[k] for k in keys} for row in super().container_episodes(tenant, container_id)]


def test_contract_shaped_container_episodes_rows_drive_the_reimport_checks(sample_meeting):
    hive = _ContractHive()
    _run(hive, FakeLLM([EP0, {"items": []}, EP2]), sample_meeting)  # episode 1 yields nothing: it must be re-extracted
    llm = FakeLLM([EP1])
    stats = _run(hive, llm, sample_meeting)
    assert stats["skipped_episodes"] == 2 and stats["failed_episodes"] == [] and len(llm.calls) == 1
    assert len(hive.meeting_episodes("orbit", "mtg_orbit_001")) == 3
    changed = copy.deepcopy(sample_meeting)
    changed["segments"][3]["text"] = "Good. We go with PayU for the gateway."
    with pytest.raises(SourceChangedError, match="seq 2"):
        _run(hive, FakeLLM([]), changed)


class _FailingHive(MemoryHive):
    def remember_fact(self, tenant, fact, supersede=False):
        if fact.get("key") == "upi flow|due":
            raise RuntimeError("simulated conflict on upi flow|due")
        return super().remember_fact(tenant, fact, supersede)


def test_item_failure_is_recorded_and_the_import_continues(sample_meeting):
    hive = _FailingHive()
    stats = _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    episodes = hive.meeting_episodes("orbit", "mtg_orbit_001")
    assert stats["failed_episodes"] == [episodes[1]["id"]]
    assert any("simulated conflict" in e for e in stats["errors"])
    assert stats["items"] == 3  # the other item of episode 1 and the facts of episodes 0 and 2 are stored
    assert {f["key"] for f in hive.active_facts("orbit")} == {"october release|scope_includes", "upi flow|blocked_by", "payment gateway|decided"}
    # a retry re-runs the model only for the episode that has no facts yet
    hive2 = MemoryHive()
    _run(hive2, FakeLLM([EP0, {"items": []}, EP2]), sample_meeting)
    retry = FakeLLM([EP1])
    stats = _run(hive2, retry, sample_meeting)
    assert len(retry.calls) == 1 and stats["skipped_episodes"] == 2 and stats["commitments"] == 1


def test_late_import_inserts_mid_chain_without_waking_the_scheduler(sample_meeting):
    hive = MemoryHive()
    _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)  # Sep 7: the 24th
    head_move = {"items": [{"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-28", "text": "moved to the 28th"}]}
    _run(hive, FakeLLM([head_move, {"verdict": "contradiction"}]), _later(sample_meeting, "mtg_orbit_004", "2026-09-21T10:00:00+05:30"))
    head = hive.active_facts("orbit", key="upi flow|due")[0]
    assert head["object"] == "2026-09-28"
    events_before = len(hive.events["orbit"])

    # a late import of an earlier meeting restating the head: confirmed, never self-superseded
    restated = {"items": [{"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-28", "text": "the 28th"}]}
    stats = _run(hive, FakeLLM([restated]), _later(sample_meeting, "mtg_orbit_003", "2026-09-14T10:00:00+05:30"))
    assert stats["duplicates"] == 1 and stats["items"] == 0
    assert [f["object"] for f in hive.active_facts("orbit", key="upi flow|due")] == ["2026-09-28"]
    assert "ep_mtg_orbit_003_000" in hive.get_fact("orbit", head["id"])["confirmed_by"]

    # a late import with a different earlier value slots in below the head; the belief now does not change
    mid = {"items": [{"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-26", "text": "the 26th"}]}
    stats = _run(hive, FakeLLM([mid, {"verdict": "contradiction"}]), _later(sample_meeting, "mtg_orbit_002b", "2026-09-16T10:00:00+05:30"))
    assert stats["superseded"] == 1 and stats["commitments"] == 1
    chain = hive.facts_by_key("orbit", "upi flow|due")
    assert [f["object"] for f in chain] == ["the 24th", "2026-09-26", "2026-09-28"]
    assert [f["status"] for f in chain] == ["superseded", "superseded", "active"]
    assert chain[1]["valid_to"] == chain[2]["valid_from"] and chain[0]["valid_to"] == chain[1]["valid_from"]
    assert hive.get_fact("orbit", head["id"])["supersedes"] == [chain[1]["id"]] and chain[1]["supersedes"] == [chain[0]["id"]]
    assert not any(e["event"] in ("fact.superseded", "fact.created") for e in hive.events["orbit"][events_before:])


def test_embedding_model_is_recorded_and_mismatches_are_refused(sample_meeting):
    hive = MemoryHive()
    _run(hive, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    assert hive.get_tenant_meta("orbit") == {"embedding_model": "fake:fake-hashed-bow-768", "embedding_dim": 768}
    other = MemoryHive()
    other.set_tenant_meta("orbit", {"embedding_model": "onnx:onnx-community/embeddinggemma-300m-ONNX"})
    with pytest.raises(EmbeddingModelMismatch, match="embedding_model_mismatch") as info:
        _run(other, FakeLLM([EP0, EP1, EP2]), sample_meeting)
    assert info.value.code == "embedding_model_mismatch"
    assert other.meeting_episodes("orbit", "mtg_orbit_001") == []


def test_dialogue_window_extraction_keeps_per_episode_provenance(sample_meeting):
    hive = MemoryHive()
    window = {
        "entities": [{"name": "October release", "type": "project"}],
        "items": [
            {"kind": "decision", "subject": "October release", "predicate": "scope_includes", "object": "payments", "text": "Aditya scoped payments.", "speaker_id": "spk_aditya", "episode": 1},
            {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "text": "Priya will have the UPI flow done by the 24th.", "speaker_id": "spk_priya", "episode": 2},
            # no episode number: routed to the speaker's episode with the most shared words (the Razorpay line)
            {"kind": "decision", "subject": "payment gateway", "predicate": "uses_vendor", "object": "Razorpay", "text": "Aditya chose Razorpay for the gateway.", "speaker_id": "spk_aditya"},
        ],
    }
    llm = FakeLLM([window])
    stats = _run(hive, llm, sample_meeting, extractor=make_extractor(llm))
    assert stats["extraction_calls"] == 1 and len(llm.calls) == 1 and stats["items"] == 3
    prompt = llm.calls[0]["user"]
    assert "[1] Aditya (spk_aditya, lead)" in prompt and "[2] Priya (spk_priya, backend)" in prompt and "[3] Aditya" in prompt
    assert "speaker_id" in prompt and "Known entities" in prompt
    by_key = {f["key"]: f for f in hive.active_facts("orbit")}
    assert by_key["october release|scope_includes"]["episode_id"] == "ep_mtg_orbit_001_000"
    assert by_key["october release|scope_includes"]["speaker_id"] == "spk_aditya"
    assert by_key["upi flow|due"]["episode_id"] == "ep_mtg_orbit_001_001" and by_key["upi flow|due"]["speaker_id"] == "spk_priya"
    assert by_key["payment gateway|uses_vendor"]["episode_id"] == "ep_mtg_orbit_001_002"
    assert by_key["upi flow|due"]["valid_from"] == hive.meeting_episodes("orbit", "mtg_orbit_001")[1]["t_occurred"]


def test_windows_are_off_for_gold_replay_and_configurable(sample_meeting, sample_gold):
    gold = GoldFile.model_validate(sample_gold)
    stats = _run(MemoryHive(), None, sample_meeting, extractor=GoldExtractor(gold))
    assert stats["extraction_calls"] == 3
    llm = FakeLLM([{"items": []}, {"items": []}, {"items": []}])
    stats = _run(MemoryHive(), llm, sample_meeting, extractor=make_extractor(llm), window_episodes=1)
    assert stats["extraction_calls"] == 3 and len(llm.calls) == 3


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
    assert {f["subject"] for f in facts} == {"October release", "UPI flow", "Payment Gateway"}


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
