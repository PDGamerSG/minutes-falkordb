"""Email threads: import (JSON body or multipart .eml/.mbox), list, messages."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from ingest.email_format import EmailFormatError, parse_thread, thread_from_eml, thread_from_mbox

from ..errors import ApiError
from ..ingest_service import import_thread
from ..state import AppContext, get_ctx

router = APIRouter(prefix="/tenants/{tenant}", tags=["email"])


async def _thread_from_request(request: Request) -> Any:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise ApiError(400, "missing_file", "multipart upload needs a 'file' field with an .eml or .mbox file")
        raw = await upload.read()
        name = (getattr(upload, "filename", "") or "").lower()
        thread_id = form.get("thread_id")
        if name.endswith(".mbox") or raw.startswith(b"From "):
            return thread_from_mbox(raw, thread_id=str(thread_id) if thread_id else None)
        if name.endswith(".json"):
            return parse_thread(raw)
        return thread_from_eml(raw, thread_id=str(thread_id) if thread_id else None)
    try:
        body = await request.json()
    except ValueError as exc:
        raise ApiError(400, "invalid_json", f"body must be the thread JSON or a multipart file: {exc}") from exc
    return parse_thread(body)


@router.post("/email/import", status_code=202)
async def import_email(tenant: str, request: Request, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    try:
        thread = await _thread_from_request(request)
    except EmailFormatError as exc:
        raise ApiError(400, "invalid_email_thread", str(exc)[:2000]) from exc
    job_id = ctx.jobs.create(tenant, "thread", thread.thread.id)

    def work(progress: Any) -> dict[str, Any]:
        return import_thread(thread, tenant, ctx, progress=progress)

    asyncio.create_task(ctx.jobs.run_async(job_id, work))
    return {"thread_id": thread.thread.id, "job_id": job_id}


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
