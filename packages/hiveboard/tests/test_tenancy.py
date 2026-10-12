import uuid

import hiveboard as hb
import pytest
from falkordb import FalkorDB
from redis.exceptions import NoPermissionError, ResponseError

from .conftest import cleanup_tenant


@pytest.fixture
def created(db):
    slug = f"test-{uuid.uuid4().hex[:12]}"
    info = hb.create_tenant(db, slug, "Test Team", "rw-secret", "ro-secret")
    yield slug, info
    cleanup_tenant(db, slug)


def _client(db, user, password):
    return FalkorDB(host=db.host, port=db.port, username=user, password=password)


def test_create_tenant_sets_up_graph_users_and_registry(db, created):
    slug, info = created
    assert (
        info["graph"] == f"team_{slug}"
        and info["rw_user"] == f"team_{slug}_rw"
        and info["ro_user"] == f"team_{slug}_ro"
    )
    assert db.graph_exists(f"team_{slug}") and slug in db.list_tenants()
    assert info["schema"]["constraints_created"] == len(hb.schema.UNIQUE_ID_LABELS)
    rules = hb.acl_rules(db, slug)["rules"]
    assert len(rules) == 2
    ro_rule = next(r for r in rules if f"team_{slug}_ro" in r)
    rw_rule = next(r for r in rules if f"team_{slug}_rw" in r)
    assert f"~team_{slug}" in ro_rule and "~commons" in ro_rule and "+graph.ro_query" in ro_rule
    assert "+graph.query" not in ro_rule.replace("+graph.ro_query", "") and "#<sha256>" in ro_rule
    assert "+graph.query" in rw_rule
    assert [t["slug"] for t in hb.list_registered_tenants(db) if t["slug"] == slug] == [slug]
    assert (
        hb.create_tenant(db, slug, "Test Team", "rw-secret", "ro-secret")["graph"] == f"team_{slug}"
    )  # idempotent
    with pytest.raises(ValueError):
        hb.create_tenant(db, "Bad Slug!", "x", "a", "b")


def test_ro_user_cannot_write_and_cannot_read_other_tenants(db, created, other_tenant):
    slug, _ = created
    hb.remember_person(db, slug, {"id": "spk_a", "name": "A"})
    # reads through the package go via the ro user and work
    ro_graph = db.ro(slug)
    assert ro_graph.ro_query("MATCH (p:Person) RETURN count(p)").result_set == [[1]]
    assert hb.active_facts(db, slug) == []
    with pytest.raises(NoPermissionError):
        ro_graph.query("CREATE (:Person {id: 'spk_b', name: 'B'})")  # GRAPH.QUERY is not granted
    with pytest.raises(ResponseError, match="read-only"):
        ro_graph.ro_query("CREATE (:Person {id: 'spk_c', name: 'C'})")  # RO_QUERY refuses writes
    ro_client = _client(db, f"team_{slug}_ro", "ro-secret")
    with pytest.raises(NoPermissionError):
        ro_client.select_graph(f"team_{other_tenant}").ro_query("MATCH (n) RETURN count(n)")
    assert ro_client.select_graph(f"team_{slug}").ro_query("MATCH (p:Person) RETURN p.id").result_set == [
        ["spk_a"]
    ]
    assert db.graph(slug).query("MATCH (p:Person) RETURN count(p)").result_set == [[1]]


def test_rw_user_is_confined_to_its_graph_and_commons(db, created, other_tenant):
    slug, _ = created
    rw_client = _client(db, f"team_{slug}_rw", "rw-secret")
    assert rw_client.select_graph(f"team_{slug}").query(
        "CREATE (:Person {id: 'spk_rw', name: 'RW'}) RETURN 1"
    ).result_set == [[1]]
    with pytest.raises(NoPermissionError):
        rw_client.select_graph(f"team_{other_tenant}").query("CREATE (:Person {id: 'x'})")
    with pytest.raises(NoPermissionError):
        rw_client.select_graph("some_other_graph").ro_query("RETURN 1")
    assert rw_client.select_graph("commons").ro_query(
        "MATCH (t:Tenant {slug: $s}) RETURN count(t)", {"s": slug}
    ).result_set == [[1]]


def test_delete_tenant_removes_graph_users_and_metadata(db, created):
    slug, _ = created
    hb.remember_person(db, slug, {"id": "spk_a", "name": "A"})
    name = hb.snapshot(db, slug, "before delete")
    assert name.startswith(f"team_{slug}__snap_") and db.graph_exists(name)
    hb.delete_tenant(db, slug)
    assert not db.graph_exists(f"team_{slug}") and not db.graph_exists(name)
    assert db.connection.execute_command("ACL", "GETUSER", f"team_{slug}_ro") is None
    assert db.connection.execute_command("ACL", "GETUSER", f"team_{slug}_rw") is None
    assert hb.list_snapshots(db, slug) == [] and slug not in [
        t["slug"] for t in hb.list_registered_tenants(db)
    ]


def test_snapshot_copies_graph_and_lists_metadata(db, created):
    slug, _ = created
    hb.remember_person(db, slug, {"id": "spk_a", "name": "A"})
    name = hb.snapshot(db, slug, "after kickoff")
    hb.remember_person(db, slug, {"id": "spk_b", "name": "B"})
    assert db.client.select_graph(name).ro_query("MATCH (p:Person) RETURN count(p)").result_set == [[1]]
    assert db.graph(slug).ro_query("MATCH (p:Person) RETURN count(p)").result_set == [[2]]
    snaps = hb.list_snapshots(db, slug)
    assert [(s["name"], s["label"], s["exists"]) for s in snaps] == [(name, "after kickoff", True)]
    assert db.usage(slug)["total_mb"] >= 0 and "raw" in db.usage(slug)


def test_missing_access_users_can_be_restored_without_recreating_graph(db, created):
    from hiveboard.tenancy import ensure_tenant_access

    slug, _ = created
    hb.remember_person(db, slug, {"id": "surviving_record", "name": "Preserved"})
    db.connection.execute_command("ACL", "DELUSER", db.ro_user(slug), db.rw_user(slug))
    ensure_tenant_access(db, slug, "rw-secret", "ro-secret")
    assert db.ro(slug).ro_query("MATCH (p:Person) RETURN p.name").result_set == [["Preserved"]]


def test_access_recovery_does_not_reenable_or_rotate_existing_users(db, created):
    from hiveboard.tenancy import ensure_tenant_access

    slug, _ = created
    db.connection.execute_command("ACL", "SETUSER", db.ro_user(slug), "off")
    before = db.connection.execute_command("ACL", "GETUSER", db.ro_user(slug))
    ensure_tenant_access(db, slug, "different-rw", "different-ro")
    assert db.connection.execute_command("ACL", "GETUSER", db.ro_user(slug)) == before
