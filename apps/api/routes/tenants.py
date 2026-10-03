"""Tenants: list, create, ACL isolation probe."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..errors import ApiError
from ..hive_adapter import register_default_agents
from ..state import AppContext, get_ctx

router = APIRouter(tags=["tenants"])

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_]{0,62}$")


class TenantCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1, max_length=120)


def tenant_object(ctx: AppContext, tenant: str) -> dict:
    info = ctx.hive.tenant_info(tenant)
    acl = info.get("acl") or {}
    return {
        "slug": info.get("slug", tenant),
        "display_name": info.get("display_name") or tenant.capitalize(),
        "graph": info.get("graph") or f"team_{tenant}",
        "usage_mb": info.get("usage_mb", 0.0),
        "counts": {k: info.get("counts", {}).get(k, 0) for k in ("episodes", "facts", "decisions", "commitments", "tasks", "skills")} | {k: v for k, v in info.get("counts", {}).items() if k not in ("episodes", "facts", "decisions", "commitments", "tasks", "skills")},
        "acl": {"rw_user": acl.get("rw_user"), "ro_user": acl.get("ro_user"), "rules": [_mask(r) for r in acl.get("rules", [])], **({"isolation": acl["isolation"]} if acl.get("isolation") else {})},
    }


def _mask(rule: str) -> str:
    """Never ship a password or hash in an ACL line (hiveboard already redacts hashes; belt and braces)."""
    rule = re.sub(r">\S+", "><redacted>", rule)
    return re.sub(r"#[0-9a-f]{64}", "#<sha256>", rule)


@router.get("/tenants")
def list_tenants(ctx: AppContext = Depends(get_ctx)) -> list[dict]:
    return [tenant_object(ctx, t) for t in ctx.hive.list_tenants()]


@router.post("/tenants", status_code=201)
async def create_tenant(body: TenantCreate, ctx: AppContext = Depends(get_ctx)) -> dict:
    if not _SLUG.match(body.slug):
        raise ApiError(400, "invalid_slug", "slug must match [a-z0-9][a-z0-9_]{0,62}")
    ctx.hive.create_tenant(body.slug, body.display_name)
    register_default_agents(ctx.hive, body.slug, getattr(ctx.llm, "model", "fake"))
    if ctx.workers is not None:
        await ctx.workers.start_tenant(body.slug)
    return tenant_object(ctx, body.slug)


@router.get("/tenants/{tenant}")
def get_tenant(tenant: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    ctx.ensure_tenant(tenant)
    return tenant_object(ctx, tenant)


@router.get("/tenants/{tenant}/acl-probe")
def acl_probe(tenant: str, target: str = Query(..., description="another tenant slug"), ctx: AppContext = Depends(get_ctx)) -> dict:
    ctx.ensure_tenant(tenant)
    if target not in ctx.hive.list_tenants():
        raise ApiError(404, "tenant_not_found", f"target tenant {target!r} does not exist")
    result = ctx.hive.acl_probe(tenant, target)
    return {"allowed": bool(result.get("allowed")), "error": result.get("error"), **{k: v for k, v in result.items() if k not in ("allowed", "error")}}
