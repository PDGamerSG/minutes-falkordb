"""Schema management: indexes from `cypher/00_schema.cypher` plus unique constraints, idempotent per graph.

`ensure_commons_schema` runs once per process per HiveDB (finding 25); `ensure_schema` also back-fills
`Entity.name_key` (finding 6) on graphs written before the normalised entity key existed."""

from __future__ import annotations

import time

from falkordb import Graph
from redis.exceptions import ResponseError

from .db import HiveDB
from .queries import schema_statements
from .udf.loader import load_udfs

__all__ = ["UNIQUE_ID_LABELS", "ConstraintFailed", "ensure_commons_schema", "ensure_schema", "load_udfs"]

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
_MIGRATIONS = (
    # Entities written before 04_upsert_entity merged on name_key get the normalised key so the MERGE finds them.
    "MATCH (e:Entity) WHERE e.name_key IS NULL AND e.name IS NOT NULL SET e.name_key = toLower(trim(e.name)) RETURN count(e)",
)


def ensure_schema(db: HiveDB, tenant: str) -> dict[str, int]:
    """Create every index and unique constraint for `team_<tenant>`; safe to run repeatedly. Returns counts."""
    graph = db.graph(tenant)
    counts = apply_schema(db, graph)
    for statement in _MIGRATIONS:
        graph.query(statement)
    return counts


def ensure_commons_schema(db: HiveDB, force: bool = False) -> dict[str, int]:
    """Same schema on the shared `commons` graph (Tenant, Snapshot and published Skill nodes live there).
    Runs the ~50 DDL statements once per process per HiveDB; later calls are no-ops unless `force`."""
    if db.commons_schema_applied and not force:
        return {"indexes_created": 0, "indexes_existing": 0, "constraints_created": 0, "constraints_existing": 0,
                "skipped": 1}
    counts = apply_schema(db, db.commons())
    db.commons_schema_applied = True
    return counts


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
    wait_for_constraints(graph, db=db)
    return counts


def wait_for_constraints(graph: Graph, timeout_s: float = 10.0, db: HiveDB | None = None) -> None:
    """Constraint creation is asynchronous (`PENDING`); block until every constraint is OPERATIONAL. A FAILED constraint
    (duplicate ids already in the graph) is dropped and reported through `ConstraintFailed`."""
    deadline = time.monotonic() + timeout_s
    while True:
        rows = graph.query("CALL db.constraints() YIELD status RETURN collect(status)").result_set
        statuses = rows[0][0] if rows else []
        if "PENDING" not in statuses:
            if "FAILED" in statuses:
                raise ConstraintFailed(_drop_failed_constraints(graph, db))
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"constraints still pending on graph {graph.name}")
        time.sleep(0.05)


class ConstraintFailed(RuntimeError):
    """A unique constraint could not be built because the graph holds duplicates (finding 22). The FAILED constraint has
    been dropped so a repaired graph can run `ensure_schema` again; `duplicates` lists `{label, property, value, count}`."""

    def __init__(self, duplicates: list[dict]):
        self.duplicates = duplicates
        shown = ", ".join(f"{d['label']}.{d['property']}={d['value']!r} x{d['count']}" for d in duplicates[:5])
        super().__init__(f"unique constraint failed, duplicates found: {shown or 'unknown'}; the constraint was dropped, "
                         "merge or delete the duplicates and run ensure_schema again")


def _drop_failed_constraints(graph: Graph, db: HiveDB | None) -> list[dict]:
    """Drop every FAILED constraint of the graph and report the duplicate values that made it fail."""
    rows = graph.query(
        "CALL db.constraints() YIELD type, label, properties, entitytype, status "
        "WHERE status = 'FAILED' RETURN type, label, properties, entitytype"
    ).result_set
    duplicates: list[dict] = []
    for ctype, label, properties, entitytype in rows:
        if entitytype != "NODE" or label not in UNIQUE_ID_LABELS or list(properties) != ["id"]:
            continue
        found = graph.query(
            f"MATCH (n:{label}) WITH n.id AS v, count(n) AS c WHERE c > 1 RETURN v, c LIMIT 20"
        ).result_set
        duplicates += [{"label": label, "property": "id", "value": v, "count": c} for v, c in found]
        (db.connection if db is not None else graph.client.connection).execute_command(
            "GRAPH.CONSTRAINT", "DROP", graph.name, str(ctype).upper(), "NODE", label, "PROPERTIES", "1", "id"
        )
    return duplicates


def _is_already(exc: ResponseError) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _ALREADY)
