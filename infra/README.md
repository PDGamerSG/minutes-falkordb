# Deployment notes

Local operation and an API container build were checked on Oct 9, 2026. These notes are a deployment recipe, not evidence of a working hosted deployment. Provider pricing, limits and free-tier policies must be checked at deployment time.

## API and database

Build the API with the **repository root as its build context**. The Dockerfile copies workspace packages, Cypher, synthetic data and stored benchmark results:

```bash
docker build -f apps/api/Dockerfile -t minutes-api .
```

For Railway or another container host, set the Dockerfile path to `apps/api/Dockerfile` while keeping the build context at the root. The container listens on **8000**; local Compose maps **8080:8000**. Configure the host to route traffic to that port. `/health` returns 503 if database checks or startup preparation fail.

Run `falkordb/falkordb:6.0.1` on the private network. Set `FALKORDB_URL` for the API, provision persistent storage at the image's configured data directory, enable persistence as appropriate, and verify recovery after restarting the database. Do not expose the unauthenticated database or FalkorDB Browser publicly. See the sponsor's [operations documentation](https://docs.falkordb.com/operations/railway.html) for platform-specific setup.

Use `LLM_BACKEND=fake EMBED_BACKEND=fake` for the deterministic synthetic-data demo, or explicitly configure and test a real model provider and embedding model. Use the same embedding model for import and retrieval; embedding spaces are not interchangeable even when both have 768 dimensions. The API no longer silently falls back to test vectors.

Seed from inside the deployed environment or from a secured connection to that database. `data/seed.py --extract gold` replays gold labels; `--extract real` invokes a model. Use `--reset` only when deliberately discarding a demo tenant's data. Leave `GITHUB_TOKEN` and `GITHUB_DEMO_REPO` unset for simulated follow-ups.

## Web

For Vercel, use `apps/web` as the project root and set `NEXT_PUBLIC_API_URL` to the HTTPS API URL before building. Set the API's `CORS_ORIGINS` to the web origin. `NEXT_PUBLIC_MOCK` must remain unset for a real API demonstration. The app does not substitute fixtures when the API fails.

A local web container can be built separately:

```bash
docker build -t minutes-web apps/web --build-arg NEXT_PUBLIC_API_URL=http://localhost:8080
docker run --rm -p 3001:3000 minutes-web
```

## Access-control gap

The current HTTP API has no login or tenant membership authorization and uses an administrative database connection. Per-graph database ACL tests do not prevent a caller from changing a tenant slug in an HTTP request. Use synthetic/public data for the hackathon as required by its rules. Before a company deployment, implement identity and tenant checks on every route, gate demo/benchmark/admin endpoints, configure upload limits and rate limits, and test unauthorized access. No private company deployment has been validated.
