"""FakeHive mirrors the substrate contract: board state machine and priority, supersede conflicts, skill ranking,
tenant meta, container_episodes, idempotent create_tenant, bounded stores."""

from __future__ import annotations

from collections import deque

import pytest

from apps.api.hive_adapter import FakeHive, HiveConflict, HiveNotFound
from apps.api.jobs import JobStore
from apps.api.state import AppContext


def test_next_open_task_priority_then_age_and_addressing(ctx):
    hive = ctx.hive
    low = hive.submit_task("orbit", "followup", {}, ["followup"], [], 2)
    high = hive.submit_task("orbit", "followup", {}, ["followup"], [], 9)
    assert hive.next_open_task("orbit", "followup_agent")["id"] == high
    hive.claim("orbit", high, "followup_agent", 0)
    assert hive.next_open_task("orbit", "followup_agent")["id"] == low
    # addressed tasks are visible only to the addressee, even without the capabilities
    addressed = hive.submit_task("orbit", "reschedule", {}, ["schedule"], [], 3, owner_agent="followup_agent")
    assert hive.next_open_task("orbit", "followup_agent")["id"] == addressed  # priority 3 beats 2
    assert hive.next_open_task("orbit", "scheduler_agent") is None
    assert hive.claim("orbit", addressed, "scheduler_agent", 0) is None
    assert hive.claim("orbit", addressed, "followup_agent", 0) == 1


def test_handoff_and_state_changes_require_a_working_owner(ctx):
    hive = ctx.hive
    task = hive.submit_task("orbit", "followup", {}, ["followup"], [], 5)
    assert hive.handoff("orbit", task, "followup_agent", "scheduler_agent", 0, "s", []) is None  # not claimed yet
    with pytest.raises(HiveNotFound):
        hive.fail("orbit", task, "followup_agent", "x")
    assert hive.claim("orbit", task, "followup_agent", 0) == 1
    assert hive.handoff("orbit", task, "scheduler_agent", "followup_agent", 1, "s", []) is None  # not the owner
    assert hive.handoff("orbit", task, "followup_agent", "scheduler_agent", 1, "needs a date", ["fact_x"]) == 2
    assert hive.get_task("orbit", task)["status"] == "submitted"
    assert hive.claim("orbit", task, "followup_agent", 2) is None  # addressed to the scheduler now
    assert hive.claim("orbit", task, "scheduler_agent", 2) == 3
    hive.complete("orbit", task, "scheduler_agent", None)
    assert hive.handoff("orbit", task, "scheduler_agent", "followup_agent", 4, "s", []) is None  # completed tasks are final
    with pytest.raises(HiveNotFound):
        hive.fail("orbit", task, "scheduler_agent", "too late")
    with pytest.raises(HiveNotFound):
        hive.need_input("orbit", task, "scheduler_agent", "?")


def test_supersede_conflicts(seeded):
    hive = seeded.hive
    head = next(f for f in hive.list_facts("orbit", status="active") if f["predicate"] == "due" and f["subject"].casefold() == "upi flow")
    base = {"kind": "commitment", "subject": head["subject"], "predicate": "due", "key": head["key"], "text": "x", "speaker_id": "spk_priya", "episode_id": head["episode_id"], "entity_ids": head["entity_ids"]}
    with pytest.raises(HiveConflict):
        hive.supersede_fact("orbit", head["id"], {**base, "object": head["object"], "valid_from": head["valid_from"] + 1})  # no-op
    with pytest.raises(HiveConflict):
        hive.supersede_fact("orbit", head["id"], {**base, "object": "2026-09-30", "valid_from": head["valid_from"] - 1})  # backdated
    with pytest.raises(HiveConflict):
        hive.supersede_fact("orbit", head["id"], {**base, "key": "other|due", "object": "2026-09-30", "valid_from": head["valid_from"] + 1})  # cross-key
    with pytest.raises(HiveNotFound):
        hive.supersede_fact("orbit", "fact_missing", {**base, "object": "2026-09-30"})
    result = hive.supersede_fact("orbit", head["id"], {**base, "object": "2026-09-30", "valid_from": head["valid_from"] + 1})
    assert hive.get_fact("orbit", head["id"])["status"] == "superseded" and hive.get_fact("orbit", result["id"])["status"] == "active"


def test_retrieve_skill_ranks_similarity_times_success(ctx):
    hive = ctx.hive
    close = [1.0] + [0.0] * 767
    far = [0.0, 1.0] + [0.0] * 766
    new_close = hive.learn_skill("orbit", "run the orbit standup", [{"tool": "recall"}], [], close)
    old_far = hive.learn_skill("orbit", "unrelated routine", [{"tool": "recall"}], [], far)
    hive.record_outcome("orbit", old_far, "standup_agent", True)
    ranked = hive.retrieve_skill("orbit", close, k=2)
    assert [s["id"] for s in ranked] == [new_close, old_far]
    assert ranked[0]["score"] == pytest.approx(0.5) and ranked[1]["score"] == pytest.approx(0.0)
    hive.record_outcome("orbit", new_close, "standup_agent", True)
    assert hive.retrieve_skill("orbit", close, k=1)[0]["score"] == pytest.approx(1.0)


def test_tenant_meta_and_idempotent_create(ctx):
    hive = ctx.hive
    assert hive.get_tenant_meta("orbit") == {}
    assert hive.set_tenant_meta("orbit", {"api_key_hash": "h1"}) == {"api_key_hash": "h1"}
    hive.set_tenant_meta("orbit", {"embedding_model": "fake:x"})
    assert hive.get_tenant_meta("orbit") == {"api_key_hash": "h1", "embedding_model": "fake:x"}
    hive.create_tenant("orbit", "Renamed")
    assert hive.tenant_info("orbit")["display_name"] == "Orbit" and hive.get_tenant_meta("orbit")["api_key_hash"] == "h1"
    hive.create_tenant("orbit", "Renamed", rotate=True)
    assert hive.tenant_info("orbit")["display_name"] == "Renamed"
    assert "api_key_hash" not in hive.tenant_info("orbit")["meta"]
    hive.delete_tenant("orbit")
    assert hive.get_tenant_meta("orbit") == {} and "orbit" not in hive.list_tenants()


def test_container_episodes(seeded):
    rows = seeded.hive.container_episodes("orbit", "mtg_orbit_001")
    assert [r["seq"] for r in rows] == sorted(r["seq"] for r in rows) and len(rows) >= 4
    assert set(rows[0]) == {"id", "seq", "t_start", "t_end", "speaker_id", "text_hash"}
    assert rows[0]["speaker_id"] == "spk_aditya" and len(rows[0]["text_hash"]) == 16
    thread = seeded.hive.container_episodes("orbit", "thr_orbit_001")
    assert len(thread) == 2 and thread[0]["speaker_id"] == "spk_priya"
    assert seeded.hive.container_episodes("orbit", "nope") == []


def test_bounded_stores(data_dir):
    jobs = JobStore(max_jobs=3)
    ids = [jobs.create("orbit", "meeting", f"m{i}") for i in range(3)]
    for jid in ids[:2]:
        jobs.run_sync(jid, lambda progress: {"episodes": 1})
    jobs.create("orbit", "meeting", "m3")
    jobs.create("orbit", "meeting", "m4")
    assert len(jobs) == 3 and jobs.get(ids[0]) is None and jobs.get(ids[2]) is not None  # queued jobs are never evicted
    ctx = AppContext(settings=None, hive=FakeHive(), llm=None, embedder=None)  # type: ignore[arg-type]
    assert isinstance(ctx.bench_results, deque) and ctx.bench_results.maxlen == 100
    for i in range(150):
        ctx.bench_results.append({"run_id": str(i)})
    assert len(ctx.bench_results) == 100 and ctx.bench_results[0]["run_id"] == "50"
