"""Chat: AnswerAgent with router decision, Cypher, subgraph, sources and (free-form) rows; persistent Turn history.

With ``TENANT_KEYS_REQUIRED`` a session is stamped with the sha256 of the API key that created it and
``GET /chat/{session_id}`` only returns sessions created with the same key.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from ..agents.answer_agent import AnswerAgent
from ..auth import require_tenant_key, tenant_key_hash
from ..state import AppContext, get_ctx

router = APIRouter(prefix="/tenants/{tenant}", tags=["chat"], dependencies=[Depends(require_tenant_key)])


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=120)

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must contain text")
        return value.strip()


def _session_key(request: Request, ctx: AppContext) -> str | None:
    """The key hash that scopes chat history, only when tenant keys are enforced."""
    return tenant_key_hash(request) if ctx.settings.tenant_keys_required else None


@router.post("/chat")
async def chat(tenant: str, body: ChatBody, request: Request, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    agent = AnswerAgent(tenant, ctx.hive, ctx.llm, ctx.embedder, ctx.settings)
    return await asyncio.to_thread(agent.answer, body.message, body.session_id, _session_key(request, ctx))


@router.get("/chat/{session_id}")
def chat_history(tenant: str, session_id: str, request: Request, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    out = []
    for turn in ctx.hive.get_turns(tenant, session_id, key_hash=_session_key(request, ctx)):
        item: dict[str, Any] = {"role": turn.get("role"), "text": turn.get("text"), "t": turn.get("t"), "id": turn.get("id")}
        meta = turn.get("meta") or {}
        if turn.get("role") == "assistant" and isinstance(meta, dict) and meta.get("response"):
            item["response"] = meta["response"]
        out.append(item)
    return out
