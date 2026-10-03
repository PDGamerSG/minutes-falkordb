# Minutes

Shared, time-aware memory for agent teams, built on FalkorDB. Minutes turns what a team said in meetings and wrote in email into a graph that a team of agents reads, writes and hands work through. Every answer comes back with the path that produced it: who said it, in which meeting or email, at what time, and what it replaced.

Built for Graph Hacks: Context for AI Agents (WeMakeDevs x FalkorDB, Oct 15 to 18, 2026). Tracks entered: 2 (Agent Memory and Coordination) and 3 (Company Brain).

> Status: under construction. Sections marked TODO are filled in as the build lands.

## Team Vulcan

| Member | GitHub |
|---|---|
| Pallab Das | [@PDGamerSG](https://github.com/PDGamerSG) |
| Yuvraj Singh | [@Yuvraj-025](https://github.com/Yuvraj-025) |
| Rudra Pratap | [@rpratap2111](https://github.com/rpratap2111) |
| Aditya Arnav | [@Hydra-Of-Malice](https://github.com/Hydra-Of-Malice) |

## What it does

- **Episodic memory**: every utterance and every email becomes an `Episode` with a speaker or sender, a timestamp and an embedding, chained in order.
- **Semantic memory**: facts, decisions and commitments are extracted by Gemma 4, validated, and stored bi-temporally (`valid_from`, `valid_to`). When a date moves or a vendor changes, the old fact is expired and linked with `SUPERSEDES`, even when the change came from a different source (a meeting commitment moved by an email).
- **Procedural memory**: recurring routines (the standup) are learned as `Skill` nodes with ordered `Step`s and a success rate that updates every time an agent runs them.
- **Coordination**: agents claim tasks with a compare-and-set Cypher query, hand off through `HANDED_OFF` edges that carry subgraph ids, and wake each other over Redis pub/sub on the same server. Task states follow A2A (submitted, working, input_required, completed, failed).
- **Tenancy**: one FalkorDB graph per team plus a shared `commons` graph, enforced with per-graph ACL users. Remove FalkorDB and nothing works: memory, tasks, skills, tenancy and answers all live in the graph.
- **Explainability**: the Why panel shows the Cypher that ran, the subgraph it touched, the router decision, and a "play at timestamp" or "open email" link for every source.

## Repository

```
cypher/              every query the product depends on, numbered, single source of truth
packages/hiveboard/  the substrate: schema, tenancy, memory, board, skills, events, UDF, MCP server, bench
packages/ingest/     recorder and email formats, chunking, EmbeddingGemma, Gemma 4 extraction, eval
apps/api/            FastAPI: routes, agents (fact, follow-up, scheduler, standup, answer), SSE
apps/web/            Next.js: sources, chat with Why panel, board, timeline, skills, bench
data/                scripted meetings and email threads (synthetic, our own), gold labels, seed
docs/                research, plan, contracts, demo script, benchmark results
```

## Run locally

```bash
cp .env.example .env
docker compose up -d falkordb          # FalkorDB 6.0.x on 6379, Browser on 3000
uv sync
uv run --package minutes-api python data/seed.py --tenants orbit,nimbus,quill --reset
uv run --package minutes-api uvicorn apps.api.main:app --port 8000
cd apps/web && pnpm install && pnpm dev -p 3001
```

Models: default `.env` uses Ollama with `gemma4:e4b` locally (`ollama pull gemma4:e4b`). For the Gemini API set `LLM_BACKEND=gemini` and `GEMINI_API_KEY`; for OpenRouter set `LLM_BACKEND=openrouter` and `OPENROUTER_API_KEY`. Embeddings: EmbeddingGemma 768-d via ONNX Runtime on CPU (`EMBED_BACKEND=onnx`), or `fake` for tests.

## Graph data model

One FalkorDB graph per team (`team_<slug>`) plus a shared `commons` graph (tenant registry, snapshot metadata, published skills). All timestamps are epoch milliseconds. Every node with an `id` has a unique constraint.

```mermaid
flowchart LR
  subgraph Sources
    M[Meeting] -->|HAS_EPISODE| E[Episode source_kind, text, t_occurred, embedding]
    T[EmailThread] -->|HAS_EPISODE| E
    E -->|NEXT| E2[Episode]
    E -->|SPOKEN_BY / SENT_BY / SENT_TO cc| P[Person]
    E -->|REPLIES_TO| E2
    E -->|MENTIONS| X[Entity]
  end
  subgraph Semantic memory
    F[Fact / Decision / Commitment valid_from, valid_to, confidence, status] -->|DERIVED_FROM| E
    F -->|ABOUT| X
    F -->|STATED_BY| P
    F -->|SUPERSEDES| F0[older Fact]
    F -->|PRECEDENT_FOR| F1[Fact]
  end
  subgraph Procedural memory
    S[Skill goal, runs, success_rate, version, embedding] -->|STEP order| ST[Step tool, args_template, guard]
    S -->|LEARNED_FROM| E
    S -->|DEPRECATED_BY| S2[Skill]
  end
  subgraph Coordination
    K[Task status, version, owner_agent] -->|REQUIRES| C[Capability]
    A[Agent] -->|HAS| C
    K -->|CLAIMED_BY at| A
    K -->|HANDED_OFF at, summary, subgraph_ids| A
    K -->|ABOUT| F
    K -->|USED| S
    K -->|PRODUCED| R[Artifact kind, uri]
  end
```

| Label | Key properties | Role |
|---|---|---|
| Person | id, name, role, email | speakers and email senders; the roster joins the two sources |
| Meeting, EmailThread | id, title or subject, started_at | episode containers |
| Episode | id, seq, source_kind (utterance, email), text, t_start, t_end, t_occurred, t_ingested, embedding | episodic memory, chained by NEXT |
| Entity | id, name, type, embedding | what episodes and facts are about; CO_MENTIONED edges feed WCC |
| Fact (+Decision, +Commitment label) | id, key (subject plus predicate), object, text, confidence, valid_from, valid_to, created_at, expired_at, status, due_at | semantic memory, bi-temporal; status active, superseded or retracted |
| Task | id, kind, status (submitted, working, input_required, completed, failed), version, owner_agent, priority, payload | blackboard; version is the compare-and-set token |
| Agent, Capability | id, name, model; name | who can claim what |
| Skill, Step, FailureMode | id, goal, runs, success_rate, version, status, embedding; order, tool, args_template, guard | procedural memory with outcome statistics |
| Artifact | id, kind (github_issue, nudge, standup_summary), uri, text, simulated | what agents produced |
| Snapshot, Tenant (in commons) | id, tenant, graph_name, taken_at; slug, display_name, users | GRAPH.COPY snapshots and the tenant registry |

Indexes per tenant graph: range indexes on ids, timestamps and status; full-text on Episode, Fact and Decision text; HNSW vector indexes (768-d cosine, EmbeddingGemma) on Episode, Fact, Skill and Entity. See `cypher/00_schema.cypher`.

Tenancy is enforced with Redis ACL users per graph. On FalkorDB 6.0.1 (and 4.22.0) the read-only key selector `%R~graph` that the docs show for read-only users rejects even `GRAPH.RO_QUERY`, because both graph commands declare their key with read-write flags (`%RW~` and `~` work). Minutes therefore enforces read-only access at the command level and isolation with key patterns:

```
ACL SETUSER team_<slug>_rw reset on ><pw> +INFO +PING +CLIENT|SETINFO +GRAPH.RO_QUERY +GRAPH.EXPLAIN +GRAPH.QUERY +GRAPH.PROFILE ~team_<slug> ~commons
ACL SETUSER team_<slug>_ro reset on ><pw> +INFO +PING +CLIENT|SETINFO +GRAPH.RO_QUERY +GRAPH.EXPLAIN ~team_<slug> ~commons
```

The read-only user cannot run `GRAPH.QUERY`, `GRAPH.RO_QUERY` rejects write clauses, and neither user can touch another tenant's graph (tested).

## Cypher

Every query the product depends on lives in `cypher/` and is loaded by name from Python (`hiveboard.queries`), so the folder is the single source of truth. Values are always parameters, never string-formatted.

- `00_schema.cypher`: indexes (range, full-text, vector); constraints are applied by `hiveboard.schema`
- `01` to `05`: upsert Person, Meeting, EmailThread, Entity; link MENTIONS and CO_MENTIONED
- `10_ingest_episode`: episodes under a Meeting or EmailThread with SPOKEN_BY / SENT_BY / SENT_TO / REPLIES_TO / NEXT
- `11_ingest_fact`: Fact (plus Decision or Commitment label) with DERIVED_FROM, ABOUT, STATED_BY
- `12_supersede_fact`: expire the active fact with the same key and link SUPERSEDES (bi-temporal)
- `13` to `17`: retract, active facts, full-text lookup, last episode, fact status
- `20_claim_task`: compare-and-set claim; zero rows means another agent won
- `21_handoff_task`: hand a task to another agent with a subgraph reference
- `22` to `29`: complete, trace, set state, register agent, submit, next open task, list tasks, list agents
- `30_recall_hybrid`: vector KNN, one-hop expansion through shared entities, policy score via the `hive.score` UDF
- `31_belief_at_time`: what was true at valid time T, optionally as known by time K
- `32_why_path`: provenance for a fact: episode, speaker or sender, container, supersession chain
- `40` to `46`: skill retrieve (KNN plus success rate), outcome (running mean), learn, deprecate, export, publish to commons, list
- `50_who_knows`: people who talked or wrote about an entity (SPOKEN_BY, SENT_BY, SENT_TO)
- `51` to `53`: open commitments, contradictions between active facts, stale decisions
- `60_pagerank_skills`: `algo.pageRank` over Task-USED-Skill
- `61_wcc_entities`: `algo.WCC` over CO_MENTIONED entities
- `70` to `74`: snapshot metadata and tenant registry in `commons`

The retrieval policy is a JavaScript UDF stored in the database (`packages/hiveboard/hiveboard/udf/score.js`, loaded with `GRAPH.UDF LOAD REPLACE hive`): `hive.score(valid_from, confidence, distance, now)` = recency (exp of minus age in days over 30) times importance (confidence) times similarity (1 minus cosine distance).

## Benchmarks

Harness: `packages/hiveboard/bench/harness.py`. N simulated agents across M tenant graphs, 80 percent reads (hybrid recall, active facts, task listing) and 20 percent writes (facts with supersession, claims, completions), plus a compare-and-set race on one task per tenant. `--procs` splits the client across processes so Python's GIL does not cap the load. Full method, machine and interpretation: [`docs/bench/README.md`](docs/bench/README.md); raw JSON in `docs/bench/`.

Machine: one laptop (i9-13900HX, 48 GB RAM, Docker Desktop on WSL2), client and server on the same host, FalkorDB image defaults (THREAD_COUNT 32). These are not server-capacity numbers.

| Engine | Agents x tenants | Client procs | Duration | Read p50 / p95 / p99 (ms) | Write p50 / p95 / p99 (ms) | Ops/s | Errors | CAS winners / attempts |
|---|---|---|---|---|---|---|---|---|
| 4.22.0 | 20 x 4 | 4 | 60 s | 11.0 / 29.0 / 36.9 | 15.1 / 51.1 / 67.7 | 1,379 | 0 | 4 / 100 |
| 6.0.1 | 20 x 4 | 4 | 60 s | 8.5 / 20.3 / 25.2 | 11.9 / 39.4 / 51.6 | 1,794 | 0 | 4 / 100 |
| 4.22.0 | 100 x 1 | 4 | 60 s | 21.4 / 52.7 / 73.9 | 321.9 / 767.8 / 871.5 | 1,092 | 0 | 1 / 25 |
| 6.0.1 | 100 x 1 | 4 | 60 s | 7.1 / 28.1 / 50.3 | 272.3 / 640.2 / 743.6 | 1,560 | 0 | 1 / 25 |
| 6.0.1 (MAX_QUEUED_QUERIES 1000) | 200 x 20 | 8 | 120 s | 52.0 / 135.1 / 168.2 | 88.6 / 262.8 / 329.3 | 2,608 | 0 | 20 / 500 |

What the numbers say:
- With the load spread over 4 tenant graphs, 6.0.1 does about 30 percent more operations per second than 4.22.0 at lower latency (repeat runs within 1 percent).
- Putting 100 agents on one graph shows per-graph write serialization on both engines: write p50 rises from about 12 ms to 260 to 360 ms while reads stay fast. Graph-per-tenant is what keeps writes cheap.
- At 200 agents over 20 graphs, every compare-and-set race had exactly one winner. With the image default MAX_QUEUED_QUERIES of 25, 18 percent of requests were rejected with "Max pending queries exceeded"; raising it to 1000 removed every error. Our compose file sets 500.
- With a single client process the two engines tie, because the Python client, not FalkorDB, is the bottleneck.

Single-request latencies on 6.0.1: recall 4 ms, why 1 ms, claim 2 ms, remember plus supersede 3.5 ms. Returning whole nodes that carry 768-float embeddings cost about 0.5 ms per node on the wire, so every user-facing read projects nodes without the embedding.

FalkorDB findings from this work, drafted as issues in [`docs/falkordb-issues.md`](docs/falkordb-issues.md): `GRAPH.MEMORY USAGE` truncates to whole MB and never counts index memory; the `%R~` ACL selector rejects `GRAPH.RO_QUERY`; and on 6.0.1 only, `MATCH ... WHERE ...` followed directly by another `MATCH` drops the first filter (4.22.0 is correct). Every query in `cypher/` avoids that shape.

## Deployment

TODO: Railway (FalkorDB template with volume + API) and Vercel (web). See `infra/`.

## AI assistance disclosure

Claude Code was used for implementation, test generation and documentation under the team's direction. The graph model, architecture, Cypher and design decisions are the team's, and every member can explain them.

## License

MIT.
