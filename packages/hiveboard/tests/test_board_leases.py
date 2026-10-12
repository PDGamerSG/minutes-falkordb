"""Finding 5 and the lease/reaper: the board state machine is enforced in Cypher."""

import hiveboard as hb
import pytest


@pytest.fixture
def agents(db, tenant):
    hb.register_agent(db, tenant, "agt_a", "A", ["followup"], "m")
    hb.register_agent(db, tenant, "agt_b", "B", ["followup"], "m")
    return ["agt_a", "agt_b"]


def _row(db, tenant, task):
    return db.graph(tenant).query(
        "MATCH (t:Task {id: $id}) RETURN t.status, t.version, t.owner_agent, t.lease_until", {"id": task}
    ).result_set[0]


def test_terminal_tasks_cannot_be_handed_off_failed_or_parked(db, tenant, agents):
    task = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    hb.claim(db, tenant, task, "agt_a", 0)
    hb.complete(db, tenant, task, "agt_a")
    assert hb.handoff(db, tenant, task, "agt_a", "agt_b", 2, "late", []) is None
    with pytest.raises(hb.NotFound):
        hb.fail(db, tenant, task, "agt_a", "too late")
    with pytest.raises(hb.NotFound):
        hb.need_input(db, tenant, task, "agt_a", "really?")
    assert _row(db, tenant, task)[:2] == ["completed", 2]
    # a submitted task (never claimed) cannot be handed off or failed either
    fresh = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    assert hb.handoff(db, tenant, fresh, "agt_a", "agt_b", 0, "x", []) is None
    with pytest.raises(hb.NotFound):
        hb.fail(db, tenant, fresh, "agt_a", "x")
    assert _row(db, tenant, fresh)[:2] == ["submitted", 0]


def test_parked_task_can_be_failed_but_not_handed_off(db, tenant, agents):
    task = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    hb.claim(db, tenant, task, "agt_a", 0)
    hb.need_input(db, tenant, task, "agt_a", "which repo?")
    assert _row(db, tenant, task)[0] == "input_required" and _row(db, tenant, task)[3] is None
    assert hb.handoff(db, tenant, task, "agt_a", "agt_b", 2, "x", []) is None
    hb.fail(db, tenant, task, "agt_a", "no answer")
    assert _row(db, tenant, task)[0] == "failed"


def test_only_the_addressee_claims_a_handed_off_task(db, tenant, agents):
    task = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    assert hb.claim(db, tenant, task, "agt_a", 0) == 1
    assert hb.handoff(db, tenant, task, "agt_a", "agt_b", 1, "yours", ["ep1"]) == 2
    assert hb.claim(db, tenant, task, "agt_a", 2) is None
    assert hb.next_open_task(db, tenant, "agt_a") is None
    assert hb.next_open_task(db, tenant, "agt_b")["id"] == task
    assert hb.claim(db, tenant, task, "agt_b", 2) == 3
    assert _row(db, tenant, task)[:3] == ["working", 3, "agt_b"]


def test_next_open_task_honours_priority_then_age(db, tenant, agents):
    low = hb.submit_task(db, tenant, "followup", {}, ["followup"], priority=1)
    high = hb.submit_task(db, tenant, "followup", {}, ["followup"], priority=9)
    mid = hb.submit_task(db, tenant, "followup", {}, ["followup"], priority=5)
    order = []
    for _ in range(3):
        nxt = hb.next_open_task(db, tenant, "agt_a")
        order.append(nxt["id"])
        hb.claim(db, tenant, nxt["id"], "agt_a", nxt["version"])
    assert order == [high, mid, low]


def test_claim_sets_a_lease_and_heartbeat_extends_it(db, tenant, agents):
    task = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    before = hb.now_ms()
    assert hb.claim(db, tenant, task, "agt_a", 0, lease_ms=5_000) == 1
    lease = _row(db, tenant, task)[3]
    assert before + 5_000 <= lease <= hb.now_ms() + 5_000
    assert hb.heartbeat(db, tenant, task, "agt_a", lease_ms=60_000) is True
    assert _row(db, tenant, task)[3] >= before + 60_000
    assert hb.heartbeat(db, tenant, task, "agt_b") is False  # not the owner
    hb.complete(db, tenant, task, "agt_a")
    assert hb.heartbeat(db, tenant, task, "agt_a") is False  # not working any more
    assert _row(db, tenant, task)[3] is None


def test_reap_expired_returns_lapsed_tasks_to_the_board(db, tenant, agents, capture):
    lapsed = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    alive = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    hb.claim(db, tenant, lapsed, "agt_a", 0, lease_ms=1)
    hb.claim(db, tenant, alive, "agt_a", 0, lease_ms=600_000)
    future = hb.now_ms() + 10
    assert hb.reap_expired(db, tenant, now=future) == [lapsed]
    assert _row(db, tenant, lapsed) == ["submitted", 2, None, None]
    assert _row(db, tenant, alive)[:2] == ["working", 1]
    assert hb.reap_expired(db, tenant, now=future) == []  # idempotent
    trace = hb.task_trace(db, tenant, lapsed)
    assert [e["type"] for e in trace["events"]] == ["claimed", "lease_expired"]
    assert trace["events"][1]["agent"] == "agt_a" and trace["events"][1]["t"] == future
    # the stale owner's CAS is dead; anyone can claim the task again at the new version
    with pytest.raises(hb.NotFound):
        hb.complete(db, tenant, lapsed, "agt_a")
    assert hb.claim(db, tenant, lapsed, "agt_b", 2) == 3
    assert _row(db, tenant, lapsed)[:3] == ["working", 3, "agt_b"]
    events = capture.stop(db, tenant)
    expired = [e["payload"] for e in events if e["event"] == "task.lease_expired"]
    assert expired == [{"task_id": lapsed, "agent_id": "agt_a", "version": 2, "at": future}]
    assert any(e["event"] == "task.claimed" and e["payload"]["lease_until"] for e in events)


def test_reap_expired_handles_legacy_claims_without_a_lease(db, tenant, agents):
    task = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    hb.claim(db, tenant, task, "agt_a", 0)
    db.graph(tenant).query("MATCH (t:Task {id: $id}) SET t.lease_until = NULL, t.updated_at = 1000", {"id": task})
    assert hb.reap_expired(db, tenant, now=1000 + 120_000) == []  # not yet lapsed with the default lease
    assert hb.reap_expired(db, tenant, now=1000 + 120_001) == [task]
