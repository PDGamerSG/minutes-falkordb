#!/bin/sh
# Production startup must never replay gold labels or mutate the persistent graph.
# Existing records remain in FalkorDB; new uploads use the configured real extractor.
set -u
exec uvicorn apps.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
