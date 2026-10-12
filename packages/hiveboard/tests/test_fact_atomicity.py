"""Findings 1, 2, 4, 8, 9, 27: atomic fact writes, chain insertion that refuses to self-supersede, event payloads."""

from concurrent.futures import ThreadPoolExecutor

import hiveboard as hb
import pytest
from hiveboard.events import SUPERSEDED_PAYLOAD_KEYS

from .conftest import BASE, DAY


def _fact(seeded, obj, **extra):
    base = {
        "subject": "UPI flow",
        "predicate": "due",
        "object": obj,
        "confidence": 0.8,
        "speaker_id": seeded["aditya"],
        "episode_id": "ep2",
        "entity_ids": [seeded["entities"]["UPI flow"]],
        "kind": "commitment",
    }
    base.update(extra)
    return base


def _active(db, tenant, key="upi flow|due"):
    return db.graph(tenant).query(
        "MATCH (f:Fact {key: $k, status: 'active'}) RETURN f.id ORDER BY f.id", {"k": key}
    ).result_set


def _chain(db, tenant, key="upi flow|due"):
    """[(id, object, status, valid_from, valid_to)] oldest first plus the SUPERSEDES edges."""
    g = db.graph(tenant)
    nodes = g.query(
        "MATCH (f:Fact {key: $k}) RETURN f.id, f.object, f.status, f.valid_from, f.valid_to ORDER BY f.valid_from",
        {"k": key},
    ).result_set
    edges = g.query(
        "MATCH (a:Fact {key: $k})-[:SUPERSEDES]->(b:Fact) RETURN a.id, b.id ORDER BY a.id, b.id", {"k": key}
    ).result_set
    return nodes, edges


# -- finding 2: concurrency ----------------------------------------------------------------------
def test_sixteen_concurrent_supersedes_leave_one_active_fact(db, tenant, seeded):
    objects = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Jan"] * 2
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(
            pool.map(
                lambda i: hb.remember_fact(
                    db, tenant, _fact(seeded, objects[i] + str(i), valid_from=BASE + DAY), supersede=True
                ),
                range(16),
            )
        )
    assert len(_active(db, tenant)) == 1
    assert hb.contradictions(db, tenant) == []
    winners = [r["id"] for r in results if not r["existing"]]
    assert len(winners) == 16  # every write landed, each superseding the previous head
    assert (
        db.graph(tenant).query("MATCH (f:Fact {key: 'upi flow|due'}) RETURN count(f)").result_set[0][0] == 17
    )


def test_eight_concurrent_identical_facts_produce_one_id(db, tenant, seeded):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda i: hb.remember_fact(
                    db, tenant, {"subject": "payments gateway", "predicate": "vendor", "object": "Razorpay"}
                ),
                range(8),
            )
        )
    ids = {r["id"] for r in results}
    assert len(ids) == 1
    assert sum(1 for r in results if not r["existing"]) == 1
    assert len(_active(db, tenant, "payments gateway|vendor")) == 1


def test_concurrent_supersede_fact_one_wins_others_raise(db, tenant, seeded):
    old = seeded["fact"]

    def attempt(i):
        try:
            return hb.supersede_fact(db, tenant, old, _fact(seeded, f"Day{i}", valid_from=BASE + DAY))
        except hb.Conflict as exc:
            return exc

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    wins = [r for r in results if isinstance(r, dict)]
    assert len(wins) == 1 and len([r for r in results if isinstance(r, hb.Conflict)]) == 7
    assert _active(db, tenant) == [[wins[0]["id"]]]


# -- findings 8, 9, 27: guards -------------------------------------------------------------------
def test_duplicate_detection_is_case_and_whitespace_insensitive(db, tenant, seeded):
    dup = hb.remember_fact(db, tenant, _fact(seeded, "  thursday "))
    assert dup["existing"] and dup["id"] == seeded["fact"]
    assert len(_active(db, tenant)) == 1


def test_reingesting_an_existing_id_does_not_rewrite_identity(db, tenant, seeded):
    hb.remember_fact(db, tenant, {**_fact(seeded, "Sunday", valid_from=BASE - DAY), "id": seeded["fact"], "text": "new text"})
    row = db.graph(tenant).query(
        "MATCH (f:Fact {id: $id}) RETURN f.object, f.valid_from, f.status, f.text", {"id": seeded["fact"]}
    ).result_set[0]
    assert row == ["Thursday", BASE, "active", "new text"]


def test_backdated_and_cross_key_supersession_are_rejected(db, tenant, seeded):
    with pytest.raises(hb.Conflict, match="insert_fact_in_chain"):
        hb.supersede_fact(db, tenant, seeded["fact"], _fact(seeded, "Wednesday", valid_from=BASE - DAY))
    with pytest.raises(hb.Conflict, match="different key"):
        hb.supersede_fact(db, tenant, seeded["fact"], {"subject": "onboarding", "predicate": "due", "object": "x"})
    with pytest.raises(hb.Conflict, match="insert_fact_in_chain"):
        hb.remember_fact(db, tenant, _fact(seeded, "Wednesday", valid_from=BASE - DAY), supersede=True)
    with pytest.raises(hb.NotFound):
        hb.supersede_fact(db, tenant, "fact_missing", _fact(seeded, "x"))
    assert _active(db, tenant) == [[seeded["fact"]]]  # nothing was written by the refused calls
    assert db.graph(tenant).query("MATCH (f:Fact) RETURN count(f)").result_set[0][0] == 1


def test_wrong_dimension_embedding_raises(db, tenant, seeded):
    with pytest.raises(ValueError, match="768"):
        hb.remember_fact(db, tenant, _fact(seeded, "x", embedding=[0.1] * 384))
    with pytest.raises(ValueError, match="768"):
        hb.upsert_entities(db, tenant, [{"name": "short", "embedding": [0.1] * 10}])
    with pytest.raises(ValueError, match="768"):
        hb.learn_skill(db, tenant, "goal", [], [], [0.1] * 12)
    with pytest.raises(ValueError, match="768"):
        hb.recall(db, tenant, [0.1] * 3)


# -- finding 1: chain insertion ------------------------------------------------------------------
def test_insert_fact_in_chain_rewires_between_predecessor_and_head(db, tenant, seeded, capture):
    thu = seeded["fact"]  # valid_from BASE
    fri = hb.supersede_fact(db, tenant, thu, _fact(seeded, "Friday", valid_from=BASE + 2 * DAY))["id"]
    # a late import of a Wednesday statement dated between Thursday and Friday
    result = hb.insert_fact_in_chain(db, tenant, _fact(seeded, "Wednesday", valid_from=BASE + DAY), before_id=fri)
    assert result["inserted"] and not result["confirmed"] and result["before_id"] == fri
    assert result["superseded"] == [thu]
    wed = result["id"]
    nodes, edges = _chain(db, tenant)
    assert [(n[0], n[2]) for n in nodes] == [(thu, "superseded"), (wed, "superseded"), (fri, "active")]
    assert nodes[0][4] == BASE + DAY and nodes[1][4] == BASE + 2 * DAY and nodes[2][4] is None
    assert edges == sorted([[fri, wed], [wed, thu]])
    assert [f["object"] for f in hb.belief_at(db, tenant, BASE + DAY + 1)] == ["Wednesday"]
    assert [f["object"] for f in hb.belief_at(db, tenant, hb.now_ms())] == ["Friday"]
    assert [h["object"] for h in hb.why(db, tenant, fri)["history"]] == ["Friday", "Wednesday", "Thursday"]
    events = capture.stop(db, tenant)
    created = [e for e in events if e["event"] in ("fact.created", "commitment.created")]
    assert all(e["payload"]["id"] == fri for e in created)  # none for the fact born superseded
    superseded = [e["payload"] for e in events if e["event"] == "fact.superseded"]
    assert [p["head_changed"] for p in superseded] == [True, False]
    assert superseded[1]["new_fact_id"] == wed and superseded[1]["old_fact_id"] == thu
    assert superseded[1]["old_object"] == "Thursday" and superseded[1]["new_object"] == "Wednesday"


def test_insert_fact_in_chain_refuses_to_self_supersede(db, tenant, seeded, capture):
    thu = seeded["fact"]
    fri = hb.supersede_fact(db, tenant, thu, _fact(seeded, "Friday", valid_from=BASE + 2 * DAY))["id"]
    # the finding-1 scenario: a late import restating the head, dated between the two chain members
    restated = hb.insert_fact_in_chain(db, tenant, _fact(seeded, " friday", valid_from=BASE + DAY, episode_id="ep3"), fri)
    assert restated == {"id": fri, "inserted": False, "confirmed": True, "before_id": fri, "superseded": []}
    # restating the predecessor confirms the predecessor
    again = hb.insert_fact_in_chain(db, tenant, _fact(seeded, "Thursday", valid_from=BASE + DAY, episode_id="ep3"), fri)
    assert again["id"] == thu and again["confirmed"] and not again["inserted"]
    # the explicit self case: new id == before id
    same_id = hb.insert_fact_in_chain(db, tenant, {**_fact(seeded, "Saturday", valid_from=BASE + DAY), "id": fri}, fri)
    assert same_id["confirmed"] and same_id["id"] == fri
    nodes, edges = _chain(db, tenant)
    assert [(n[0], n[2]) for n in nodes] == [(thu, "superseded"), (fri, "active")] and edges == [[fri, thu]]
    assert _active(db, tenant) == [[fri]]
    assert [f["object"] for f in hb.belief_at(db, tenant, hb.now_ms())] == ["Friday"]
    g = db.graph(tenant)
    assert g.query("MATCH (a:Fact)-[:SUPERSEDES]->(a) RETURN count(a)").result_set[0][0] == 0
    assert g.query(
        "MATCH (f:Fact {id: $id})-[c:CONFIRMED_BY]->(ep:Episode) RETURN ep.id, c.at IS NOT NULL ORDER BY ep.id",
        {"id": fri},
    ).result_set == [["ep2", True], ["ep3", True]]  # one per confirming episode (ep2 from the explicit-id case)
    why = hb.why(db, tenant, fri)
    assert [e["id"] for e in why["episodes"]] == ["ep2", "ep3"] and why["episode"]["id"] == "ep2"
    events = capture.stop(db, tenant)
    assert [e["event"] for e in events if e["event"] != "task.submitted"] == [
        "fact.created",
        "commitment.created",
        "fact.superseded",
        "commitment.updated",
    ]  # the three confirmations published nothing


def test_insert_fact_in_chain_rejects_wrong_targets(db, tenant, seeded):
    thu = seeded["fact"]
    with pytest.raises(hb.Conflict, match="not later"):
        hb.insert_fact_in_chain(db, tenant, _fact(seeded, "Saturday", valid_from=BASE + DAY), thu)
    with pytest.raises(hb.Conflict, match="different key"):
        hb.insert_fact_in_chain(db, tenant, {"subject": "onboarding", "predicate": "due", "object": "x", "valid_from": BASE - 1}, thu)
    with pytest.raises(hb.NotFound):
        hb.insert_fact_in_chain(db, tenant, _fact(seeded, "x", valid_from=BASE - 1), "fact_missing")
    assert db.graph(tenant).query("MATCH (f:Fact) RETURN count(f)").result_set[0][0] == 1


def test_insert_first_statement_before_the_chain_start(db, tenant, seeded):
    thu = seeded["fact"]
    first = hb.insert_fact_in_chain(db, tenant, _fact(seeded, "Tuesday", valid_from=BASE - DAY), thu)
    assert first["inserted"] and first["superseded"] == []
    nodes, edges = _chain(db, tenant)
    assert [(n[1], n[2], n[4]) for n in nodes] == [("Tuesday", "superseded", BASE), ("Thursday", "active", None)]
    assert edges == [[thu, first["id"]]]


# -- finding 4: the fact.superseded payload --------------------------------------------------------
def test_superseded_payload_is_the_superset_schema(db, tenant, seeded, capture):
    new = hb.remember_fact(
        db, tenant, _fact(seeded, "Friday", valid_from=BASE + DAY, due_at=BASE + 4 * DAY), supersede=True
    )
    events = capture.stop(db, tenant)
    payload = next(e["payload"] for e in events if e["event"] == "fact.superseded")
    assert SUPERSEDED_PAYLOAD_KEYS <= set(payload)
    assert payload["new_fact_id"] == payload["new_id"] == new["id"]
    assert payload["old_fact_id"] == seeded["fact"] and payload["old_ids"] == payload["old_fact_ids"] == [seeded["fact"]]
    assert payload["old_object"] == "Thursday" and payload["new_object"] == payload["object"] == "Friday"
    assert payload["subject"] == "UPI flow" and payload["predicate"] == "due" and payload["key"] == "upi flow|due"
    assert payload["kind"] == "commitment" and payload["due_at"] == BASE + 4 * DAY and payload["valid_from"] == BASE + DAY
    assert payload["episode_id"] == "ep2" and payload["speaker_id"] == seeded["aditya"]
    assert payload["head_changed"] is True and payload["tenant"] == tenant
    updated = next(e["payload"] for e in events if e["event"] == "commitment.updated")
    assert updated["commitment_id"] == new["id"] and updated["replaces"] == [seeded["fact"]]
    created = next(e["payload"] for e in events if e["event"] == "fact.created")
    assert created["fact_id"] == new["id"] and created["tenant"] == tenant


def test_episode_ingested_fires_once_per_batch(db, tenant, seeded, capture):
    rows = [
        {"id": f"ep{i}", "seq": i, "speaker_id": seeded["priya"], "text": f"Line {i}", "t_occurred": BASE + i}
        for i in range(10, 16)
    ]
    hb.remember_episodes(db, tenant, seeded["meeting"], rows)
    events = capture.stop(db, tenant)
    ingested = [e["payload"] for e in events if e["event"] == "episode.ingested"]
    assert len(ingested) == 1
    assert ingested[0]["count"] == 6 and ingested[0]["first_episode_id"] == "ep10"
    assert ingested[0]["last_episode_id"] == "ep15" and ingested[0]["container_id"] == seeded["meeting"]
