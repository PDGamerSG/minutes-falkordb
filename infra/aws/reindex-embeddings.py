"""Rebuild all tenant vectors in place before switching a persistent graph to ONNX embeddings.

This is deliberately an explicit one-time command. It never deletes tenants, episodes, facts or
relationships, and it changes the tenant embedding metadata only after every node was updated.
Run inside the API image while the API is stopped or before it is allowed to serve traffic:

    docker compose -f infra/aws/docker-compose.yml --env-file infra/aws/.env stop api
    docker compose ... run --rm api python /app/reindex-embeddings.py
    docker compose ... up -d api
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from apps.api.main import build_context

log = logging.getLogger("reindex_embeddings")
CHUNK = 32

NODE_TEXT: dict[str, str] = {
    "Episode": "coalesce(n.text, '')",
    "Fact": "coalesce(n.text, n.subject + ' ' + n.predicate + ' ' + n.object, '')",
    "Entity": "coalesce(n.name, '')",
    "Skill": "coalesce(n.goal, '')",
}


def rows_for(ctx: Any, tenant: str, label: str) -> list[tuple[str, str]]:
    query = f"MATCH (n:{label}) RETURN n.id, {NODE_TEXT[label]} ORDER BY n.id"
    result = ctx.hive._ro(tenant, query)  # explicit maintenance command; RealHive keeps RO reads here
    return [(str(row[0]), str(row[1])) for row in result.result_set if row[0] and str(row[1]).strip()]


def write_vectors(ctx: Any, tenant: str, label: str, rows: Iterable[tuple[str, str]]) -> int:
    materialised = list(rows)
    total = 0
    for start in range(0, len(materialised), CHUNK):
        batch = materialised[start : start + CHUNK]
        vectors = ctx.embedder.embed([text for _, text in batch], "document")
        params = {"rows": [{"id": node_id, "embedding": vector} for (node_id, _), vector in zip(batch, vectors)]}
        query = f"UNWIND $rows AS r MATCH (n:{label} {{id: r.id}}) SET n.embedding = vecf32(r.embedding) RETURN count(n)"
        result = ctx.hive._rw(tenant, query, params)
        total += int(result.result_set[0][0] or 0) if result.result_set else 0
    return total


def main() -> int:
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
    ctx = build_context()
    try:
        identity = ctx.embedder.identity
        if not identity.startswith("onnx:"):
            raise SystemExit(f"Refusing migration with non-ONNX embedder: {identity}")
        for tenant in ctx.hive.list_tenants():
            counts: dict[str, int] = {}
            for label in NODE_TEXT:
                rows = rows_for(ctx, tenant, label)
                counts[label] = write_vectors(ctx, tenant, label, rows)
            ctx.hive.set_tenant_meta(tenant, {"embedding_model": identity, "embedding_dim": ctx.embedder.dim})
            log.info("reindexed %s: %s", tenant, counts)
    finally:
        close = getattr(ctx.hive, "close", None)
        if callable(close):
            close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
