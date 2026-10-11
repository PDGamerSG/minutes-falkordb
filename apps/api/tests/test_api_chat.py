"""Chat: router decisions, provenance in answers, persistent history."""

from __future__ import annotations


def _ask(client, message, session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    response = client.post("/tenants/orbit/chat", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_chat_response_shape_and_why_route(client):
    body = _ask(client, "Why is the UPI flow due on the 28th?")
    assert set(body) >= {"answer", "session_id", "router", "cypher", "subgraph", "sources", "model", "latency_ms"}
    assert body["router"]["route"] == "template" and body["router"]["template"] == "32_why_path"
    assert body["router"]["intent"] == "why" and "UPI Flow" in body["router"]["entities"]
    assert body["cypher"] and body["subgraph"]["nodes"]
    source = next(s for s in body["sources"] if s["kind"] == "email")
    assert source["speaker"] == "Priya" and source["thread"] == "UPI flow timeline" and source["container_id"] == "thr_orbit_001"
    assert source["sent_at"] == 1789633920000 and source["message_id"] == "msg_orbit_001_1"
    assert "2026-09-28" in body["answer"] and "[fact_" in body["answer"]
    assert body["model"] == "fake"


def test_chat_graph_route_for_entity_question(client):
    body = _ask(client, "What do we know about the PayU integration?")
    assert body["router"]["route"] == "graph" and body["router"]["entities"] == ["PayU Integration"]
    assert any(s["fact_id"].startswith("fact_") for s in body["sources"])
    source = body["sources"][0]
    assert source["kind"] == "utterance" and source["meeting"] == "Orbit kickoff" and source["t_start"] == 8000
    assert "2026-10-01" in body["answer"]


def test_chat_template_routes(client):
    who = _ask(client, "Who knows about the UPI flow?")
    assert who["router"]["route"] == "template" and who["router"]["template"] == "50_who_knows"
    assert "Priya" in who["answer"]

    open_c = _ask(client, "What are Priya's open commitments?")
    assert open_c["router"]["template"] == "51_open_commitments"
    assert all(s["speaker"] == "Priya" for s in open_c["sources"])

    contradictions = _ask(client, "Do we have any contradictions?")
    assert contradictions["router"]["template"] == "52_contradictions"
    assert "No contradictions" in contradictions["answer"]

    belief = _ask(client, "What did we believe about the UPI flow on 15 Sep 2026?")
    assert belief["router"]["template"] == "31_belief_at_time" and belief["router"]["t"] is not None
    assert "2026-09-25" in belief["answer"]


def test_chat_vector_route(client):
    body = _ask(client, "anything about payments slipping?")
    assert body["router"]["route"] == "vector"
    assert body["cypher"] and isinstance(body["sources"], list)


def test_chat_freeform_cypher_is_read_only(client):
    ok = _ask(client, "cypher: MATCH (f:Fact {status:'active'}) RETURN f LIMIT 3")
    assert ok["router"]["route"] == "freeform_ro"
    rejected = _ask(client, "MATCH (f:Fact) SET f.status = 'retracted' RETURN f")
    assert rejected["router"]["route"] == "freeform_ro"
    assert "could not run" in rejected["answer"] and "write clause" in rejected["answer"]


def test_chat_history_is_persistent(client):
    first = _ask(client, "Why did we pick Razorpay?")
    session = first["session_id"]
    _ask(client, "And when is the UPI flow due?", session)
    history = client.get(f"/tenants/orbit/chat/{session}").json()
    assert [t["role"] for t in history] == ["user", "assistant", "user", "assistant"]
    assert history[0]["text"] == "Why did we pick Razorpay?" and history[0]["t"] > 0
    assert history[1]["response"]["router"]["intent"] == "why"
    assert "response" not in history[0]
    assert client.get("/tenants/orbit/chat/sess_unknown").json() == []


def test_chat_no_match(client):
    body = _ask(client, "zzzz qqqq")
    assert body["router"]["route"] == "vector"
    assert isinstance(body["answer"], str) and body["answer"]


def test_owner_lookup_is_not_a_mentions_ranking(client):
    body = _ask(client, "Who owns the UPI flow?")
    assert body["router"]["template"] == "54_owners"
    assert "Priya" in body["answer"] and "Aditya" not in body["answer"]
    assert "[fact_" in body["answer"]
    assert any(e["type"] == "OWNED_BY" for e in body["subgraph"]["edges"])
    unassigned = _ask(client, "Who owns the payment gateway?")
    assert "No commitment owner is recorded" in unassigned["answer"]


def test_entity_filter_does_not_fall_back_to_other_projects(client):
    body = _ask(client, "Open commitments for the payment gateway")
    assert body["sources"] == []
    assert "No open commitments match" in body["answer"]
    assert "PayU Integration" not in body["answer"]


def test_followup_uses_persisted_session_topic(client):
    first = _ask(client, "When is the UPI flow due?")
    followup = _ask(client, "Who owns it?", first["session_id"])
    assert followup["router"]["entities"] == ["UPI Flow"]
    assert "Priya" in followup["answer"]
    fresh = _ask(client, "Who owns it?")
    assert fresh["router"]["entities"] == []
    assert "Name the project" in fresh["answer"]
    other = client.post("/tenants/nimbus/chat", json={"message": "Who owns it?", "session_id": first["session_id"]}).json()
    assert other["router"]["entities"] == []


def test_explicit_followup_topic_overrides_previous_topic(client):
    first = _ask(client, "When is the UPI flow due?")
    body = _ask(client, "Who owns the PayU integration?", first["session_id"])
    assert body["router"]["entities"] == ["PayU Integration"]


def test_empty_chat_is_rejected_before_creating_history(client):
    response = client.post("/tenants/orbit/chat", json={"message": "  \n\t  "})
    assert response.status_code == 422


def test_explicit_assignment_overrides_the_person_announcing_deadline(client, seeded):
    entity = next(e for e in seeded.hive.list_entities("orbit") if e["name"] == "UPI Flow")
    seeded.hive.remember_fact("orbit", {
        "id": "fact_owner_assignment", "kind": "decision", "subject": "UPI Flow",
        "predicate": "owner", "object": "Rahul", "speaker_id": "spk_aditya",
        "entity_ids": [entity["id"]], "episode_id": "ep_mtg_orbit_001_000",
    })
    response = _ask(client, "Who owns the UPI flow?")
    assert "Rahul" in response["answer"] and "Priya" not in response["answer"]
    assert "[fact_owner_assignment]" in response["answer"]
    rows = client.get("/tenants/orbit/analytics/open-commitments", params={"person": "spk_rahul"}).json()
    assert any(r["subject"] == "UPI Flow" and r["owner"]["name"] == "Rahul" for r in rows)
