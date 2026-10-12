"""MCP server (stdio) exposing memory-semantic tools to MCP clients (IDE assistants, agent runtimes).

Run: `uv run --package hiveboard python -m hiveboard.mcp_server`. Read tools go through the tenant's
read-only handle (`HiveDB.ro`, `ro_query` with a 3 s timeout); `claim` and `handoff` write through the rw handle.
`recall` needs an embedder: inject one into `build_server`, or the deterministic hashed fake embedder is used.
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Callable
from typing import Any

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp.exceptions import ToolError
except ImportError:  # mcp 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError

from . import analytics, board, memory
from .db import HiveDB, validate_slug
from .embed import fake_embedding
from .errors import HiveError, NotFound
from .udf.loader import load_udfs

Embedder = Callable[[str], list[float]]
log = logging.getLogger("hiveboard.mcp")
MAX_K = 50  # recall results per call
MAX_LIMIT = 200  # rows per list call


def _guarded(fn: Callable) -> Callable:
    """Report domain errors (bad slug, unknown tenant or id, conflicts) to the client as readable tool errors; the MCP
    server otherwise hides the message of any exception that is not a ToolError."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (ValueError, HiveError) as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def build_server(db: HiveDB | None = None, embedder: Embedder | None = None, name: str = "hiveboard") -> Any:
    """Create the MCP server with the seven tools bound to `db` (default: `$FALKORDB_URL`) and `embedder`."""
    db = db or HiveDB()
    embed = embedder or fake_embedding
    server = _Server(name)

    def known(tenant: str) -> str:
        """Validate the slug (ValueError for `x y`) and that the tenant graph exists (NotFound), so a bad call fails with a
        clear message instead of reaching the database."""
        validate_slug(tenant)
        if not db.graph_exists(db.graph_name(tenant)):
            raise NotFound(f"unknown tenant {tenant!r}")
        return tenant

    @server.tool()
    @_guarded
    def recall(tenant: str, query_text: str, k: int = 8, label: str = "Fact") -> dict:
        """Hybrid recall: embed the text, vector KNN, 1-hop graph expansion, hive.score ranking. Returns items, cypher, subgraph."""
        return memory.recall(db, known(tenant), embed(query_text), k=max(1, min(int(k), MAX_K)), label=label)

    @server.tool()
    @_guarded
    def why(tenant: str, node_id: str) -> dict:
        """Provenance of a fact/decision/commitment: who said it, in which meeting or email, the episode and the supersession chain."""
        return memory.why(db, known(tenant), node_id)

    @server.tool()
    @_guarded
    def belief_at(tenant: str, t_ms: int, entity_id: str | None = None, known_by_ms: int | None = None) -> dict:
        """Facts that were true at epoch-ms time t (optionally only about one entity id, and only what was known by `known_by_ms`)."""
        rows = memory.belief_at(db, known(tenant), t_ms, entity_id, known_by_ms, limit=MAX_LIMIT)
        return {"t": t_ms, "facts": list(rows), "cypher": rows.cypher}

    @server.tool()
    @_guarded
    def list_tasks(tenant: str, status: str | None = None, limit: int = 50) -> dict:
        """Board tasks newest first, optionally filtered by status (submitted|working|input_required|completed|failed)."""
        rows = board.list_tasks(db, known(tenant), status, max(1, min(int(limit), MAX_LIMIT)))
        return {"tasks": list(rows), "cypher": rows.cypher}

    @server.tool()
    @_guarded
    def claim(tenant: str, task_id: str, agent_id: str, expected_version: int) -> dict:
        """Compare-and-set claim of a submitted task. `version` is null when another agent won."""
        version = board.claim(db, known(tenant), task_id, agent_id, expected_version)
        return {"task_id": task_id, "agent_id": agent_id, "version": version, "won": version is not None}

    @server.tool()
    @_guarded
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
            db, known(tenant), task_id, from_agent, to_agent, expected_version, summary, subgraph_ids
        )
        return {"task_id": task_id, "to_agent": to_agent, "version": version, "ok": version is not None}

    @server.tool()
    @_guarded
    def open_commitments(tenant: str, person_id: str | None = None) -> dict:
        """Active commitments (optionally for one person id), soonest due first."""
        rows = analytics.open_commitments(db, known(tenant), person_id, limit=MAX_LIMIT)
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
