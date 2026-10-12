"""Review fixes in memory.py: findings 3 (known_by), 6 (entity key), 7 (episode order), 11-13 (projections, anchoring,
limits) and 14 (why collects every DERIVED_FROM episode)."""

import time

import hiveboard as hb
from hiveboard.embed import fake_embedding

from .conftest import BASE, DAY


def test_belief_at_known_by_between_creation_and_supersession(db, tenant, seeded):
    entity = seeded["entities"]["UPI flow"]
    created_at = db.graph(tenant).query(
        "MATCH (f:Fact {id: $id}) RETURN f.created_at", {"id": seeded["fact"]}
    ).result_set[0][0]
    time.sleep(0.01)
    known = hb.now_ms()  # K: after the Thursday fact was learned, before it was superseded
    time.sleep(0.01)
    new = hb.supersede_fact(
        db,
        tenant,
        seeded["fact"],
        {
            "subject": "UPI flow",
            "predicate": "due",
            "object": "Friday",
            "kind": "commitment",
            "speaker_id": seeded["aditya"],
            "episode_id": "ep2",
            "entity_ids": [entity],
            "valid_from": BASE + 2 * DAY,
        },
    )
    assert created_at <= known
    # valid time inside the old window, as known at K: the old fact (its supersession was learned later)
    assert [f["object"] for f in hb.belief_at(db, tenant, BASE + DAY, entity, known_by=known)] == ["Thursday"]
    # valid time after the switch, as known at K: still Thursday (Friday had not been learned yet)
    assert [f["object"] for f in hb.belief_at(db, tenant, BASE + 3 * DAY, entity, known_by=known)] == ["Thursday"]
    # as known now: Thursday then Friday
    assert [f["object"] for f in hb.belief_at(db, tenant, BASE + DAY, entity)] == ["Thursday"]
    assert [f["object"] for f in hb.belief_at(db, tenant, BASE + 3 * DAY, entity)] == ["Friday"]
    # a retraction learned after K does not erase what was believed at K
    time.sleep(0.01)
    known2 = hb.now_ms()
    time.sleep(0.01)
    hb.retract_fact(db, tenant, new["id"], "mis-heard")
    assert [f["object"] for f in hb.belief_at(db, tenant, BASE + 3 * DAY, entity, known_by=known2)] == ["Friday"]
    assert hb.belief_at(db, tenant, BASE + 3 * DAY, entity) == []
    assert hb.belief_at(db, tenant, BASE + DAY, entity, limit=0) == []


def test_entity_case_variants_merge_into_one_node(db, tenant, seeded):
    ids = hb.upsert_entities(db, tenant, [{"name": "UPI Flow", "type": "project"}, {"name": " upi flow  "}])
    assert set(ids.values()) == {seeded["entities"]["UPI flow"]}
    g = db.graph(tenant)
    assert g.query(
        "MATCH (e:Entity) WHERE e.name_key = 'upi flow' RETURN count(e), collect(e.name)"
    ).result_set == [[1, ["UPI flow"]]]
    assert hb.who_knows(db, tenant, "upi FLOW")[0]["mentions"] == 1
    # legacy entities without name_key are back-filled by ensure_schema so the MERGE finds them
    g.query("CREATE (:Entity {id: 'ent_legacy', name: 'Legacy Topic'})")
    hb.ensure_schema(db, tenant)
    assert hb.upsert_entities(db, tenant, [{"name": "legacy topic"}]) == {"legacy topic": "ent_legacy"}


def test_out_of_order_episode_batches_keep_the_next_chain_linear(db, tenant, seeded):
    meeting = hb.remember_meeting(db, tenant, {"id": "mtg_ooo", "title": "Out of order", "started_at": BASE})

    def row(i):
        return {"id": f"o{i}", "seq": i, "speaker_id": seeded["priya"], "text": f"L{i}", "t_occurred": BASE + i}

    hb.remember_episodes(db, tenant, meeting, [row(1)])
    hb.remember_episodes(db, tenant, meeting, [row(3), row(6)])
    hb.remember_episodes(db, tenant, meeting, [row(2)])
    hb.remember_episodes(db, tenant, meeting, [row(4), row(5)])
    edges = db.graph(tenant).query(
        "MATCH (:Meeting {id: 'mtg_ooo'})-[:HAS_EPISODE]->(a:Episode)-[:NEXT]->(b:Episode) "
        "RETURN a.id, b.id ORDER BY a.seq"
    ).result_set
    assert edges == [["o1", "o2"], ["o2", "o3"], ["o3", "o4"], ["o4", "o5"], ["o5", "o6"]]
    forks = db.graph(tenant).query(
        "MATCH (a:Episode)-[:NEXT]->(b:Episode) WITH a, count(b) AS n WHERE n > 1 RETURN count(a)"
    ).result_set[0][0]
    assert forks == 0


def test_fulltext_and_skill_reads_carry_no_embedding(db, tenant, seeded):
    rows = hb.fulltext(db, tenant, "UPI flow")
    assert rows and all("embedding" not in r for r in rows) and rows[0]["has_embedding"] is True
    assert "t_ingested" in rows[0] and "subject" not in rows[0]  # the other label's null fields are dropped
    skill = hb.learn_skill(db, tenant, "goal", [{"order": 1, "tool": "recall"}], [], fake_embedding("goal"))
    detail = hb.get_skill(db, tenant, skill)
    assert "embedding" not in detail and detail["has_embedding"] is True
    out = hb.record_outcome(db, tenant, skill, "agt_none", True)
    assert "embedding" not in out and out["runs"] == 1
    assert "embedding" not in hb.list_skills(db, tenant, limit=10)[0]
    commons_id = hb.publish_to_commons(db, tenant, skill)  # the one path that needs the vector
    assert db.commons().query(
        "MATCH (s:Skill {id: $id}) RETURN s.embedding IS NOT NULL", {"id": commons_id}
    ).result_set == [[True]]


def test_active_facts_by_entity_is_anchored_on_the_entity(db, tenant, seeded):
    hb.remember_fact(
        db,
        tenant,
        {
            "subject": "onboarding",
            "predicate": "status",
            "object": "blocked",
            "entity_ids": [seeded["entities"]["onboarding"]],
        },
    )
    rows = hb.active_facts(db, tenant, entity_id=seeded["entities"]["UPI flow"])
    assert [f["id"] for f in rows] == [seeded["fact"]]
    assert rows.cypher.startswith("MATCH (anchor:Entity {id: $entity})")
    assert hb.active_facts(db, tenant, entity_id=seeded["entities"]["UPI flow"], key="onboarding|status") == []
    assert hb.active_facts(db, tenant, entity_id="ent_nope") == []
    everything = hb.active_facts(db, tenant)
    assert len(everything) == 2 and everything.cypher.startswith("MATCH (f:Fact")
    assert len(hb.active_facts(db, tenant, limit=1)) == 1
    assert hb.open_commitments(db, tenant, limit=0) == [] and len(hb.who_knows(db, tenant, "UPI flow", limit=1)) == 1
    assert hb.contradictions(db, tenant, limit=5) == [] and hb.stale_decisions(db, tenant, 0, limit=5) == []


def test_why_collects_every_derived_from_episode_and_handles_none(db, tenant, seeded):
    db.graph(tenant).query(
        "MATCH (f:Fact {id: $id}), (ep:Episode {id: 'ep3'}) MERGE (f)-[:DERIVED_FROM]->(ep)",
        {"id": seeded["fact"]},
    )
    w = hb.why(db, tenant, seeded["fact"])
    assert w["episode"]["id"] == "ep1" and [e["id"] for e in w["episodes"]] == ["ep1", "ep3"]
    assert w["speaker"]["name"] == "Priya" and w["source"]["episode_id"] == "ep1"
    assert sum(1 for e in w["subgraph"]["edges"] if e["type"] == "DERIVED_FROM") == 2
    bare = hb.remember_fact(
        db, tenant, {"subject": "x", "predicate": "y", "object": "z", "speaker_id": seeded["aditya"]}
    )
    w2 = hb.why(db, tenant, bare["id"])
    assert w2["episode"] is None and w2["episodes"] == [] and w2["speaker"]["id"] == seeded["aditya"]
    assert w2["source"] is None and w2["history"][0]["id"] == bare["id"]
