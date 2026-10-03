"""Load `score.js` into FalkorDB as the `hive` UDF library (server-wide, not per graph)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import HiveDB

UDF_LIBRARY = "hive"
_SCRIPT = Path(__file__).with_name("score.js")


def udf_source() -> str:
    """The JavaScript source of the library."""
    return _SCRIPT.read_text(encoding="utf-8")


def load_udfs(db: HiveDB) -> None:
    """`GRAPH.UDF LOAD REPLACE hive <score.js>`; raises if the server rejects the script or does not list it afterwards."""
    db.client.udf_load(UDF_LIBRARY, udf_source(), replace=True)
    if not udf_loaded(db):
        raise RuntimeError(f"GRAPH.UDF LOAD succeeded but library {UDF_LIBRARY!r} is not listed")


def udf_loaded(db: HiveDB) -> bool:
    """True when `GRAPH.UDF LIST` reports the `hive` library."""
    for entry in db.client.udf_list():
        flat = (
            [e.decode() if isinstance(e, bytes) else e for e in entry] if isinstance(entry, list) else [entry]
        )
        if UDF_LIBRARY in flat:
            return True
    return False
