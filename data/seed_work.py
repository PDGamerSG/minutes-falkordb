"""Import the synthetic work dependency registers after the meeting/email gold replay.

    uv run --package minutes-api python data/seed_work.py --tenants orbit

The manifests name exact reviewed baseline facts; no relationship is inferred from a
co-mention. Invalid references fail the import rather than linking to a similar fact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.main import build_context
from apps.api.routes.impact import WorkManifest


def import_work_file(ctx, tenant: str) -> int:
    path = ctx.settings.data_path / "work-items" / f"{tenant}.json"
    if not path.is_file():
        return 0
    ctx.ensure_tenant(tenant)
    ctx.hive.ensure_schema(tenant)
    manifest = WorkManifest.model_validate_json(path.read_text(encoding="utf-8"))
    return ctx.hive.import_work_manifest(tenant, manifest.graph_payload())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenants", default="orbit")
    args = parser.parse_args()
    ctx = build_context()
    try:
        for tenant in args.tenants.split(","):
            count = import_work_file(ctx, tenant.strip())
            print(json.dumps({"tenant": tenant.strip(), "work_items_imported": count}))
    finally:
        close = getattr(ctx.hive, "close", None)
        if callable(close):
            close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
