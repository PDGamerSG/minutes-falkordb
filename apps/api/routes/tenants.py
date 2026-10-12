"""Tenants: list, create (admin), delete (admin), key rotation (admin), ACL isolation probe."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from ..auth import SLUG, api_key_from, hash_key, is_admin, issue_tenant_key, require_admin, require_tenant_key, stored_key_hash, valid_slug
from ..errors import ApiError
from ..hive_adapter import register_default_agents
from ..state import AppContext, get_ctx

log = logging.getLogger(__name__)

router = APIRouter(tags=["tenants"])


class TenantCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1, max_length=120)


def tenant_object(ctx: AppContext, tenant: str) -> dict[str, Any]:
    info = ctx.hive.tenant_info(tenant)
    acl = info.get("acl") or {}
    meta = {k: v for k, v in (info.get("meta") or {}).items() if k != "api_key_hash"}
    return {
        "slug": info.get("slug", tenant),
        "display_name": info.get("display_name") or tenant.capitalize(),
        "graph": info.get("graph") or f"team_{tenant}",
        "usage_mb": float(info.get("usage_mb", 0.0)),
        "nodes": int(info.get("nodes", 0)),
        "edges": int(info.get("edges", 0)),
        "counts": {k: info.get("counts", {}).get(k, 0) for k in ("episodes", "facts", "decisions", "commitments", "tasks", "skills")} | {k: v for k, v in info.get("counts", {}).items() if k not in ("episodes", "facts", "decisions", "commitments", "tasks", "skills")},
        "acl": {"rw_user": acl.get("rw_user"), "ro_user": acl.get("ro_user"), "rules": [_mask(r) for r in acl.get("rules", [])], **({"isolation": acl["isolation"]} if acl.get("isolation") else {})},
        "has_api_key": bool(stored_key_hash(ctx, tenant)),
        "embedding_model": meta.get("embedding_model"),
        "embedding_dim": meta.get("embedding_dim"),
    }


def _mask(rule: str) -> str:
    """Never ship a password or hash in an ACL line (hiveboard already redacts hashes; belt and braces)."""
    rule = re.sub(r">\S+", "><redacted>", rule)
    return re.sub(r"#[0-9a-f]{64}", "#<sha256>", rule)


def _visible_tenants(request: Request, ctx: AppContext) -> list[str]:
    """Every tenant locally; with TENANT_KEYS_REQUIRED only the tenants the supplied key (or admin token) unlocks."""
    tenants = list(ctx.hive.list_tenants())
    if not ctx.settings.tenant_keys_required or (ctx.settings.admin_token and is_admin(request, ctx) and (request.headers.get("x-admin-token") or request.headers.get("authorization"))):
        return tenants
    key = api_key_from(request)
    if not key:
        return []
    digest = hash_key(key)
    return [t for t in tenants if stored_key_hash(ctx, t) == digest]


@router.get("/tenants")
def list_tenants(request: Request, ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    return [tenant_object(ctx, t) for t in _visible_tenants(request, ctx)]


@router.post("/tenants", status_code=201, dependencies=[Depends(require_admin)])
async def create_tenant(
    body: TenantCreate,
    rotate: bool = Query(False, description="admin: re-issue the API key (and refresh the display name) of an existing tenant"),
    ctx: AppContext = Depends(get_ctx),
) -> dict[str, Any]:
    """Create a tenant and return it with its API key (shown once). An existing slug is 409 unless ``?rotate=true``."""
    if not valid_slug(body.slug):
        raise ApiError(400, "invalid_slug", f"slug must match {SLUG.pattern} and must not contain '__snap_'")

    def provision() -> tuple[bool, str]:
        exists = body.slug in ctx.hive.list_tenants()
        if exists and not rotate:
            raise ApiError(409, "tenant_exists", f"tenant {body.slug!r} already exists; pass ?rotate=true (admin) to re-issue its key")
        ctx.hive.create_tenant(body.slug, body.display_name, rotate=rotate)
        register_default_agents(ctx.hive, body.slug, getattr(ctx.llm, "model", "fake"))
        return exists, issue_tenant_key(ctx, body.slug, reason="rotated" if exists else "created")

    _, key = await asyncio.to_thread(provision)  # blocking database calls stay off the event loop
    if ctx.workers is not None:
        await ctx.workers.start_tenant(body.slug)
    return {**(await asyncio.to_thread(tenant_object, ctx, body.slug)), "api_key": key}


@router.get("/tenants/{tenant}", dependencies=[Depends(require_tenant_key)])
def get_tenant(tenant: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    return tenant_object(ctx, tenant)


@router.delete("/tenants/{tenant}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_tenant(tenant: str, ctx: AppContext = Depends(get_ctx)) -> Response:
    """Admin: stop the tenant's workers and drop its graph, snapshots, ACL users and registry row."""
    await asyncio.to_thread(ctx.ensure_tenant, tenant)
    if ctx.workers is not None:
        await ctx.workers.stop_tenant(tenant)
    await asyncio.to_thread(ctx.hive.delete_tenant, tenant)
    log.warning("tenant %s deleted", tenant)
    return Response(status_code=204)


@router.post("/tenants/{tenant}/rotate-key", dependencies=[Depends(require_admin)])
def rotate_key(tenant: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Admin: issue a new API key for the tenant (the old one stops working immediately)."""
    ctx.ensure_tenant(tenant)
    return {"slug": tenant, "api_key": issue_tenant_key(ctx, tenant, reason="rotated")}


@router.get("/tenants/{tenant}/acl-probe", dependencies=[Depends(require_tenant_key)])
def acl_probe(tenant: str, target: str = Query(..., description="another tenant slug"), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ctx.ensure_tenant(tenant)
    if not valid_slug(target) or target not in ctx.hive.list_tenants():
        raise ApiError(404, "tenant_not_found", f"target tenant {target!r} does not exist")
    result = ctx.hive.acl_probe(tenant, target)
    return {"allowed": bool(result.get("allowed")), "error": result.get("error"), **{k: v for k, v in result.items() if k not in ("allowed", "error")}}
