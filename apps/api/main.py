"""FastAPI application factory and lifespan (connect DB, ensure schema, load UDFs, start workers).

Run from the repo root: ``uv run --package minutes-api uvicorn apps.api.main:app --port 8080``.
"""

from __future__ import annotations

import asyncio
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
from .llm import make_llm
from .routes import all_routers
from .state import AppContext
from .workers import WorkerPool

log = logging.getLogger("apps.api")


def build_context(settings: Settings | None = None) -> AppContext:
    """Connect everything from the environment (used by the lifespan and by ``data/seed.py``)."""
    settings = settings or get_settings()
    if settings.hf_home:
        os.environ.setdefault("HF_HOME", settings.hf_home)
    hive = build_hive(settings)
    llm = make_llm(settings)
    embedder = Embedder(settings.embed_backend, settings.embed_model, settings.hf_home or os.environ.get("HF_HOME"), settings.gemini_api_key)
    if embedder.is_fake and settings.embed_backend != "fake":
        log.warning("EMBED_BACKEND=%s requested but the FakeEmbedder is in use (see the warning above)", settings.embed_backend)
    return AppContext(settings=settings, hive=hive, llm=llm, embedder=embedder)


def prepare_tenants(ctx: AppContext, tenants: list[str], *, create_missing: bool) -> list[str]:
    """Ensure schema (and optionally existence) of the seeded tenants; register the agents."""
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
        ready.append(tenant)
    return ready


def create_app(ctx: AppContext | None = None, *, start_workers: bool | None = None) -> FastAPI:
    """Build the app. Tests pass a ready ``AppContext`` (FakeHive, FakeLLM, FakeEmbedder)."""
    provided = ctx

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        context = provided or build_context()
        context.started_at = now_ms()
        app.state.ctx = context
        context.bus.bind(asyncio.get_running_loop())
        settings = context.settings
        tenants: list[str] = []
        try:
            if provided is None:
                context.hive.load_udfs()
            tenants = prepare_tenants(context, settings.seed_tenant_list, create_missing=settings.auto_create_tenants)
            for tenant in context.hive.list_tenants():
                if tenant not in tenants:
                    register_default_agents(context.hive, tenant, getattr(context.llm, "model", "fake"))
                    tenants.append(tenant)
        except Exception as exc:  # noqa: BLE001 - fail loudly in logs but let /health report the state
            log.error("startup preparation failed: %s", exc)
        run_workers = settings.workers_enabled if start_workers is None else start_workers
        if run_workers:
            context.workers = WorkerPool(context)
            await context.workers.start(tenants)
        log.info("Minutes API ready: hive=%s llm=%s/%s embedder=%s tenants=%s", getattr(context.hive, "kind", "?"), getattr(context.llm, "backend", "?"), getattr(context.llm, "model", "?"), context.embedder.name, tenants)
        try:
            yield
        finally:
            if context.workers is not None:
                await context.workers.stop()
            context.bus.close()
            close = getattr(context.hive, "close", None)
            if callable(close) and provided is None:
                close()

    settings = (ctx.settings if ctx is not None else get_settings())
    app = FastAPI(title="Minutes API", version="0.1.0", lifespan=lifespan, docs_url="/docs")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["http://localhost:3001"],
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
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
