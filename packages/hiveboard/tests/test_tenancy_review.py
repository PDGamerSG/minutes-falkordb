"""Findings 15, 17, 19, 20 and the tenant meta store: commons is read-only for tenants, passwords are never reset
without `rotate`, generated secrets are returned once, deleting a tenant removes its published skills."""

import uuid

import hiveboard as hb
import pytest
from falkordb import FalkorDB
from hiveboard.embed import fake_embedding
from redis.exceptions import NoPermissionError

from .conftest import cleanup_tenant


def _client(db, user, password):
    return FalkorDB(host=db.host, port=db.port, username=user, password=password)


def _password_hashes(db, user):
    """The `#<sha256>` tokens of the user's ACL LIST line (ACL GETUSER comes back as a flat list on this connection)."""
    for line in db.connection.execute_command("ACL", "LIST"):
        text = line.decode() if isinstance(line, bytes) else str(line)
        parts = text.split(" ")
        if len(parts) > 1 and parts[1] == user:
            return sorted(p for p in parts if p.startswith("#"))
    return None


@pytest.fixture
def generated(db):
    slug = f"test-{uuid.uuid4().hex[:12]}"
    info = hb.create_tenant(db, slug, "Generated Team")
    yield slug, info
    cleanup_tenant(db, slug)


def test_rw_user_is_read_only_on_commons(db, generated, other_tenant):
    slug, info = generated
    creds = info["credentials"]
    rw = _client(db, creds["rw_user"], creds["rw_password"])
    # its own graph: full access
    assert rw.select_graph(f"team_{slug}").query("CREATE (:Person {id: 'p', name: 'P'}) RETURN 1").result_set == [[1]]
    # commons: reads work, every write path is denied
    assert rw.select_graph("commons").ro_query("MATCH (t:Tenant {slug: $s}) RETURN count(t)", {"s": slug}).result_set == [[1]]
    with pytest.raises(NoPermissionError):
        rw.select_graph("commons").query("MATCH (t:Tenant {slug: $s}) RETURN count(t)", {"s": slug})
    with pytest.raises(NoPermissionError):
        rw.select_graph("commons").query("MATCH (t:Tenant) SET t.display_name = 'pwned' RETURN count(t)")
    with pytest.raises(NoPermissionError):
        rw.select_graph("commons").query("MATCH (t:Tenant) DELETE t")
    # other tenants: nothing
    with pytest.raises(NoPermissionError):
        rw.select_graph(f"team_{other_tenant}").ro_query("RETURN 1")
    assert hb.list_registered_tenants(db) and all(t["display_name"] != "pwned" for t in hb.list_registered_tenants(db))
    rules = hb.acl_rules(db, slug)
    rw_rule = next(r for r in rules["rules"] if f"team_{slug}_rw" in r)
    assert "(~commons" in rw_rule and "+graph.ro_query" in rw_rule.split("(")[1] and "+graph.query" not in rw_rule.split("(")[1]
    assert rules["isolation"]["rw_user_can_write_commons"] is False
    ro = _client(db, creds["ro_user"], creds["ro_password"])
    assert ro.select_graph("commons").ro_query("RETURN 1").result_set == [[1]]
    with pytest.raises(NoPermissionError):
        ro.select_graph("commons").query("RETURN 1")


def test_create_tenant_generates_secrets_once_and_never_resets_them(db, generated):
    slug, info = generated
    creds = info["credentials"]
    assert info["created"] and not info["rotated"]
    assert creds["rw_user"] == f"team_{slug}_rw" and len(creds["rw_password"]) >= 32 and creds["rw_password"] != creds["ro_password"]
    assert db.ro_configured(slug)
    hashes_before = _password_hashes(db, creds["rw_user"])
    assert hashes_before
    # re-running without passwords keeps the users intact and returns no credentials
    again = hb.create_tenant(db, slug, "Generated Team")
    assert again["credentials"] is None and not again["created"] and not again["rotated"]
    assert _password_hashes(db, creds["rw_user"]) == hashes_before
    assert _client(db, creds["rw_user"], creds["rw_password"]).select_graph(f"team_{slug}").ro_query("RETURN 1").result_set == [[1]]
    # the right passwords are accepted silently, a wrong one is refused instead of overwriting
    assert hb.create_tenant(db, slug, "Generated Team", creds["rw_password"], creds["ro_password"])["credentials"] is None
    with pytest.raises(hb.Conflict, match="rotate=True"):
        hb.create_tenant(db, slug, "Generated Team", "wrong", creds["ro_password"])
    assert _password_hashes(db, creds["rw_user"]) == hashes_before
    # explicit rotation replaces them
    rotated = hb.create_tenant(db, slug, "Generated Team", "new-rw", rotate=True)
    assert rotated["rotated"] and rotated["credentials"]["rw_password"] == "new-rw"
    assert len(rotated["credentials"]["ro_password"]) >= 32
    with pytest.raises(Exception):
        _client(db, creds["rw_user"], creds["rw_password"]).select_graph(f"team_{slug}").ro_query("RETURN 1")
    assert _client(db, creds["rw_user"], "new-rw").select_graph(f"team_{slug}").ro_query("RETURN 1").result_set == [[1]]
    assert db.ro(slug).ro_query("RETURN 1").result_set == [[1]]


def test_ensure_tenant_access_reapplies_rules_without_touching_passwords(db, generated):
    from hiveboard.tenancy import ensure_tenant_access

    slug, info = generated
    creds = info["credentials"]
    rw_user = creds["rw_user"]
    # simulate the pre-fix policy: commons writable, no selector
    db.connection.execute_command("ACL", "SETUSER", rw_user, "clearselectors", "~commons")
    rw = _client(db, rw_user, creds["rw_password"])
    assert rw.select_graph("commons").query("RETURN 1").result_set == [[1]]  # writable (the finding)
    before = _password_hashes(db, rw_user)
    ensure_tenant_access(db, slug, None, None)
    with pytest.raises(NoPermissionError):
        _client(db, rw_user, creds["rw_password"]).select_graph("commons").query("RETURN 1")
    assert _password_hashes(db, rw_user) == before
    with pytest.raises(hb.NotFound):
        ensure_tenant_access(db, "test-nope-000000", "a", "b")


def test_delete_tenant_removes_published_skills(db, generated):
    slug, _ = generated
    skill = hb.learn_skill(db, slug, "publish me", [{"order": 1, "tool": "recall"}], [], fake_embedding("publish me"))
    commons_id = hb.publish_to_commons(db, slug, skill)
    assert db.commons().query("MATCH (s:Skill {id: $id}) RETURN count(s)", {"id": commons_id}).result_set == [[1]]
    hb.delete_tenant(db, slug)
    assert db.commons().query("MATCH (s:Skill {origin_tenant: $t}) RETURN count(s)", {"t": slug}).result_set == [[0]]
    assert db.commons().query("MATCH (st:Step) WHERE st.id ENDS WITH $suffix RETURN count(st)", {"suffix": f"@{slug}"}).result_set == [[0]]


def test_tenant_meta_round_trip(db, tenant):
    assert hb.get_tenant_meta(db, tenant) == {}
    stored = hb.set_tenant_meta(db, tenant, {"embedding_model": "embeddinggemma-300m", "dims": 768})
    assert stored == {"embedding_model": "embeddinggemma-300m", "dims": 768}
    assert hb.set_tenant_meta(db, tenant, {"note": "x", "dims": None}) == {"embedding_model": "embeddinggemma-300m", "note": "x"}
    assert hb.get_tenant_meta(db, tenant) == {"embedding_model": "embeddinggemma-300m", "note": "x"}
    assert [t["slug"] for t in hb.list_registered_tenants(db) if t["slug"] == tenant] == [tenant]
    with pytest.raises(ValueError):
        hb.get_tenant_meta(db, "Bad Slug")
