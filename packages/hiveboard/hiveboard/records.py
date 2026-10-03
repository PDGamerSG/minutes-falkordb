"""Conversions from falkordb-py result objects, or Cypher map projections such as `n {.id, labels: labels(n)}`,
to plain dicts, plus the `{nodes, edges}` subgraph shape the UI renders.

Read queries project nodes without their 768-d `embedding` (returning whole nodes costs ~0.5 ms per node on the
wire), so most helpers here accept either a `Node` or an already-projected dict."""

from __future__ import annotations

from typing import Any

from falkordb import Edge, Node

Record = Node | dict
_SPECIFIC_LABELS = ("Decision", "Commitment")


class CypherRows(list):
    """A list of result rows that also carries the Cypher text that produced it (`rows.cypher`).

    It serialises as a plain JSON array; callers that show the query to users read `.cypher`.
    """

    def __init__(self, rows: list | None = None, cypher: str = ""):
        super().__init__(rows or [])
        self.cypher = cypher


def primary_label(labels: list[str]) -> str | None:
    """`Commitment`/`Decision` beat the generic `Fact`; otherwise the first label."""
    for label in _SPECIFIC_LABELS:
        if label in labels:
            return label
    return labels[0] if labels else None


def labels_of(x: Record | None) -> list[str]:
    """Labels of a Node, or the `labels` key of a projection."""
    if x is None:
        return []
    if isinstance(x, Node):
        return list(x.labels)
    return list(x.get("labels") or [])


def get(x: Record | None, key: str, default: Any = None) -> Any:
    """Property lookup that works for Nodes and projections alike."""
    if x is None:
        return default
    if isinstance(x, Node):
        return x.properties.get(key, default)
    return x.get(key, default)


def props(x: Record | None, *, keep_embedding: bool = False) -> dict[str, Any] | None:
    """Flat property dict (embedding replaced by `has_embedding` unless asked) with `labels` added."""
    if x is None:
        return None
    if isinstance(x, Node):
        out = dict(x.properties)
        if not keep_embedding:
            out["has_embedding"] = out.pop("embedding", None) is not None
        out["labels"] = list(x.labels)
        return out
    out = dict(x)
    out.setdefault("has_embedding", False)
    out["labels"] = list(out.get("labels") or [])
    return out


def compact(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop None-valued keys: a label-generic projection yields nulls for fields the label does not have."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if v is not None}


def brief(x: Record | None, *fields: str) -> dict[str, Any] | None:
    """Only the requested fields, for nested references like `speaker: {id, name}`."""
    if x is None:
        return None
    return {f: get(x, f) for f in (fields or ("id", "name"))}


def graph_node(x: Record) -> dict[str, Any]:
    """`{id, label, labels, props}` as the Why panel's GraphView expects."""
    data = props(x) or {}
    labels = data.pop("labels", [])
    return {"id": data.get("id"), "label": primary_label(labels), "labels": labels, "props": data}


def graph_edge(source: str, target: str, type_: str, edge_props: dict | None = None) -> dict[str, Any]:
    """`{source, target, type, props}` edge record."""
    return {"source": source, "target": target, "type": type_, "props": edge_props or {}}


class Subgraph:
    """Accumulates nodes and edges without duplicates; `.to_dict()` gives `{nodes, edges}`."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict] = {}
        self._edges: dict[tuple[str, str, str], dict] = {}

    def add_node(self, x: Record | None) -> str | None:
        if x is None:
            return None
        record = graph_node(x)
        nid = record["id"] or (f"_{x.id}" if isinstance(x, Node) else f"_{id(x)}")
        record["id"] = nid
        self._nodes.setdefault(nid, record)
        return nid

    def add_edge(
        self, source: str | None, target: str | None, type_: str, edge_props: dict | None = None
    ) -> None:
        if source is None or target is None:
            return
        self._edges.setdefault((source, target, type_), graph_edge(source, target, type_, edge_props))

    def add_falkor_edge(self, edge: Edge, source_id: str, target_id: str) -> None:
        self.add_edge(source_id, target_id, edge.relation, dict(edge.properties))

    def to_dict(self) -> dict[str, list[dict]]:
        return {"nodes": list(self._nodes.values()), "edges": list(self._edges.values())}


def row_value(value: Any) -> Any:
    """Recursively convert Nodes inside lists/maps returned by collect() to dicts."""
    if isinstance(value, Node):
        return props(value)
    if isinstance(value, list):
        return [row_value(v) for v in value]
    if isinstance(value, dict):
        return {k: row_value(v) for k, v in value.items()}
    return value
