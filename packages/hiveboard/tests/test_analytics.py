import hiveboard as hb
from conftest import BASE, DAY


def test_who_knows_counts_speakers(db, tenant, seeded):
    rows = hb.who_knows(db, tenant, "Payments Gateway")  # case-insensitive; ep2 (Aditya) and ep3 (Priya)
    assert [(r["person"]["id"], r["mentions"], r["via"]) for r in rows] == [
        ("spk_priya", 1, ["SPOKEN_BY"]),
        ("spk_aditya", 1, ["SPOKEN_BY"]),
    ]  # ties: latest mention first
    upi = hb.who_knows(db, tenant, "UPI flow")  # ep1 (Priya) and ep2 (Aditya)
    assert [(r["person"]["name"], r["mentions"]) for r in upi] == [("Aditya", 1), ("Priya", 1)]
    assert upi[0]["last_at"] >= BASE and upi.cypher.startswith("MATCH (en:Entity)")
    assert hb.who_knows(db, tenant, "nothing") == []


def test_open_commitments_contradictions_and_stale_decisions(db, tenant, seeded):
    hb.remember_fact(
        db,
        tenant,
        {
            "subject": "onboarding",
            "predicate": "due",
            "object": "next sprint",
            "confidence": 0.8,
            "kind": "commitment",
            "speaker_id": seeded["aditya"],
            "owner_id": seeded["aditya"],
            "episode_id": "ep3",
            "entity_ids": [seeded["entities"]["onboarding"]],
            "due_at": BASE + DAY,
        },
    )
    hb.remember_fact(
        db,
        tenant,
        {
            "subject": "payments gateway",
            "predicate": "vendor",
            "object": "Razorpay",
            "confidence": 0.9,
            "kind": "decision",
            "speaker_id": seeded["priya"],
            "episode_id": "ep2",
            "entity_ids": [seeded["entities"]["payments gateway"]],
        },
    )
    hb.remember_fact(
        db,
        tenant,
        {
            "subject": "payments gateway",
            "predicate": "vendor",
            "object": "Stripe",
            "confidence": 0.6,
            "kind": "fact",
            "speaker_id": seeded["aditya"],
            "episode_id": "ep2",
            "entity_ids": [seeded["entities"]["payments gateway"]],
        },
    )
    everyone = hb.open_commitments(db, tenant)
    assert [(c["object"], c["owner"]["id"]) for c in everyone] == [
        ("next sprint", "spk_aditya"),
        ("Thursday", "spk_priya"),
    ]
    assert everyone[0]["entities"][0]["name"] == "onboarding" and "Commitment" in everyone.cypher
    assert [c["object"] for c in hb.open_commitments(db, tenant, "spk_priya")] == ["Thursday"]
    contras = hb.contradictions(db, tenant)
    assert len(contras) == 1 and contras[0]["key"] == "payments gateway|vendor"
    assert sorted(f["object"] for f in contras[0]["facts"]) == ["Razorpay", "Stripe"]
    stale = hb.stale_decisions(db, tenant, 0)
    assert [d["object"] for d in stale] == ["Razorpay"] and stale[0]["decider"]["id"] == "spk_priya"
    assert stale[0]["age_ms"] > 0 and "Decision" in stale[0]["labels"]
    assert hb.stale_decisions(db, tenant, 365 * DAY) == []


def test_entity_clusters_use_co_mentions(db, tenant, seeded):
    hb.remember_entities(db, tenant, [{"name": "lonely topic", "type": "topic"}])
    clusters = hb.entity_clusters(db, tenant)
    assert "algo.WCC" in clusters.cypher
    sizes = sorted(len(c["entities"]) for c in clusters)
    assert sizes == [1, 3]  # UPI flow + payments gateway + onboarding are linked; lonely topic is alone
    big = max(clusters, key=lambda c: len(c["entities"]))
    assert {e["name"] for e in big["entities"]} == {"UPI flow", "payments gateway", "onboarding"}
