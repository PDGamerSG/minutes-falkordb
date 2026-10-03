"""Seed the demo tenants: create them, register the agents, import every meeting and email thread.

    uv run --package minutes-api python data/seed.py --tenants orbit,nimbus,quill --reset
    uv run --package minutes-api python data/seed.py --tenants orbit --skip orbit_002   # import it live later

Idempotent: tenants are MERGEd, episodes and facts carry deterministic ids, restated facts are
confirmations rather than duplicates. Works without any model when LLM_BACKEND=fake (gold labels
are replayed) and without the ONNX model when EMBED_BACKEND=fake.
Files are dispatched on their top-level key (``meeting`` vs ``thread``); rosters are loaded first
and are never imported; ``data/generator/`` is ignored.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.config import get_settings
from apps.api.hive_adapter import register_default_agents
from apps.api.ingest_service import import_meeting, import_thread, load_roster, source_kind_of
from apps.api.main import build_context

log = logging.getLogger("seed")


def discover(meetings_dir: Path, tenant: str) -> list[tuple[str, Path]]:
    """``(kind, path)`` for a tenant's meetings and threads in chronological order (``started_at``).

    Chronological import keeps supersession chains honest: a restatement is a confirmation only
    when the statement it confirms is already in the graph. Rosters and unknown files are skipped.
    """
    found: list[tuple[str, str, Path]] = []
    for path in sorted(meetings_dir.glob(f"{tenant}_*.json")):
        if path.stem.endswith("_roster"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("skipping unreadable %s: %s", path.name, exc)
            continue
        kind = source_kind_of(data) if isinstance(data, dict) else None
        if kind is None:
            log.info("skipping %s (no meeting/thread key)", path.name)
            continue
        started = str((data.get("meeting") or data.get("thread") or {}).get("started_at") or "")
        found.append((started, kind, path))
    found.sort(key=lambda row: (row[0], row[2].name))
    return [(kind, path) for _, kind, path in found]


def seed_tenant(ctx, tenant: str, meetings_dir: Path, *, reset: bool, skip: set[str]) -> list[dict]:
    hive = ctx.hive
    if reset and tenant in hive.list_tenants():
        log.info("resetting tenant %s", tenant)
        hive.delete_tenant(tenant)
    if tenant not in hive.list_tenants():
        hive.create_tenant(tenant, tenant.capitalize())
    else:
        hive.ensure_schema(tenant)
    register_default_agents(hive, tenant, getattr(ctx.llm, "model", "fake"))
    roster = load_roster(ctx.settings.data_path, tenant)
    rows: list[dict] = []
    for kind, path in discover(meetings_dir, tenant):
        if path.stem in skip:
            log.info("skipping %s (--skip)", path.stem)
            rows.append({"tenant": tenant, "file": path.stem, "kind": kind, "status": "skipped"})
            continue
        started = time.perf_counter()
        data = json.loads(path.read_text(encoding="utf-8"))
        try:
            if kind == "meeting":
                stats = import_meeting(data, tenant, ctx, slug=path.stem)
            else:
                stats = import_thread(data, tenant, ctx, slug=path.stem, roster=roster)
        except Exception as exc:
            log.exception("import of %s failed", path.name)
            rows.append({"tenant": tenant, "file": path.stem, "kind": kind, "status": f"failed: {type(exc).__name__}: {exc}"[:120]})
            continue
        rows.append({"tenant": tenant, "file": path.stem, "kind": kind, "status": "ok", "seconds": round(time.perf_counter() - started, 1), **stats})
    return rows


def print_table(rows: list[dict]) -> None:
    header = f"{'tenant':<8}{'file':<22}{'kind':<9}{'status':<10}{'eps':>5}{'facts':>6}{'dec':>5}{'com':>5}{'sup':>5}{'dup':>5}{'drop':>5}{'s':>7}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['tenant']:<8}{r['file']:<22}{r['kind']:<9}{r['status'][:9]:<10}{r.get('episodes', ''):>5}{r.get('facts', ''):>6}"
            f"{r.get('decisions', ''):>5}{r.get('commitments', ''):>5}{r.get('superseded', ''):>5}{r.get('duplicates', ''):>5}"
            f"{r.get('dropped', ''):>5}{r.get('seconds', ''):>7}"
        )
    total = {k: sum(int(r.get(k) or 0) for r in rows) for k in ("episodes", "facts", "decisions", "commitments", "superseded", "duplicates", "dropped")}
    print("-" * len(header))
    print(f"{'TOTAL':<8}{'':<22}{'':<9}{'':<10}{total['episodes']:>5}{total['facts']:>6}{total['decisions']:>5}{total['commitments']:>5}{total['superseded']:>5}{total['duplicates']:>5}{total['dropped']:>5}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Minutes tenants from data/meetings.")
    parser.add_argument("--tenants", default=None, help="comma-separated slugs (default: SEED_TENANTS env or orbit,nimbus,quill)")
    parser.add_argument("--reset", action="store_true", help="delete and recreate the tenant graphs first")
    parser.add_argument("--skip", action="append", default=[], help="file slug to leave out, e.g. --skip orbit_002 (repeatable, comma-separated ok)")
    parser.add_argument("--meetings-dir", default=None, help="directory with the data files (default: <data_dir>/meetings)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = get_settings()
    tenants = [t.strip() for t in (args.tenants or settings.seed_tenants).split(",") if t.strip()]
    skip = {s.strip() for chunk in args.skip for s in chunk.split(",") if s.strip()}
    meetings_dir = Path(args.meetings_dir) if args.meetings_dir else settings.data_path / "meetings"
    if not meetings_dir.is_dir():
        print(f"no such directory: {meetings_dir}", file=sys.stderr)
        return 2

    ctx = build_context(settings)
    log.info(
        "hive=%s llm=%s/%s embedder=%s (%s) tenants=%s skip=%s",
        getattr(ctx.hive, "kind", "?"), getattr(ctx.llm, "backend", "?"), getattr(ctx.llm, "model", "?"),
        ctx.embedder.name, ctx.embedder.model, tenants, sorted(skip) or "-",
    )
    try:
        ctx.hive.load_udfs()
    except Exception as exc:  # noqa: BLE001 - recall falls back to loading the UDF lazily
        log.warning("load_udfs failed: %s", exc)

    rows: list[dict] = []
    for tenant in tenants:
        rows.extend(seed_tenant(ctx, tenant, meetings_dir, reset=args.reset, skip=skip))
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print_table(rows)
    failures = [r for r in rows if r["status"].startswith("failed")]
    close = getattr(ctx.hive, "close", None)
    if callable(close):
        close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
