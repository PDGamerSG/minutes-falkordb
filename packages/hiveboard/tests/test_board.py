from concurrent.futures import ThreadPoolExecutor

import hiveboard as hb
import pytest


@pytest.fixture
def agents(db, tenant):
    hb.register_agent(db, tenant, "agt_follow", "FollowUp", ["followup", "answer"], "gemma-4")
    hb.register_agent(db, tenant, "agt_sched", "Scheduler", ["schedule"], "gemma-4")
    hb.register_agent(
        db, tenant, "agt_all", "Generalist", ["followup", "schedule", "answer", "standup"], "gemma-4"
    )
    return ["agt_follow", "agt_sched", "agt_all"]


def test_cas_claim_exactly_one_winner_under_50_threads(db, tenant, agents):
    task = hb.submit_task(db, tenant, "followup", {"about": "x"}, ["followup"])
    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(lambda i: hb.claim(db, tenant, task, agents[i % 3], 0), range(50)))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1 and winners[0] == 1
    g = db.graph(tenant)
    assert g.query(
        "MATCH (t:Task {id: $id}) RETURN t.status, t.version, t.owner_agent IS NOT NULL", {"id": task}
    ).result_set == [["working", 1, True]]
    assert (
        g.query("MATCH (:Task {id: $id})-[c:CLAIMED_BY]->() RETURN count(c)", {"id": task}).result_set[0][0]
        == 1
    )
    assert hb.claim(db, tenant, task, "agt_all", 1) is None  # no longer submitted


def test_handoff_bumps_version_and_records_subgraph(db, tenant, agents):
    task = hb.submit_task(db, tenant, "schedule", {"move": "Friday"}, ["schedule"])
    assert hb.claim(db, tenant, task, "agt_sched", 0) == 1
    assert hb.handoff(db, tenant, task, "agt_sched", "agt_follow", 0, "stale", []) is None
    assert (
        hb.handoff(
            db,
            tenant,
            task,
            "agt_sched",
            "agt_follow",
            1,
            "commitment moved, please follow up",
            ["fact_1", "ep2"],
        )
        == 2
    )
    g = db.graph(tenant)
    row = g.query(
        "MATCH (t:Task {id: $id})-[h:HANDED_OFF]->(a:Agent) RETURN t.status, t.version, t.owner_agent, "
        "a.id, h.summary, h.subgraph_ids, h.from_agent",
        {"id": task},
    ).result_set[0]
    assert row == [
        "submitted",
        2,
        "agt_follow",
        "agt_follow",
        "commitment moved, please follow up",
        ["fact_1", "ep2"],
        "agt_sched",
    ]
    # only the addressee can claim a handed-off task (finding 5); anyone else loses the CAS
    assert hb.claim(db, tenant, task, "agt_all", 2) is None
    assert hb.claim(db, tenant, task, "agt_follow", 2) == 3
    trace = hb.task_trace(db, tenant, task)
    assert [e["type"] for e in trace["events"]] == ["claimed", "handed_off", "claimed"]
    assert (
        trace["events"][1]["subgraph_ids"] == ["fact_1", "ep2"]
        and trace["events"][1]["to_agent"] == "agt_follow"
    )


def test_next_open_task_respects_requires_subset_of_has(db, tenant, agents):
    t_standup = hb.submit_task(db, tenant, "standup", {}, ["standup", "answer"])
    t_follow = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    t_free = hb.submit_task(db, tenant, "misc", {}, [])
    assert hb.next_open_task(db, tenant, "agt_sched")["id"] == t_free  # only the unconstrained task fits
    assert hb.next_open_task(db, tenant, "agt_follow")["id"] == t_follow
    nxt = hb.next_open_task(db, tenant, "agt_all")
    assert nxt["id"] == t_standup and sorted(nxt["requires"]) == ["answer", "standup"]  # oldest first
    # a handed-off task is only visible to its addressee
    assert hb.claim(db, tenant, t_follow, "agt_follow", 0) == 1
    assert hb.handoff(db, tenant, t_follow, "agt_follow", "agt_all", 1, "yours", []) == 2
    assert hb.next_open_task(db, tenant, "agt_follow")["id"] == t_free
    assert hb.next_open_task(db, tenant, "agt_all")["id"] == t_standup
    hb.claim(db, tenant, t_standup, "agt_all", 0)
    assert hb.next_open_task(db, tenant, "agt_all")["id"] == t_follow
    assert hb.next_open_task(db, tenant, "agt_nobody") is None


def test_complete_fail_need_input_and_trace(db, tenant, agents):
    task = hb.submit_task(db, tenant, "followup", {"issue": 1}, ["followup"], about_ids=["ep_missing"])
    hb.claim(db, tenant, task, "agt_follow", 0)
    with pytest.raises(hb.NotFound):
        hb.complete(db, tenant, task, "agt_sched")  # not the owner
    hb.need_input(db, tenant, task, "agt_follow", "Which repo?")
    assert hb.list_tasks(db, tenant, status="input_required")[0]["question"] == "Which repo?"
    hb.complete(
        db,
        tenant,
        task,
        "agt_follow",
        {"kind": "github_issue", "uri": "https://github.com/orbit/app/issues/7"},
    )
    trace = hb.task_trace(db, tenant, task)
    assert [e["type"] for e in trace["events"]] == ["claimed", "artifact", "completed"]
    assert trace["events"][1]["artifact"]["kind"] == "github_issue" and trace["task"]["status"] == "completed"
    assert trace["task"]["payload"] == {"issue": 1} and "MATCH (t:Task" in trace["cypher"]

    other = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    hb.claim(db, tenant, other, "agt_follow", 0)
    hb.fail(db, tenant, other, "agt_follow", "model timeout")
    failed = hb.list_tasks(db, tenant, status="failed")
    assert [t["id"] for t in failed] == [other] and failed[0]["failure_reason"] == "model timeout"
    assert failed.cypher.startswith("MATCH (t:Task)")
    agents_rows = {a["id"]: a for a in hb.list_agents(db, tenant)}
    assert agents_rows["agt_follow"]["state"] == "idle" and sorted(
        agents_rows["agt_all"]["capabilities"]
    ) == ["answer", "followup", "schedule", "standup"]
    assert len(hb.list_tasks(db, tenant)) == 2
