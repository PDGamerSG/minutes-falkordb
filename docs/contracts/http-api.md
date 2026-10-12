# Contract: HTTP API (`apps/api`, FastAPI) consumed by `apps/web`

Base URL: `NEXT_PUBLIC_API_URL` (default `http://localhost:8080`). JSON everywhere. All timestamps epoch ms. `tenant` is a team slug (`orbit`, `nimbus`, `quill` in the seed). Slugs match `^[a-z0-9][a-z0-9-]{1,40}$` and never contain `__snap_`.

## Conventions

**Errors.** Every failure uses `{"error": {"code": str, "message": str, ...}}`, including unknown routes (404 `not_found`), wrong methods (405 `method_not_allowed`) and request validation (422 `validation_error`, message is `field: reason` pairs only, never the submitted input). Unexpected errors are 500 `internal_error` with a generic message and a `request_id`; the exception text stays in the server log. A model that is rate limited gives 503 `llm_rate_limited` with `retry_after` (seconds) in the envelope and a `Retry-After` header. Other codes: 400 `bad_status` / `bad_kind` / `bad_cursor` / `invalid_slug` / `invalid_json`, 401 `admin_token_required` / `api_key_required`, 403 `admin_token_invalid` / `api_key_invalid`, 404 `tenant_not_found` / `fact_not_found` / `task_not_found` / ..., 409 `tenant_exists` / `snapshot_quota` / `embedding_model_mismatch` / `conflict`, 413 `payload_too_large`, 415 `unsupported_media_type`, 503 `database_unavailable` (FalkorDB unreachable, the API retries in the background).

**Request ids.** Every response carries `X-Request-ID` (the request's own value is echoed, else generated). 500 envelopes repeat it as `error.request_id`.

**Authentication.** Both layers are off in local development (nothing configured, everything open; `/health` reports it under `auth`).
- Admin token (`ADMIN_TOKEN`): required as `Authorization: Bearer <token>` or `X-Admin-Token: <token>` on `POST /tenants`, `DELETE /tenants/{t}`, `POST /tenants/{t}/rotate-key`, `POST /tenants/{t}/snapshots`, `POST /tenants/{t}/work-items/import`, `POST /tenants/{t}/demo/*` and `POST /bench/run`. Missing: 401; wrong: 403.
- Tenant key (`TENANT_KEYS_REQUIRED=true`): every `/tenants/{t}/...` route requires `X-API-Key: <key>` matching that tenant (the admin token is accepted in its place). `GET /tenants` then lists only the tenants the supplied key unlocks. `EventSource` and `<audio>` cannot set headers, so `GET .../events` and `GET .../meetings/{id}/audio` also accept `?api_key=` (no other route does). A key is generated when a tenant is created, returned once in the creation response, logged once by the API and stored only as a sha256 hash. Chat sessions are scoped to the key that created them.
- CORS: development allows `CORS_ORIGINS` and any localhost origin; `ENV=production` allows `CORS_ORIGINS` only. `X-Request-ID`, `X-Next-Cursor`, `X-Truncated` and `Retry-After` are exposed to browsers.

**Limits.** Import bodies are capped at `MAX_IMPORT_BYTES` (default 10 MB): 413 before parsing, content types checked (415). Snapshots are capped at `MAX_SNAPSHOTS_PER_TENANT` (10). Free-form Cypher results return at most 200 rows.

## Tenants
- `GET /tenants` → `[{slug, display_name, graph, usage_mb, nodes, edges, counts: {episodes, facts, decisions, commitments, tasks, skills, ...}, acl: {rw_user, ro_user, rules: [str], isolation?}, has_api_key, embedding_model, embedding_dim}]`
  - `nodes` / `edges` (int): total nodes and edges in the tenant graph, counted with read-only Cypher. This is the size signal the UI shows ("N nodes · M edges").
  - `usage_mb` (float): `GRAPH.MEMORY USAGE` total. FalkorDB 6.0.1 reports 0 for every field, so clients show MB only when `usage_mb > 0`.
  - `embedding_model` / `embedding_dim`: the embedding space recorded for the tenant on its first ingest (`null` before). ACL rules never contain a password or hash.
  - The same object is returned by `GET /tenants/{tenant}`.
- `POST /tenants` `{slug, display_name}` (admin) → 201 tenant object plus `api_key` (shown once). An existing slug is **409 `tenant_exists`** and nothing changes; `?rotate=true` (admin) re-issues the key and refreshes the display name of an existing tenant. Bad slugs (including `__snap_`) are 400 `invalid_slug`.
- `POST /tenants/{tenant}/rotate-key` (admin) → `{slug, api_key}`; the old key stops working immediately.
- `DELETE /tenants/{tenant}` (admin) → 204; stops the tenant's workers and drops its graph, snapshots, ACL users and registry row.
- `GET /tenants/{tenant}/acl-probe?target={other_tenant}` → `{allowed: false, error: "...", user, target_graph, command}` (demonstrates database-level isolation: this tenant's ro user is refused on another tenant's graph; it is not an HTTP boundary, the key above is)

## Meetings and ingestion
- `GET /tenants/{tenant}/meetings` → `[{id, title, started_at, ended_at, source_uri, episodes, facts, status}]`; `GET .../meetings/{id}` → one row.
- `POST /tenants/{tenant}/meetings/import` body = recorder export JSON (see recorder-format.md), `Content-Type: application/json`, ≤ `MAX_IMPORT_BYTES` → 202 `{meeting_id, job_id}`. 409 `embedding_model_mismatch` when the API's embedding model differs from the one the tenant was embedded with. Re-importing a meeting whose episodes changed fails the job with `source_changed`.
- `GET /tenants/{tenant}/jobs/{job_id}` → `{status: "queued"|"running"|"done"|"failed", stage, progress: 0..1, kind, container_id, stats: {episodes, entities, facts, decisions, commitments, superseded, ...}, error?}`. Jobs are kept in a bounded in-memory store (500).
- `GET /tenants/{tenant}/meetings/{id}/episodes` → `[{id, seq, speaker: {id, name}, text, t_start, t_end, t_occurred, source_kind}]`
- `GET /tenants/{tenant}/meetings/{id}/audio` → audio file if present (source_uri under data/meetings), else 404 `audio_not_found`
- `POST /tenants/{tenant}/email/import` body = thread JSON (`application/json`) or multipart field `file` (`.eml`, `.mbox`; content types message/rfc822, application/mbox, text/plain, application/json, application/octet-stream) → 202 `{thread_id, job_id, threads: [{thread_id, job_id}]}`. An `.mbox` with several conversations creates one job per thread; `thread_id` / `job_id` are the first. See email-format.md.
- `GET /tenants/{tenant}/threads` → `[{id, subject, started_at, messages, facts, status}]`; `GET .../threads/{id}` → one row; `GET .../threads/{id}/messages` → `[{id, seq, message_id, sender: {id,name,email}, to: [...], cc: [...], sent_at, text, in_reply_to, source_kind}]`

## Memory
- `GET /tenants/{tenant}/people` → `[{id, name, email?, role?}]`, sorted by case-insensitive name then ID. Used for explicit work-owner selection.
- `GET /tenants/{tenant}/entities` → `[{id, name, type}]`
- `GET /tenants/{tenant}/facts?status=active|superseded|retracted|all&entity=...&kind=fact|decision|commitment&limit=200&cursor=...` → `[{id, kind, subject, predicate, object, text, confidence, valid_from, valid_to, created_at, expired_at, status, speaker: {id,name}, meeting: {id,title}, thread, episode_id, due_at?, entities, source, supersedes, supersedes_ids, precedent_ids}]`, ordered by `(valid_from, id)`. The body stays an array. **Paging headers:** `X-Truncated: true|false` and, when more rows match, `X-Next-Cursor: <opaque>` to pass as `cursor`. `limit` is 1–1000 (default 200). Bad status / kind / cursor are 400. Timeline, belief and impact page through all facts internally, so they never see a silent cap.
- `GET /tenants/{tenant}/facts/{id}` → one fact (404 `fact_not_found`)
- `GET /tenants/{tenant}/why/{node_id}` → `{node, speaker, meeting, thread, episode: {id, text, t_start, t_end, t_occurred}, source, entities, history: [...], supersedes, superseded_by, cypher, subgraph: {nodes: [{id, label, props}], edges: [{source, target, type, props}]}}`
- `GET /tenants/{tenant}/belief?t={ms}&entity={id?}` → `{t, entity, facts: [...], cypher}` (what was believed at `t`, honouring retraction and expiry)
- `GET /tenants/{tenant}/timeline` → `{events: [{t, type: "fact.created"|"fact.superseded"|"decision"|"commitment"|"meeting"|"email", id, text, kind?, status?}], snapshots: [{name, taken_at, label, id}]}`
- `POST /tenants/{tenant}/snapshots` `{label}` (admin) → 201 `{name, taken_at, label, id}`; 409 `snapshot_quota` beyond `MAX_SNAPSHOTS_PER_TENANT`. `GET .../snapshots` lists them.
- `GET /tenants/{tenant}/analytics/who-knows?entity=...` → `[{person: {id,name}, mentions, last_at, via}]`
- `GET /tenants/{tenant}/analytics/open-commitments?person=...` → `[fact + owner]`
- `GET /tenants/{tenant}/analytics/contradictions` → `[{key, facts: [a, b]}]`
- `GET /tenants/{tenant}/analytics/clusters` → `[{component, entities: [...]}]`
- `GET /tenants/{tenant}/analytics/stale-decisions?older_than_days=14` → `[fact + age_ms]`

## Decision impact

- `POST /tenants/{tenant}/work-items/import` (admin) → `{imported, document_id}`. Accepts a versioned dependency document and 1–200 work items with explicit owner and baseline fact IDs. Used by both the seed script and the overview's connect/edit form (which needs the admin token when one is configured).
- `GET /tenants/{tenant}/impact` → `{summary, items, cypher}`. Items include original/current evidence, owner, assessment, dependency document, graph path and a matching local draft.
- `POST /tenants/{tenant}/impact/{work_id}/draft` `{current_fact_id}` → persisted local draft. Repeated creation is idempotent; stale or nonreviewable requests return 409.
- `GET /tenants/{tenant}/impact/drafts` → historical local drafts, including those from earlier dependency versions.

See [decision-impact.md](../decision-impact.md) for complete manifest fields, assessment rules, versioning and result limits.

## Chat (AnswerAgent)
- `POST /tenants/{tenant}/chat` `{message, session_id?}` → `{answer, session_id, router: {intent, entities: [str], route: "vector"|"graph"|"template"|"freeform_ro", template?: str, notes?}, cypher: [str], subgraph: {nodes, edges}, sources: [{fact_id, speaker, meeting, t_start}], episodes: [{episode_id, kind, speaker, container_id, meeting|thread, t_start|sent_at, text, t, score}], rows: [object], model, latency_ms}`. `episodes` are the raw utterances and emails retrieved by episode recall (vector KNN plus full-text, fused by reciprocal rank) and shown to the model as evidence; the Why subgraph includes them.
  - **Free-form Cypher** (`cypher: MATCH ...` or a message that starts with `MATCH`/`RETURN`/...): runs as the tenant's read-only user with a 3 s timeout. `LIMIT 200` is appended when the query has none. The write-keyword check ignores strings, comments and backtick names. `LOAD CSV`, writes and any mention of the `Turn` / `ChatSession` labels (chat history) are refused with an explanatory answer. The result rows (embeddings stripped, at most 200) come back in `rows` and `answer` is a table of them; no model call is made. For every other route `rows` is `[]`.
  - A model that is rate limited returns 503 `llm_rate_limited` with `retry_after`; failures of the model otherwise degrade to a grounded answer from the retrieved facts.
- `GET /tenants/{tenant}/chat/{session_id}` → prior turns (stored as `Turn` nodes in the tenant graph; persistent conversation history). With tenant keys required only the key that created the session can read it; other keys get `[]`.

## Board (coordination)
- `GET /tenants/{tenant}/agents` → `[{id, name, model, capabilities: [str], last_seen, state: "idle"|"working"}]` (`last_seen` is refreshed at most every 30 s per agent)
- `GET /tenants/{tenant}/tasks?status=submitted|working|input_required|completed|failed|all&limit=50&include_bench=false` → `[{id, kind, status, version, owner_agent, priority, created_at, updated_at, lease_until, payload, about: [ids], requires: [str], failure_reason, question}]`. An unknown status is 400 `bad_status`. Tasks created by `POST /bench/run` (kind `bench*`) are hidden unless `include_bench=true`.
- `GET /tenants/{tenant}/tasks/{id}` → task; `GET .../tasks/{id}/trace` → `{task, events: [{t, type: "submitted"|"claimed"|"handed_off"|"lease_expired"|"artifact"|"skill_used"|"completed"|"failed"|"input_required", agent, to_agent?, summary?, subgraph_ids?, artifact?, reason?, question?}], about, cypher}`
- `POST /tenants/{tenant}/tasks` `{kind, payload, requires: [str], about_ids?, priority?}` → 201 task
- **Leases.** A claim carries a lease (`TASK_LEASE_MS`, default 120 s). The running worker extends it every `WORKER_HEARTBEAT_S` (30 s); a reaper (every `REAPER_INTERVAL_S`, 30 s) returns working tasks whose lease lapsed to `submitted` (version + 1, owner cleared, `lease_expired` in the trace, `task.lease_expired` event). A worker killed mid-task therefore never strands a task.
- `POST /tenants/{tenant}/demo/supersede` `{fact_id?, new_object, speaker_id?}` (admin) → runs the "move it to Friday" path: supersedes the fact, publishes a live `fact.superseded` event, the Scheduler (the only agent with the `schedule` capability) claims the reschedule task and hands it to the FollowUp agent. Returns `{old_fact_id, new_fact_id, subject, old_object, new_object, due_at}`
- `POST /tenants/{tenant}/demo/double-claim` `{task_id?}` (admin) → launches 25 concurrent claims on one task (25 fixed `demo_claimer_NN` agents, registered once); returns `{winners: 1, losers: 24, task_id, winner_agent, attempts, errors}`
- `GET /tenants/{tenant}/events?replay=0&limit=` → **SSE** stream of `{event, payload, ts}` from one long-lived Redis subscription; first frame is `connected`, keep-alive every 15 s, `replay` (≤ 200) re-sends the last events seen by the process, `limit` closes after N events (0 = right after `connected`). Supersessions older than `LIVE_EVENT_MAX_AGE_DAYS` (14) are historical imports: they stream to clients but do not wake the Scheduler unless the payload says `live: true`.

## Skills (procedural memory)
- `GET /tenants/{tenant}/skills` → `[{id, goal, version, runs, success_rate, status, steps: [{order, tool, args_template, guard}], learned_from: [ids], pagerank, created_at}]`; `GET .../skills/{id}` → one skill
- `POST /tenants/{tenant}/skills/{id}/outcome` `{ok: bool, agent_id?, task_id?}` → updated skill
- `POST /tenants/{tenant}/skills/run` `{goal}` → 202 `{task_id}` (StandupAgent retrieves and runs the skill; retrieval ranks similarity first with success rate as a boost)

## Bench
- `GET /bench/results` → `[{run_id, ts, engine: "6.0.1"|"4.22.0", target: "local"|"railway", agents, tenants, duration_s, read_p50, read_p95, read_p99, write_p50, write_p95, write_p99, errors, cas: {attempts, winners, losers}}]`
- `POST /bench/run` `{agents, tenants, duration_s}` (admin) → 202 `{run_id}` (runs the harness in-process against the configured DB; dev only; its tasks are tagged `bench*` and hidden from the board). In-process results keep the last 100 runs.

## Health
- `GET /health` → 200 or 503 `{ok, falkordb: {version, graphs, kind}, llm: {backend, model, native_tools, reachable, error?}, embeddings: {model, dim, backend}, workers: {alive, expected, enabled, agents: [{tenant, agent, processed, skipped_historical, stopped}]}, auth: {admin_token: bool, tenant_keys_required: bool}, env, started_at, embedding_mismatch?, error?}`.
  - `ok` is false (503) when the database does not answer, startup preparation failed, or a tenant's embedding model differs from the API's. FalkorDB being down at boot does not stop the process: it serves 503 here and `database_unavailable` elsewhere and reconnects every `STARTUP_RETRY_S`.
  - `llm.reachable` comes from a cheap metadata probe cached for 60 s (no generation, no quota); `workers.alive` counts running worker and reaper coroutines. Both only affect `ok` when `STRICT_HEALTH=true`.
  - No file paths are reported.
