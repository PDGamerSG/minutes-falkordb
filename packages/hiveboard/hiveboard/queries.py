"""Loader for the repo's `cypher/NN_name.cypher` files: the single source of truth for every query.

Lookup order: `$HIVEBOARD_CYPHER_DIR`, the monorepo `cypher/` folder next to `packages/`, then a copy
bundled into the wheel at `hiveboard/cypher/` (added at build time by hatch, never committed twice).
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent


def cypher_dirs() -> list[Path]:
    """Candidate directories holding the numbered Cypher files, in priority order."""
    dirs: list[Path] = []
    env = os.environ.get("HIVEBOARD_CYPHER_DIR")
    if env:
        dirs.append(Path(env))
    dirs.append(_PKG_DIR.parents[2] / "cypher")
    dirs.append(_PKG_DIR / "cypher")
    return [d for d in dirs if d.is_dir()]


@cache
def cypher_path(name: str) -> Path:
    """Resolve `claim_task` or `20_claim_task` to its file. The prefix is two characters: a decade digit and a
    digit or capital letter (`2A_reap_tasks` follows `29_list_agents` when a decade runs out of digits)."""
    for directory in cypher_dirs():
        exact = directory / f"{name}.cypher"
        if exact.is_file():
            return exact
        matches = sorted(directory.glob(f"[0-9][0-9A-Z]_{name}.cypher"))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"no cypher file for {name!r} in {[str(d) for d in cypher_dirs()]}")


def _strip_comments(text: str) -> list[str]:
    return [
        line.rstrip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("//")
    ]


@cache
def load_cypher(name: str) -> str:
    """Query text of one file with the `//` comment lines removed."""
    return "\n".join(_strip_comments(cypher_path(name).read_text(encoding="utf-8")))


def schema_statements() -> list[str]:
    """Each non-comment line of `00_schema.cypher` is one standalone statement."""
    return _strip_comments(cypher_path("00_schema").read_text(encoding="utf-8"))


def list_queries() -> list[str]:
    """Names (without extension) of every Cypher file visible to the loader."""
    seen: dict[str, None] = {}
    for directory in cypher_dirs():
        for path in sorted(directory.glob("[0-9][0-9A-Z]_*.cypher")):
            seen.setdefault(path.stem, None)
    return list(seen)
