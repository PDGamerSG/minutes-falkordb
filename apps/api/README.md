# Minutes API (`apps/api`)

FastAPI service plus agent workers over the Hive Board substrate (`packages/hiveboard`) and the
ingestion pipeline (`packages/ingest`). Every answer carries the Cypher it ran, the subgraph it
touched, the sources and the router decision.

## Run

From the repo root (the package is imported as `apps.api`; `apps` is a namespace package):

```bash
export LLM_BACKEND=fake EMBED_BACKEND=fake # deterministic local demonstration
uv sync --all-packages                    # workspace: hiveboard, ingest, minutes-api
docker compose up -d falkordb             # FalkorDB 6.0.x on localhost:6379
uv run --package minutes-api python data/seed.py --tenants orbit,nimbus,quill --extract gold
uv run --package minutes-api python data/seed_work.py --tenants orbit
uv run --package minutes-api uvicorn apps.api.main:app --port 8080 --reload
```

The documented local API listens on 8080 (the `--port 8080` above; `docker compose` maps `8080:8000`; the web app points at 8080).

Tests (no FalkorDB, no models: `FakeHive`, `FakeLLM`, `FakeEmbedder`):

```bash
uv run --package minutes-api pytest apps/api/tests -q
uv run --package ingest pytest packages/ingest/tests -q
```

Extraction eval against the gold labels:

```bash
uv run --package minutes-api python -m ingest.eval --backend fake            # plumbing check (replays gold)
uv run --package minutes-api python -m ingest.eval --backend ollama --model gemma4:e4b --show-misses
```

Container: `docker build -f apps/api/Dockerfile -t minutes-api .` (multi-stage python:3.12-slim, `uv sync --frozen`, embedding model baked in and `HF_HUB_OFFLINE=1`, runs as a non-root user, uvicorn on `$PORT` or 8000). See `infra/README.md`.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `FALKORDB_URL` | `falkor://localhost:6379` | admin connection (`FALKORDB_ADMIN_USER/PASSWORD` optional) |
| `TENANT_RW_PASSWORD` / `TENANT_RO_PASSWORD` | `change-me-*` | ACL users `team_<slug>_rw` / `team_<slug>_ro` created per tenant |
| `LLM_BACKEND` | `ollama` | `gemini` \| `openrouter` \| `ollama` \| `fake` |
| `LLM_MODEL` | `gemma4:e4b` | gemini: `gemma-4-26b-a4b-it`; openrouter: `google/gemma-4-26b-a4b-it`; ollama: `gemma4:e4b` |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | the native `/api/chat` is derived from it (thinking disabled, `format: json`) |
| `GEMINI_API_KEY` / `OPENROUTER_API_KEY` | | required for those backends |
| `LLM_MAX_TOKENS` / `LLM_TIMEOUT_S` | `1024` / `180` | completion budget and HTTP timeout |
| `EMBED_BACKEND` | `onnx` | `onnx` (EmbeddingGemma-300m, 768-d) \| `gemini` \| `fake`; startup fails if the requested model cannot load; select fake explicitly for tests |
| `EMBED_MODEL` | `onnx-community/embeddinggemma-300m-ONNX` | HF repo for the ONNX backend |
| `HF_HOME` | | optional model cache directory (platform default if unset) |
| `HIVE_BACKEND` | | set to `fake` to run the API entirely in memory (no FalkorDB) |
| `ENV` | `development` | `production`: CORS trusts `CORS_ORIGINS` only, `AUTO_CREATE_TENANTS` defaults off, warnings for missing secrets |
| `ADMIN_TOKEN` | | when set, admin routes need `Authorization: Bearer` / `X-Admin-Token` (tenant create/delete/rotate, snapshots, work-item import, `/demo/*`, `/bench/run`) |
| `TENANT_KEYS_REQUIRED` | `false` | every `/tenants/{t}/...` route needs the tenant's `X-API-Key` (`?api_key=` for `/events` and `/audio` only) |
| `CORS_ORIGINS` | `http://localhost:3001` | in development any localhost origin is also allowed |
| `MAX_IMPORT_BYTES` / `MAX_SNAPSHOTS_PER_TENANT` | 10 MB / 10 | 413 / 409 beyond |
| `GEMINI_TPM_BUDGET` / `AGENT_TASK_DEADLINE_S` | `14000` / `300` | shared input-token budget per minute (requests queue up to 20 s, then 503 `llm_rate_limited`); wall clock per agent task |
| `STRICT_HEALTH` / `STARTUP_RETRY_S` | `false` / `15` | fold llm and worker liveness into `/health` ok; DB reconnect interval when FalkorDB is down at boot |
| `LIVE_EVENT_MAX_AGE_DAYS` | `14` | older `fact.superseded` events are historical imports and do not wake the Scheduler |
| `DATA_DIR` | `data` | `meetings/`, `gold/`, rosters; audio under `data/meetings` |
| `SEED_TENANTS` | `orbit,nimbus,quill` | tenants whose schema is ensured on startup (`AUTO_CREATE_TENANTS=true` creates missing ones) |
| `WORKERS_ENABLED` / `WORKER_POLL_S` | `true` / `15` | agent workers in the API process; they wake on task events, the poll is a fallback |
| `TASK_LEASE_MS` / `WORKER_HEARTBEAT_S` / `REAPER_INTERVAL_S` / `WORKER_TOUCH_S` | `120000` / `30` / `30` / `30` | task lease, heartbeat, reaper cadence and the `Agent.last_seen` write throttle |
| `STANDUP_MIN_MEETINGS` | `2` | meetings with the same title prefix before a Skill is learned |
| `GITHUB_TOKEN` / `GITHUB_DEMO_REPO` | | when both set, `create_issue` opens a real issue; otherwise `simulated: true` |
| `BENCH_RESULTS_DIR` | `docs/bench` | JSON results shown by `GET /bench/results` |

With `LLM_BACKEND=fake` extraction replays `data/gold/<slug>.json`, supersession follows the gold
hints (`supersedes`, `follows_precedent`, `confirms`) and the agents follow a scripted tool policy,
so the model calls run offline (a real FalkorDB service is still needed unless `HIVE_BACKEND=fake`). Gold replay does not measure extraction quality.

`data/seed.py` dispatches each `data/meetings/<tenant>_*.json` on its top-level key (`meeting` or
`thread`), loads `<tenant>_roster.json` first, ignores `data/generator/`, and imports sources in
chronological order (`started_at`) so restatements become confirmations rather than chain links.
`--skip orbit_002` leaves one file out for a live import in the demo; a fact imported later but said
earlier slots into its supersession chain by `valid_from` without changing the current belief (and
without waking the Scheduler).

Authentication is opt-in: an admin token for shared and demo routes and a per-tenant key for tenant routes (see the table). There is no per-person identity inside a tenant. Per-tenant database ACL passwords are derived from `TENANT_RW_PASSWORD` / `TENANT_RO_PASSWORD` (HMAC of the slug), so set those to random values in a deployment. Database ACL probes demonstrate isolation; the HTTP boundary is the key. Use synthetic data.

## Routes

The full route list, error codes, headers and auth rules are in `docs/contracts/http-api.md`. Errors are `{"error": {"code", "message"}}` (500s add `request_id`, rate limits add `retry_after`). Timestamps are epoch milliseconds.

Tenants
- `GET /tenants` - `[{slug, display_name, graph, usage_mb, counts, acl: {rw_user, ro_user, rules}}]`
- `POST /tenants` `{slug, display_name}` - full tenant object (201)
- `GET /tenants/{t}` - one tenant
- `GET /tenants/{t}/acl-probe?target=` - `{allowed: false, error, user, target_graph, command}`

Sources
- `GET /tenants/{t}/meetings` - `[{id, title, started_at, ended_at, source_uri, episodes, facts, status}]`
- `POST /tenants/{t}/meetings/import` (recorder export JSON) - `{meeting_id, job_id}` (202)
- `GET /tenants/{t}/jobs/{job_id}` - `{status, stage, progress, stats: {episodes, entities, facts, decisions, commitments, superseded, ...}, error?}`
- `GET /tenants/{t}/meetings/{id}`, `GET /tenants/{t}/meetings/{id}/episodes`, `GET /tenants/{t}/meetings/{id}/audio` (404 without a file)
- `POST /tenants/{t}/email/import` (thread JSON, or multipart `file` = `.eml`/`.mbox`) - `{thread_id, job_id}`
- `GET /tenants/{t}/threads` - `[{id, subject, started_at, messages, facts, status}]`
- `GET /tenants/{t}/threads/{id}`, `GET /tenants/{t}/threads/{id}/messages` - `[{id, seq, sender: {id,name,email}, to, cc, sent_at, text, in_reply_to}]`

Memory
- `GET /tenants/{t}/facts?status=active|superseded|retracted|all&entity=&kind=` - facts with `speaker`, `meeting`/`thread`, `episode_id`, `due_at`, `source`, `supersedes`
- `GET /tenants/{t}/facts/{id}`
- `GET /tenants/{t}/why/{node_id}` - `{node, speaker, meeting, thread, episode, source, history, supersedes, superseded_by, cypher, subgraph}`
- `GET /tenants/{t}/belief?t=&entity=` - `{t, facts, cypher}`
- `GET /tenants/{t}/timeline` - `{events: [{t, type: meeting|email|fact.created|fact.superseded|decision|commitment, id, text}], snapshots}`
- `POST /tenants/{t}/snapshots` `{label}` - `{name, taken_at, label}`; `GET /tenants/{t}/snapshots`
- `GET /tenants/{t}/analytics/who-knows?entity=`, `.../open-commitments?person=`, `.../contradictions`, `.../clusters`, `.../stale-decisions?older_than_days=`
- `GET /tenants/{t}/entities`

Decision impact
- `POST /tenants/{t}/work-items/import` - validated explicit dependency manifest; returns `{imported, document_id}`
- `GET /tenants/{t}/impact` - `{summary, items, cypher}` with original/current facts, owner, dependency document and actual graph paths
- `POST /tenants/{t}/impact/{work_id}/draft` `{current_fact_id}` - idempotent local draft; 409 if the graph changed or work cannot be reviewed
- `GET /tenants/{t}/impact/drafts` - persisted local draft history

See [the contract and limitations](../../docs/decision-impact.md). These routes never contact an external service.

Chat
- `POST /tenants/{t}/chat` `{message, session_id?}` - `{answer, session_id, router: {intent, entities, route, template}, cypher: [..], subgraph, sources: [{fact_id, kind, speaker, meeting?, thread?, t_start?, sent_at?, message_id?, container_id}], model, latency_ms}`
- `GET /tenants/{t}/chat/{session_id}` - `[{role, text, t, response?}]`
- Prefix a message with `cypher:` (or start with `MATCH`) for the read-only free-form route (ro user, 3 s timeout, write clauses rejected).

Board
- `GET /tenants/{t}/agents`, `GET /tenants/{t}/tasks?status=`, `POST /tenants/{t}/tasks` `{kind, payload, requires, about_ids?}`
- `GET /tenants/{t}/tasks/{id}`, `GET /tenants/{t}/tasks/{id}/trace` - `{task, events: [{t, type: submitted|claimed|handed_off|artifact|skill_used|completed|failed|input_required, agent, ...}]}`
- `POST /tenants/{t}/demo/supersede` `{fact_id?, new_object, speaker_id?}` - without `fact_id` targets the active `PayU integration | due` commitment; returns `{old_fact_id, new_fact_id}`; the Scheduler wakes, hands off to FollowUp, which files a (simulated) GitHub issue
- `POST /tenants/{t}/demo/double-claim` `{task_id?}` - 25 concurrent CAS claims: `{winners: 1, losers: 24, task_id, winner_agent}`
- `GET /tenants/{t}/events` - SSE, each `data:` line is `{event, payload, ts}`; `?replay=N` re-sends the last N events, `?limit=N` closes after N (tests)

Skills
- `GET /tenants/{t}/skills` - `[{id, goal, version, runs, success_rate, status, steps, learned_from, pagerank}]`
- `POST /tenants/{t}/skills/{id}/outcome` `{ok, agent_id?, task_id?}`
- `POST /tenants/{t}/skills/run` `{goal}` - `{task_id}` (StandupAgent retrieves and runs the Skill)

Bench and health
- `GET /bench/results`, `POST /bench/run` `{agents, tenants, duration_s}` - `{run_id}`
- `GET /health` - `{ok, falkordb: {version, graphs}, llm: {backend, model}, embeddings: {model, dim}}`

## Agents

| Agent | Capability | Task kinds | Tools |
|---|---|---|---|
| FactAgent | `extract` | `extract_episode`, `record_fact` | recall, active_facts, write_fact, finish |
| FollowUpAgent | `followup` | `followup`, `nudge`, `reschedule` (after hand-off) | recall, why, open_commitments, active_facts, create_issue, finish |
| SchedulerAgent | `schedule` | `reschedule` (wakes on `fact.superseded` with a date predicate) | why, active_facts, open_commitments, update_commitment, submit_task, hand_off, finish |
| StandupAgent | `standup` | `learn_standup`, `run_skill` | open_commitments, active_facts, stale_decisions, recall, retrieve_skill, learn_skill, finish |
| AnswerAgent | `answer` | `question` (and `POST /chat`) | router + recall / graph / templates / read-only Cypher |

Workflow tasks submitted by an agent for another agent (`reschedule`) carry `requires: []` and are
claimed immediately by the submitter, because `next_open_task` only returns tasks whose REQUIRES
is a subset of the agent's capabilities and a hand-off keeps the original REQUIRES. Workers only
claim task kinds they handle or tasks addressed to them.
