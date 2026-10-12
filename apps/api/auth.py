"""Authentication: an admin token for mutating/shared endpoints and per-tenant API keys.

* ``ADMIN_TOKEN`` (env). When set, ``POST /tenants``, ``DELETE /tenants/{t}``, ``/tenants/{t}/demo/*``,
  ``POST /bench/run``, ``POST /tenants/{t}/snapshots``, ``POST /tenants/{t}/work-items/import`` and
  ``POST /tenants/{t}/rotate-key`` require ``Authorization: Bearer <token>`` or ``X-Admin-Token: <token>``.
  Unset (local development) means those routes are open, and ``/health`` says so.
* ``TENANT_KEYS_REQUIRED`` (env, default false). When true every ``/tenants/{t}/...`` route requires
  ``X-API-Key`` matching the tenant's key. Keys are generated at tenant creation
  (``secrets.token_urlsafe(24)``), stored as a sha256 hash in the tenant meta (``api_key_hash``), returned
  once by ``POST /tenants`` (and ``POST /tenants/{t}/rotate-key``) and printed in the API log at creation.
  The admin token is also accepted in place of a tenant key. Browser-native consumers that cannot set
  headers (``EventSource`` for ``/events``, ``<audio>`` for ``/audio``) may pass ``?api_key=`` instead.

401 (missing credential) and 403 (wrong credential) use the error envelope.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from typing import Any

from fastapi import Depends, Request

from .errors import ApiError
from .state import AppContext, get_ctx

log = logging.getLogger(__name__)

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")  # mirrors hiveboard.HiveDB.graph_name
SNAPSHOT_MARK = "__snap_"
QUERY_KEY_ROUTES = ("/events", "/audio")  # the only routes that accept ?api_key= (EventSource and <audio> cannot set headers)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_api_key() -> tuple[str, str]:
    """``(plain, sha256)`` for a fresh tenant key."""
    key = secrets.token_urlsafe(24)
    return key, hash_key(key)


def valid_slug(slug: str) -> bool:
    return bool(SLUG.match(slug)) and SNAPSHOT_MARK not in slug


def _admin_token_from(request: Request) -> str | None:
    header = request.headers.get("x-admin-token")
    if header:
        return header.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def is_admin(request: Request, ctx: AppContext) -> bool:
    """True when no admin token is configured (open local mode) or the request carries the right one."""
    expected = ctx.settings.admin_token
    if not expected:
        return True
    supplied = _admin_token_from(request)
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def require_admin(request: Request, ctx: AppContext = Depends(get_ctx)) -> None:
    """Dependency for admin-only routes."""
    expected = ctx.settings.admin_token
    if not expected:
        return
    supplied = _admin_token_from(request)
    if not supplied:
        raise ApiError(401, "admin_token_required", "this route requires Authorization: Bearer <ADMIN_TOKEN> or X-Admin-Token")
    if not hmac.compare_digest(supplied, expected):
        raise ApiError(403, "admin_token_invalid", "the admin token is not valid")


def api_key_from(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    if any(request.url.path.endswith(suffix) for suffix in QUERY_KEY_ROUTES):
        return request.query_params.get("api_key") or None
    return None


def tenant_key_hash(request: Request) -> str | None:
    """sha256 of the X-API-Key the request carries (None when absent); used to scope chat sessions."""
    key = api_key_from(request)
    return hash_key(key) if key else None


def stored_key_hash(ctx: AppContext, tenant: str) -> str | None:
    try:
        meta = ctx.hive.get_tenant_meta(tenant) or {}
    except Exception as exc:  # noqa: BLE001 - a meta read failure must not grant access
        log.warning("get_tenant_meta(%s) failed: %s", tenant, exc)
        return None
    value = meta.get("api_key_hash")
    return str(value) if value else None


def require_tenant_key(tenant: str, request: Request, ctx: AppContext = Depends(get_ctx)) -> None:
    """Dependency on every ``/tenants/{tenant}`` router: existence check plus the per-tenant key when required."""
    if not ctx.settings.tenant_keys_required:
        ctx.ensure_tenant(tenant)
        return
    if is_admin(request, ctx) and _admin_token_from(request):
        ctx.ensure_tenant(tenant)
        return
    supplied = api_key_from(request)
    if not supplied:
        raise ApiError(401, "api_key_required", "this tenant route requires X-API-Key")
    ctx.ensure_tenant(tenant)
    expected = stored_key_hash(ctx, tenant)
    if not expected or not hmac.compare_digest(hash_key(supplied), expected):
        raise ApiError(403, "api_key_invalid", f"the API key is not valid for tenant {tenant!r}")


def issue_tenant_key(ctx: AppContext, tenant: str, *, reason: str) -> str:
    """Generate, store (hashed) and log a new key for ``tenant``; returns the plain key (shown once)."""
    from ingest.fakes import now_ms

    key, digest = new_api_key()
    ctx.hive.set_tenant_meta(tenant, {"api_key_hash": digest, "api_key_created_at": now_ms()})
    log.info("tenant %s API key (%s): %s", tenant, reason, key)
    return key


def admin_mode(ctx: AppContext) -> dict[str, Any]:
    """What ``/health`` reports about auth."""
    return {"admin_token": bool(ctx.settings.admin_token), "tenant_keys_required": bool(ctx.settings.tenant_keys_required)}
