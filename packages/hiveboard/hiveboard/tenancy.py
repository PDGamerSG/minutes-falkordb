"""Tenants: one graph `team_<slug>` plus two ACL users (`team_<slug>_rw`, `team_<slug>_ro`), snapshots via GRAPH.COPY.

ACL syntax verified on FalkorDB 6.0.1 (redis 8.10): GRAPH.* commands declare their key with RW flags, so the
read-only key selectors `%R~graph` / `%W~graph` deny access even for GRAPH.RO_QUERY. The working pattern is a
plain key pattern `~team_<slug>` and command-level restriction (`+GRAPH.RO_QUERY` only for the ro user). The
falkordb-py client also needs `+INFO` (sentinel probe), `+PING` and `+CLIENT|SETINFO` at connect time.
"""

from __future__ import annotations

import re
from typing import Any

from .db import COMMONS, SNAPSHOT_MARK, HiveDB
from .errors import NotFound
from .ids import new_id
from .queries import load_cypher
from .schema import ensure_commons_schema, ensure_schema
from .temporal import now_ms

RO_COMMANDS = ("+INFO", "+PING", "+CLIENT|SETINFO", "+GRAPH.RO_QUERY", "+GRAPH.EXPLAIN")
RW_COMMANDS = RO_COMMANDS + ("+GRAPH.QUERY", "+GRAPH.PROFILE")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_]{0,62}$")
_HASH = re.compile(r"#[0-9a-f]{64}")


def validate_slug(tenant: str) -> str:
    """Slugs are `[a-z0-9_]`, start alphanumeric, at most 63 chars (they become graph and ACL user names)."""
    if not _SLUG.match(tenant):
        raise ValueError(f"invalid tenant slug {tenant!r}: use [a-z0-9_], 1-63 chars")
    return tenant


def acl_setuser_args(user: str, password: str, commands: tuple[str, ...], graphs: list[str]) -> list[str]:
    """`ACL SETUSER <user> reset on ><pw> <commands...> ~<graph>...` (reset makes re-creation idempotent)."""
    return ["ACL", "SETUSER", user, "reset", "on", f">{password}", *commands, *[f"~{g}" for g in graphs]]


def ensure_tenant_access(db: HiveDB, tenant: str, password_rw: str, password_ro: str) -> None:
    """Restore missing runtime ACL users after Redis restarts; preserve existing policy."""
    validate_slug(tenant)
    if not db.graph_exists(db.graph_name(tenant)):
        raise NotFound(f"tenant {tenant!r} does not exist")
    graphs = [db.graph_name(tenant), COMMONS]
    for user, password, commands in (
        (db.rw_user(tenant), password_rw, RW_COMMANDS),
        (db.ro_user(tenant), password_ro, RO_COMMANDS),
    ):
        if db.connection.execute_command("ACL", "GETUSER", user) is None:
            db.connection.execute_command(*acl_setuser_args(user, password, commands, graphs))
    db.configure_ro(tenant, password_ro)


def create_tenant(
    db: HiveDB, tenant: str, display_name: str, password_rw: str, password_ro: str
) -> dict[str, Any]:
    """Create graph + schema + ACL users + registry row in `commons`. Idempotent; re-running resets the passwords."""
    validate_slug(tenant)
    graph = db.graph_name(tenant)
    schema = ensure_schema(db, tenant)
    ensure_commons_schema(db)
    conn = db.connection
    conn.execute_command(*acl_setuser_args(db.rw_user(tenant), password_rw, RW_COMMANDS, [graph, COMMONS]))
    conn.execute_command(*acl_setuser_args(db.ro_user(tenant), password_ro, RO_COMMANDS, [graph, COMMONS]))
    db.configure_ro(tenant, password_ro)
    db.commons().query(
        load_cypher("upsert_tenant"),
        {
            "slug": tenant,
            "display_name": display_name,
            "graph": graph,
            "rw_user": db.rw_user(tenant),
            "ro_user": db.ro_user(tenant),
            "now": now_ms(),
        },
    )
    info = acl_rules(db, tenant)
    info.update({"slug": tenant, "display_name": display_name, "schema": schema})
    return info


def delete_tenant(db: HiveDB, tenant: str) -> None:
    """GRAPH.DELETE the tenant graph and its snapshots, ACL DELUSER both users, drop the registry rows."""
    validate_slug(tenant)
    graph = db.graph_name(tenant)
    for name in db.list_graphs():
        if name == graph or name.startswith(graph + SNAPSHOT_MARK):
            db.client.select_graph(name).delete()
    db.connection.execute_command("ACL", "DELUSER", db.rw_user(tenant), db.ro_user(tenant))
    db.configure_ro(tenant, None)
    if db.graph_exists(COMMONS):
        db.commons().query(load_cypher("delete_tenant_meta"), {"slug": tenant})


def acl_rules(db: HiveDB, tenant: str) -> dict[str, Any]:
    """The ACL lines in force for the tenant's two users (password hashes redacted), for the UI."""
    users = {db.rw_user(tenant), db.ro_user(tenant)}
    rules = []
    for line in db.connection.execute_command("ACL", "LIST"):
        text = line.decode() if isinstance(line, bytes) else str(line)
        parts = text.split(" ")
        if len(parts) > 1 and parts[1] in users:
            rules.append(_HASH.sub("#<sha256>", text))
    graph = db.graph_name(tenant)
    return {
        "graph": graph,
        "rw_user": db.rw_user(tenant),
        "ro_user": db.ro_user(tenant),
        "rules": rules,
        "isolation": {
            "graphs": [graph, COMMONS],
            "ro_user_can_write": False,
            "ro_user_can_read_other_tenants": False,
            "rw_user_can_write_commons": True,
            "note": "FalkorDB 6.0.1 GRAPH.* commands carry RW key flags, so %R~ selectors deny reads; "
            "read-only is enforced per command (+GRAPH.RO_QUERY) and per graph (~pattern).",
        },
    }


def list_registered_tenants(db: HiveDB) -> list[dict[str, Any]]:
    """Registry rows from `commons` (slug, display_name, graph, users)."""
    if not db.graph_exists(COMMONS):
        return []
    res = db.commons().ro_query(load_cypher("list_tenants"), timeout=3000)
    keys = ["slug", "display_name", "graph", "rw_user", "ro_user", "created_at"]
    return [dict(zip(keys, row)) for row in res.result_set]


def snapshot(db: HiveDB, tenant: str, label: str) -> str:
    """`GRAPH.COPY team_<slug> team_<slug>__snap_<ms>` and a Snapshot node in `commons`; returns the copy's name."""
    graph = db.graph_name(tenant)
    if not db.graph_exists(graph):
        raise NotFound(f"graph {graph} does not exist")
    taken_at = now_ms()
    name = f"{graph}{SNAPSHOT_MARK}{taken_at}"
    db.graph(tenant).copy(name)
    ensure_commons_schema(db)
    db.commons().query(
        load_cypher("record_snapshot"),
        {"id": new_id("snap"), "tenant": tenant, "graph_name": name, "label": label, "now": taken_at},
    )
    return name


def list_snapshots(db: HiveDB, tenant: str) -> list[dict[str, Any]]:
    """Snapshots of a tenant, newest first: `[{id, name, label, taken_at, exists}]`."""
    if not db.graph_exists(COMMONS):
        return []
    res = db.commons().ro_query(load_cypher("list_snapshots"), {"tenant": tenant}, timeout=3000)
    graphs = set(db.list_graphs())
    return [
        {"id": row[0], "name": row[1], "label": row[2], "taken_at": row[3], "exists": row[1] in graphs}
        for row in res.result_set
    ]
