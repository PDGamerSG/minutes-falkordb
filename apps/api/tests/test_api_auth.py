"""Admin token and per-tenant API keys (findings 2.1, 2.2): 401/403 envelopes, key issuance and rotation,
tenant visibility, snapshot quota, admin-only demo/bench/import routes and chat session scoping."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.auth import issue_tenant_key
from apps.api.main import create_app
from apps.api.tests.conftest import make_ctx, seed

ADMIN = {"X-Admin-Token": "s3cret-admin"}
BEARER = {"Authorization": "Bearer s3cret-admin"}


@pytest.fixture
def locked(data_dir):
    ctx = make_ctx(data_dir, admin_token="s3cret-admin", tenant_keys_required=True, max_snapshots_per_tenant=2)
    seed(ctx, data_dir)
    key = issue_tenant_key(ctx, "orbit", reason="test")
    with TestClient(create_app(ctx, start_workers=False)) as client:
        yield client, ctx, key


def test_tenant_routes_require_a_matching_key(locked):
    client, ctx, key = locked
    missing = client.get("/tenants/orbit/facts")
    assert missing.status_code == 401 and missing.json()["error"]["code"] == "api_key_required"
    wrong = client.get("/tenants/orbit/facts", headers={"X-API-Key": "nope"})
    assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "api_key_invalid"
    assert client.get("/tenants/orbit/facts", headers={"X-API-Key": key}).status_code == 200
    assert client.get("/tenants/orbit/agents", headers=ADMIN).status_code == 200  # the admin token opens every tenant
    assert client.get("/tenants/orbit", headers={"X-API-Key": key}).json()["has_api_key"] is True
    # nimbus has no key yet: nobody but the admin gets in
    assert client.get("/tenants/nimbus/facts", headers={"X-API-Key": key}).status_code == 403
    assert client.get("/tenants/nimbus/facts", headers=BEARER).status_code == 200


def test_tenant_list_is_scoped_by_key(locked):
    client, ctx, key = locked
    assert client.get("/tenants").json() == []
    assert [t["slug"] for t in client.get("/tenants", headers={"X-API-Key": key}).json()] == ["orbit"]
    assert {t["slug"] for t in client.get("/tenants", headers=ADMIN).json()} >= {"orbit", "nimbus"}
    assert all("api_key" not in t and "api_key_hash" not in json.dumps(t) for t in client.get("/tenants", headers=ADMIN).json())


def test_create_tenant_is_admin_only_and_returns_the_key_once(locked):
    client, ctx, _ = locked
    denied = client.post("/tenants", json={"slug": "quill", "display_name": "Quill"})
    assert denied.status_code == 401 and denied.json()["error"]["code"] == "admin_token_required"
    forged = client.post("/tenants", json={"slug": "quill", "display_name": "Quill"}, headers={"X-Admin-Token": "guess"})
    assert forged.status_code == 403 and forged.json()["error"]["code"] == "admin_token_invalid"
    created = client.post("/tenants", json={"slug": "quill", "display_name": "Quill"}, headers=BEARER)
    assert created.status_code == 201
    body = created.json()
    key = body["api_key"]
    assert len(key) >= 24 and body["has_api_key"] is True and body["slug"] == "quill"
    assert client.get("/tenants/quill", headers={"X-API-Key": key}).status_code == 200
    assert "api_key" not in client.get("/tenants/quill", headers={"X-API-Key": key}).json()
    # an existing slug is a conflict, never a silent reset
    again = client.post("/tenants", json={"slug": "quill", "display_name": "Quill 2"}, headers=ADMIN)
    assert again.status_code == 409 and again.json()["error"]["code"] == "tenant_exists"
    assert client.get("/tenants/quill", headers={"X-API-Key": key}).json()["display_name"] == "Quill"
    # ?rotate=true re-issues the key and invalidates the old one
    rotated = client.post("/tenants?rotate=true", json={"slug": "quill", "display_name": "Quill 2"}, headers=ADMIN)
    assert rotated.status_code == 201 and rotated.json()["api_key"] != key
    assert client.get("/tenants/quill", headers={"X-API-Key": key}).status_code == 403
    assert client.get("/tenants/quill", headers={"X-API-Key": rotated.json()["api_key"]}).json()["display_name"] == "Quill 2"


def test_slug_rules(locked):
    client, ctx, _ = locked
    for slug in ("Bad Slug!", "x", "ghost__snap_1", "under_score", "a" * 42):
        response = client.post("/tenants", json={"slug": slug, "display_name": "x"}, headers=ADMIN)
        assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_slug", slug
    assert client.get("/tenants/orbit__snap_123/facts", headers=ADMIN).status_code == 404
    assert client.get("/tenants/Orbit!/facts", headers=ADMIN).status_code == 404


def test_rotate_key_and_delete_tenant(locked):
    client, ctx, key = locked
    assert client.post("/tenants/orbit/rotate-key", headers={"X-API-Key": key}).status_code == 401
    rotated = client.post("/tenants/orbit/rotate-key", headers=ADMIN).json()
    assert rotated["slug"] == "orbit" and rotated["api_key"] != key
    assert client.get("/tenants/orbit/facts", headers={"X-API-Key": key}).status_code == 403
    assert client.get("/tenants/orbit/facts", headers={"X-API-Key": rotated["api_key"]}).status_code == 200
    assert client.delete("/tenants/nimbus").status_code == 401
    assert client.delete("/tenants/nimbus", headers=ADMIN).status_code == 204
    assert client.get("/tenants/nimbus", headers=ADMIN).status_code == 404
    assert "nimbus" not in ctx.hive.list_tenants()
    assert client.delete("/tenants/nimbus", headers=ADMIN).status_code == 404


def test_admin_only_routes_and_snapshot_quota(locked):
    client, ctx, key = locked
    tenant_key = {"X-API-Key": key}
    assert client.post("/tenants/orbit/demo/double-claim", json={}, headers=tenant_key).status_code == 401
    assert client.post("/tenants/orbit/demo/supersede", json={"new_object": "2026-10-02"}, headers=tenant_key).status_code == 401
    assert client.post("/bench/run", json={"agents": 1, "tenants": 1, "duration_s": 0.5}).status_code == 401
    assert client.post("/tenants/orbit/snapshots", json={"label": "a"}, headers=tenant_key).status_code == 401
    assert client.post("/tenants/orbit/work-items/import", json={}, headers=tenant_key).status_code == 401
    assert client.post("/tenants/orbit/snapshots", json={"label": "a"}, headers=ADMIN).status_code == 201
    assert client.post("/tenants/orbit/snapshots", json={"label": "b"}, headers=ADMIN).status_code == 201
    capped = client.post("/tenants/orbit/snapshots", json={"label": "c"}, headers=ADMIN)
    assert capped.status_code == 409 and capped.json()["error"]["code"] == "snapshot_quota"
    assert len(client.get("/tenants/orbit/snapshots", headers=tenant_key).json()) == 2
    # the demo button works for the admin and is idempotent about its 25 claimers
    first = client.post("/tenants/orbit/demo/double-claim", json={}, headers=ADMIN).json()
    second = client.post("/tenants/orbit/demo/double-claim", json={}, headers=ADMIN).json()
    assert first["winners"] == second["winners"] == 1
    claimers = [a for a in ctx.hive.list_agents("orbit") if a["id"].startswith("demo_claimer_")]
    assert len(claimers) == 25


def test_chat_sessions_are_scoped_to_the_key_that_created_them(locked):
    client, ctx, key = locked
    first = client.post("/tenants/orbit/chat", json={"message": "When is the UPI flow due?"}, headers={"X-API-Key": key}).json()
    session = first["session_id"]
    assert len(client.get(f"/tenants/orbit/chat/{session}", headers={"X-API-Key": key}).json()) == 2
    other = client.post("/tenants/orbit/rotate-key", headers=ADMIN).json()["api_key"]
    assert client.get(f"/tenants/orbit/chat/{session}", headers={"X-API-Key": other}).json() == []
    assert ctx.hive.get_turns("orbit", session) and ctx.hive.get_turns("orbit", session, key_hash="not-the-key") == []


def test_events_accept_the_key_as_a_query_parameter(locked):
    client, ctx, key = locked
    assert client.get("/tenants/orbit/events?limit=1").status_code == 401
    with client.stream("GET", f"/tenants/orbit/events?replay=0&limit=0&api_key={key}") as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data:"):
                assert json.loads(line[5:].strip())["event"] == "connected"
                break
    # the query fallback exists only for browser-native consumers (EventSource, <audio>)
    assert client.get(f"/tenants/orbit/facts?api_key={key}").status_code == 401


def test_open_mode_when_no_admin_token_is_configured(client):
    """Local development: no ADMIN_TOKEN and no tenant keys means every route is open (documented)."""
    assert client.post("/tenants/orbit/snapshots", json={"label": "x"}).status_code == 201
    assert client.get("/health").json()["auth"] == {"admin_token": False, "tenant_keys_required": False}
