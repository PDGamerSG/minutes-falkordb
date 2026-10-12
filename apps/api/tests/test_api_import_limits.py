"""Import body limits and content types (finding 2.3); mbox imports yield one job per thread."""

from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient
from ingest.email_format import parse_thread

from apps.api.main import create_app
from apps.api.routes import email as email_routes
from apps.api.tests.conftest import THREAD_001, make_ctx, seed


@pytest.fixture
def small_client(data_dir):
    ctx = make_ctx(data_dir, max_import_bytes=600)
    seed(ctx, data_dir)
    with TestClient(create_app(ctx, start_workers=False)) as client:
        yield client, ctx


def test_declared_content_length_over_the_limit_is_413(small_client, sample_meeting):
    client, _ = small_client
    body = json.dumps(sample_meeting).encode()
    assert len(body) > 600
    response = client.post("/tenants/orbit/meetings/import", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 413 and response.json()["error"]["code"] == "payload_too_large"
    response = client.post("/tenants/orbit/email/import", content=json.dumps(THREAD_001).encode(), headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_streamed_body_over_the_limit_is_413(small_client, sample_meeting):
    client, _ = small_client
    body = json.dumps(sample_meeting).encode()

    def chunks():
        for i in range(0, len(body), 100):
            yield body[i : i + 100]

    response = client.post("/tenants/orbit/meetings/import", content=chunks(), headers={"content-type": "application/json", "transfer-encoding": "chunked"})
    assert response.status_code == 413 and response.json()["error"]["code"] == "payload_too_large"


def test_small_bodies_still_import(client, sample_meeting):
    sample_meeting["meeting"]["id"] = "mtg_orbit_small"
    response = client.post("/tenants/orbit/meetings/import", json=sample_meeting)
    assert response.status_code == 202 and response.json()["meeting_id"] == "mtg_orbit_small"


def test_content_type_whitelist(client, sample_meeting):
    response = client.post("/tenants/orbit/meetings/import", content=json.dumps(sample_meeting), headers={"content-type": "text/xml"})
    assert response.status_code == 415 and response.json()["error"]["code"] == "unsupported_media_type"
    response = client.post("/tenants/orbit/email/import", content=b"hello", headers={"content-type": "text/plain"})
    assert response.status_code == 415
    upload = client.post("/tenants/orbit/email/import", files={"file": ("x.bin", b"\x00\x01", "application/x-msdownload")})
    assert upload.status_code == 415


def test_mbox_with_several_threads_creates_one_job_each(client, monkeypatch):
    first = parse_thread(copy.deepcopy(THREAD_001))
    second_raw = copy.deepcopy(THREAD_001)
    second_raw["thread"]["id"] = "thr_orbit_002"
    second_raw["thread"]["subject"] = "Second conversation"
    for i, message in enumerate(second_raw["messages"]):
        message["id"] = f"msg_orbit_002_{i}"
        message["in_reply_to"] = None if i == 0 else f"msg_orbit_002_{i - 1}"
    second = parse_thread(second_raw)
    monkeypatch.setattr(email_routes, "thread_from_mbox", lambda raw, thread_id=None: [first, second])
    response = client.post("/tenants/orbit/email/import", files={"file": ("mail.mbox", b"From alice@example.com\nSubject: x\n\nbody\n", "application/mbox")})
    assert response.status_code == 202
    body = response.json()
    assert body["thread_id"] == "thr_orbit_001" and len(body["threads"]) == 2
    assert {t["thread_id"] for t in body["threads"]} == {"thr_orbit_001", "thr_orbit_002"}
    for job in body["threads"]:
        assert client.get(f"/tenants/orbit/jobs/{job['job_id']}").status_code == 200
    # a single-thread return value (older ingest builds) still works
    monkeypatch.setattr(email_routes, "thread_from_mbox", lambda raw, thread_id=None: first)
    single = client.post("/tenants/orbit/email/import", files={"file": ("mail.mbox", b"From a@b\n\nx\n", "application/mbox")}).json()
    assert len(single["threads"]) == 1 and single["job_id"] == single["threads"][0]["job_id"]
