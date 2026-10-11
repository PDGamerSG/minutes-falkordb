# Backend review 3: API, agents, LLM client, operations (2026-10-12, read-only)

Scope: `apps/api/**` and the `hiveboard` seams it uses, plus `hiveboard/mcp_server.py`. Evidence from code, the live API on 8080 (reads and 5 chat calls) and a scratch API on 8095 against FalkorDB 6383. Baseline: 109 API tests pass.

## 1. Contract conformance

Shapes in `docs/contracts/http-api.md` and the email delta match; the code returns supersets. `status=all` works; job states are queued, running, done, failed; SSE frames carry a `connected` frame, keep-alives every 15 s and replay up to 200; health returns 503 on ping failure or a startup error.

1.1 **MEDIUM. Unknown routes and 405s bypass the error envelope.** `errors.py:257-260` handles `fastapi.HTTPException` only; Starlette's router raises the parent class. `GET /nope` returns `{"detail": "Not Found"}`. Fix: register the handler for `starlette.exceptions.HTTPException`.
1.2 **MEDIUM. `GET /facts` has no pagination and silently caps at 500.** `hive_adapter.py:1062-1075`. Timeline, belief and impact all build on `list_facts(status="all")`, so a tenant with more than 500 facts gets wrong timelines and impact evidence with no signal. Fix: `limit` and cursor, plus a `truncated` flag.
1.3 **MEDIUM. Free-form Cypher results never reach the caller.** `answer_agent.py:296-305` keeps only fact-shaped rows; other rows go only into the model prompt. `MATCH (p:Person) RETURN p.name, p.role` produced a non-answer after a wasted model call. Fix: return capped, embedding-stripped `rows` and tabulate them for freeform intent without a model call.
1.4 **LOW. `GET /tasks?status=bogus` returns 200 and an empty list.** `routes/board.py:373-376`. Fix: validate against the task states.
1.5 **LOW. Undocumented routes** (facts/{id}, snapshots list, entities, stale-decisions, tasks/{id}, skills/{id}, meetings/{id}, threads/{id}) and trace event types `submitted` and `artifact` missing from the contract enum. Fix: one pass over the contract.
1.6 **LOW. Validation errors echo Python reprs including the submitted input.** `errors.py:264`.
1.7 **INFO. The teammates' impact routes are graph-backed and sound.** `routes/impact.py` -> `hiveboard/impact.py` -> Cypher 80 to 83; assessment logic is Python over graph rows, traversal is Cypher, `cypher` is returned for the Why panel. Demo-state issue: on the live database `GET /tenants/orbit/impact` returns `tracked: 0` because `data/seed_work.py --tenants orbit` has not been run against 6379. Run it before recording (it is additive).

## 2. Security

2.1 **CRITICAL. No authentication or tenant membership on any route.** Every handler takes `tenant` from the path and checks existence only (`state.py:330-335`); all access uses the admin connection. Fix, smallest useful: a hashed per-tenant API key on the Tenant node in commons, a `require_tenant(tenant, x_api_key)` dependency on every `/tenants/{tenant}` router, and an admin token for `POST /tenants`, `/demo/*`, `/bench/run`, `/snapshots`, `/work-items/import`.
2.2 **HIGH. Unauthenticated state-mutating demo and admin endpoints pollute or exhaust the shared database.** `POST /tenants` on an existing slug returns 201 and resets both ACL passwords and the display name; slugs containing `__snap_` create ghost tenants hidden from the list but with workers started; `POST /demo/double-claim` registers 25 permanent agents per call; `POST /bench/run` registers agents and submits about 60 tasks per second of run (they become the "newest 50" on the board); `POST /snapshots` copies the whole graph per call with no quota. Fix: gate behind the admin token or `DEMO_ENDPOINTS_ENABLED=false`; cap snapshots; reject `__snap_` slugs.
2.3 **MEDIUM. No request body size limit on import routes; multipart type inferred, not checked.** A 31 MB export was fully read and parsed before rejection. Fix: `MAX_IMPORT_BYTES` (about 10 MB) with a 413 envelope; whitelist content types.
2.4 **MEDIUM. Chat history of every user is readable by anyone in the tenant, including through free-form Cypher.** Turn nodes carry the full response JSON; `GET /chat/{session_id}` accepts any id; `MATCH (t:Turn) RETURN t.text` is a valid read-only query. Fix: stamp `Turn.user_id` once auth exists; exclude Turn and ChatSession from the free-form path.
2.5 **MEDIUM. Tenant ACL users can read the whole registry; rw users can write commons.** Same as substrate finding 15. Cross-tenant graph reads are correctly denied.
2.6 **LOW. Free-form Cypher guard: no bypass found.** Writes, `CALL { CREATE }`, index creation and `GRAPH.QUERY` as the ro user are all refused; a Cartesian product times out at 3 s. Edges: the write-keyword regex ignores strings and comments (false positives on `CONTAINS 'create'`); `LOAD CSV` is routed to vector search rather than rejected; `RETURN n LIMIT 100000` pulls embeddings into the API process before discarding. Fix: run the keyword check on the stripped text; inject `LIMIT 200` when absent.
2.7 **LOW. 500 handler leaks exception text; `/health` leaks a local file path.**
2.8 **LOW. CORS regex admits any localhost origin;** acceptable in dev, make it dev-only.
2.9 **LOW. Simulated issues get real-looking GitHub URLs** into someone else's namespace. Fix: `minutes://simulated/issue/<id>` or null.

Verified safe: audio path traversal, no SSRF surface, ACL rules masked, `.env` ignored by git and docker.

## 3. Agents and workers

3.1 **HIGH. Tasks stuck in `working` forever after a crash or restart; no lease, no reaper.** Nothing flips working back; `_mine` only considers submitted tasks; a worker killed mid-LLM-call leaves the task invisible to every worker. Fix: `lease_until` on claim, a periodic reaper that returns expired leases to submitted with a version bump, heartbeat from the running worker.
3.2 **MEDIUM. Historical imports or seeding with workers running fan out into reschedule tasks and simulated issues.** Every supersession publishes `fact.superseded`, and the worker treats any date-predicate supersession as live. Evidence: two extra reschedule tasks appeared during a concurrent seed. Fix: ignore events whose new `valid_from` is older than N days unless flagged live; document "stop the API before `seed.py --reset`".
3.3 **MEDIUM. Scheduler and FollowUp both handle `reschedule`; the Scheduler can lose its own claim.** When FollowUp wins, the trace has no handoff edge and the commitment date is never updated, so the demo story breaks nondeterministically. Fix: submit the reschedule task with `requires: ["schedule"]` or `owner_agent = scheduler_agent`, and remove `reschedule` from FollowUp's handled kinds.
3.4 **MEDIUM. The event pump re-subscribes every 2 s and can drop events in the gap.** `hive_adapter.py:1158-1173`, `events.py:99-113`. A `fact.superseded` published in that window is lost and polling does not recover it. Fix: one long-lived pubsub with a stop check between `get_message` calls.
3.5 **LOW. Real-backend handoff summaries say "moved from ? to Friday"** because the substrate payload lacks `old_object`. Visible in the demo trace. Fix: include `old_object` in the substrate event.
3.6 **LOW. Every worker writes `last_seen` every 2 s poll** (2.5 writes per second per tenant of churn). Fix: touch at most every 30 s; poll every 15 to 30 s and wake on events.
3.7 **LOW. Unbounded in-process growth** (`processed` lists, job store, bench results). Fix: bounded deques or TTL.
3.8 **LOW. `retrieve_skill` ranks by success rate before similarity**, so a new skill at 0.0 loses to any unrelated skill with one success. Fix: combine similarity and success rate.
3.9 **LOW. Blocking DB and CPU calls inside `async def` handlers** (chat, double-claim, meeting import parsing a 30 MB body on the loop). Fix: sync `def` routes or `asyncio.to_thread`.

Verified good: tool loop terminates; args validated; Standup learning idempotent; success rate is a correct running mean; chat turns are graph nodes; LLM failures return a grounded fallback, never a 500; shared ONNX and genai clients are used thread-safely.

## 4. LLM client

4.1 **MEDIUM. Key rotation cannot help with the shared 16k tokens-per-minute limit, and the backoff can stall a request about 90 s.** Fix: a process-wide token bucket so requests queue instead of burning retries; surface `retry_after`.
4.2 **LOW. No input-token budget.** Measured prompts: belief about 0.9k tokens, why and vector about 2.3k; six questions a minute fit the free tier, concurrent extraction does not.
4.3 **LOW. Timeouts multiply:** 180 s per call times 6 steps lets a worker hold a task for 18 minutes. Fix: a per-task deadline.
4.4 **INFO. Observed latencies on the live stack:** ownership template 133 ms with no model call; belief question 7.2 s; "why did we switch from Razorpay to PayU" 16.7 s with 12 sources, correct chain and rationale; sandbox question 6.5 s, correct.

## 5. Operations

5.1 **HIGH. The container downloads the 300 MB ONNX model on every cold start and has no persistent cache.** `Dockerfile:9` sets `HF_HOME` to an ephemeral layer; startup is strict, so a failed download aborts the API; small plans will OOM or fail the health check. Fix: bake the model into the image or mount a volume; `WORKERS_ENABLED=false` on small plans.
5.2 **MEDIUM. Dockerfile hygiene:** second `uv sync` not frozen; runs as root; `API_HOST` and `API_PORT` settings are dead config.
5.3 **MEDIUM. `/health` says nothing about model or embedder liveness.** Fix: cached probes outside `ok` unless strict.
5.4 **LOW. If FalkorDB is down at boot, the lifespan raises before the try block**, so uvicorn restart-loops instead of serving a 503. `AUTO_CREATE_TENANTS=true` creates the seed tenants on every boot. Fix: move context build inside the try; default auto-create off for deployments.
5.5 **LOW. No request ids or structured latency logs; a worker mid-LLM-call blocks shutdown up to the timeout.**

## 6. Test gaps and flaky risks

- All API tests run on FakeHive; untested on FalkorDB: free-form Cypher path, `_FACT_QUERY`, `get_turns`, `graph_size`, `acl_probe`, the MATCH-WHERE-MATCH guard's effect on the planner, `work_impacts` with more than one active candidate.
- Missing: error envelope on unknown routes; `tasks?status=bogus`; body size limits; `POST /tenants` on an existing or `__snap_` slug; SSE isolation between tenants; replay after reconnect; worker restart with a working task; the Scheduler versus FollowUp race; `GeminiBackend` retry and rotation with a stubbed client; `/health` 503 on startup error.
- Flaky: `test_sse_live_delivery` relies on `sleep(0.3)` and a daemon thread; worker tests use wall-clock waits; the in-process bench test runs a timed loop.

## 7. Feature gaps judges may probe

| # | Gap | Value | Effort |
|---|---|---|---|
| 1 | Per-tenant API key plus admin token on every tenant route | very high | S |
| 2 | MCP over HTTP backed by the API's hive and the real embedder (today stdio-only and `recall` defaults to the fake embedding, so it returns noise against the ONNX-embedded graph) | high | S to M |
| 3 | Task lease and reaper, deterministic Scheduler claim | high | S |
| 4 | A2A-compatible task surface and agent card | medium-high | S |
| 5 | Handoff visualisation data (`GET /tenants/{t}/handoffs`) | medium | S |
| 6 | Consolidation and forgetting with audit (`retract_fact` exists in the substrate with no route) | medium-high | M |
| 7 | Per-tenant export and `DELETE /tenants/{t}` | medium | S |
| 8 | Streaming chat (router, cypher, then answer chunks) | medium | M |
| 9 | Rate and body limits | medium | S |
| 10 | Real GitHub issue path tested end to end | medium | S |
| 11 | OpenAPI quality (typed response models, contract sync) | low-medium | M |
| 12 | Free-form Cypher rows in the response and a rows tab in the Why panel | medium | S |

## Deployment-readiness checklist (blockers first)

1. Auth: at minimum an admin token on mutating endpoints and a per-tenant key on the rest, or deploy with synthetic data and a documented "public playground, resets nightly" note.
2. Embedding model baked into the image or on a volume; never mix embedding spaces between seed and query.
3. Memory: ONNX about 0.6 GB RSS plus 15 workers; `WORKERS_ENABLED=false` or one seed tenant on small plans; `AUTO_CREATE_TENANTS=false`.
4. FalkorDB persistence, `MAX_QUEUED_QUERIES 500`, `TIMEOUT_MAX 10000`, private network only.
5. Seed with the API stopped, then run `data/seed_work.py --tenants orbit` (the live database has 0 work items today).
6. `CORS_ORIGINS` set to the Vercel domain; `NEXT_PUBLIC_API_URL` set; `NEXT_PUBLIC_MOCK` unset.
7. Gemini: both keys share one 16k tokens-per-minute quota; budget the demo to about 5 model calls a minute or use a paid tier; `LLM_TIMEOUT_S` at most 60.
8. Body limits and 413s; snapshot cap.
9. Task lease and reaper so a redeploy mid-demo leaves no stuck tasks.
10. Error envelope on unknown routes; generic 500 text; drop the file path from `/health`.
11. Non-root user and frozen syncs in the Dockerfile; verify a cold container reaches `/health` 200.
12. Smoke script against the deployed URL: health, tenants, impact (tracked 5), two chat calls, events replay, demo supersede trace.
