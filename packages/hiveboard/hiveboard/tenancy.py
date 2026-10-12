"""Tenants: one graph `team_<slug>` plus two ACL users (`team_<slug>_rw`, `team_<slug>_ro`), snapshots via GRAPH.COPY,
and per-tenant metadata on the registry row in `commons`.

ACL syntax verified on FalkorDB 6.0.1 (redis 8.10.2):
- GRAPH.* commands declare their key with RW flags, so the read-only key selectors `%R~graph` deny access even for
  GRAPH.RO_QUERY (`%RW~` and a plain `~` work). Read-only is therefore enforced per COMMAND (`+GRAPH.RO_QUERY`,
  `+GRAPH.EXPLAIN`) and per GRAPH (`~pattern`).
- Redis 7+ ACL selectors make `commons` read-only for the rw user while its own graph stays writable (finding 15):
      ACL SETUSER team_x_rw reset on >pw +INFO +PING +CLIENT|SETINFO +GRAPH.RO_QUERY +GRAPH.EXPLAIN +GRAPH.QUERY
          +GRAPH.PROFILE ~team_x resetchannels (+GRAPH.RO_QUERY +GRAPH.EXPLAIN ~commons)
  Verified: `GRAPH.QUERY commons ...` as team_x_rw -> NOPERM; `GRAPH.RO_QUERY commons ...` -> OK; `GRAPH.QUERY team_x`
  -> OK; `GRAPH.RO_QUERY team_other` -> NOPERM. ACL LIST renders the selector as
  `(~commons resetchannels -@all +graph.ro_query +graph.explain)`.
- Rules are re-applied WITHOUT touching passwords with `-@all <commands> resetkeys ~team_x resetchannels clearselectors
  (<selector>)` (no `reset`, no `>pw`): that is what `ensure_tenant_access` and a non-rotating `create_tenant` send.
- The falkordb-py client needs `+INFO` (sentinel probe), `+PING` and `+CLIENT|SETINFO` at connect time.
- Commons writes (registry rows, snapshots metadata, published skills, tenant meta) always go through the admin handle.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

import orjson
import redis

from .db import COMMONS, SNAPSHOT_MARK, HiveDB, validate_slug
from .errors import Conflict, NotFound
from .ids import new_id
from .queries import load_cypher
from .schema import ensure_commons_schema, ensure_schema
from .temporal import now_ms

__all__ = [
    "RO_COMMANDS",
    "RW_COMMANDS",
    "acl_rules",
    "acl_setuser_args",
    "create_tenant",
    "delete_tenant",
    "ensure_tenant_access",
    "generate_password",
    "get_tenant_meta",
    "list_registered_tenants",
    "list_snapshots",
    "set_tenant_meta",
    "snapshot",
    "validate_slug",
]

RO_COMMANDS = ("+INFO", "+PING", "+CLIENT|SETINFO", "+GRAPH.RO_QUERY", "+GRAPH.EXPLAIN")
RW_COMMANDS = RO_COMMANDS + ("+GRAPH.QUERY", "+GRAPH.PROFILE")
COMMONS_SELECTOR = "(+GRAPH.RO_QUERY +GRAPH.EXPLAIN ~commons)"
_HASH_PREFIX = "#"

log = logging.getLogger("hiveboard.tenancy")


def generate_password() -> str:
    """A per-tenant secret (URL-safe, 32 random bytes)."""
    return secrets.token_urlsafe(32)


def _rules(user: str, commands: tuple[str, ...], graph: str) -> list[str]:
    """Command, key and selector rules of one tenant user (no `reset`, no password): the rw user may read commons through a
    selector only; the ro user reads its graph and commons."""
    if "+GRAPH.QUERY" in commands:
        return ["-@all", *commands, "resetkeys", f"~{graph}", "resetchannels", "clearselectors", COMMONS_SELECTOR]
    return ["-@all", *commands, "resetkeys", f"~{graph}", f"~{COMMONS}", "resetchannels", "clearselectors"]


def acl_setuser_args(
    user: str, password: str | None, commands: tuple[str, ...], graph: str, *, reset: bool = True
) -> list[str]:
    """`ACL SETUSER <user> [reset on ><pw>] <rules...>`. With `reset=True` the user is (re)created with that single
    password; with `reset=False` only the rules are re-applied and passwords and the on/off flag are left alone."""
    head = ["ACL", "SETUSER", user]
    if reset:
        if password is None:
            raise ValueError("a password is required to (re)create an ACL user")
        head += ["reset", "on", f">{password}"]
    return head + _rules(user, commands, graph)


def _user_exists(db: HiveDB, user: str) -> bool:
    return db.connection.execute_command("ACL", "GETUSER", user) is not None


def _password_accepted(db: HiveDB, user: str, password: str) -> bool:
    """Probe AUTH as the user (a throwaway connection); False on an invalid pair or a disabled user."""
    probe = redis.Redis(
        host=db.host, port=db.port, username=user, password=password, socket_connect_timeout=2, socket_timeout=5
    )
    try:
        return bool(probe.ping())
    except redis.AuthenticationError:
        return False
    finally:
        probe.close()


def ensure_tenant_access(db: HiveDB, tenant: str, password_rw: str | None, password_ro: str | None) -> None:
    """(Re)apply the ACL rules of both tenant users without changing anything else: existing users keep their passwords
    and on/off flag; a missing user is recreated with the supplied password (after a Redis restart without ACL persistence).
    Configures `db.ro()` with `password_ro` when it is given."""
    validate_slug(tenant)
    graph = db.graph_name(tenant)
    if not db.graph_exists(graph):
        raise NotFound(f"tenant {tenant!r} does not exist")
    for user, password, commands in (
        (db.rw_user(tenant), password_rw, RW_COMMANDS),
        (db.ro_user(tenant), password_ro, RO_COMMANDS),
    ):
        if _user_exists(db, user):
            db.connection.execute_command(*acl_setuser_args(user, None, commands, graph, reset=False))
        elif password is not None:
            db.connection.execute_command(*acl_setuser_args(user, password, commands, graph))
        else:
            raise NotFound(f"ACL user {user!r} is missing and no password was supplied to recreate it")
    if password_ro is not None:
        db.configure_ro(tenant, password_ro)


def create_tenant(
    db: HiveDB,
    tenant: str,
    display_name: str,
    password_rw: str | None = None,
    password_ro: str | None = None,
    rotate: bool = False,
) -> dict[str, Any]:
    """Create graph + schema + ACL users + registry row in `commons`. Idempotent.

    New tenant (or `rotate=True`): both users are (re)created with `password_rw`/`password_ro`, or with freshly generated
    secrets when they are not supplied; the result carries them ONCE under `credentials` (they are never stored).
    Existing tenant without `rotate`: passwords are left alone (finding 17), only the ACL rules are re-applied;
    supplied passwords are verified and a mismatch raises Conflict (pass `rotate=True` to replace them); `credentials` is
    None. `db.ro()` is configured for the tenant whenever the ro password is known."""
    validate_slug(tenant)
    graph = db.graph_name(tenant)
    schema = ensure_schema(db, tenant)
    ensure_commons_schema(db)
    rw_user, ro_user = db.rw_user(tenant), db.ro_user(tenant)
    exists = _user_exists(db, rw_user) and _user_exists(db, ro_user)
    credentials: dict[str, str] | None = None
    if rotate or not exists:
        pw_rw = password_rw or generate_password()
        pw_ro = password_ro or generate_password()
        db.connection.execute_command(*acl_setuser_args(rw_user, pw_rw, RW_COMMANDS, graph))
        db.connection.execute_command(*acl_setuser_args(ro_user, pw_ro, RO_COMMANDS, graph))
        db.configure_ro(tenant, pw_ro)
        credentials = {"rw_user": rw_user, "rw_password": pw_rw, "ro_user": ro_user, "ro_password": pw_ro}
    else:
        for user, password in ((rw_user, password_rw), (ro_user, password_ro)):
            if password is not None and not _password_accepted(db, user, password):
                raise Conflict(
                    f"ACL user {user!r} already exists with a different password; pass rotate=True to replace it"
                )
        ensure_tenant_access(db, tenant, password_rw, password_ro)
    db.commons().query(
        load_cypher("upsert_tenant"),
        {
            "slug": tenant,
            "display_name": display_name,
            "graph": graph,
            "rw_user": rw_user,
            "ro_user": ro_user,
            "now": now_ms(),
        },
    )
    info = acl_rules(db, tenant)
    info.update(
        {
            "slug": tenant,
            "display_name": display_name,
            "schema": schema,
            "created": not exists,
            "rotated": bool(rotate and exists),
            "credentials": credentials,
        }
    )
    return info


def delete_tenant(db: HiveDB, tenant: str) -> None:
    """GRAPH.DELETE the tenant graph and its snapshots, ACL DELUSER both users, drop the registry rows and the skills
    it published to `commons` (finding 19)."""
    validate_slug(tenant)
    graph = db.graph_name(tenant)
    for name in db.list_graphs():
        if name == graph or name.startswith(graph + SNAPSHOT_MARK):
            db.client.select_graph(name).delete()
    db.connection.execute_command("ACL", "DELUSER", db.rw_user(tenant), db.ro_user(tenant))
    db.configure_ro(tenant, None)
    if db.graph_exists(COMMONS):
        db.commons().query(load_cypher("delete_tenant_meta"), {"slug": tenant})
        db.commons().query(
            "MATCH (s:Skill {origin_tenant: $t}) OPTIONAL MATCH (s)-[:STEP]->(st:Step) DETACH DELETE s, st",
            {"t": tenant},
        )


def _redact(text: str) -> str:
    return " ".join("#<sha256>" if p.startswith(_HASH_PREFIX) else p for p in text.split(" "))


def acl_rules(db: HiveDB, tenant: str) -> dict[str, Any]:
    """The ACL lines in force for the tenant's two users (password hashes redacted), for the UI."""
    users = {db.rw_user(tenant), db.ro_user(tenant)}
    rules = []
    for line in db.connection.execute_command("ACL", "LIST"):
        text = line.decode() if isinstance(line, bytes) else str(line)
        parts = text.split(" ")
        if len(parts) > 1 and parts[1] in users:
            rules.append(_redact(text))
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
            "rw_user_can_write_other_tenants": False,
            "rw_user_can_write_commons": False,
            "rw_user_can_read_commons": True,
            "commons_selector": COMMONS_SELECTOR,
            "note": "FalkorDB 6.0.1 GRAPH.* commands carry RW key flags, so %R~ selectors deny reads; read-only is "
            "enforced per command (+GRAPH.RO_QUERY) and per graph (~pattern). The rw user reaches commons only "
            "through an ACL selector that grants GRAPH.RO_QUERY/GRAPH.EXPLAIN; commons writes are admin-only.",
        },
    }


def list_registered_tenants(db: HiveDB) -> list[dict[str, Any]]:
    """Registry rows from `commons` (slug, display_name, graph, users)."""
    if not db.graph_exists(COMMONS):
        return []
    res = db.commons().ro_query(load_cypher("list_tenants"), timeout=3000)
    keys = ["slug", "display_name", "graph", "rw_user", "ro_user", "created_at"]
    return [dict(zip(keys, row)) for row in res.result_set]


def set_tenant_meta(db: HiveDB, tenant: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Merge `meta` (JSON-serialisable, e.g. `{"embedding_model": "embeddinggemma-300m"}`) into the tenant's metadata on
    its registry row in `commons` (created if missing); a key set to None is removed. Returns the stored metadata."""
    validate_slug(tenant)
    ensure_commons_schema(db)
    merged = {**get_tenant_meta(db, tenant), **meta}
    merged = {k: v for k, v in merged.items() if v is not None}
    res = db.commons().query(
        load_cypher("set_tenant_meta"),
        {"slug": tenant, "meta": orjson.dumps(merged, default=str).decode(), "now": now_ms()},
    )
    return orjson.loads(res.result_set[0][0]) if res.result_set and res.result_set[0][0] else {}


def get_tenant_meta(db: HiveDB, tenant: str) -> dict[str, Any]:
    """The tenant's metadata dict from `commons` (`{}` when there is none)."""
    validate_slug(tenant)
    if not db.graph_exists(COMMONS):
        return {}
    res = db.commons().ro_query(load_cypher("get_tenant_meta"), {"slug": tenant}, timeout=3000)
    raw = res.result_set[0][0] if res.result_set else None
    if not raw:
        return {}
    try:
        data = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def snapshot(db: HiveDB, tenant: str, label: str) -> str:
    """`GRAPH.COPY team_<slug> team_<slug>__snap_<ms>` and a Snapshot node in `commons`; returns the copy's name."""
    graph = db.graph_name(tenant)
    if not db.graph_exists(graph):
        raise NotFound(f"graph {graph} does not exist")
    taken_at = now_ms()
    existing = set(db.list_graphs())
    while f"{graph}{SNAPSHOT_MARK}{taken_at}" in existing:  # two snapshots in the same millisecond must not collide
        taken_at += 1
    name = f"{graph}{SNAPSHOT_MARK}{taken_at}"
    ensure_commons_schema(db)
    db.graph(tenant).copy(name)
    try:
        db.commons().query(
            load_cypher("record_snapshot"),
            {"id": new_id("snap"), "tenant": tenant, "graph_name": name, "label": label, "now": taken_at},
        )
    except Exception:
        db.client.select_graph(name).delete()  # never leave an unregistered copy behind
        raise
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
