# Deployment notes

Local operation and an API container build were checked on Oct 9, 2026. These notes are a deployment recipe, not evidence of a working hosted deployment. Provider pricing, limits and free-tier policies must be checked at deployment time.

## API and database

Build the API with the **repository root as its build context**. The Dockerfile copies workspace packages, Cypher, synthetic data and stored benchmark results:

```bash
docker build -f apps/api/Dockerfile -t minutes-api .
```

The build is reproducible and self-contained at run time:

- Dependencies come from `uv sync --frozen` (a stale `uv.lock` fails the build, nothing is re-resolved).
- The EmbeddingGemma ONNX model (about 300 MB) is downloaded once **at build time** into `/app/hf-cache`, the Hub symlinks are flattened (onnxruntime rejects external weights behind a symlink) and a 768-d embedding is computed before the image is accepted. The runtime sets `HF_HUB_OFFLINE=1`, so a cold container needs no network to start and cannot silently switch embedding models. Override the model with `--build-arg EMBED_MODEL=...` and the matching `EMBED_MODEL` env at run time.
- The runtime stage is a separate `python:3.12-slim` layer, runs as the unprivileged user `minutes` (uid 10001) and carries no build tooling. Image size is about 1.1 GB.
- `PORT` (default 8000) selects the listening port, which suits hosts that inject `PORT`. The `HEALTHCHECK` calls `/health` with a 60 s start period.

Verified 2026-10-12: the image built, started against a scratch FalkorDB with `LLM_BACKEND=fake EMBED_BACKEND=onnx`, logged `ONNX embedder: using cached ... (no network)`, reported `healthy` and `/health` 200 with 18 workers alive.

For Railway or another container host, set the Dockerfile path to `apps/api/Dockerfile` while keeping the build context at the root. The container listens on **8000**; local Compose maps **8080:8000**. Configure the host to route traffic to that port. `/health` returns 503 if database checks or startup preparation fail; if FalkorDB is unreachable at boot the API still starts, answers 503 and reconnects every `STARTUP_RETRY_S` seconds instead of restart-looping.

Run `falkordb/falkordb:6.0.1` on the private network (no published ports; the local Compose file publishes 6379 and 3000 for development only). Set `FALKORDB_URL` for the API, provision persistent storage at the image's configured data directory, enable persistence as appropriate, and verify recovery after restarting the database. Add `MAX_QUEUED_QUERIES 500 TIMEOUT_MAX 10000` to `FALKORDB_ARGS` as the Compose file does. Do not expose the unauthenticated database or FalkorDB Browser publicly. See the sponsor's [operations documentation](https://docs.falkordb.com/operations/railway.html) for platform-specific setup.

### Deployment checklist

1. `ENV=production`: CORS trusts `CORS_ORIGINS` only, `AUTO_CREATE_TENANTS` defaults off, startup warns about missing secrets.
2. `ADMIN_TOKEN=<random>`: guards tenant creation and deletion, key rotation, snapshots, work-item import, `/demo/*` and `/bench/run`. `TENANT_KEYS_REQUIRED=true`: every tenant route needs the tenant's `X-API-Key` (created with the tenant, shown once, stored hashed). Create tenants with `POST /tenants` and the admin token, keep the returned key.
3. `TENANT_RW_PASSWORD` / `TENANT_RO_PASSWORD`: random values. They are master secrets: each tenant's database ACL passwords are an HMAC of the slug under them (nothing is stored in the graph, because tenant users can read the commons registry). Tenants created before this scheme keep their old shared password until `POST /tenants?rotate=true`.
4. `CORS_ORIGINS` = the web origin; `NEXT_PUBLIC_API_URL` = the API URL; `NEXT_PUBLIC_MOCK` unset.
5. `WORKERS_ENABLED=false` on small plans (three tenants mean 18 coroutines plus the 0.6 GB ONNX model); keep `LLM_TIMEOUT_S` at 60 or below; `GEMINI_TPM_BUDGET` at or under the provider's per-minute limit (free tier 16000, shared by both keys).
6. Seed with the API stopped (`data/seed.py --reset` while workers run would fan out reschedule tasks), then `data/seed_work.py --tenants orbit`. Historical supersessions older than `LIVE_EVENT_MAX_AGE_DAYS` (14) are ignored by the Scheduler either way.
7. `STRICT_HEALTH=true` if the platform should restart the container when the model is unreachable or a worker died.
8. Smoke test against the deployed URL: `/health`, `/tenants`, `/tenants/orbit/impact`, two chat calls, `/tenants/orbit/events?replay=50`, `POST /demo/supersede` then the task trace.

Use `LLM_BACKEND=fake EMBED_BACKEND=fake` for the deterministic synthetic-data demo, or explicitly configure and test a real model provider and embedding model. A tenant records the embedding model that built it (`embedding_model`, `embedding_dim` in its registry metadata); an API running a different model refuses imports (409) and reports `embedding_mismatch` on `/health` (503). The API never silently falls back to test vectors.

Seed from inside the deployed environment or from a secured connection to that database. `data/seed.py --extract gold` replays gold labels; `--extract real` invokes a model. Use `--reset` only when deliberately discarding a demo tenant's data. Leave `GITHUB_TOKEN` and `GITHUB_DEMO_REPO` unset for simulated follow-ups (`minutes://simulated/issue/<id>` URIs).

## AWS single host (live demo)

`infra/aws/` runs the whole backend on one small Ubuntu 24.04 host: FalkorDB 6.0.1 (no published ports, append-only persistence on a named volume), the API (scripted LLM and test embeddings, reseeded idempotently on every start) and Caddy for automatic HTTPS. `setup.sh` adds 2 GB of swap, installs Docker with capped container logs, generates the tenant master secrets once into `infra/aws/.env` (git-ignored) and starts the stack:

```bash
sudo bash infra/aws/setup.sh <hostname> https://<web-origin>
```

The live demo uses a 1 GB AWS Lightsail instance in ap-southeast-2 with a static IP, the `<ip>.sslip.io` hostname for the certificate and daily automatic snapshots. Update it with `git pull` followed by the same `docker compose ... up -d --build` command.

## Web

For Vercel, use `apps/web` as the project root and set `NEXT_PUBLIC_API_URL` to the HTTPS API URL before building. Set the API's `CORS_ORIGINS` to the web origin. `NEXT_PUBLIC_MOCK` must remain unset for a real API demonstration. The app does not substitute fixtures when the API fails.

A local web container can be built separately:

```bash
docker build -t minutes-web apps/web --build-arg NEXT_PUBLIC_API_URL=http://localhost:8080
docker run --rm -p 3001:3000 minutes-web
```

## Access control

What is enforced (all of it off in local development until configured, see the checklist):

- Admin token on mutating shared and demo routes, per-tenant API keys on every `/tenants/{t}/...` route, 401 for a missing and 403 for a wrong credential, `?api_key=` accepted only for the event stream and audio.
- Database-level isolation: per-tenant ACL users; the tenant rw user can write only its own graph and read `commons` through a selector; the ro user reads its graph and `commons`. `GET /tenants/{t}/acl-probe` demonstrates the denial.
- Free-form Cypher runs as the tenant's ro user with a 3 s timeout, `LIMIT 200`, and may not name the chat-history labels.
- Import bodies are capped (`MAX_IMPORT_BYTES`), snapshots are capped, duplicate tenant slugs are refused, `__snap_` slugs are rejected, 500 responses carry a request id instead of exception text.

What is not done: there is no user identity inside a tenant (anyone with a tenant's key sees all of that tenant's data and chat sessions are scoped by key, not by person), no rate limiting beyond the model token budget, and no private company deployment has been validated. Use synthetic or public data as the hackathon rules require.
