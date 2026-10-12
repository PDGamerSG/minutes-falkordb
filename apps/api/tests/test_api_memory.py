"""Facts, why, belief-at-T, timeline, snapshots and analytics over the seeded Orbit corpus."""

from __future__ import annotations

from apps.api.tests.conftest import cf, cfs

SEP_14 = 1788755400000 + 7 * 86_400_000  # 2026-09-14 10:00 +05:30
SEP_16 = SEP_14 + 2 * 86_400_000
SEP_20 = SEP_14 + 6 * 86_400_000


def _upi_chain(client, status="all"):
    facts = client.get("/tenants/orbit/facts", params={"status": status, "entity": "UPI Flow"}).json()
    return [f for f in facts if f["predicate"] == "due"]


def test_active_facts_shape_and_filters(client):
    facts = client.get("/tenants/orbit/facts").json()
    assert all(f["status"] == "active" for f in facts)
    commitment = next(f for f in facts if cf(f["subject"]) == "payu integration")
    assert commitment["kind"] == "commitment" and commitment["object"] == "2026-10-01"
    assert commitment["speaker"] == {"id": "spk_priya", "name": "Priya"}
    assert commitment["meeting"] == {"id": "mtg_orbit_001", "title": "Orbit kickoff"}
    assert commitment["episode_id"] == "ep_mtg_orbit_001_001"
    assert abs(commitment["due_at"] - 1790812800000) <= 14 * 3600 * 1000  # 2026-10-01 at midnight, UTC or the source timezone
    assert commitment["source"]["kind"] == "utterance" and commitment["source"]["t_start"] == 8000
    assert set(commitment) >= {"id", "kind", "subject", "predicate", "object", "text", "confidence", "valid_from", "valid_to", "status", "speaker", "meeting", "episode_id"}

    decisions = client.get("/tenants/orbit/facts", params={"kind": "decision"}).json()
    assert cfs(d["subject"] for d in decisions) == {"october release", "payment gateway", "code freeze"}
    assert client.get("/tenants/orbit/facts", params={"kind": "rumour"}).status_code == 400
    assert client.get("/tenants/orbit/facts", params={"status": "weird"}).status_code == 400


def test_upi_chain_is_bitemporal(client):
    chain = sorted(_upi_chain(client), key=lambda f: f["valid_from"])
    assert [f["object"] for f in chain] == ["2026-09-24", "2026-09-25", "2026-09-28"]
    assert [f["status"] for f in chain] == ["superseded", "superseded", "active"]
    assert chain[1]["supersedes"] == chain[0]["id"] and chain[2]["supersedes"] == chain[1]["id"]
    assert chain[0]["valid_to"] == chain[1]["valid_from"] and chain[1]["valid_to"] == chain[2]["valid_from"]
    # the email-derived fact has a thread, not a meeting, and an email source
    assert chain[2]["meeting"] is None and chain[2]["thread"] == {"id": "thr_orbit_001", "subject": "UPI flow timeline"}
    assert chain[2]["source"]["kind"] == "email" and chain[2]["source"]["message_id"] == "msg_orbit_001_1"
    # standup 2 restated the 28th: a confirmation, not a fourth link
    assert len(_upi_chain(client, "active")) == 1


def test_why_has_provenance_history_and_source(client):
    head = _upi_chain(client, "active")[0]
    why = client.get(f"/tenants/orbit/why/{head['id']}").json()
    assert why["node"]["id"] == head["id"]
    assert why["speaker"]["name"] == "Priya"
    assert why["thread"]["subject"] == "UPI flow timeline" and why["meeting"] is None
    assert why["episode"]["text"].startswith("Aditya, KYC lead time")
    assert why["source"]["kind"] == "email" and why["source"]["container"]["id"] == "thr_orbit_001"
    assert [h["object"] for h in why["history"]] == ["2026-09-25", "2026-09-24"]
    assert why["cypher"] and why["subgraph"]["nodes"]
    assert any(e["type"] == "SUPERSEDES" for e in why["subgraph"]["edges"])
    assert client.get("/tenants/orbit/why/fact_missing").status_code == 404

    first = min(_upi_chain(client), key=lambda f: f["valid_from"])
    why_first = client.get(f"/tenants/orbit/why/{first['id']}").json()
    assert why_first["source"]["kind"] == "utterance" and why_first["source"]["t_start"] == 8000
    assert why_first["meeting"]["title"] == "Orbit kickoff"


def test_belief_at_time_travel(client):
    before = client.get("/tenants/orbit/belief", params={"t": SEP_14 - 1, "entity": "ent_upi_flow"}).json()
    after = client.get("/tenants/orbit/belief", params={"t": SEP_16}).json()
    later = client.get("/tenants/orbit/belief", params={"t": SEP_20, "entity": "ent_upi_flow"}).json()
    assert before["t"] == SEP_14 - 1 and before["cypher"] is not None
    assert {f["object"] for f in before["facts"] if f["predicate"] == "due"} == {"2026-09-24"}
    assert {f["object"] for f in after["facts"] if cf(f["subject"]) == "upi flow" and f["predicate"] == "due"} == {"2026-09-25"}
    assert {f["object"] for f in later["facts"] if f["predicate"] == "due"} == {"2026-09-28"}


def test_timeline_and_snapshots(client):
    timeline = client.get("/tenants/orbit/timeline").json()
    types = {e["type"] for e in timeline["events"]}
    assert {"meeting", "email", "commitment", "decision", "fact.superseded"} <= types
    assert timeline["events"] == sorted(timeline["events"], key=lambda e: (e["t"], e["type"]))
    assert timeline["snapshots"] == []
    created = client.post("/tenants/orbit/snapshots", json={"label": "before demo"})
    assert created.status_code == 201
    snap = created.json()
    assert snap["name"].startswith("team_orbit__snap_") and snap["label"] == "before demo" and snap["taken_at"] > 0
    timeline = client.get("/tenants/orbit/timeline").json()
    assert timeline["snapshots"][0]["name"] == snap["name"]


def test_analytics_routes(client):
    who = client.get("/tenants/orbit/analytics/who-knows", params={"entity": "UPI flow"}).json()
    assert who[0]["person"]["name"] == "Priya" and who[0]["mentions"] >= 3
    names = {row["person"]["name"] for row in who}
    assert {"Priya", "Aditya", "Rahul"} <= names  # Rahul was cc on the email (SENT_TO)

    open_all = client.get("/tenants/orbit/analytics/open-commitments").json()
    assert cfs(c["subject"] for c in open_all) >= {"upi flow", "payu integration"}
    priya = client.get("/tenants/orbit/analytics/open-commitments", params={"person": "spk_priya"}).json()
    assert all(c["owner"]["id"] == "spk_priya" for c in priya)

    assert client.get("/tenants/orbit/analytics/contradictions").json() == []
    clusters = client.get("/tenants/orbit/analytics/clusters").json()
    assert clusters and all({"component", "entities"} <= set(c) for c in clusters)
    stale = client.get("/tenants/orbit/analytics/stale-decisions", params={"older_than_days": 1}).json()
    assert any(cf(d["subject"]) == "payment gateway" for d in stale)
    entities = client.get("/tenants/orbit/entities").json()
    assert any(cf(e["name"]) == "upi flow" for e in entities)


def test_get_single_fact(client):
    head = _upi_chain(client, "active")[0]
    assert client.get(f"/tenants/orbit/facts/{head['id']}").json()["id"] == head["id"]
    assert client.get("/tenants/orbit/facts/fact_nope").status_code == 404
