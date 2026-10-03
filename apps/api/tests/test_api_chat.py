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
