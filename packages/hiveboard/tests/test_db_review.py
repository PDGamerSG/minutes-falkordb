"""Review fixes in db.py / schema.py / recall: findings 16 (slug validation), 18 (ro fallback warning), 21 (timeouts,
lazy connect, ping), 25 (commons schema once) and 26 (exact UDF error match)."""

import logging
import time

import hiveboard as hb
import pytest
from hiveboard.embed import fake_embedding
from redis.exceptions import ResponseError


def test_ping_is_false_and_fast_when_the_server_is_down():
    t0 = time.monotonic()
    down = hb.HiveDB("falkor://localhost:1")  # lazy: constructing never touches the network
    assert time.monotonic() - t0 < 0.5
    assert down.ping() is False
    assert time.monotonic() - t0 < 6
    down.close()


def test_connection_timeouts_are_configured(db):
    kwargs = db.connection.connection_pool.connection_kwargs
    assert kwargs["socket_connect_timeout"] == 2 and kwargs["socket_timeout"] == 10
    assert kwargs["health_check_interval"] == 30


def test_graph_name_validates_slugs(db):
    for bad in ["x y/z", "Orbit", "orbit__snap_1", "a", "-dash", "x" * 42, "", None, "team;drop", "under_score"]:
        with pytest.raises(ValueError):
            hb.HiveDB.graph_name(bad)
        with pytest.raises(ValueError):
            hb.ensure_schema(db, bad)
        with pytest.raises(ValueError):
            hb.create_tenant(db, bad, "x")
    assert hb.HiveDB.graph_name("orbit-2") == "team_orbit-2" and hb.validate_slug("test-ab12") == "test-ab12"
    assert all(hb.validate_slug(t) for t in db.list_tenants())


def test_ro_falls_back_to_admin_with_one_warning_per_tenant(db, tenant, caplog):
    caplog.set_level(logging.WARNING, logger="hiveboard.db")
    db.ro(tenant).ro_query("RETURN 1")
    db.ro(tenant).ro_query("RETURN 1")
    warnings = [r for r in caplog.records if tenant in r.getMessage() and "admin connection" in r.getMessage()]
    assert len(warnings) == 1


def test_commons_schema_runs_once_per_process(db):
    db.commons_schema_applied = False
    first = hb.ensure_commons_schema(db)
    second = hb.ensure_commons_schema(db)
    assert "skipped" not in first and second.get("skipped") == 1
    assert "skipped" not in hb.ensure_commons_schema(db, force=True)


def test_recall_udf_retry_matches_the_exact_error(db, tenant, seeded, monkeypatch):
    from hiveboard import memory

    calls = []
    monkeypatch.setattr(memory, "load_udfs", lambda d: calls.append("loaded"))
    graph_cls = db.ro(tenant).__class__
    original = graph_cls.ro_query
    state = {"n": 0}

    def flaky(self, q, params=None, timeout=None):
        state["n"] += 1
        if state["n"] == 1:
            raise ResponseError("Unknown function 'hive.score'")
        return original(self, q, params, timeout=timeout)

    monkeypatch.setattr(graph_cls, "ro_query", flaky)
    out = hb.recall(db, tenant, fake_embedding("UPI flow"), k=1)
    assert calls == ["loaded"] and out["items"]

    def unrelated(self, q, params=None, timeout=None):
        raise ResponseError("Timed out while running the hive query")

    monkeypatch.setattr(graph_cls, "ro_query", unrelated)
    with pytest.raises(ResponseError, match="Timed out"):
        hb.recall(db, tenant, fake_embedding("UPI flow"), k=1)
    assert calls == ["loaded"]  # an unrelated error that merely mentions 'hive' does not trigger a reload
