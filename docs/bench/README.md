# Benchmarks

Results of `packages/hiveboard/bench/harness.py` against FalkorDB 4.22.0 and 6.0.1, collected on 2026-10-03.
Every run is kept as one JSON file in this folder, named `<engine>-<target>-<agents>x<tenants>-<timestamp>.json`.

## Machine

| | |
|---|---|
| Laptop | Intel Core i9-13900HX (24 cores: 8 P + 16 E, 32 threads), 48 GB RAM, RTX 4060 Laptop GPU (not used) |
| OS | Windows 11 Home 10.0.26200 |
| Docker | Docker Desktop 29.5.3, WSL2 kernel 6.6.87.2, VM limits 32 vCPU and 23.3 GiB |
| FalkorDB 4.22.0 | `falkordb/falkordb:v4.22.0` (`sha256:4ac83f55062d...`), module ver 42200, redis 8.10.2, port 6380 |
| FalkorDB 6.0.1 | `falkordb/falkordb:latest` (`sha256:e2765e207e5b...`), module ver 60001, redis 8.10.2, port 6381 |
| Server config (both) | image defaults, no extra arguments: `THREAD_COUNT 32` (read with `GRAPH.CONFIG GET`), `MAX_QUEUED_QUERIES 25`, `TIMEOUT 1000`, `CACHE_SIZE 25` |
| Client | Python 3.12.13, falkordb-py 1.7.1, redis-py 8.1.0, on the same laptop as the server |

Each engine ran in its own fresh container. Three other FalkorDB containers used by the team (ports 6379, 6382,
6383) were running on the same laptop during the runs, with light, unknown load. Treat the numbers as a
same-machine comparison between engines, not as capacity figures for a server.

## Method

- **Seed.** Per tenant graph `team_bench<i>`: full schema (30 range, 3 full-text, 4 HNSW vector indexes of 768-d
  cosine, 14 unique constraints), 4 people, one meeting with 12 episodes, 6 entities, 30 facts written through the
  supersede path, 3 agents and 10 open tasks. Embeddings are deterministic fake 768-d vectors.
- **Load.** N simulated agents, each a loop that picks a random tenant and runs one operation: 80 % reads
  (`recall`: vector KNN plus one-hop expansion plus the `hive.score` UDF; `active_facts`; `list_tasks`) and
  20 % writes (`remember_fact` with supersede; `claim`, the compare-and-set query; `complete`). Latency is
  measured around the whole hiveboard call on the client, so it includes queueing in the client and in FalkorDB.
  Ops/s counts successful operations only. Graphs grow during the run (writes create facts and tasks), so an
  engine that completes more writes ends with a bigger graph.
- **CAS race.** After the load, for each tenant a fresh task is claimed by 25 concurrent agents at version 0; the
  run records attempts, winners and losers and flags any tenant without exactly one winner.
- **Client processes.** One Python process saturates about one core (the GIL). `--procs 1` is the original mode;
  `--procs P` splits the agents across P worker processes (seeding and the CAS race stay in the parent). The table
  shows server and client CPU (cores busy = CPU seconds from `INFO cpu` and `process_time` divided by duration) so
  you can see which side was the limit.
- **Order.** Runs alternated between engines (4.22.0, 6.0.1, 4.22.0, 6.0.1, ...) to spread any background drift.

Commands (from the repo root, `UV_CACHE_DIR=D:/uv-cache`):

```bash
uv run --package hiveboard python -m bench.harness --agents 20  --tenants 4  --duration 60  --url falkor://localhost:6380 --target local
uv run --package hiveboard python -m bench.harness --agents 20  --tenants 4  --duration 60  --procs 4 --url falkor://localhost:6381 --target local-p4
uv run --package hiveboard python -m bench.harness --agents 100 --tenants 1  --duration 60  --procs 4 --url falkor://localhost:6381 --target local-p4
uv run --package hiveboard python -m bench.harness --agents 200 --tenants 20 --duration 120 --procs 8 --url falkor://localhost:6381 --target local-p8
uv run --package hiveboard python -m bench.harness --agents 200 --tenants 20 --duration 120 --procs 8 --max-queued 1000 --url falkor://localhost:6381 --target local-p8-q1000
```

## Results

| Engine | Agents x tenants | Client procs | MAX_QUEUED | Duration | Read p50 / p95 / p99 (ms) | Write p50 / p95 / p99 (ms) | Ops/s | Errors | CAS (attempts, winners, losers) | Cores busy server / client | File |
|---|---|---|---|---|---|---|---|---|---|---|---|
| FalkorDB 4.22.0 | 20 x 4 | 1 | 25 | 60 s | 17.9 / 37.0 / 45.6 | 20.7 / 49.6 / 60.6 | 958 | 0 | 100, 4, 96 | 1.39 / 1.10 | [json](4.22.0-local-20x4-20261003-015840.json) |
| FalkorDB 4.22.0 | 20 x 4 | 1 | 25 | 60 s | 20.5 / 42.3 / 54.0 | 23.4 / 56.7 / 71.4 | 844 | 0 | 100, 4, 96 | 1.32 / 1.12 | [json](4.22.0-local-20x4-20261003-020043.json) |
| FalkorDB 6.0.1 | 20 x 4 | 1 | 25 | 60 s | 18.8 / 37.8 / 47.7 | 21.9 / 52.5 / 66.7 | 921 | 0 | 100, 4, 96 | 1.09 / 1.10 | [json](6.0.1-local-20x4-20261003-015941.json) |
| FalkorDB 6.0.1 | 20 x 4 | 1 | 25 | 60 s | 19.2 / 39.4 / 51.1 | 22.5 / 53.8 / 68.2 | 898 | 0 | 100, 4, 96 | 1.06 / 1.10 | [json](6.0.1-local-20x4-20261003-020145.json) |
| FalkorDB 4.22.0 | 20 x 4 | 4 | 25 | 60 s | 11.0 / 29.0 / 36.9 | 15.1 / 51.1 / 67.7 | 1379 | 0 | 100, 4, 96 | 3.24 / 2.24 | [json](4.22.0-local-p4-20x4-20261003-020347.json) |
| FalkorDB 4.22.0 | 20 x 4 | 4 | 25 | 60 s | 11.2 / 29.3 / 36.4 | 15.7 / 52.7 / 67.4 | 1347 | 0 | 100, 4, 96 | 3.26 / 2.28 | [json](4.22.0-local-p4-20x4-20261003-021408.json) |
| FalkorDB 6.0.1 | 20 x 4 | 4 | 25 | 60 s | 8.5 / 20.3 / 25.2 | 11.9 / 39.4 / 51.6 | 1794 | 0 | 100, 4, 96 | 3.27 / 2.85 | [json](6.0.1-local-p4-20x4-20261003-020454.json) |
| FalkorDB 6.0.1 | 20 x 4 | 4 | 25 | 60 s | 8.5 / 20.3 / 25.1 | 11.8 / 39.0 / 50.8 | 1801 | 0 | 100, 4, 96 | 3.30 / 2.87 | [json](6.0.1-local-p4-20x4-20261003-021301.json) |
| FalkorDB 4.22.0 | 100 x 1 | 4 | 25 | 60 s | 21.4 / 52.7 / 73.9 | 321.9 / 767.8 / 871.5 | 1092 | 0 | 25, 1, 24 | 2.43 / 2.54 | [json](4.22.0-local-p4-100x1-20261003-020600.json) |
| FalkorDB 4.22.0 | 100 x 1 | 4 | 25 | 60 s | 22.4 / 54.4 / 72.9 | 358.0 / 847.2 / 975.4 | 1030 | 0 | 25, 1, 24 | 2.34 / 2.37 | [json](4.22.0-local-p4-100x1-20261003-021621.json) |
| FalkorDB 6.0.1 | 100 x 1 | 4 | 25 | 60 s | 7.1 / 28.1 / 50.3 | 272.3 / 640.2 / 743.6 | 1560 | 0 | 25, 1, 24 | 2.14 / 2.54 | [json](6.0.1-local-p4-100x1-20261003-020707.json) |
| FalkorDB 6.0.1 | 100 x 1 | 4 | 25 | 60 s | 6.9 / 26.8 / 49.7 | 261.7 / 629.0 / 790.3 | 1564 | 0 | 25, 1, 24 | 2.16 / 2.51 | [json](6.0.1-local-p4-100x1-20261003-021514.json) |
| FalkorDB 6.0.1 | 200 x 20 | 8 | 25 | 120 s | 50.1 / 129.5 / 158.7 | 82.2 / 240.0 / 299.8 | 2508 | 64529 | 500, 20, 480 | 7.78 / 5.90 | [json](6.0.1-local-p8-200x20-20261003-020813.json) |
| FalkorDB 6.0.1 | 200 x 20 | 8 | 1000 | 120 s | 52.0 / 135.1 / 168.2 | 88.6 / 262.8 / 329.3 | 2608 | 0 | 500, 20, 480 | 7.27 / 5.54 | [json](6.0.1-local-p8-q1000-200x20-20261003-021048.json) |

All 64529 errors in the default-config 200 x 20 run are `ResponseError: Max pending queries exceeded`
(`error_kinds` in the JSON). Per-operation percentiles, graph sizes and server config are in each JSON file.

Per-operation p50 in the single-graph runs (ms; first run of each engine):

| Engine | recall | active_facts | list_tasks | claim | complete | remember_fact |
|---|---|---|---|---|---|---|
| 4.22.0, 100 x 1 | 19.2 | 17.0 | 30.2 | 296.4 | 294.5 | 558.9 |
| 6.0.1, 100 x 1 | 4.5 | 6.6 | 10.0 | 250.2 | 251.4 | 397.9 |
| 6.0.1, 20 x 4 (for contrast) | 6.8 | 6.5 | 15.1 | 7.5 | 10.8 | 27.2 |

`6.0.1-local-20261002-210317.json` is an earlier 20 s run from the shared development container (port 6379, other
work running) with an older harness that did not record CPU or config; it is kept for history and is not comparable.

## Interpretation

With the original single-process client at 20 agents x 4 tenants, the two engines are tied within run-to-run noise
(4.22.0: 844 and 958 ops/s; 6.0.1: 898 and 921 ops/s, and 4.22.0 had the best single run), because the Python client
is pinned at about one core while FalkorDB uses barely more than one of its 32; that configuration measures our client,
not the database. Once the client is split across four processes, 6.0.1 is consistently ahead on this workload: about
1.8k against 1.36k ops/s, read p50 8.5 against 11 ms, and roughly 1.8 against 2.4 ms of server CPU per operation, even
though its graphs grew larger during the run (about 14.7k against 11k nodes in total). The 100-agent single-graph runs
show per-graph write serialization clearly on both engines: reads stay in single or low double digits of milliseconds
while writes queue to a p50 of 260 to 360 ms, against 12 to 16 ms when the same writes are spread over four graphs,
which is why Minutes keeps one graph per team. At 200 agents x 20 tenants, 6.0.1 sustained about 2.6k ops/s with
exactly one CAS winner in all 20 races, but only after raising `MAX_QUEUED_QUERIES`; with the image default of 25, 18 %
of requests were rejected with "Max pending queries exceeded", so that setting must be sized to the number of
concurrent clients. In the large run the server used about 7 to 8 of 32 cores and the client about 5.5, so neither side
was saturated, and we have not isolated the bottleneck. Possible causes are the Redis main thread, client-side
scheduling, or both processes sharing one laptop. All of this is one laptop with the client on the same machine and
other containers running, so the numbers say nothing about a dedicated server.

## Engine differences seen by the harness

- 4.22.0 accepted everything the harness uses: `GRAPH.UDF LOAD` of the `hive` library, vector index options,
  `GRAPH.CONSTRAINT CREATE`, `db.constraints()`, `GRAPH.MEMORY USAGE` and `GRAPH.CONFIG GET` of every key we read.
  No degradation was needed. The `--udf auto|require|off` flag exists for engines that reject UDFs (it drops
  `recall` from the read mix and records why in `capabilities`).
- `GRAPH.MEMORY USAGE` reports whole megabytes and does not reflect HNSW vector index memory, on both engines (issue 1 in
  `docs/falkordb-issues.md`). A freshly seeded tenant graph (about 250 nodes) reads `0` in every field; after the
  load, graphs of 2k to 4k nodes read 3 to 7 MB in total. The JSON records node counts next to it (`memory`).
- 6.0.1 drops the WHERE of a MATCH that is followed by another MATCH (4.22.0 does not; issue 3 in
  `docs/falkordb-issues.md`). The queries in `cypher/` already use WITH barriers, so the benchmark workload is
  not affected.
