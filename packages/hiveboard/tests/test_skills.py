import hiveboard as hb
import pytest
from hiveboard.embed import fake_embedding

STEPS = [
    {"order": 1, "tool": "recall", "args_template": '{"query": "standup {{week}}"}'},
    {"order": 2, "tool": "open_commitments", "args_template": "{}", "guard": "items > 0"},
    {"order": 3, "tool": "summarise", "args_template": '{"style": "bullets"}'},
]


def test_learn_retrieve_and_record_outcome(db, tenant, seeded):
    hb.register_agent(db, tenant, "agt_standup", "Standup", ["standup"], "gemma-4")
    skill = hb.learn_skill(
        db, tenant, "run the weekly standup", STEPS, ["ep1", "ep2"], fake_embedding("run the weekly standup")
    )
    other = hb.learn_skill(
        db,
        tenant,
        "file a github issue for a slipped commitment",
        STEPS[:1],
        [],
        fake_embedding("file a github issue for a slipped commitment"),
    )
    found = hb.retrieve_skill(db, tenant, fake_embedding("weekly standup"), k=2)
    assert [s["id"] for s in found] == [skill, other]  # equal success_rate, ordered by distance
    assert [st["tool"] for st in found[0]["steps"]] == ["recall", "open_commitments", "summarise"]
    assert found[0]["steps"][1]["guard"] == "items > 0" and found.cypher.startswith(
        "CALL db.idx.vector.queryNodes('Skill'"
    )

    task = hb.submit_task(db, tenant, "standup", {}, ["standup"])
    hb.claim(db, tenant, task, "agt_standup", 0)
    for ok in (True, True, False):
        out = hb.record_outcome(db, tenant, skill, "agt_standup", ok, task)
    assert out["runs"] == 3 and out["success_rate"] == pytest.approx(2 / 3)
    hb.record_outcome(db, tenant, other, "agt_standup", False)
    # success_rate now decides the order, distance breaks ties
    assert [s["id"] for s in hb.retrieve_skill(db, tenant, fake_embedding("github issue"), k=2)] == [
        skill,
        other,
    ]
    g = db.graph(tenant)
    assert (
        g.query(
            "MATCH (:Agent {id: 'agt_standup'})-[r:RAN]->(:Skill {id: $s}) RETURN count(r), collect(r.outcome)",
            {"s": skill},
        ).result_set[0][0]
        == 3
    )
    assert g.query("MATCH (:Task {id: $t})-[:USED]->(s:Skill) RETURN s.id", {"t": task}).result_set == [
        [skill]
    ]
    detail = hb.get_skill(db, tenant, skill)
    assert detail["learned_from"] == ["ep1", "ep2"] or sorted(detail["learned_from"]) == ["ep1", "ep2"]
    assert [e["type"] for e in hb.task_trace(db, tenant, task)["events"]] == ["claimed", "skill_used"]


def test_pagerank_deprecate_and_publish_to_commons(db, tenant):
    hb.register_agent(db, tenant, "agt_x", "X", ["standup"], "gemma-4")
    popular = hb.learn_skill(db, tenant, "popular", STEPS, [], fake_embedding("popular"))
    niche = hb.learn_skill(db, tenant, "niche", STEPS[:1], [], fake_embedding("niche"))
    for _ in range(3):
        task = hb.submit_task(db, tenant, "standup", {}, ["standup"])
        hb.claim(db, tenant, task, "agt_x", 0)
        hb.record_outcome(db, tenant, popular, "agt_x", True, task)
    task = hb.submit_task(db, tenant, "standup", {}, ["standup"])
    hb.record_outcome(db, tenant, niche, "agt_x", True, task)
    ranked = hb.skill_pagerank(db, tenant)
    assert [r["id"] for r in ranked] == [popular, niche] and ranked[0]["score"] > ranked[1]["score"]
    assert "algo.pageRank" in ranked.cypher

    hb.deprecate_skill(db, tenant, niche, popular)
    assert [s["id"] for s in hb.retrieve_skill(db, tenant, fake_embedding("niche"), k=5)] == [popular]
    assert db.graph(tenant).query(
        "MATCH (a:Skill {id: $n})-[:DEPRECATED_BY]->(b) RETURN a.status, b.id", {"n": niche}
    ).result_set == [["deprecated", popular]]
    assert {s["id"]: s["status"] for s in hb.list_skills(db, tenant)} == {
        popular: "active",
        niche: "deprecated",
    }

    commons_id = hb.publish_to_commons(db, tenant, popular)
    row = (
        db.commons()
        .query(
            "MATCH (s:Skill {id: $id})-[:STEP]->(st) RETURN s.origin_tenant, s.runs, count(st)",
            {"id": commons_id},
        )
        .result_set[0]
    )
    assert row == [tenant, 3, 3]
    with pytest.raises(hb.NotFound):
        hb.publish_to_commons(db, tenant, "skl_missing")
