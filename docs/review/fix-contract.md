# Fix contract between the substrate, ingest and API streams (2026-10-12)

Priority 0 and priority 1 items from `docs/review/README.md` are being fixed in three streams with disjoint file ownership. This file is the agreed interface. Code against it; mirror every substrate function in the API's `FakeHive` and ingest's `MemoryHive`.

## Substrate (`packages/hiveboard`, `cypher/`)

- `memory.insert_fact_in_chain(db, tenant, fact, before_id) -> {"id", "inserted", "confirmed", "before_id"}`: atomic mid-chain insertion in one Cypher statement; refuses self-supersede and confirms instead (`confirmed=True`) when an identical fact (same key, normalised object) already exists or the id would equal `before_id`.
- `memory.remember_fact(..., supersede=...)`: lookup, ingest and supersede in one Cypher statement; return `{id, superseded, conflicts, existing}`; object comparison case-insensitive and trimmed; `11_ingest_fact` uses `ON CREATE SET` for identity and bi-temporal fields.
- `memory.supersede_fact` raises `hiveboard.errors.Conflict` when nothing was superseded, when `new.valid_from < old.valid_from`, or when keys differ.
- `board.claim(db, tenant, task_id, agent_id, expected_version, lease_ms=120000)` sets `lease_until`; claim requires the task unaddressed or addressed to the agent.
- `board.heartbeat(db, tenant, task_id, agent_id, lease_ms=120000) -> bool`; `board.reap_expired(db, tenant, now=None) -> list[str]` returns expired working tasks to submitted, version + 1, `owner_agent = NULL`, writes a `LEASE_EXPIRED {at}` edge.
- `handoff` requires `status = 'working'` and the owner; `set_task_state` requires working or input_required and the owner; `next_open_task` orders by priority desc then created_at asc and returns only unaddressed tasks or tasks addressed to the agent.
- Tenancy: rw users are read-only on `commons` via ACL selectors; `create_tenant(db, slug, name, pw_rw=None, pw_ro=None, rotate=False)` does not reset passwords for an existing tenant unless `rotate=True` and generates per-tenant secrets when none are given; `ensure_tenant_access(db, slug, rw_pw, ro_pw)`; `set_tenant_meta(db, slug, meta)` and `get_tenant_meta(db, slug) -> dict` on the Tenant node in commons.
- `HiveDB.graph_name` rejects slugs not matching `^[a-z0-9][a-z0-9-]{1,40}$` and anything containing `__snap_` (ValueError). `HiveDB.ro()` logs once per tenant when it falls back to admin. Socket timeouts `connect 2 s, socket 10 s, health check 30 s`; `ping()` returns False when the server is down.
- `belief_at(t, known_by)` honours `expired_at` and retraction time.
- Event `fact.superseded` payload: `{new_fact_id, new_id, old_fact_id, old_fact_ids, old_ids, key, subject, predicate, kind, old_object, new_object, object, valid_from, due_at, episode_id, speaker_id, head_changed, tenant}`; `head_changed` false for chain insertion; no `fact.created` or `commitment.created` for facts born superseded. `episode.ingested` once per batch. Schema documented in `packages/hiveboard/hiveboard/EVENTS.md`.
- Entities MERGE on `name_key = toLower(trim(name))`; embeddings validated at 768 dimensions; hot reads project without embeddings; `limit` params (default 500) on unbounded reads; `why()` returns all DERIVED_FROM episodes; out-of-order episode batches keep one linear NEXT chain.

## Ingest (`packages/ingest`, `data/seed.py`, `data/seed_work.py`, `docs/eval`)

- Fact ids: `fact_<episode_id>_<sha1(key|normalized object)[:8]>`.
- Hive protocol additions that the API's `RealHive` must implement: `insert_fact_in_chain(tenant, fact, before_id)` (passthrough), `container_episodes(tenant, container_id) -> list[{id, seq, t_start, t_end, speaker_id, text_hash}]` (read-only Cypher), `set_tenant_meta(tenant, meta)`, `get_tenant_meta(tenant) -> dict`.
- A changed source (different episode set for an existing container) fails with error code `source_changed`.
- `thread_from_mbox` returns a list of threads; `routes/email.py` iterates it.
- Tenant meta keys for the embedding guard: `embedding_model` (`"<backend>:<model>"`) and `embedding_dim` (768).
- The pipeline does not publish `episode.ingested` per episode and does not duplicate fact events when `hive.publishes_memory_events` is true.

## API (`apps/api`, `apps/web/lib/api.ts`, `apps/web/.env.example`, `docs/contracts/http-api.md`, `infra/README.md`, `docker-compose.yml`, `.env.example`)

- Auth: `ADMIN_TOKEN` on mutating admin and demo routes; per-tenant keys when `TENANT_KEYS_REQUIRED=true`, header `X-API-Key` (and `?key=` for SSE).
- Workers: claim with leases, heartbeat every 30 s, reaper every 30 s; Scheduler addresses its reschedule task to itself, FollowUp no longer handles `reschedule`; one long-lived pubsub; historical supersessions older than `LIVE_EVENT_MAX_AGE_DAYS` (14) ignored unless `live: true`.

## Rules for every stream

No git commands. No AI-assistant product names anywhere in code, comments, docs, prompts or test data. Keep all storage on drive D. Never touch the demo database on 6379; use the scratch FalkorDB on 6383.
