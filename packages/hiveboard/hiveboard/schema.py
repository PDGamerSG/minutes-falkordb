"""Schema management: indexes from `cypher/00_schema.cypher` plus unique constraints, idempotent per graph."""

from __future__ import annotations

import time

from falkordb import Graph
from redis.exceptions import ResponseError

from .db import HiveDB
from .queries import schema_statements
from .udf.loader import load_udfs

__all__ = ["UNIQUE_ID_LABELS", "ensure_commons_schema", "ensure_schema", "load_udfs"]

UNIQUE_ID_LABELS = [
    "Person",
    "Meeting",
    "EmailThread",
    "Episode",
    "Entity",
    "Fact",
    "Decision",
    "Commitment",
    "Task",
    "Agent",
    "Skill",
    "Step",
    "Artifact",
    "Snapshot",
    "WorkItem",
    "Document",
    "FollowUpDraft",
]
_ALREADY = ("already indexed", "already exists")


def ensure_schema(db: HiveDB, tenant: str) -> dict[str, int]:
    """Create every index and unique constraint for `team_<tenant>`; safe to run repeatedly. Returns counts."""
    return apply_schema(db, db.graph(tenant))


def ensure_commons_schema(db: HiveDB) -> dict[str, int]:
    """Same schema on the shared `commons` graph (Tenant, Snapshot and published Skill nodes live there)."""
    return apply_schema(db, db.commons())


def apply_schema(db: HiveDB, graph: Graph) -> dict[str, int]:
    """Run the schema statements and constraints against one graph handle."""
    counts = {
        "indexes_created": 0,
        "indexes_existing": 0,
        "constraints_created": 0,
        "constraints_existing": 0,
    }
    for statement in schema_statements():
        try:
            graph.query(statement)
            counts["indexes_created"] += 1
        except ResponseError as exc:
            if not _is_already(exc):
                raise
            counts["indexes_existing"] += 1
    for label in UNIQUE_ID_LABELS:
        try:
            db.connection.execute_command(
                "GRAPH.CONSTRAINT", "CREATE", graph.name, "UNIQUE", "NODE", label, "PROPERTIES", "1", "id"
            )
            counts["constraints_created"] += 1
        except ResponseError as exc:
            if not _is_already(exc):
                raise
            counts["constraints_existing"] += 1
    wait_for_constraints(graph)
    return counts


def wait_for_constraints(graph: Graph, timeout_s: float = 10.0) -> None:
    """Constraint creation is asynchronous (`PENDING`); block until every constraint is OPERATIONAL."""
    deadline = time.monotonic() + timeout_s
    while True:
        rows = graph.query("CALL db.constraints() YIELD status RETURN collect(status)").result_set
        statuses = rows[0][0] if rows else []
        if "PENDING" not in statuses:
            if "FAILED" in statuses:
                raise RuntimeError(f"constraint creation failed on graph {graph.name}")
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"constraints still pending on graph {graph.name}")
        time.sleep(0.05)


def _is_already(exc: ResponseError) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _ALREADY)
