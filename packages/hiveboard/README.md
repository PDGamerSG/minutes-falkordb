# hiveboard

The substrate of **Minutes**: a shared, time-aware memory for agent teams on FalkorDB. Episodic memory (meeting
utterances and email messages as `Episode` nodes with `NEXT`/`REPLIES_TO` chains), semantic memory (bi-temporal
`Fact`/`Decision`/`Commitment` nodes with `SUPERSEDES` chains, `belief_at(T)` and `why()` provenance), a coordination
board (A2A-shaped `Task` states, compare-and-set `claim`, `handoff` with subgraph references), procedural memory
(`Skill` + `Step`, success rates, PageRank) and Track-3 analytics (who knows X, open commitments, contradictions, WCC clusters).

**Graph per tenant.** Every team gets its own FalkorDB graph `team_<slug>` plus two ACL users: `team_<slug>_rw`
(`+GRAPH.QUERY +GRAPH.RO_QUERY ~team_<slug> ~commons`) and `team_<slug>_ro` (`+GRAPH.RO_QUERY` only). A shared
`commons` graph holds the tenant registry, snapshot metadata (`GRAPH.COPY`) and skills published across teams.
Every query lives in the repo's `cypher/NN_name.cypher` files and is loaded by name (`hiveboard.queries.load_cypher`);
user-facing reads run through `ro_query` with a 3 s timeout and return their Cypher text (`result["cypher"]` or
`rows.cypher` on list results). Ranking uses the `hive.score` UDF in `hiveboard/udf/score.js` (recency x importance x similarity).

```bash
# from the repo root, with FalkorDB 6.0.x on localhost:6379 (docker compose up falkordb)
uv sync
uv run --package hiveboard pytest packages/hiveboard/tests -q            # fresh graph per test, deleted at teardown
uv run --package hiveboard python -m hiveboard.mcp_server                # MCP over stdio: recall, why, belief_at, list_tasks, claim, handoff, open_commitments
uv run --package hiveboard python -m bench.harness --agents 20 --tenants 4 --duration 20 --target local   # -> docs/bench/<run_id>.json
```

Python: `from hiveboard import HiveDB, ensure_schema, load_udfs, create_tenant, remember_episodes, remember_fact, recall, why, claim, ...`
(see `docs/contracts/hiveboard-api.md`). Set `FALKORDB_URL=falkor://host:port` or pass it to `HiveDB(url)`.
