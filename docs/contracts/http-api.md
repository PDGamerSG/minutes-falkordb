# Contract: HTTP API (`apps/api`, FastAPI) consumed by `apps/web`

Base URL: `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). JSON everywhere. Errors: `{"error": {"code": str, "message": str}}` with 4xx/5xx. All timestamps epoch ms. `tenant` is a team slug (`orbit`, `nimbus`, `quill` in the seed).

## Tenants
- `GET /tenants` → `[{slug, display_name, graph, usage_mb, nodes, edges, counts: {episodes, facts, decisions, commitments, tasks, skills}, acl: {rw_user, ro_user, rules: [str]}}]`
  - `nodes` / `edges` (int): total nodes and edges in the tenant graph, counted with read-only Cypher (`MATCH (n) RETURN count(n)`, `MATCH ()-[r]->() RETURN count(r)`). This is the size signal the UI shows ("N nodes · M edges").
  - `usage_mb` (float): `GRAPH.MEMORY USAGE` total. FalkorDB 6.0.1 reports 0 for every field, so clients show MB only when `usage_mb > 0`.
  - The same tenant object (with `nodes`/`edges`) is returned by `POST /tenants` and `GET /tenants/{tenant}`.
- `POST /tenants` `{slug, display_name}` → tenant object
- `GET /tenants/{tenant}/acl-probe?target={other_tenant}` → `{allowed: false, error: "..."}` (demonstrates isolation: attempts to read another tenant's graph with this tenant's ro user)

## Meetings and ingestion
- `GET /tenants/{tenant}/meetings` → `[{id, title, started_at, ended_at, source_uri, episodes, facts, status}]`
- `POST /tenants/{tenant}/meetings/import` body = recorder export JSON (see recorder-format.md) → `{meeting_id, job_id}`
- `GET /tenants/{tenant}/jobs/{job_id}` → `{status: "queued"|"running"|"done"|"failed", stage, progress: 0..1, stats: {episodes, entities, facts, decisions, commitments, superseded}, error?}`
- `GET /tenants/{tenant}/meetings/{id}/episodes` → `[{id, seq, speaker: {id, name}, text, t_start, t_end, t_occurred}]`
- `GET /tenants/{tenant}/meetings/{id}/audio` → audio file if present (source_uri under data/meetings), else 404

## Memory
- `GET /tenants/{tenant}/facts?status=active&entity=...&kind=fact|decision|commitment` → `[{id, kind, subject, predicate, object, text, confidence, valid_from, valid_to, status, speaker: {id,name}, meeting: {id,title}, episode_id, due_at?}]`
- `GET /tenants/{tenant}/why/{node_id}` → `{node, speaker, meeting, episode: {id, text, t_start, t_end}, history: [...], cypher, subgraph: {nodes: [{id, label, props}], edges: [{source, target, type, props}]}}`
- `GET /tenants/{tenant}/belief?t={ms}&entity={id?}` → `{t, facts: [...], cypher}`
- `GET /tenants/{tenant}/timeline` → `{events: [{t, type: "fact.created"|"fact.superseded"|"decision"|"commitment"|"meeting", id, text}], snapshots: [{name, taken_at, label}]}`
- `POST /tenants/{tenant}/snapshots` `{label}` → `{name, taken_at}`
- `GET /tenants/{tenant}/analytics/who-knows?entity=...` → `[{person: {id,name}, mentions, last_at}]`
- `GET /tenants/{tenant}/analytics/open-commitments?person=...` → `[...]`
- `GET /tenants/{tenant}/analytics/contradictions` → `[{key, facts: [a, b]}]`
- `GET /tenants/{tenant}/analytics/clusters` → `[{component, entities: [...]}]`

## Chat (AnswerAgent)
- `POST /tenants/{tenant}/chat` `{message, session_id?}` → `{answer, session_id, router: {intent, entities: [str], route: "vector"|"graph"|"template"|"freeform_ro", template?: str}, cypher: [str], subgraph: {nodes, edges}, sources: [{fact_id, speaker, meeting, t_start}], episodes: [{episode_id, kind, speaker, container_id, meeting|thread, t_start|sent_at, text, t, score}], model, latency_ms}`. `episodes` are the raw utterances and emails retrieved by episode recall (vector KNN plus full-text, fused by reciprocal rank) and shown to the model as evidence; the Why subgraph includes them.
- `GET /tenants/{tenant}/chat/{session_id}` → prior turns (stored as Episode-like `Turn` nodes in the tenant graph; persistent conversation history)

## Board (coordination)
- `GET /tenants/{tenant}/agents` → `[{id, name, model, capabilities: [str], last_seen, state: "idle"|"working"}]`
- `GET /tenants/{tenant}/tasks?status=` → `[{id, kind, status, version, owner_agent, priority, created_at, updated_at, payload, about: [ids]}]`
- `GET /tenants/{tenant}/tasks/{id}/trace` → `{task, events: [{t, type: "claimed"|"handed_off"|"completed"|"failed"|"input_required"|"skill_used", agent, summary?, subgraph_ids?, artifact?}]}`
- `POST /tenants/{tenant}/tasks` `{kind, payload, requires: [str], about_ids?}` → task
- `POST /tenants/{tenant}/demo/supersede` `{fact_id?, new_object, speaker_id?}` → runs the "move it to Friday" path: supersedes the fact, publishes event, Scheduler wakes. Returns `{old_fact_id, new_fact_id}`
- `POST /tenants/{tenant}/demo/double-claim` `{task_id?}` → launches 25 concurrent claims on one task; returns `{winners: 1, losers: 24, task_id, winner_agent}`
- `GET /tenants/{tenant}/events` → **SSE** stream of `{event, payload, ts}` from Redis pub/sub

## Skills (procedural memory)
- `GET /tenants/{tenant}/skills` → `[{id, goal, version, runs, success_rate, status, steps: [{order, tool, args_template, guard}], learned_from: [ids], pagerank}]`
- `POST /tenants/{tenant}/skills/{id}/outcome` `{ok: bool, agent_id?}` → updated skill
- `POST /tenants/{tenant}/skills/run` `{goal}` → `{task_id}` (StandupAgent retrieves and runs the skill)

## Bench
- `GET /bench/results` → `[{run_id, ts, engine: "6.0.1"|"4.22.0", target: "local"|"railway", agents, tenants, duration_s, read_p50, read_p95, read_p99, write_p50, write_p95, write_p99, errors, cas: {attempts, winners, losers}}]`
- `POST /bench/run` `{agents, tenants, duration_s}` → `{run_id}` (runs the harness in-process against the configured DB; dev only)

## Health
- `GET /health` → `{ok, falkordb: {version, graphs}, llm: {backend, model}, embeddings: {model, dim}}`
