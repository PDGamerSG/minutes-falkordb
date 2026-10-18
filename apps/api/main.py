"""FastAPI application factory and lifespan (connect DB, ensure schema, load UDFs, start workers).

Run from the repo root: ``uv run --package minutes-api uvicorn apps.api.main:app --port 8080``.

A FalkorDB that is down at boot does not crash the process: the API serves with ``/health`` 503 and
retries the connection every ``STARTUP_RETRY_S`` seconds until it succeeds (then prepares tenants and
starts workers). Same for a model or embedder that fails to initialise.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ingest.embed import Embedder
from ingest.fakes import now_ms

from .config import Settings, get_settings
from .errors import install_error_handlers
from .hive_adapter import build_hive, register_default_agents
from .ingest_service import check_embedding_space
from .llm import make_llm
from .routes import all_routers
from .state import AppContext
from .workers import WorkerPool

log = logging.getLogger("apps.api")

STARTUP_RETRY_S = float(os.environ.get("STARTUP_RETRY_S", "15"))
LOCALHOST_CORS = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"


def cors_origin_regex(settings: Settings) -> str | None:
    patterns = [] if settings.is_production else [LOCALHOST_CORS]
    if settings.cors_origin_regex:
        patterns.append(settings.cors_origin_regex)
    return "|".join(f"(?:{p})" for p in patterns) or None


class UnavailableHive:
    """Placeholder hive while the database cannot be reached: every probe reports the failure."""

    kind = "unavailable"
    publishes_memory_events = False

    def __init__(self, error: str) -> None:
        self.error = error

    def ping(self) -> bool:
        return False

    def list_tenants(self) -> list[str]:
        raise RuntimeError(self.error)

    def db_version(self) -> str:
        return "unknown"

    def add_listener(self, tenant: str, fn: Any) -> None:
        return None

    def remove_listener(self, tenant: str, fn: Any) -> None:
        return None

    def close(self) -> None:
        return None


def build_context(settings: Settings | None = None) -> AppContext:
    """Connect everything from the environment (used by the lifespan and by ``data/seed.py``)."""
    settings = settings or get_settings()
    if settings.hf_home:
        os.environ.setdefault("HF_HOME", settings.hf_home)
    hive = build_hive(settings)
    llm = make_llm(settings)
    # Mixing embedding models in one index invalidates similarity scores. Demo vectors
    # must be requested explicitly; a model load failure must not change the vector space.
    embedder = Embedder(settings.embed_backend, settings.embed_model, settings.hf_home or os.environ.get("HF_HOME"), settings.gemini_api_key, strict=True)
    return AppContext(settings=settings, hive=hive, llm=llm, embedder=embedder)


def degraded_context(settings: Settings, error: str) -> AppContext:
    """A context that serves ``/health`` 503 (and nothing else useful) until the real one can be built."""
    ctx = AppContext(settings=settings, hive=UnavailableHive(error), llm=None, embedder=None)
    ctx.startup_error = error
    return ctx


def prepare_tenants(ctx: AppContext, tenants: list[str], *, create_missing: bool) -> list[str]:
    """Ensure schema (and optionally existence) of the seeded tenants; register the agents; check the embedding space."""
    hive = ctx.hive
    existing = set(hive.list_tenants())
    ready: list[str] = []
    for tenant in tenants:
        if tenant not in existing:
            if not create_missing:
                continue
            hive.create_tenant(tenant, tenant.capitalize())
        else:
            hive.ensure_schema(tenant)
        register_default_agents(hive, tenant, getattr(ctx.llm, "model", "fake"))
        check_embedding_space(ctx, tenant)
        ready.append(tenant)
    return ready


async def _prepare(context: AppContext, *, load_udfs: bool, start_workers: bool) -> None:
    """Schema, agents, embedding-space check and workers; failures land in ``startup_error`` (health 503)."""
    settings = context.settings
    tenants: list[str] = []
    try:
        if load_udfs:
            context.hive.load_udfs()
        tenants = await asyncio.to_thread(prepare_tenants, context, settings.seed_tenant_list, create_missing=bool(settings.auto_create_tenants))
        for tenant in await asyncio.to_thread(context.hive.list_tenants):
            if tenant not in tenants:
                await asyncio.to_thread(context.hive.ensure_schema, tenant)
                register_default_agents(context.hive, tenant, getattr(context.llm, "model", "fake"))
                check_embedding_space(context, tenant)
                tenants.append(tenant)
    except Exception as exc:  # noqa: BLE001 - fail loudly in logs but let /health report the state
        log.error("startup preparation failed: %s", exc)
        context.startup_error = f"Startup preparation failed: {type(exc).__name__}: {exc}"
    if context.embedding_mismatch and not context.startup_error:
        context.startup_error = "Embedding model mismatch: " + "; ".join(
            f"{t}: graph has {m['expected']}, API runs {m['actual']}" for t, m in context.embedding_mismatch.items()
        )
    if start_workers and not context.startup_error:
        context.workers = WorkerPool(context)
        await context.workers.start(tenants)
    log.info(
        "Minutes API ready: hive=%s llm=%s/%s embedder=%s tenants=%s auth=%s",
        getattr(context.hive, "kind", "?"),
        getattr(context.llm, "backend", "?"),
        getattr(context.llm, "model", "?"),
        getattr(context.embedder, "name", "?"),
        tenants,
        "admin_token" if settings.admin_token else "open",
    )
    if settings.is_production and not settings.admin_token:
        log.warning("ENV=production without ADMIN_TOKEN: demo, bench and tenant management routes are open")
    if settings.is_production and (settings.tenant_rw_password.startswith("change-me") or settings.tenant_ro_password.startswith("change-me")):
        log.warning("ENV=production with the default TENANT_RW_PASSWORD/TENANT_RO_PASSWORD: per-tenant database passwords are derived from them; set random values")


async def _retry_startup(app: FastAPI, settings: Settings, *, start_workers: bool, interval_s: float) -> None:
    """Rebuild the context until the database (or model) comes back, then swap it in."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            context = await asyncio.to_thread(build_context, settings)
        except Exception as exc:  # noqa: BLE001
            app.state.ctx.startup_error = f"Startup failed: {type(exc).__name__}: {exc}"
            log.warning("startup retry failed (%s); next attempt in %.0f s", exc, interval_s)
            continue
        context.started_at = now_ms()
        context.bus.bind(asyncio.get_running_loop())
        await _prepare(context, load_udfs=True, start_workers=start_workers)
        app.state.ctx = context
        log.info("startup retry succeeded; the API is now fully serving")
        return


def create_app(ctx: AppContext | None = None, *, start_workers: bool | None = None) -> FastAPI:
    """Build the app. Tests pass a ready ``AppContext`` (FakeHive, FakeLLM, FakeEmbedder)."""
    provided = ctx

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = provided.settings if provided is not None else get_settings()
        retry_task: asyncio.Task[None] | None = None
        try:
            context = provided or await asyncio.to_thread(build_context, settings)
        except Exception as exc:  # noqa: BLE001 - serve /health 503 instead of a restart loop (finding 5.4)
            log.error("startup failed: %s", exc)
            context = degraded_context(settings, f"Startup failed: {type(exc).__name__}: {exc}")
        context.started_at = now_ms()
        app.state.ctx = context
        run_workers = settings.workers_enabled if start_workers is None else start_workers
        if isinstance(context.hive, UnavailableHive):
            retry_task = asyncio.create_task(_retry_startup(app, settings, start_workers=run_workers, interval_s=STARTUP_RETRY_S), name="startup-retry")
        else:
            context.bus.bind(asyncio.get_running_loop())
            await _prepare(context, load_udfs=provided is None, start_workers=run_workers)
        try:
            yield
        finally:
            if retry_task is not None:
                retry_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await retry_task
            context = app.state.ctx
            if context.workers is not None:
                await context.workers.stop()
            if context.bus is not None:
                context.bus.close()
            close = getattr(context.hive, "close", None)
            if callable(close) and provided is None:
                close()

    settings = (ctx.settings if ctx is not None else get_settings())
    app = FastAPI(title="Minutes API", version="0.1.0", lifespan=lifespan, docs_url="/docs")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["http://localhost:3001"],
        # Any localhost origin is fine while developing; production trusts CORS_ORIGINS and CORS_ORIGIN_REGEX only (finding 2.8).
        allow_origin_regex=cors_origin_regex(settings),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    install_error_handlers(app)
    for router in all_routers():
        app.include_router(router)
    if ctx is not None:
        app.state.ctx = ctx
    return app


def _configure_logging() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


_configure_logging()
app: Any = create_app()
