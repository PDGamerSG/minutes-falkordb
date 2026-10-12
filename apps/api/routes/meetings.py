"""Meetings: list, import (async job, size-limited), job polling, episodes, audio."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from ingest.recorder_format import parse_export

from ..auth import require_tenant_key
from ..config import REPO_ROOT
from ..errors import ApiError
from ..ingest_service import ensure_embedding_space, import_meeting
from ..state import AppContext, get_ctx

router = APIRouter(prefix="/tenants/{tenant}", tags=["meetings"], dependencies=[Depends(require_tenant_key)])

JSON_TYPES = ("application/json", "text/json", "application/*+json")


async def read_limited_body(request: Request, max_bytes: int) -> bytes:
    """The raw body, refused with 413 when ``Content-Length`` or the bytes actually read exceed ``max_bytes``."""
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > max_bytes:
                raise ApiError(413, "payload_too_large", f"body is {int(declared)} bytes; the limit is {max_bytes} bytes (MAX_IMPORT_BYTES)")
        except ValueError:
            raise ApiError(400, "bad_request", "invalid Content-Length") from None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise ApiError(413, "payload_too_large", f"body exceeds the {max_bytes} byte limit (MAX_IMPORT_BYTES)")
        chunks.append(chunk)
    return b"".join(chunks)


def require_json_content_type(request: Request) -> None:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type and not (content_type in JSON_TYPES or content_type.endswith("+json")):
        raise ApiError(415, "unsupported_media_type", f"content-type {content_type!r} is not accepted; send application/json")


def meeting_row(ctx: AppContext, tenant: str, meeting: dict[str, Any]) -> dict[str, Any]:
    job = ctx.jobs.for_container(tenant, meeting["id"])
    status = "ingested"
    if job and job["status"] in ("queued", "running"):
        status = job["status"]
    elif job and job["status"] == "failed":
        status = "failed"
    return {
        "id": meeting["id"],
        "title": meeting.get("title"),
        "started_at": meeting.get("started_at"),
        "ended_at": meeting.get("ended_at"),
        "source_uri": meeting.get("source_uri"),
        "episodes": int(meeting.get("episodes") or 0),
        "facts": int(meeting.get("facts") or 0),
        "status": status,
    }


@router.get("/meetings")
def list_meetings(tenant: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return [meeting_row(ctx, tenant, m) for m in ctx.hive.list_meetings(tenant)]


def _parse_export_bytes(raw: bytes) -> Any:
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise ApiError(400, "invalid_json", f"body must be the recorder export JSON: {exc}") from exc
    return parse_export(body)


@router.post("/meetings/import", status_code=202)
async def import_meeting_route(tenant: str, request: Request, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    require_json_content_type(request)
    await asyncio.to_thread(ensure_embedding_space, ctx, tenant)
    raw = await read_limited_body(request, ctx.settings.max_import_bytes)
    export = await asyncio.to_thread(_parse_export_bytes, raw)  # parsing a multi-MB export stays off the event loop
    job_id = ctx.jobs.create(tenant, "meeting", export.meeting.id)

    def work(progress: Any) -> dict[str, Any]:
        return import_meeting(export, tenant, ctx, progress=progress)

    ctx.spawn(ctx.jobs.run_async(job_id, work))
    return {"meeting_id": export.meeting.id, "job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(tenant: str, job_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    job = ctx.jobs.get(job_id)
    if job is None or job["tenant"] != tenant:
        raise ApiError(404, "job_not_found", f"job {job_id!r} not found for tenant {tenant!r}")
    stats = job.get("stats") or {}
    out = {
        "job_id": job_id,
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "kind": job["kind"],
        "container_id": job["container_id"],
        "stats": {
            "episodes": stats.get("episodes", 0),
            "entities": stats.get("entities", 0),
            "facts": stats.get("facts", 0),
            "decisions": stats.get("decisions", 0),
            "commitments": stats.get("commitments", 0),
            "superseded": stats.get("superseded", 0),
            **{k: v for k, v in stats.items() if k not in ("episodes", "entities", "facts", "decisions", "commitments", "superseded")},
        },
    }
    if job.get("error"):
        out["error"] = job["error"]
    return out


@router.get("/meetings/{meeting_id}")
def get_meeting(tenant: str, meeting_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    rows = [m for m in ctx.hive.list_meetings(tenant) if m["id"] == meeting_id]
    if not rows:
        raise ApiError(404, "meeting_not_found", f"meeting {meeting_id!r} not found")
    return meeting_row(ctx, tenant, rows[0])


@router.get("/meetings/{meeting_id}/episodes")
def meeting_episodes(tenant: str, meeting_id: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    if ctx.hive.get_meeting(tenant, meeting_id) is None:
        raise ApiError(404, "meeting_not_found", f"meeting {meeting_id!r} not found")
    persons = {p["id"]: p for p in ctx.hive.list_persons(tenant)}
    out = []
    for ep in ctx.hive.meeting_episodes(tenant, meeting_id):
        speaker_id = ep.get("speaker_id")
        person = persons.get(speaker_id or "", {})
        out.append(
            {
                "id": ep["id"],
                "seq": ep.get("seq"),
                "speaker": {"id": speaker_id, "name": person.get("name") or (ep.get("speaker") or {}).get("name") or speaker_id},
                "text": ep.get("text"),
                "t_start": ep.get("t_start"),
                "t_end": ep.get("t_end"),
                "t_occurred": ep.get("t_occurred"),
                "source_kind": ep.get("source_kind") or "utterance",
            }
        )
    return out


def _audio_path(source_uri: str | None, data_root: Path) -> Path | None:
    """Resolve ``source_uri`` under the repo root or the data dir; only files under data/meetings are served."""
    if not source_uri:
        return None
    candidates = [REPO_ROOT / source_uri, data_root.parent / source_uri, data_root / "meetings" / Path(source_uri).name]
    allowed = (data_root / "meetings").resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_relative_to(allowed) and resolved.is_file():
            return resolved
    return None


@router.get("/meetings/{meeting_id}/audio")
def meeting_audio(tenant: str, meeting_id: str, ctx: AppContext = Depends(get_ctx)) -> FileResponse:
    """Audio file when present. ``<audio>`` cannot set headers: with tenant keys required this route also accepts ``?api_key=``."""
    ctx.ensure_tenant(tenant)
    meeting = ctx.hive.get_meeting(tenant, meeting_id)
    if meeting is None:
        raise ApiError(404, "meeting_not_found", f"meeting {meeting_id!r} not found")
    path = _audio_path(meeting.get("source_uri"), ctx.settings.data_path)
    if path is None:
        raise ApiError(404, "audio_not_found", f"no audio file for meeting {meeting_id!r} (source_uri={meeting.get('source_uri')!r})")
    media = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mp4" if path.suffix.lower() == ".m4a" else "application/octet-stream"
    return FileResponse(str(path), media_type=media, filename=path.name)
