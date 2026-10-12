# hiveboard

The substrate of **Minutes**: a shared, time-aware memory for agent teams on FalkorDB. Episodic memory (meeting
utterances and email messages as `Episode` nodes with `NEXT`/`REPLIES_TO` chains), semantic memory (bi-temporal
`Fact`/`Decision`/`Commitment` nodes with `SUPERSEDES` chains, `belief_at(T)` and `why()` provenance), a coordination
board (A2A-shaped `Task` states, compare-and-set `claim`, `handoff` with subgraph references), procedural memory
(`Skill` + `Step`, success rates, PageRank) and Track-3 analytics (who knows X, open commitments, contradictions, WCC clusters).

**Graph per tenant.** Every team gets its own FalkorDB graph `team_<slug>` (slug `^[a-z0-9][a-z0-9-]{1,40}$`, never
containing `__snap_`; anything else raises `ValueError` in `HiveDB.graph_name`) plus two ACL users. `team_<slug>_rw` reads and
writes its own graph and can only READ `commons`, through an ACL selector:

```
ACL SETUSER team_x_rw reset on >pw +INFO +PING +CLIENT|SETINFO +GRAPH.RO_QUERY +GRAPH.EXPLAIN +GRAPH.QUERY +GRAPH.PROFILE
    ~team_x resetchannels (+GRAPH.RO_QUERY +GRAPH.EXPLAIN ~commons)
```

`team_<slug>_ro` has only `+GRAPH.RO_QUERY +GRAPH.EXPLAIN` on `~team_<slug> ~commons`. (On FalkorDB 6.0.1 the `%R~` read-only key
selector rejects even `GRAPH.RO_QUERY`, so read-only is enforced per command and per graph.) Commons writes (registry rows,
snapshot metadata, published skills, tenant metadata) always use the admin handle. `create_tenant` generates a fresh secret per
user and returns it once under `credentials`; calling it again for an existing tenant never touches passwords unless
`rotate=True`. `ensure_tenant_access` re-applies the rules without resetting anything. `HiveDB.ro()` uses the tenant's ro user
once its password is known (`create_tenant`, `ensure_tenant_access` or `configure_ro`) and otherwise logs one warning per tenant
and falls back to the admin connection. Sockets time out (connect 2 s, socket 10 s, health check 30 s); `ping()` returns `False`
instead of raising.

A shared `commons` graph holds the tenant registry (plus per-tenant metadata via `set_tenant_meta` / `get_tenant_meta`, e.g. the
embedding model that produced a tenant's vectors), snapshot metadata (`GRAPH.COPY`) and skills published across teams.
Every query lives in the repo's `cypher/NN_name.cypher` files and is loaded by name (`hiveboard.queries.load_cypher`);
user-facing reads run through `ro_query` with a 3 s timeout and return their Cypher text (`result["cypher"]` or
`rows.cypher` on list results). Ranking uses the `hive.score` UDF in `hiveboard/udf/score.js` (recency x importance x similarity).

**Atomic writes.** `remember_fact`, `supersede_fact` and `insert_fact_in_chain` are each ONE Cypher statement, so FalkorDB's
per-graph write serialisation keeps "one active fact per key" true under concurrent writers. `insert_fact_in_chain` imports a late
statement between two chain members and refuses to supersede itself (it confirms the existing fact instead). The board state
machine is enforced in Cypher too: claims carry a lease, `heartbeat` extends it, `reap_expired` returns lapsed tasks to
`submitted`; `handoff` needs a working task and its owner; `next_open_task` orders by priority then age.

**Events.** The substrate is the only publisher of memory and board events (Redis pub/sub, channel `team_<slug>:events`); the
payload schemas, including the full `fact.superseded` payload, are in `hiveboard/EVENTS.md`.

**Data hygiene.** Entities merge on `name_key = lower(trim(name))`; embeddings must be exactly 768 floats (`ValueError`
otherwise); hot reads project nodes without embeddings (`has_embedding` instead); unbounded reads take a `limit` (default 500);
`why()` returns every `DERIVED_FROM` episode under `episodes`; out-of-order episode batches keep one linear `NEXT` chain.

```bash
# from the repo root, with FalkorDB 6.0.x on localhost:6379 (docker compose up falkordb)
uv sync
uv run --package hiveboard pytest packages/hiveboard/tests -q            # fresh graph per test, deleted at teardown
uv run --package hiveboard python -m hiveboard.mcp_server                # MCP over stdio (IDE assistants, agent runtimes): recall, why, belief_at, list_tasks, claim, handoff, open_commitments
uv run --package hiveboard python -m bench.harness --agents 20 --tenants 4 --duration 20 --target local   # -> docs/bench/<run_id>.json
```

Python: `from hiveboard import HiveDB, ensure_schema, load_udfs, create_tenant, remember_episodes, remember_fact, recall, why, claim, ...`
(see `docs/contracts/hiveboard-api.md`). Set `FALKORDB_URL=falkor://host:port` or pass it to `HiveDB(url)`.
