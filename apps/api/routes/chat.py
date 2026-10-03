"""Chat: AnswerAgent with router decision, Cypher, subgraph and sources; persistent Turn history."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..agents.answer_agent import AnswerAgent
from ..state import AppContext, get_ctx

router = APIRouter(prefix="/tenants/{tenant}", tags=["chat"])


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=120)


@router.post("/chat")
async def chat(tenant: str, body: ChatBody, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    agent = AnswerAgent(tenant, ctx.hive, ctx.llm, ctx.embedder, ctx.settings)
    return await asyncio.to_thread(agent.answer, body.message, body.session_id)


@router.get("/chat/{session_id}")
def chat_history(tenant: str, session_id: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    out = []
    for turn in ctx.hive.get_turns(tenant, session_id):
        item: dict[str, Any] = {"role": turn.get("role"), "text": turn.get("text"), "t": turn.get("t"), "id": turn.get("id")}
        meta = turn.get("meta") or {}
        if turn.get("role") == "assistant" and isinstance(meta, dict) and meta.get("response"):
            item["response"] = meta["response"]
        out.append(item)
    return out
