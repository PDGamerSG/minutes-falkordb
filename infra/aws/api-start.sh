#!/bin/sh
# Seeding is idempotent: tenants are merged and facts have content-derived ids, so it is safe on every start.
set -u
python data/seed.py --tenants orbit,nimbus,quill --extract gold || echo "WARN: seed failed"
python data/seed_work.py --tenants orbit || echo "WARN: seed_work failed"
exec uvicorn apps.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
