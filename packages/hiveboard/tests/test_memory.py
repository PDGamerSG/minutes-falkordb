import hiveboard as hb
import pytest
from conftest import BASE, DAY
from hiveboard.embed import fake_embedding


def test_remember_episodes_creates_next_chain(db, tenant, seeded):
    g = db.graph(tenant)
    chain = g.query(
        "MATCH p = (a:Episode)-[:NEXT*]->(b:Episode) WHERE NOT ()-[:NEXT]->(a) AND NOT (b)-[:NEXT]->() "
        "RETURN [n IN nodes(p) | n.id]"
    ).result_set
    assert chain == [[["ep1", "ep2", "ep3"]]]
    assert g.query("MATCH ()-[r:NEXT]->() RETURN count(r)").result_set[0][0] == 2
    # a later batch continues the chain and defaults source_kind to 'utterance'
    assert (
        hb.remember_episodes(
            db,
            tenant,
            seeded["meeting"],
            [
                {
                    "id": "ep4",
                    "seq": 4,
                    "speaker_id": seeded["priya"],
                    "text": "Wrap up",
                    "t_start": 12000,
                    "t_end": 13000,
                    "t_occurred": BASE + 12000,
                }
            ],
        )
        == 1
    )
    assert g.query("MATCH (:Episode {id: 'ep3'})-[:NEXT]->(e) RETURN e.id, e.source_kind").result_set == [
        ["ep4", "utterance"]
    ]
    assert g.query("MATCH (p:Person)-[:ATTENDED]->(m:Meeting) RETURN count(DISTINCT p)").result_set[0][0] == 2
    assert g.query("MATCH (e:Episode {id: 'ep2'})-[:SPOKEN_BY]->(p) RETURN p.id").result_set == [
        ["spk_aditya"]
    ]


def test_remember_fact_and_supersede_fact_build_chain(db, tenant, seeded):
    old_id = seeded["fact"]
    new = hb.supersede_fact(
        db,
        tenant,
        old_id,
        {
            "subject": "UPI flow",
            "predicate": "due",
            "object": "Friday",
            "text": "UPI flow moved to Friday",
            "confidence": 0.95,
            "speaker_id": seeded["aditya"],
            "episode_id": "ep2",
            "entity_ids": [seeded["entities"]["UPI flow"]],
            "kind": "commitment",
            "valid_from": BASE + 5000,
        },
    )
    assert new["superseded"] == [old_id]
    g = db.graph(tenant)
    old, new_node = g.query(
        "MATCH (n:Fact {id: $n})-[:SUPERSEDES]->(o:Fact {id: $o}) RETURN o, n", {"n": new["id"], "o": old_id}
    ).result_set[0]
    assert old.properties["status"] == "superseded"
    assert old.properties["valid_to"] == BASE + 5000 == new_node.properties["valid_from"]
    assert (
        old.properties["expired_at"] is not None and "valid_to" not in new_node.properties
    )  # NULL props are dropped
    active = hb.active_facts(db, tenant, key="upi flow|due")
    assert [f["id"] for f in active] == [new["id"]] and active[0][
        "valid_to"
    ] is None  # records always carry the key
    with pytest.raises(hb.Conflict):
        hb.supersede_fact(
            db, tenant, old_id, {"subject": "UPI flow", "predicate": "due", "object": "x", "kind": "fact"}
        )


def test_remember_fact_auto_supersede_and_conflicts(db, tenant, seeded):
    base_fact = {
        "subject": "UPI flow",
        "predicate": "due",
        "confidence": 0.8,
        "speaker_id": seeded["aditya"],
        "episode_id": "ep2",
        "entity_ids": [seeded["entities"]["UPI flow"]],
        "kind": "commitment",
    }
    dup = hb.remember_fact(db, tenant, {**base_fact, "object": "Thursday"})
    assert dup["existing"] and dup["id"] == seeded["fact"]
    conflict = hb.remember_fact(db, tenant, {**base_fact, "object": "Friday", "valid_from": BASE + 5000})
    assert conflict["conflicts"] == [seeded["fact"]] and not conflict["superseded"]
    assert len(hb.contradictions(db, tenant)) == 1
    resolved = hb.remember_fact(
        db, tenant, {**base_fact, "object": "Monday", "valid_from": BASE + 9000}, supersede=True
    )
    assert sorted(resolved["superseded"]) == sorted([seeded["fact"], conflict["id"]])
    assert hb.contradictions(db, tenant) == []


def test_belief_at_three_timestamps(db, tenant, seeded):
    entity = seeded["entities"]["UPI flow"]
    hb.supersede_fact(
        db,
        tenant,
        seeded["fact"],
        {
            "subject": "UPI flow",
            "predicate": "due",
            "object": "Friday",
            "confidence": 0.9,
            "speaker_id": seeded["aditya"],
            "episode_id": "ep2",
            "entity_ids": [entity],
            "kind": "commitment",
            "valid_from": BASE + 2 * DAY,
        },
    )
    assert [f["object"] for f in hb.belief_at(db, tenant, BASE - 1, entity)] == []
    before = hb.belief_at(db, tenant, BASE + DAY, entity)
    assert [f["object"] for f in before] == ["Thursday"] and before.cypher.startswith("MATCH (f:Fact)")
    assert [f["object"] for f in hb.belief_at(db, tenant, BASE + 3 * DAY, entity)] == ["Friday"]
    # transaction-time view: nothing was known before ingestion
    assert hb.belief_at(db, tenant, BASE + DAY, entity, known_by=BASE) == []
    hb.retract_fact(db, tenant, seeded["fact"], "mis-heard")
    assert hb.belief_at(db, tenant, BASE + DAY, entity) == []


def test_why_returns_provenance_and_chain(db, tenant, seeded):
    new = hb.supersede_fact(
        db,
        tenant,
        seeded["fact"],
        {
            "subject": "UPI flow",
            "predicate": "due",
            "object": "Friday",
            "confidence": 0.9,
            "speaker_id": seeded["aditya"],
            "episode_id": "ep2",
            "entity_ids": [seeded["entities"]["UPI flow"]],
            "kind": "commitment",
            "valid_from": BASE + 5000,
        },
    )
    w = hb.why(db, tenant, new["id"])
    assert w["speaker"]["name"] == "Aditya" and w["meeting"]["title"] == "Kickoff"
    assert w["episode"]["id"] == "ep2" and w["episode"]["t_start"] == 5000
    assert w["source"]["kind"] == "utterance" and w["source"]["container"]["id"] == "mtg_kickoff"
    assert (
        w["source"]["t_start"] == 5000
        and w["source"]["container"]["source_uri"] == "data/meetings/kickoff.wav"
    )
    assert [h["object"] for h in w["history"]] == ["Friday", "Thursday"]
    assert w["supersedes"][0]["id"] == seeded["fact"] and w["superseded_by"] == []
    assert "SUPERSEDES" in w["cypher"]
    types = {e["type"] for e in w["subgraph"]["edges"]}
    assert {"DERIVED_FROM", "SPOKEN_BY", "HAS_EPISODE", "ABOUT", "SUPERSEDES"} <= types
    assert {n["label"] for n in w["subgraph"]["nodes"]} >= {
        "Commitment",
        "Episode",
        "Person",
        "Meeting",
        "Entity",
    }
    older = hb.why(db, tenant, seeded["fact"])
    assert older["superseded_by"][0]["id"] == new["id"]
    with pytest.raises(hb.NotFound):
        hb.why(db, tenant, "nope")


def test_recall_ranks_items_and_returns_cypher(db, tenant, seeded):
    hb.remember_fact(
        db,
        tenant,
        {
            "subject": "payments gateway",
            "predicate": "owner",
            "object": "Aditya",
            "confidence": 0.7,
            "speaker_id": seeded["aditya"],
            "episode_id": "ep2",
            "entity_ids": [seeded["entities"]["payments gateway"], seeded["entities"]["UPI flow"]],
            "kind": "fact",
            "embedding": fake_embedding("payments gateway owner Aditya"),
        },
    )
    hb.remember_fact(
        db,
        tenant,
        {
            "subject": "onboarding",
            "predicate": "status",
            "object": "blocked",
            "confidence": 0.7,
            "speaker_id": seeded["priya"],
            "episode_id": "ep3",
            "entity_ids": [seeded["entities"]["onboarding"]],
            "kind": "fact",
            "embedding": fake_embedding("onboarding status blocked"),
        },
    )
    out = hb.recall(db, tenant, fake_embedding("when is the UPI flow due"), k=3)
    assert "hive.score" in out["cypher"] and "db.idx.vector.queryNodes" in out["cypher"]
    items = out["items"]
    assert len(items) == 3 and items[0]["id"] == seeded["fact"]
    ranks = [i["rank"] for i in items]
    assert ranks == sorted(ranks, reverse=True) and all(0.0 <= i["distance"] <= 2.0 for i in items)
    assert items[0]["entities"][0]["name"] == "UPI flow"
    assert any(n["id"] for n in items[0]["neighbours"])  # 1-hop expansion through the shared entity
    assert {n["label"] for n in out["subgraph"]["nodes"]} >= {"Commitment", "Entity"}
    episodes = hb.recall(db, tenant, fake_embedding("payments gateway needs UPI flow"), k=2, label="Episode")
    assert episodes["items"][0]["id"] == "ep2"
    with pytest.raises(ValueError):
        hb.recall(db, tenant, fake_embedding("x"), label="Person")


def test_fulltext_sanitises_and_matches(db, tenant, seeded):
    rows = hb.fulltext(db, tenant, "UPI flow_ -please")
    assert [r["id"] for r in rows][:1] == ["ep1"] or "ep1" in [r["id"] for r in rows]
    assert all("score" in r for r in rows) and rows.cypher.startswith("CALL db.idx.fulltext.queryNodes")
    assert hb.fulltext(db, tenant, "___") == []


def test_email_source_supersedes_meeting_commitment(db, tenant, seeded):
    """A commitment made in a meeting is moved in an email: SUPERSEDES crosses sources, why() shows the email."""
    thread = hb.remember_thread(
        db, tenant, {"id": "thr_upi", "subject": "UPI flow timeline", "started_at": BASE + DAY}
    )
    assert (
        hb.remember_email_episodes(
            db,
            tenant,
            thread,
            [
                {
                    "id": "em1",
                    "seq": 1,
                    "sender_id": seeded["priya"],
                    "to_ids": [seeded["aditya"]],
                    "cc_ids": [],
                    "text": "Aditya, moving the UPI flow to Monday",
                    "t_occurred": BASE + DAY,
                    "message_id": "msg_001",
                    "embedding": fake_embedding("moving the UPI flow to Monday"),
                },
                {
                    "id": "em2",
                    "seq": 2,
                    "sender_id": seeded["aditya"],
                    "to_ids": [seeded["priya"]],
                    "cc_ids": [seeded["priya"]],
                    "in_reply_to_episode_id": "em1",
                    "text": "Ack, Monday.",
                    "t_occurred": BASE + DAY + 60_000,
                },
            ],
        )
        == 2
    )
    hb.link_mentions(db, tenant, "em1", [seeded["entities"]["UPI flow"]])
    moved = hb.supersede_fact(
        db,
        tenant,
        seeded["fact"],
        {
            "subject": "UPI flow",
            "predicate": "due",
            "object": "Monday",
            "confidence": 0.9,
            "speaker_id": seeded["priya"],
            "episode_id": "em1",
            "entity_ids": [seeded["entities"]["UPI flow"]],
            "kind": "commitment",
            "valid_from": BASE + DAY,
        },
    )
    g = db.graph(tenant)
    kinds = g.query(
        "MATCH (n:Fact {id: $n})-[:SUPERSEDES]->(o:Fact) MATCH (n)-[:DERIVED_FROM]->(a:Episode), "
        "(o)-[:DERIVED_FROM]->(b:Episode) RETURN a.source_kind, b.source_kind",
        {"n": moved["id"]},
    ).result_set
    assert kinds == [["email", "utterance"]]
    assert g.query("MATCH (:Episode {id: 'em2'})-[:REPLIES_TO]->(p) RETURN p.id").result_set == [["em1"]]
    assert g.query("MATCH (:Episode {id: 'em1'})-[:NEXT]->(n) RETURN n.id").result_set == [["em2"]]
    assert g.query(
        "MATCH (:Episode {id: 'em2'})-[s:SENT_TO]->(p) RETURN p.id, s.cc ORDER BY s.cc"
    ).result_set == [["spk_priya", True]]
    w = hb.why(db, tenant, moved["id"])
    assert w["source"] == {
        "kind": "email",
        "episode_id": "em1",
        "sent_at": BASE + DAY,
        "message_id": "msg_001",
        "container": {"id": "thr_upi", "subject": "UPI flow timeline", "label": "EmailThread"},
    }
    assert (
        w["speaker"]["name"] == "Priya"
        and w["thread"]["subject"] == "UPI flow timeline"
        and w["meeting"] is None
    )
    assert [h["object"] for h in w["history"]] == ["Monday", "Thursday"]
    assert {e["type"] for e in w["subgraph"]["edges"]} >= {"SENT_BY", "HAS_EPISODE", "SUPERSEDES"}
    knows = {r["person"]["id"]: r for r in hb.who_knows(db, tenant, "upi flow")}
    assert knows["spk_priya"]["mentions"] == 2 and "SENT_BY" in knows["spk_priya"]["via"]
    assert knows["spk_aditya"]["mentions"] == 2 and "SENT_TO" in knows["spk_aditya"]["via"]
    assert [c["object"] for c in hb.open_commitments(db, tenant, seeded["priya"])] == ["Monday"]
