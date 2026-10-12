"""Email threads: import (JSON body or multipart .eml/.mbox, size-limited), list, messages.

An mbox may hold several conversations: ``thread_from_mbox`` returns a list of threads and the import
creates one job per thread (``threads: [{thread_id, job_id}]``; ``thread_id``/``job_id`` are the first).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from ingest.email_format import EmailFormatError, parse_thread, thread_from_eml, thread_from_mbox

from ..auth import require_tenant_key
from ..errors import ApiError
from ..ingest_service import ensure_embedding_space, import_thread
from ..state import AppContext, get_ctx
from .meetings import read_limited_body

router = APIRouter(prefix="/tenants/{tenant}", tags=["email"], dependencies=[Depends(require_tenant_key)])

UPLOAD_TYPES = {"message/rfc822", "application/mbox", "application/json", "text/plain", "application/octet-stream", "text/x-mbox"}
BODY_TYPES = {"application/json", "multipart/form-data"}


def _as_threads(parsed: Any) -> list[Any]:
    return list(parsed) if isinstance(parsed, (list, tuple)) else [parsed]


def _parse_upload(raw: bytes, name: str, thread_id: str | None) -> list[Any]:
    """CPU-bound parsing of an uploaded file (runs in a thread)."""
    if name.endswith(".mbox") or raw.startswith(b"From "):
        return _as_threads(thread_from_mbox(raw, thread_id=thread_id))
    if name.endswith(".json"):
        return [parse_thread(raw)]
    return [thread_from_eml(raw, thread_id=thread_id)]


def _parse_json(raw: bytes) -> list[Any]:
    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise ApiError(400, "invalid_json", f"body must be the thread JSON or a multipart file: {exc}") from exc
    return [parse_thread(body)]


async def _threads_from_request(request: Request, max_bytes: int) -> list[Any]:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type and content_type not in BODY_TYPES:
        raise ApiError(415, "unsupported_media_type", f"content-type {content_type!r} is not accepted; send application/json or multipart/form-data")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise ApiError(413, "payload_too_large", f"body is {declared} bytes; the limit is {max_bytes} bytes (MAX_IMPORT_BYTES)")
    if content_type == "multipart/form-data":
        form = await request.form(max_files=2, max_fields=10)
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise ApiError(400, "missing_file", "multipart upload needs a 'file' field with an .eml or .mbox file")
        upload_type = (getattr(upload, "content_type", "") or "").split(";")[0].strip().lower()
        if upload_type and upload_type not in UPLOAD_TYPES:
            raise ApiError(415, "unsupported_media_type", f"uploaded file type {upload_type!r} is not accepted; expected one of {sorted(UPLOAD_TYPES)}")
        raw = await upload.read()
        if len(raw) > max_bytes:
            raise ApiError(413, "payload_too_large", f"uploaded file exceeds the {max_bytes} byte limit (MAX_IMPORT_BYTES)")
        name = (getattr(upload, "filename", "") or "").lower()
        thread_id = form.get("thread_id")
        return await asyncio.to_thread(_parse_upload, raw, name, str(thread_id) if thread_id else None)
    raw = await read_limited_body(request, max_bytes)
    return await asyncio.to_thread(_parse_json, raw)


@router.post("/email/import", status_code=202)
async def import_email(tenant: str, request: Request, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    await asyncio.to_thread(ensure_embedding_space, ctx, tenant)
    try:
        threads = await _threads_from_request(request, ctx.settings.max_import_bytes)
    except EmailFormatError as exc:
        raise ApiError(400, "invalid_email_thread", str(exc)[:2000]) from exc
    if not threads:
        raise ApiError(400, "invalid_email_thread", "no messages found in the upload")
    jobs: list[dict[str, str]] = []
    for thread in threads:
        job_id = ctx.jobs.create(tenant, "thread", thread.thread.id)

        def work(progress: Any, thread: Any = thread) -> dict[str, Any]:
            return import_thread(thread, tenant, ctx, progress=progress)

        ctx.spawn(ctx.jobs.run_async(job_id, work))
        jobs.append({"thread_id": thread.thread.id, "job_id": job_id})
    return {"thread_id": jobs[0]["thread_id"], "job_id": jobs[0]["job_id"], "threads": jobs}


def thread_row(ctx: AppContext, tenant: str, thread: dict[str, Any]) -> dict[str, Any]:
    job = ctx.jobs.for_container(tenant, thread["id"])
    status = "ingested"
    if job and job["status"] in ("queued", "running"):
        status = job["status"]
    elif job and job["status"] == "failed":
        status = "failed"
    return {
        "id": thread["id"],
        "subject": thread.get("subject"),
        "started_at": thread.get("started_at"),
        "messages": int(thread.get("messages") or 0),
        "facts": int(thread.get("facts") or 0),
        "status": status,
    }


@router.get("/threads")
def list_threads(tenant: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    return [thread_row(ctx, tenant, t) for t in ctx.hive.list_threads(tenant)]


@router.get("/threads/{thread_id}")
def get_thread(tenant: str, thread_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    rows = [t for t in ctx.hive.list_threads(tenant) if t["id"] == thread_id]
    if not rows:
        raise ApiError(404, "thread_not_found", f"thread {thread_id!r} not found")
    return thread_row(ctx, tenant, rows[0])


@router.get("/threads/{thread_id}/messages")
def thread_messages(tenant: str, thread_id: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    if ctx.hive.get_thread(tenant, thread_id) is None:
        raise ApiError(404, "thread_not_found", f"thread {thread_id!r} not found")
    persons = {p["id"]: p for p in ctx.hive.list_persons(tenant)}

    def person(pid: str | None) -> dict[str, Any]:
        p = persons.get(pid or "", {})
        return {"id": pid, "name": p.get("name") or pid, "email": p.get("email")}

    out = []
    for msg in ctx.hive.thread_messages(tenant, thread_id):
        sender_id = msg.get("speaker_id") or msg.get("sender_id")
        out.append(
            {
                "id": msg["id"],
                "seq": msg.get("seq"),
                "message_id": msg.get("message_id") or msg["id"],
                "sender": person(sender_id),
                "to": [person(p) for p in msg.get("to_ids") or []],
                "cc": [person(p) for p in msg.get("cc_ids") or []],
                "sent_at": msg.get("t_occurred"),
                "text": msg.get("text"),
                "in_reply_to": msg.get("in_reply_to_episode_id"),
                "source_kind": "email",
            }
        )
    return out
