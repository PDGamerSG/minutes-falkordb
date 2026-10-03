"""Board: agents, tasks, traces, demo buttons and the SSE stream."""

from __future__ import annotations

import json
import threading
import time


def test_agents_list(client):
    agents = client.get("/tenants/orbit/agents").json()
    by_id = {a["id"]: a for a in agents}
    assert set(by_id) == {"fact_agent", "followup_agent", "scheduler_agent", "standup_agent", "answer_agent"}
    assert by_id["scheduler_agent"]["capabilities"] == ["schedule"] and by_id["scheduler_agent"]["state"] == "idle"
    assert set(by_id["answer_agent"]) >= {"id", "name", "model", "capabilities", "last_seen", "state"}


def test_task_lifecycle_and_trace(client, seeded):
    created = client.post("/tenants/orbit/tasks", json={"kind": "followup", "payload": {"note": "ping"}, "requires": ["followup"], "about_ids": []})
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "submitted" and task["version"] == 0 and task["kind"] == "followup"
    assert task["payload"] == {"note": "ping"} and task["requires"] == ["followup"]
    listed = client.get("/tenants/orbit/tasks", params={"status": "submitted"}).json()
    assert any(t["id"] == task["id"] for t in listed)
    assert client.get("/tenants/orbit/tasks", params={"status": "completed"}).json() == []

    hive = seeded.hive
    assert hive.claim("orbit", task["id"], "followup_agent", 0) == 1
    assert hive.handoff("orbit", task["id"], "followup_agent", "scheduler_agent", 1, "needs a date", ["fact_x"]) == 2
    assert hive.claim("orbit", task["id"], "scheduler_agent", 2) == 3
    hive.complete("orbit", task["id"], "scheduler_agent", {"kind": "nudge_message", "text": json.dumps({"title": "Nudge", "simulated": True})})

    trace = client.get(f"/tenants/orbit/tasks/{task['id']}/trace").json()
    assert trace["task"]["status"] == "completed" and trace["task"]["version"] == 4
    types = [e["type"] for e in trace["events"]]
    assert types[0] == "submitted"
    assert types.count("claimed") == 2 and "handed_off" in types and "artifact" in types and types[-1] == "completed"
    handoff = next(e for e in trace["events"] if e["type"] == "handed_off")
    assert handoff["agent"] == "followup_agent" and handoff["to_agent"] == "scheduler_agent" and handoff["subgraph_ids"] == ["fact_x"]
    artifact = next(e for e in trace["events"] if e["type"] == "artifact")["artifact"]
    assert artifact["kind"] == "nudge_message" and artifact["title"] == "Nudge" and artifact["simulated"] is True
    assert client.get("/tenants/orbit/tasks/task_missing/trace").status_code == 404
    assert client.get(f"/tenants/orbit/tasks/{task['id']}").json()["owner_agent"] == "scheduler_agent"


def test_demo_supersede_targets_payu(client, seeded):
    before = client.get("/tenants/orbit/facts", params={"entity": "PayU Integration"}).json()
    old = next(f for f in before if f["predicate"] == "due")
    assert old["object"] == "2026-10-01"
    response = client.post("/tenants/orbit/demo/supersede", json={"new_object": "2026-10-02", "speaker_id": "spk_priya"})
    assert response.status_code == 200
    body = response.json()
    assert body["old_fact_id"] == old["id"] and body["new_fact_id"].startswith("fact_")
    assert body["new_object"] == "2026-10-02" and body["due_at"] == 1790899200000
    active = [f for f in client.get("/tenants/orbit/facts", params={"entity": "PayU Integration"}).json() if f["predicate"] == "due"]
    assert len(active) == 1 and active[0]["id"] == body["new_fact_id"] and active[0]["supersedes"] == old["id"]
    assert client.get(f"/tenants/orbit/facts/{old['id']}").json()["status"] == "superseded"
    events = [e["event"] for e in seeded.hive.events["orbit"]]
    assert "fact.superseded" in events and "commitment.updated" in events
    # superseding an already superseded fact is a conflict
    again = client.post("/tenants/orbit/demo/supersede", json={"fact_id": old["id"], "new_object": "2026-10-03"})
    assert again.status_code == 409


def test_demo_supersede_with_weekday_text(client):
    body = client.post("/tenants/orbit/demo/supersede", json={"new_object": "Oct 2 2026", "speaker_id": "spk_priya"}).json()
    assert body["new_object"] == "2026-10-02"


def test_demo_double_claim(client):
    body = client.post("/tenants/orbit/demo/double-claim", json={}).json()
    assert body["winners"] == 1 and body["losers"] == 24 and body["attempts"] == 25
    assert body["winner_agent"].startswith("demo_claimer_") and body["task_id"].startswith("task_")
    task = client.get(f"/tenants/orbit/tasks/{body['task_id']}").json()
    assert task["status"] == "completed" and task["owner_agent"] == body["winner_agent"]
    explicit = client.post("/tenants/orbit/tasks", json={"kind": "demo_double_claim", "payload": {}, "requires": ["demo"]}).json()
    body2 = client.post("/tenants/orbit/demo/double-claim", json={"task_id": explicit["id"]}).json()
    assert body2["winners"] == 1 and body2["task_id"] == explicit["id"]
    assert client.post("/tenants/orbit/demo/double-claim", json={"task_id": "task_nope"}).status_code == 404


def _read_events(client, url, expected, headers=None):
    received = []
    with client.stream("GET", url, headers=headers or {}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        _read_events.last_headers = dict(response.headers)
        for line in response.iter_lines():
            if line.startswith("data:"):
                received.append(json.loads(line[len("data:"):].strip()))
                if len(received) >= expected:
                    break
    return received


def test_sse_replay_shape_and_cors(client, seeded):
    seeded.bus.recent("orbit")  # make sure the bus listens before publishing
    seeded.hive.publish("orbit", "fact.created", {"fact_id": "fact_sse_1"})
    seeded.hive.publish("orbit", "task.submitted", {"task_id": "task_sse_1"})
    received = _read_events(client, "/tenants/orbit/events?replay=2&limit=2", 3, headers={"Origin": "http://localhost:3001"})
    assert _read_events.last_headers.get("access-control-allow-origin") == "http://localhost:3001"
    assert received[0]["event"] == "connected"
    assert [e["event"] for e in received[1:]] == ["fact.created", "task.submitted"]
    assert set(received[1]) == {"event", "payload", "ts"} and received[1]["payload"] == {"fact_id": "fact_sse_1"}


def test_sse_live_delivery(client, seeded):
    received = []

    def consume():
        received.extend(_read_events(client, "/tenants/orbit/events?limit=1", 2))

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    time.sleep(0.3)
    seeded.hive.publish("orbit", "commitment.updated", {"commitment_id": "fact_live"})
    thread.join(timeout=10)
    assert not thread.is_alive(), "stream did not close after the live event"
    assert received[-1]["event"] == "commitment.updated" and received[-1]["payload"]["commitment_id"] == "fact_live"
