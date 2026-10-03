# Deployment notes

## FalkorDB on Railway (database + API)

1. New Railway project → "Deploy a template" → search FalkorDB (docs: https://docs.falkordb.com/operations/railway.html, template: https://railway.com/deploy/falkordb-1). Attach a volume at `/var/lib/falkordb/data` (check the image's data path; docs show both `/data` and `/var/lib/falkordb/data`). Set `REDIS_ARGS=--requirepass <password> --appendonly yes` and `FALKORDB_ARGS=TIMEOUT_DEFAULT 3000 TIMEOUT_MAX 10000 MAX_QUEUED_QUERIES 500`. Note the public TCP proxy host and port (`FALKORDB_PUBLIC_URL`).
2. Add a second service from this repo with root `apps/api` (Dockerfile build). Env: `FALKORDB_URL=falkor://default:<password>@<internal host>:6379`, `LLM_BACKEND=gemini`, `GEMINI_API_KEY`, `LLM_MODEL=gemma-4-26b-a4b-it` (verify the id in AI Studio), `EMBED_BACKEND=onnx`, `CORS_ORIGINS=https://<web>.vercel.app`. Expose port 8000.
3. Seed once: `railway run uv run --package minutes-api python data/seed.py --tenants orbit,nimbus,quill --reset` (or run the seed container locally against the public URL).
4. Keep-warm: a Vercel cron or cron-job.org hitting `GET /health` every 10 minutes.

Budget: Hobby plan $5 per month including $5 usage; a 1 GB container all month is roughly $10 to $15 more.

## Web on Vercel

Import the repo, root directory `apps/web`, framework Next.js. Env: `NEXT_PUBLIC_API_URL=https://<api>.up.railway.app`. Hobby plan, free.

## $0 alternative

Oracle Cloud Always Free ARM VM (4 OCPU, 24 GB): `docker compose up -d` with this repo's compose file, Caddy for TLS. A few hours of setup; no monthly cost.

## FalkorDB Cloud free tier

Fine for development (100 MB, no card). Not for the judging window: no persistence, stops after one idle day, deleted after seven. If used anyway, keep `data/seed.py --reset` ready and a keep-warm ping.
