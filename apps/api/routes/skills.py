"""Skills (procedural memory): list with PageRank, record outcome, run via the StandupAgent."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..state import AppContext, get_ctx

router = APIRouter(prefix="/tenants/{tenant}", tags=["skills"])


class OutcomeBody(BaseModel):
    ok: bool
    agent_id: str | None = Field(default=None, max_length=80)
    task_id: str | None = Field(default=None, max_length=80)


class RunBody(BaseModel):
    goal: str = Field(min_length=2, max_length=500)


def skill_view(skill: dict[str, Any], pagerank: dict[str, float]) -> dict[str, Any]:
    return {
        "id": skill.get("id"),
        "goal": skill.get("goal"),
        "version": skill.get("version", 1),
        "runs": skill.get("runs", 0),
        "success_rate": skill.get("success_rate", 0.0),
        "status": skill.get("status", "active"),
        "steps": [
            {"order": s.get("order"), "tool": s.get("tool"), "args_template": s.get("args_template"), "guard": s.get("guard")}
            for s in sorted(skill.get("steps") or [], key=lambda s: s.get("order") or 0)
        ],
        "learned_from": skill.get("learned_from") or [],
        "pagerank": pagerank.get(str(skill.get("id")), 0.0),
        "created_at": skill.get("created_at"),
    }


def _pagerank(ctx: AppContext, tenant: str) -> dict[str, float]:
    try:
        return {str(r.get("id")): float(r.get("score") or 0.0) for r in ctx.hive.skill_pagerank(tenant)}
    except Exception:  # noqa: BLE001 - PageRank is decoration
        return {}


@router.get("/skills")
def list_skills(tenant: str, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    ctx.ensure_tenant(tenant)
    ranks = _pagerank(ctx, tenant)
    return [skill_view(s, ranks) for s in ctx.hive.list_skills(tenant)]


@router.get("/skills/{skill_id}")
def get_skill(tenant: str, skill_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    return skill_view(ctx.hive.get_skill(tenant, skill_id), _pagerank(ctx, tenant))


@router.post("/skills/{skill_id}/outcome")
def record_outcome(tenant: str, skill_id: str, body: OutcomeBody, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    ctx.hive.record_outcome(tenant, skill_id, body.agent_id or "standup_agent", body.ok, body.task_id)
    return skill_view(ctx.hive.get_skill(tenant, skill_id), _pagerank(ctx, tenant))


@router.post("/skills/run", status_code=202)
def run_skill(tenant: str, body: RunBody, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Submit a ``run_skill`` task; the StandupAgent retrieves the Skill and executes its steps."""
    ctx.ensure_tenant(tenant)
    task_id = ctx.hive.submit_task(tenant, "run_skill", {"goal": body.goal}, ["standup"], [], 4)
    return {"task_id": task_id}
