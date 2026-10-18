"""A database that is down at boot yields a serving API with /health 503 and a later recovery (finding 5.4);
AUTO_CREATE_TENANTS defaults off in production; CORS localhost regex only outside production;
STRICT_HEALTH folds llm.reachable and workers.alive into ok (5.3)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from apps.api import main as main_module
from apps.api.config import Settings
from apps.api.main import create_app
from apps.api.routes.health import llm_reachable, reset_probe_cache
from apps.api.tests.conftest import make_ctx, make_settings


def test_db_down_at_boot_serves_503_then_recovers(data_dir, monkeypatch):
    settings = make_settings(data_dir)
    attempts = {"n": 0}
    good = make_ctx(data_dir)

    def flaky_build(settings_arg=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("FalkorDB unreachable at localhost:6383")
        return good

    monkeypatch.setattr(main_module, "build_context", flaky_build)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "STARTUP_RETRY_S", 0.05)
    with TestClient(create_app(None, start_workers=False)) as client:
        first = client.get("/health")
        assert first.status_code == 503
        body = first.json()
        assert body["ok"] is False and "unreachable" in body["error"] and body["falkordb"]["kind"] == "unavailable"
        assert client.get("/tenants/orbit/facts").status_code in (404, 500, 503)  # degraded, but the process is alive
        deadline = time.time() + 5
        while time.time() < deadline and client.get("/health").status_code != 200:
            time.sleep(0.05)
        recovered = client.get("/health").json()
        assert recovered["ok"] is True and "team_orbit" in recovered["falkordb"]["graphs"]
        assert attempts["n"] == 3


def test_auto_create_tenants_defaults_by_env():
    assert Settings(_env_file=None).auto_create_tenants is True
    assert Settings(_env_file=None, env="production").auto_create_tenants is False
    assert Settings(_env_file=None, env="production", auto_create_tenants=True).auto_create_tenants is True
    assert Settings(_env_file=None, env="prod").is_production


def test_cors_localhost_regex_only_outside_production(data_dir):
    dev = make_ctx(data_dir)
    prod = make_ctx(data_dir, env="production", cors_origins="https://minutes.example")
    for ctx, allowed in ((dev, True), (prod, False)):
        with TestClient(create_app(ctx, start_workers=False)) as client:
            response = client.get("/health", headers={"Origin": "http://localhost:5555"})
            assert (response.headers.get("access-control-allow-origin") == "http://localhost:5555") is allowed
        if not allowed:
            with TestClient(create_app(ctx, start_workers=False)) as client:
                response = client.get("/health", headers={"Origin": "https://minutes.example"})
                assert response.headers.get("access-control-allow-origin") == "https://minutes.example"


def test_cors_origin_regex_admits_matching_origins_in_production(data_dir):
    ctx = make_ctx(
        data_dir,
        env="production",
        cors_origins="https://minutes.example",
        cors_origin_regex=r"https://minutes(-[a-z0-9-]+)?\.vercel\.app",
    )
    with TestClient(create_app(ctx, start_workers=False)) as client:
        for origin, allowed in (
            ("https://minutes-abc123-team.vercel.app", True),
            ("https://minutes-git-main-team.vercel.app", True),
            ("https://minutes.example", True),
            ("https://other.vercel.app", False),
            ("http://localhost:5555", False),
        ):
            response = client.get("/health", headers={"Origin": origin})
            assert (response.headers.get("access-control-allow-origin") == origin) is allowed, origin


class DeadLLM:
    backend = "ollama"
    model = "gemma"

    def probe(self) -> bool:
        raise ConnectionError("refused")


class LiveLLM:
    backend = "ollama"
    model = "gemma"
    calls = 0

    def probe(self) -> bool:
        LiveLLM.calls += 1
        return True


def test_llm_probe_is_cached_and_strict_health(data_dir):
    reset_probe_cache()
    live = LiveLLM()
    assert llm_reachable(live, now=0.0) == (True, None)
    assert llm_reachable(live, now=30.0) == (True, None) and LiveLLM.calls == 1  # cached
    assert llm_reachable(live, now=61.0) == (True, None) and LiveLLM.calls == 2  # expired after 60 s
    reachable, error = llm_reachable(DeadLLM(), now=0.0)
    assert reachable is False and "refused" in error

    lenient = make_ctx(data_dir)
    lenient.llm = DeadLLM()
    with TestClient(create_app(lenient, start_workers=False)) as client:
        body = client.get("/health")
        assert body.status_code == 200 and body.json()["llm"]["reachable"] is False and "refused" in body.json()["llm"]["error"]
    strict = make_ctx(data_dir, strict_health=True)
    strict.llm = DeadLLM()
    reset_probe_cache()
    with TestClient(create_app(strict, start_workers=False)) as client:
        response = client.get("/health")
        assert response.status_code == 503 and "llm unreachable" in response.json()["error"]


def test_workers_alive_in_health(data_dir):
    ctx = make_ctx(data_dir, workers_enabled=True)
    with TestClient(create_app(ctx, start_workers=True)) as client:
        body = client.get("/health").json()
        workers = body["workers"]
        assert workers["enabled"] is True and workers["expected"] > 0 and workers["alive"] == workers["expected"]
        assert {a["agent"] for a in workers["agents"] if a["tenant"] == "orbit"} == {"fact_agent", "followup_agent", "scheduler_agent", "standup_agent", "answer_agent"}
