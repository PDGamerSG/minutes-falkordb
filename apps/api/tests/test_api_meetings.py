"""Meetings and email threads: list, import jobs, episodes, audio, messages, multipart upload."""

from __future__ import annotations

import copy
import time


def _wait_job(client, tenant, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/tenants/{tenant}/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {job}")


def test_list_meetings(client):
    meetings = client.get("/tenants/orbit/meetings").json()
    assert [m["id"] for m in meetings] == ["mtg_orbit_001", "mtg_orbit_002", "mtg_orbit_003"]
    kickoff = meetings[0]
    assert kickoff["title"] == "Orbit kickoff" and kickoff["status"] == "ingested"
    assert kickoff["episodes"] == 4 and kickoff["facts"] == 5
    assert kickoff["source_uri"] == "data/meetings/orbit_001.wav" and kickoff["started_at"] == 1788755400000


def test_import_meeting_job_and_episodes(client, sample_meeting):
    meeting = copy.deepcopy(sample_meeting)
    meeting["meeting"].update({"id": "mtg_orbit_099", "title": "Orbit extra", "started_at": "2026-10-01T10:00:00+05:30", "ended_at": None})
    response = client.post("/tenants/orbit/meetings/import", json=meeting)
    assert response.status_code == 202
    body = response.json()
    assert body["meeting_id"] == "mtg_orbit_099" and body["job_id"].startswith("job_")
    job = _wait_job(client, "orbit", body["job_id"])
    assert job["status"] == "done" and job["progress"] == 1.0 and job["stage"] == "done"
    assert job["stats"]["episodes"] == 4 and set(job["stats"]) >= {"episodes", "entities", "facts", "decisions", "commitments", "superseded"}
    episodes = client.get("/tenants/orbit/meetings/mtg_orbit_099/episodes").json()
    assert len(episodes) == 4
    assert episodes[1]["speaker"] == {"id": "spk_priya", "name": "Priya"}
    assert episodes[1]["t_start"] == 8000 and episodes[1]["t_end"] == 22000 and episodes[1]["seq"] == 1
    assert episodes[1]["t_occurred"] == episodes[0]["t_occurred"] + 8000
    assert client.get("/tenants/orbit/meetings/mtg_orbit_099").json()["status"] == "ingested"


def test_import_rejects_invalid_export(client):
    response = client.post("/tenants/orbit/meetings/import", json={"version": 1, "meeting": {}})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_recorder_export"


def test_job_not_found(client):
    assert client.get("/tenants/orbit/jobs/job_missing").status_code == 404


def test_episodes_unknown_meeting(client):
    assert client.get("/tenants/orbit/meetings/mtg_nope/episodes").status_code == 404


def test_audio_404_when_missing(client):
    response = client.get("/tenants/orbit/meetings/mtg_orbit_001/audio", headers={"Range": "bytes=0-0"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "audio_not_found"


def test_audio_path_rejects_sibling_directory_with_same_prefix(tmp_path):
    from apps.api.routes.meetings import _audio_path

    allowed = tmp_path / "meetings"
    sibling = tmp_path / "meetings_private"
    allowed.mkdir()
    sibling.mkdir()
    private = sibling / "private.wav"
    private.write_bytes(b"private")
    assert _audio_path(str(private), tmp_path) is None
    public = allowed / "public.wav"
    public.write_bytes(b"RIFF")
    assert _audio_path(str(public), tmp_path) == public


def test_audio_served_when_present(client, data_dir):
    wav = data_dir / "meetings" / "orbit_001.wav"
    wav.write_bytes(b"RIFF....WAVEfmt ")
    try:
        response = client.get("/tenants/orbit/meetings/mtg_orbit_001/audio")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/wav")
        assert response.content.startswith(b"RIFF")
    finally:
        wav.unlink()


def test_threads_and_messages(client):
    threads = client.get("/tenants/orbit/threads").json()
    assert threads == [{"id": "thr_orbit_001", "subject": "UPI flow timeline", "started_at": 1789633920000, "messages": 2, "facts": 1, "status": "ingested"}]
    messages = client.get("/tenants/orbit/threads/thr_orbit_001/messages").json()
    assert len(messages) == 2
    first, second = messages
    assert first["sender"] == {"id": "spk_priya", "name": "Priya", "email": "priya@orbit.example"}
    assert [p["id"] for p in first["to"]] == ["spk_aditya"] and [p["id"] for p in first["cc"]] == ["spk_rahul"]
    assert first["sent_at"] == 1789633920000 and first["in_reply_to"] is None
    assert second["in_reply_to"] == first["id"] and second["text"] == "Understood, Monday it is."
    assert client.get("/tenants/orbit/threads/thr_nope/messages").status_code == 404


def test_import_thread_json(client, sample_thread):
    thread = copy.deepcopy(sample_thread)
    thread["thread"].update({"id": "thr_orbit_077", "subject": "Launch checklist", "started_at": "2026-10-02T09:00:00+05:30"})
    for i, msg in enumerate(thread["messages"]):
        msg["id"] = f"msg_077_{i}"
        msg["sent_at"] = f"2026-10-02T09:{i:02d}:00+05:30"
        msg["in_reply_to"] = None if i == 0 else "msg_077_0"
    response = client.post("/tenants/orbit/email/import", json=thread)
    assert response.status_code == 202
    body = response.json()
    assert body["thread_id"] == "thr_orbit_077"
    job = _wait_job(client, "orbit", body["job_id"])
    assert job["status"] == "done" and job["kind"] == "thread" and job["stats"]["episodes"] == 2
    assert any(t["id"] == "thr_orbit_077" for t in client.get("/tenants/orbit/threads").json())


def test_import_thread_multipart_eml(client):
    eml = (
        b"From: Priya <priya@orbit.example>\nTo: Aditya <aditya@orbit.example>\nSubject: Sandbox keys\n"
        b"Date: Fri, 02 Oct 2026 10:00:00 +0530\nMessage-ID: <keys-1@orbit.example>\nContent-Type: text/plain\n\n"
        b"Keys arrived, UPI flow unblocked.\n\nOn Thu, Oct 1, 2026 Aditya wrote:\n> any news?\n"
    )
    response = client.post("/tenants/orbit/email/import", files={"file": ("keys.eml", eml, "message/rfc822")})
    assert response.status_code == 202
    body = response.json()
    job = _wait_job(client, "orbit", body["job_id"])
    assert job["status"] == "done"
    messages = client.get(f"/tenants/orbit/threads/{body['thread_id']}/messages").json()
    assert messages[0]["text"] == "Keys arrived, UPI flow unblocked."
    assert messages[0]["sender"]["id"] == "spk_priya"


def test_import_thread_multipart_requires_file(client):
    response = client.post("/tenants/orbit/email/import", files={"other": ("x.eml", b"...", "message/rfc822")})
    assert response.status_code == 400 and response.json()["error"]["code"] == "missing_file"


def test_import_thread_invalid(client):
    response = client.post("/tenants/orbit/email/import", json={"version": 1, "thread": {"id": "t"}, "messages": []})
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_email_thread"
