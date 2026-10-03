"""MCP server (stdio) exposing memory-semantic tools to Claude Code / Cursor.

Run: `uv run --package hiveboard python -m hiveboard.mcp_server`. Read tools go through the tenant's
read-only handle (`HiveDB.ro`, `ro_query` with a 3 s timeout); `claim` and `handoff` write through the rw handle.
`recall` needs an embedder: inject one into `build_server`, or the deterministic hashed fake embedder is used.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
except ImportError:  # mcp 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as _Server

from . import analytics, board, memory
from .db import HiveDB
from .embed import fake_embedding
from .udf.loader import load_udfs

Embedder = Callable[[str], list[float]]
log = logging.getLogger("hiveboard.mcp")


def build_server(db: HiveDB | None = None, embedder: Embedder | None = None, name: str = "hiveboard") -> Any:
    """Create the MCP server with the seven tools bound to `db` (default: `$FALKORDB_URL`) and `embedder`."""
    db = db or HiveDB()
    embed = embedder or fake_embedding
    server = _Server(name)

    @server.tool()
    def recall(tenant: str, query_text: str, k: int = 8, label: str = "Fact") -> dict:
        """Hybrid recall: embed the text, vector KNN, 1-hop graph expansion, hive.score ranking. Returns items, cypher, subgraph."""
        return memory.recall(db, tenant, embed(query_text), k=k, label=label)

    @server.tool()
    def why(tenant: str, node_id: str) -> dict:
        """Provenance of a fact/decision/commitment: who said it, in which meeting or email, the episode and the supersession chain."""
        return memory.why(db, tenant, node_id)

    @server.tool()
    def belief_at(tenant: str, t_ms: int, entity_id: str | None = None) -> dict:
        """Facts that were true at epoch-ms time t (optionally only about one entity id)."""
        rows = memory.belief_at(db, tenant, t_ms, entity_id)
        return {"t": t_ms, "facts": list(rows), "cypher": rows.cypher}

    @server.tool()
    def list_tasks(tenant: str, status: str | None = None, limit: int = 50) -> dict:
        """Board tasks newest first, optionally filtered by status (submitted|working|input_required|completed|failed)."""
        rows = board.list_tasks(db, tenant, status, limit)
        return {"tasks": list(rows), "cypher": rows.cypher}

    @server.tool()
    def claim(tenant: str, task_id: str, agent_id: str, expected_version: int) -> dict:
        """Compare-and-set claim of a submitted task. `version` is null when another agent won."""
        version = board.claim(db, tenant, task_id, agent_id, expected_version)
        return {"task_id": task_id, "agent_id": agent_id, "version": version, "won": version is not None}

    @server.tool()
    def handoff(
        tenant: str,
        task_id: str,
        from_agent: str,
        to_agent: str,
        expected_version: int,
        summary: str,
        subgraph_ids: list[str],
    ) -> dict:
        """Hand a working task to another agent with a summary and the ids of the subgraph it should read."""
        version = board.handoff(
            db, tenant, task_id, from_agent, to_agent, expected_version, summary, subgraph_ids
        )
        return {"task_id": task_id, "to_agent": to_agent, "version": version, "ok": version is not None}

    @server.tool()
    def open_commitments(tenant: str, person_id: str | None = None) -> dict:
        """Active commitments (optionally for one person id), soonest due first."""
        rows = analytics.open_commitments(db, tenant, person_id)
        return {"commitments": list(rows), "cypher": rows.cypher}

    return server


def main() -> None:
    """Entry point: load the UDF library (best effort, logged) and serve over stdio."""
    logging.basicConfig(level=os.environ.get("HIVEBOARD_LOG_LEVEL", "INFO"))
    db = HiveDB()
    try:
        load_udfs(db)
    except Exception as exc:  # noqa: BLE001 - the server still serves why/belief_at/board tools without the UDF
        log.warning("could not load hive UDF library: %s", exc)
    build_server(db).run(transport="stdio")


if __name__ == "__main__":
    main()
