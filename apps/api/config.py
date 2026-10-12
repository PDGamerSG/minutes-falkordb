"""Environment-driven settings for the API (see ``.env.example``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All knobs the API reads from the environment (``.env`` at the repo root is honoured)."""

    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    # Deployment
    env: str = "development"  # ENV=production tightens defaults (CORS, AUTO_CREATE_TENANTS)

    # FalkorDB
    falkordb_url: str = "falkor://localhost:6379"
    falkordb_admin_user: str | None = None
    falkordb_admin_password: str | None = None
    tenant_rw_password: str = "change-me-rw"
    tenant_ro_password: str = "change-me-ro"

    # Auth
    admin_token: str | None = None  # when set: required on POST/DELETE /tenants, /demo/*, /bench/run, POST /snapshots, work-items import
    tenant_keys_required: bool = False  # when true: every /tenants/{t}/... route needs X-API-Key (set true for deployments)

    # LLM
    llm_backend: str = "ollama"
    llm_model: str = "gemma4:e4b"
    llm_model_small: str = "gemma4:e4b"
    gemini_api_key: str | None = None
    gemini_api_key_2: str | None = None  # optional second key, rotated to on 429/5xx
    gemini_tpm_budget: int = 14000  # process-wide input-token budget per minute (chars/4), queue up to 20 s
    openrouter_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434/v1"
    llm_max_tokens: int = 1024
    llm_timeout_s: float = 180.0
    agent_task_deadline_s: float = 300.0  # per-task wall clock for the agent tool loop

    # Embeddings
    embed_backend: str = "onnx"
    embed_model: str = "onnx-community/embeddinggemma-300m-ONNX"
    hf_home: str | None = None

    # API
    cors_origins: str = "http://localhost:3001"
    data_dir: str = "data"
    bench_results_dir: str = "docs/bench"
    seed_tenants: str = "orbit,nimbus,quill"
    auto_create_tenants: bool | None = None  # default: true unless ENV=production
    max_import_bytes: int = 10 * 1024 * 1024
    max_snapshots_per_tenant: int = 10
    strict_health: bool = False  # when true, llm.reachable and workers.alive take part in /health ok
    live_event_max_age_days: int = 14  # fact.superseded older than this is historical: no reschedule task

    # Workers
    workers_enabled: bool = True
    worker_poll_s: float = 15.0
    worker_touch_s: float = 30.0  # Agent.last_seen written at most this often
    worker_heartbeat_s: float = 30.0
    task_lease_ms: int = 120_000
    reaper_interval_s: float = 30.0
    standup_min_meetings: int = 2

    # Tickets (FollowUpAgent)
    github_token: str | None = None
    github_demo_repo: str | None = None

    @model_validator(mode="after")
    def _defaults_by_env(self) -> Settings:
        if self.auto_create_tenants is None:
            self.auto_create_tenants = not self.is_production
        return self

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() in ("production", "prod")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def seed_tenant_list(self) -> list[str]:
        return [t.strip() for t in self.seed_tenants.split(",") if t.strip()]

    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def bench_path(self) -> Path:
        path = Path(self.bench_results_dir)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def llm_api_key(self) -> str | None:
        return {
            "gemini": ",".join(k for k in (self.gemini_api_key, self.gemini_api_key_2) if k) or None,
            "openrouter": self.openrouter_api_key,
        }.get(self.llm_backend)

    @property
    def llm_base_url(self) -> str | None:
        if self.llm_backend == "ollama":
            return self.ollama_base_url
        if self.llm_backend == "openrouter":
            return "https://openrouter.ai/api/v1"
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
