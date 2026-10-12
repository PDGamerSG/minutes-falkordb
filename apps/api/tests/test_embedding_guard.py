"""Embedding-space guard: the tenant meta records which model produced the vectors; imports and startup
refuse to mix spaces (keys ``embedding_model`` and ``embedding_dim``, shared with the ingest pipeline)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.ingest_service import EMBEDDING_DIM_KEY, EMBEDDING_MODEL_KEY, check_embedding_space, embedding_identity
from apps.api.main import create_app
from apps.api.tests.conftest import make_ctx, seed


def test_first_ingest_records_the_embedding_space(seeded):
    meta = seeded.hive.get_tenant_meta("orbit")
    assert meta[EMBEDDING_MODEL_KEY] == embedding_identity(seeded.embedder) == "fake:fake-hashed-bow-768"
    assert meta[EMBEDDING_DIM_KEY] == 768
    assert seeded.hive.get_tenant_meta("nimbus") == {}
    tenant = next(t for t in seeded.hive.list_tenants() if t == "orbit")
    assert seeded.hive.tenant_info(tenant)["meta"][EMBEDDING_MODEL_KEY] == "fake:fake-hashed-bow-768"


def test_import_into_a_mismatched_space_is_409(client, seeded, sample_meeting):
    seeded.hive.set_tenant_meta("nimbus", {EMBEDDING_MODEL_KEY: "onnx:onnx-community/embeddinggemma-300m-ONNX", EMBEDDING_DIM_KEY: 768})
    sample_meeting["meeting"]["id"] = "mtg_nimbus_001"
    response = client.post("/tenants/nimbus/meetings/import", json=sample_meeting)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "embedding_model_mismatch" and error["expected"].startswith("onnx:") and error["actual"] == "fake:fake-hashed-bow-768"
    assert client.get("/tenants/nimbus/meetings").json() == []
    assert client.get("/tenants/nimbus").json()["embedding_model"].startswith("onnx:")
    # a matching space imports normally
    sample_meeting["meeting"]["id"] = "mtg_orbit_009"
    assert client.post("/tenants/orbit/meetings/import", json=sample_meeting).status_code == 202


def test_startup_refuses_a_mismatched_tenant(data_dir):
    ctx = make_ctx(data_dir)
    seed(ctx, data_dir)
    ctx.hive.set_tenant_meta("orbit", {EMBEDDING_MODEL_KEY: "gemini:gemini-embedding-001", EMBEDDING_DIM_KEY: 768})
    assert check_embedding_space(ctx, "orbit")["expected"] == "gemini:gemini-embedding-001"
    with TestClient(create_app(ctx, start_workers=True)) as client:
        body = client.get("/health")
        assert body.status_code == 503
        assert "Embedding model mismatch" in body.json()["error"] and body.json()["embedding_mismatch"]["orbit"]["actual"] == "fake:fake-hashed-bow-768"
        assert ctx.workers is None  # no workers run against a graph whose vectors we cannot compare
