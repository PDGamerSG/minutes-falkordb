"""/health, /tenants, /tenants/{t}/acl-probe and the error envelope."""

from __future__ import annotations


def test_health(client):
    body = client.get("/health").json()
    assert body["ok"] is True
    assert "team_orbit" in body["falkordb"]["graphs"]
    assert {k: body["llm"][k] for k in ("backend", "model", "native_tools")} == {"backend": "fake", "model": "fake", "native_tools": False}
    assert body["llm"]["reachable"] is True
    assert body["workers"]["enabled"] is False and body["workers"]["alive"] == 0
    assert "source" not in body["embeddings"]  # no local file paths in a public health body
    assert body["auth"] == {"admin_token": False, "tenant_keys_required": False}
    assert body["embeddings"]["dim"] == 768 and body["embeddings"]["backend"] == "fake"


def test_health_fails_when_graph_queries_fail_after_ping(client, seeded, monkeypatch):
    def unavailable():
        raise RuntimeError("graph module unavailable")

    monkeypatch.setattr(seeded.hive, "list_tenants", unavailable)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["ok"] is False


def test_list_tenants_shape(client):
    tenants = client.get("/tenants").json()
    orbit = next(t for t in tenants if t["slug"] == "orbit")
    assert orbit["display_name"] == "Orbit" and orbit["graph"] == "team_orbit"
    assert set(orbit["counts"]) >= {"episodes", "facts", "decisions", "commitments", "tasks", "skills"}
    assert orbit["counts"]["commitments"] >= 3 and orbit["counts"]["episodes"] >= 8
    assert orbit["acl"]["rw_user"] == "team_orbit_rw" and orbit["acl"]["ro_user"] == "team_orbit_ro"
    rules = orbit["acl"]["rules"]
    assert rules and all("change-me" not in r and "fake-ro" not in r and "#<sha256>" in r for r in rules)
    assert isinstance(orbit["usage_mb"], float)
    assert isinstance(orbit["nodes"], int) and isinstance(orbit["edges"], int)
    assert orbit["nodes"] >= orbit["counts"]["episodes"] + orbit["counts"]["facts"] and orbit["edges"] > 0


def test_create_tenant_returns_full_object(client):
    created = client.post("/tenants", json={"slug": "quill", "display_name": "Quill"})
    assert created.status_code == 201
    body = created.json()
    assert body["slug"] == "quill" and body["display_name"] == "Quill" and body["graph"] == "team_quill"
    assert body["counts"]["facts"] == 0 and body["acl"]["ro_user"] == "team_quill_ro"
    assert body["edges"] == 0 and isinstance(body["nodes"], int)
    assert "quill" in [t["slug"] for t in client.get("/tenants").json()]
    agents = client.get("/tenants/quill/agents").json()
    assert {a["id"] for a in agents} == {"fact_agent", "followup_agent", "scheduler_agent", "standup_agent", "answer_agent"}


def test_create_tenant_rejects_bad_slug(client):
    response = client.post("/tenants", json={"slug": "Bad Slug!", "display_name": "x"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_slug"


def test_acl_probe(client):
    body = client.get("/tenants/orbit/acl-probe", params={"target": "nimbus"}).json()
    assert body["allowed"] is False and "team_orbit_ro" in body["user"] and body["error"]
    assert client.get("/tenants/orbit/acl-probe", params={"target": "ghost"}).status_code == 404


def test_unknown_tenant_error_envelope(client):
    response = client.get("/tenants/ghost/facts")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "tenant_not_found", "message": "tenant 'ghost' does not exist"}}


def test_validation_error_envelope(client):
    response = client.post("/tenants", json={"slug": "x"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
