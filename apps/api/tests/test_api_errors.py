"""Error envelope everywhere (1.1), task status validation (1.4), JSON-safe validation messages (1.6),
generic 500 text with a request id (2.7), bench tasks hidden from the board (2.2)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.llm.gemma import LLMRateLimited
from apps.api.main import create_app


def test_unknown_route_and_method_use_the_envelope(client):
    missing = client.get("/nope")
    assert missing.status_code == 404 and missing.json() == {"error": {"code": "not_found", "message": "Not Found"}}
    wrong_method = client.delete("/health")
    assert wrong_method.status_code == 405 and wrong_method.json()["error"]["code"] == "method_not_allowed"
    assert missing.headers.get("x-request-id")


def test_task_status_is_validated(client):
    response = client.get("/tenants/orbit/tasks", params={"status": "bogus"})
    assert response.status_code == 400 and response.json()["error"]["code"] == "bad_status"
    assert client.get("/tenants/orbit/tasks", params={"status": "all"}).status_code == 200
    assert client.get("/tenants/orbit/tasks", params={"status": "working"}).json() == []


def test_validation_messages_are_json_safe(client):
    response = client.post("/tenants/orbit/tasks", json={"kind": "x", "priority": 99, "payload": "not a dict"})
    assert response.status_code == 422
    message = response.json()["error"]["message"]
    assert "kind" in message and "priority" in message
    assert "input_value" not in message and "{" not in message and "ValidationError" not in message


def test_unexpected_errors_are_generic_and_carry_a_request_id(seeded):
    app = create_app(seeded, start_workers=False)

    @app.get("/boom")
    def boom() -> dict:
        raise RuntimeError("secret internal detail /home/user/file.py")

    @app.get("/limited")
    def limited() -> dict:
        raise LLMRateLimited("quota", retry_after=12.0)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom", headers={"X-Request-ID": "req-abc123"})
        body = response.json()["error"]
        assert response.status_code == 500 and body["code"] == "internal_error"
        assert "secret" not in body["message"] and "/home" not in body["message"]
        assert body["request_id"] == "req-abc123" and response.headers["x-request-id"] == "req-abc123"
        limited = client.get("/limited")
        assert limited.status_code == 503 and limited.json()["error"]["code"] == "llm_rate_limited"
        assert limited.json()["error"]["retry_after"] == 12.0 and limited.headers["retry-after"] == "12"


def test_bench_tasks_are_hidden_unless_requested(client):
    created = client.post("/tenants/orbit/tasks", json={"kind": "bench_cas", "payload": {}, "requires": ["bench"]}).json()
    visible = client.post("/tenants/orbit/tasks", json={"kind": "followup", "payload": {}, "requires": ["followup"]}).json()
    default = {t["id"] for t in client.get("/tenants/orbit/tasks").json()}
    assert visible["id"] in default and created["id"] not in default
    everything = {t["id"] for t in client.get("/tenants/orbit/tasks", params={"include_bench": "true"}).json()}
    assert created["id"] in everything


def test_health_has_no_file_paths(client):
    body = client.get("/health").json()
    assert "source" not in body["embeddings"]
