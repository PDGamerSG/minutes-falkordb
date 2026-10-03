"""Connection handling: one FalkorDB graph per tenant (`team_<slug>`), a shared `commons` graph,
and per-tenant read-only clients that authenticate as the tenant's `team_<slug>_ro` ACL user."""

from __future__ import annotations

import os
import threading
from typing import Any
from urllib.parse import urlparse

import redis
from falkordb import FalkorDB, Graph

DEFAULT_URL = "falkor://localhost:6379"
COMMONS = "commons"
SNAPSHOT_MARK = "__snap_"


def _parse_memory(reply: Any) -> dict[str, Any]:
    """Turn the flat `[key, value, key, [label, value, ...]]` reply of GRAPH.MEMORY USAGE into a dict."""
    if isinstance(reply, dict):
        return {k: _parse_memory(v) if isinstance(v, (list, dict)) else v for k, v in reply.items()}
    out: dict[str, Any] = {}
    items = list(reply)
    for i in range(0, len(items) - 1, 2):
        key = items[i].decode() if isinstance(items[i], bytes) else str(items[i])
        value = items[i + 1]
        out[key] = _parse_memory(value) if isinstance(value, list) else value
    return out


class HiveDB:
    """Admin connection plus graph handles. Thread-safe: falkordb-py uses a redis connection pool."""

    def __init__(
        self,
        url: str | None = None,
        admin_user: str | None = None,
        admin_password: str | None = None,
    ):
        self.url = url or os.environ.get("FALKORDB_URL") or DEFAULT_URL
        parsed = urlparse(self.url)
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or 6379
        self.admin_user = admin_user or parsed.username or os.environ.get("FALKORDB_ADMIN_USER") or None
        self.admin_password = (
            admin_password or parsed.password or os.environ.get("FALKORDB_ADMIN_PASSWORD") or None
        )
        self._client = FalkorDB(
            host=self.host, port=self.port, username=self.admin_user, password=self.admin_password
        )
        self._ro_clients: dict[str, FalkorDB] = {}
        self._ro_passwords: dict[str, str] = {}
        self._lock = threading.Lock()

    # -- naming -------------------------------------------------------------------------------
    @staticmethod
    def graph_name(tenant: str) -> str:
        """`team_<slug>`."""
        return f"team_{tenant}"

    @staticmethod
    def rw_user(tenant: str) -> str:
        return f"team_{tenant}_rw"

    @staticmethod
    def ro_user(tenant: str) -> str:
        return f"team_{tenant}_ro"

    # -- handles ------------------------------------------------------------------------------
    @property
    def client(self) -> FalkorDB:
        """The admin falkordb client (GRAPH.UDF, GRAPH.LIST, ACL ...)."""
        return self._client

    @property
    def connection(self) -> redis.Redis:
        """Raw redis-py connection of the admin client, for commands falkordb-py does not wrap."""
        return self._client.connection

    def graph(self, tenant: str) -> Graph:
        """Read-write graph handle for a tenant (admin credentials)."""
        return self._client.select_graph(self.graph_name(tenant))

    def ro(self, tenant: str) -> Graph:
        """Read-only handle: the tenant's `team_<slug>_ro` ACL user when its password is configured,
        otherwise the admin connection. Callers still use `ro_query`, which FalkorDB refuses for writes."""
        with self._lock:
            client = self._ro_clients.get(tenant)
            if client is None and tenant in self._ro_passwords:
                client = FalkorDB(
                    host=self.host,
                    port=self.port,
                    username=self.ro_user(tenant),
                    password=self._ro_passwords[tenant],
                )
                self._ro_clients[tenant] = client
        return (client or self._client).select_graph(self.graph_name(tenant))

    def configure_ro(self, tenant: str, password: str | None) -> None:
        """Register (or forget, with None) the ro user's password so `ro()` connects as that user."""
        with self._lock:
            self._ro_clients.pop(tenant, None)
            if password is None:
                self._ro_passwords.pop(tenant, None)
            else:
                self._ro_passwords[tenant] = password

    def commons(self) -> Graph:
        """The shared `commons` graph (tenant registry, snapshots metadata, published skills)."""
        return self._client.select_graph(COMMONS)

    # -- introspection ------------------------------------------------------------------------
    def list_graphs(self) -> list[str]:
        return [g.decode() if isinstance(g, bytes) else g for g in self._client.list_graphs()]

    def graph_exists(self, name: str) -> bool:
        return name in self.list_graphs()

    def list_tenants(self) -> list[str]:
        """Tenant slugs derived from `team_*` graphs (snapshot copies excluded)."""
        names = [g[5:] for g in self.list_graphs() if g.startswith("team_") and SNAPSHOT_MARK not in g]
        return sorted(names)

    def usage(self, tenant: str) -> dict[str, Any]:
        """`GRAPH.MEMORY USAGE team_<slug>` as `{"total_mb", "indices_mb", "nodes_by_label_mb", "edges_by_type_mb", "raw"}`."""
        raw = _parse_memory(self.connection.execute_command("GRAPH.MEMORY", "USAGE", self.graph_name(tenant)))
        return {
            "total_mb": float(raw.get("total_graph_sz_mb", 0) or 0),
            "indices_mb": float(raw.get("indices_sz_mb", 0) or 0),
            "nodes_by_label_mb": raw.get("amortized_node_attributes_by_label_sz_mb", {}),
            "edges_by_type_mb": raw.get("amortized_edge_attributes_by_type_sz_mb", {}),
            "raw": raw,
        }

    def ping(self) -> bool:
        try:
            return bool(self.connection.ping())
        except redis.RedisError:
            return False

    def server_version(self) -> str:
        """FalkorDB module version, e.g. `6.0.1`, from MODULE LIST (`ver` 60001)."""
        for module in self.connection.execute_command("MODULE", "LIST"):
            entry = _parse_memory(module) if isinstance(module, list) else module
            if str(entry.get("name")) == "graph":
                ver = int(entry.get("ver", 0))
                return f"{ver // 10000}.{(ver // 100) % 100}.{ver % 100}"
        return "unknown"

    def close(self) -> None:
        with self._lock:
            for client in self._ro_clients.values():
                client.connection.close()
            self._ro_clients.clear()
        self._client.connection.close()
