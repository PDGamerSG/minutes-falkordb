"""Late review fixes: FAILED constraint recovery (22), snapshot collisions (23), impact candidate de-duplication,
MCP tenant validation and result caps."""

import uuid

import hiveboard as hb
import pytest
from hiveboard.embed import fake_embedding
from hiveboard.impact import _distinct_candidates
from hiveboard.mcp_server import MAX_K, build_server
from hiveboard.schema import ConstraintFailed

from .conftest import cleanup_tenant
from .test_events_mcp_temporal import _tool_payload


def test_failed_unique_constraint_is_dropped_reported_and_repairable(db):
    slug = f"test-{uuid.uuid4().hex[:12]}"
    try:
        graph = db.graph(slug)
        graph.query("CREATE (:Person {id: 'dup', name: 'A'}), (:Person {id: 'dup', name: 'B'})")
        with pytest.raises(ConstraintFailed) as exc:
            hb.ensure_schema(db, slug)
        assert {"label": "Person", "property": "id", "value": "dup", "count": 2} in exc.value.duplicates
        assert "dup" in str(exc.value)
        graph.query("MATCH (p:Person {id: 'dup', name: 'B'}) DELETE p")
        hb.ensure_schema(db, slug)  # recovers: the FAILED constraint no longer blocks the retry
        statuses = graph.query("CALL db.constraints() YIELD status RETURN collect(DISTINCT status)").result_set[0][0]
        assert statuses == ["OPERATIONAL"]
    finally:
        cleanup_tenant(db, slug)


def test_snapshots_in_the_same_millisecond_do_not_collide(db, tenant, seeded, monkeypatch):
    from hiveboard import tenancy

    monkeypatch.setattr(tenancy, "now_ms", lambda: 1_800_000_000_000)
    first = hb.snapshot(db, tenant, "a")
    second = hb.snapshot(db, tenant, "b")
    assert first != second and db.graph_exists(first) and db.graph_exists(second)
    assert {s["name"] for s in hb.list_snapshots(db, tenant)} == {first, second}


def test_impact_candidates_are_distinct_per_fact_with_the_shortest_path():
    fact = {"id": "f2", "object": "Friday"}
    rows = [
        {"fact": fact, "via": ["f2", "fx", "f1"]},
        {"fact": fact, "via": ["f2", "f1"]},
        {"fact": {"id": None}, "via": []},
        {"fact": {"id": "f3"}, "via": ["f3", "f1"]},
    ]
    out = _distinct_candidates(rows)
    assert [c["fact"]["id"] for c in out] == ["f2", "f3"] and out[0]["via"] == ["f2", "f1"]


async def test_mcp_rejects_bad_slugs_and_unknown_tenants_and_caps_k(db, tenant, seeded):
    server = build_server(db, embedder=fake_embedding)
    for bad in ("x y", "Orbit", "a/../b"):
        with pytest.raises(Exception, match="invalid tenant slug"):
            await server.call_tool("why", {"tenant": bad, "node_id": "f"})
    with pytest.raises(Exception, match="unknown tenant"):
        await server.call_tool("list_tasks", {"tenant": "no-such-team"})
    out = _tool_payload(await server.call_tool("recall", {"tenant": tenant, "query_text": "UPI flow", "k": 10_000}))
    assert out["k"] == MAX_K
