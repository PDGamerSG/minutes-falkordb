# Backend review 1: hiveboard substrate and Cypher (2026-10-12, read-only, FalkorDB 6.0.1)

Baseline: 44 substrate tests pass. Findings were verified with probe scripts against a scratch instance unless marked "code reading".

Verified OK: no `MATCH ... WHERE ... MATCH` shape in any Cypher file or Python string; `10_ingest_episode` keeps its Filter on 6.0.1; `GRAPH.COPY` snapshots carry indexes and constraints; `recall` auto-reloads the UDF; no Cypher injection path (values are parameters, labels allow-listed, graph names are separate command args).

## 1. Correctness

1. **CRITICAL. Mid-chain insertion deletes the current belief when the late statement restates the head (self-SUPERSEDES).** `apps/api/hive_adapter.py:901-922` (`insert_fact_in_chain`) from `packages/ingest/ingest/pipeline.py:558-575`; root cause `memory.py:309-312` (`remember_fact` returns the existing head id with `existing: True`). Evidence: chain Thu -> Fri (head); a late import of "Fri" dated between them makes `remember_fact` return the Fri id with `existing: True`; the follow-up Cypher then runs with `new_id == before_id`. Result: no active fact for the key, `(a)-[:SUPERSEDES]->(a)`, `belief_at(now)` empty. Trigger: a meeting imported before an earlier email proposing the same date. Fix: bail out to `confirm_fact` when `existing` or `id == before_id`; better, move chain insertion into the substrate as one Cypher statement that refuses `new = before`.
2. **HIGH. `remember_fact` and `supersede_fact` are read-then-write across three queries; concurrent writers break "one active fact per key".** `memory.py:299-339`, `cypher/12_supersede_fact.cypher`. Evidence: 16 threads on one key -> 4 active facts and 6 contradictions; 8 threads inserting an identical fact -> 5 ids; 8 threads calling `supersede_fact(old)` -> 8 active facts, 7 callers got `superseded: []` with no error. The bench harness runs this pattern, so bench graphs accumulate contradictions. Fix: one Cypher statement (OPTIONAL MATCH the active fact, MERGE the new one, SET the old) so per-graph write serialization makes it atomic; raise `Conflict` when nothing was superseded.
3. **HIGH. `belief_at(t, known_by)` ignores `expired_at`.** `cypher/31_belief_at_time.cypher:4-6`. A fact superseded after K is treated as already expired at K: `belief_at(BASE+20, known_by=K)` returned `[]` instead of the old fact. Fix: `(valid_to IS NULL OR valid_to > $t OR ($known_by IS NOT NULL AND expired_at > $known_by))`, the same for retraction; add the test.
4. **HIGH. Two incompatible `fact.superseded` payload schemas; production gets the poorer one.** Substrate payload `memory.py:280-292` carries only new_id, old_ids, key, kind, object; `hive_adapter.py:664` suppresses the pipeline's richer payload; the consumer `scheduler_agent.py:22-39` reads `old_object`, `new_object`, `subject`, `episode_id`; `routes/board.py:189-203` emits a third variant. The Scheduler gets `old_object=None`, no `due_at`, and a title-cased subject. Fix: the substrate emits the full schema; the pipeline and the route stop duplicating.
5. **HIGH. Board state machine is not enforced in Cypher.** `21_handoff_task` has no status check, `24_set_task_state` has no status check, `20_claim_task` has no owner check, `27_next_open_task` orders by created_at before priority so priority never matters. Evidence: handing off a completed task succeeded and reopened it; `fail()` on a completed task set it failed; after handoff(a1 -> a2), a1 claimed it. Fix: status guards, owner guard, `ORDER BY priority DESC, created_at ASC`.
6. **MEDIUM. Entity MERGE on name plus slug id: case variants collide and abort the batch.** `04_upsert_entity.cypher:3-4`, `memory.py:149-163`. "UPI flow" then "UPI Flow" raises a unique constraint violation. Fix: MERGE on a normalised key and keep `name` for display.
7. **MEDIUM. NEXT chain forks when episode batches arrive out of seq order.** `memory.py:103-111`, `cypher/16`. Ingesting e1, e3, e2 yields `e1->e2` and `e1->e3`. Fix: relink the successor in `10_ingest_episode`.
8. **MEDIUM. Re-ingesting an existing fact id rewrites history while leaving status superseded.** `11_ingest_fact.cypher:5-9` (`SET` after `MERGE`). Fix: `ON CREATE SET` for identity and bi-temporal fields, or raise `Conflict`.
9. **MEDIUM. Backdated or cross-key supersession produces inverted validity windows.** `12_supersede_fact.cypher:5`. Fix: raise `Conflict` when `new.valid_from < old.valid_from` or the keys differ.
10. **MEDIUM. Wrong-dimension embeddings are stored but invisible to recall.** `memory.py:30-31`. A 384-d fact ingests fine and never appears in KNN; switching `EMBED_BACKEND` would silently drop new facts from recall. Fix: validate length 768 in `_vec`, `learn_skill`, `upsert_entities`.
11. **MEDIUM. Hot read paths ship 768-float embeddings.** `15_fulltext` (`RETURN node`), `41_skill_outcome`, `44_export_skill`. Fix: map projections.
12. **LOW to MEDIUM. `active_facts(entity_id)` scans every active fact then filters.** `14_active_facts.cypher:3-7`; the Entity index is unused; this is one of the three bench read operations. Fix: anchor on the entity when given.
13. **LOW. Unbounded reads versus `RESULTSET_SIZE 10000`.** Files 31, 46, 50, 51, 52 and 53 have no LIMIT; results beyond 10,000 rows are truncated silently. Fix: `$limit` parameters or set RESULTSET_SIZE explicitly.
14. **LOW. `why()` takes `result_set[0]` when a fact has several DERIVED_FROM episodes.** `memory.py:408`. Fix: collect in `32_why_path`.

## 2. Isolation and safety

15. **HIGH. Any tenant's read-write ACL user can read, rewrite and delete every other tenant's registry row and published skills in `commons`.** `tenancy.py:21-22, 63-64` grants `+GRAPH.QUERY ~commons`. Evidence as `team_A_rw`: `SET t.display_name='pwned'` on tenant B's row succeeded; `DELETE t` removed B from the registry. Fix: ACL selectors so commons is read-only for tenants (`~team_x (+GRAPH.RO_QUERY +GRAPH.EXPLAIN ~commons)`); commons writes stay on the admin handle.
16. **MEDIUM. No slug validation on the substrate hot path.** `db.py:58-60`; `validate_slug` is only used in `tenancy.py`. `ensure_schema(db, "x y/z")` created graph `team_x y/z`; `"orbit__snap_1"` created a graph that `delete_tenant("orbit")` would delete by prefix; the MCP server passes `tenant` raw. Fix: validate in `graph_name`.
17. **MEDIUM. One shared password pair for all tenants, reset on every API start.** `config.py:22-23`; `main.py:52` calls `create_tenant`, which runs `ACL SETUSER ... reset`. Fix: per-tenant secrets generated in `create_tenant`; never reset existing users.
18. **MEDIUM. `ro()` silently falls back to the admin connection.** `db.py:85-98`. The MCP server, the bench and any new process run "read-only" reads as admin with no log line. Fix: log once, or require an explicit opt-in.
19. **LOW. `delete_tenant` leaves commons Skills with `origin_tenant`.** `tenancy.py:82-92`.
20. **LOW. Read-only users can enumerate the tenant registry through `~commons`.**

## 3. Robustness

21. **MEDIUM. No client-side socket timeouts or health checks.** `db.py:49-51`: `socket_timeout None`, `socket_connect_timeout None`; a hung server blocks every API thread. `HiveDB()` against a closed port raises after 4.1 s of retries, so `ping()` cannot serve as the liveness probe. Fix: `socket_connect_timeout=2, socket_timeout=10, health_check_interval=30`, lazy first connection.
22. **MEDIUM. A FAILED unique constraint is unrecoverable.** `schema.py:78-90`: two `Person {id:'dup'}` nodes make `ensure_schema` raise on both attempts and leave the tenant half-initialised. Fix: drop the FAILED constraint, report the duplicates, surface a repair path.
23. **MEDIUM. Multi-statement operations have no atomicity** (`remember_fact`, `supersede_fact`, `snapshot` can orphan a snapshot graph, `create_tenant`). Fix: single-statement writes for facts; for snapshots write the metadata first, then copy, then flip.
24. **LOW. Pub/sub wake-ups are fire-and-forget.** A worker restart loses events and tasks wait for polling. Fix: Redis Streams with consumer groups, or a periodic sweep.
25. **LOW. `ensure_commons_schema` re-runs about 50 DDL statements on every `snapshot()` and `publish_to_commons()`.**
26. **LOW. The UDF-retry heuristic in `recall` matches any error containing "hive".** `memory.py:467`.
27. **LOW. Duplicate detection in `remember_fact` is case-sensitive on `object`.** `memory.py:310`.

## 4. Test gaps

- 16 concurrent `remember_fact(supersede=True)` on one key leaves exactly one active fact; two concurrent `supersede_fact` on one old id: one wins, one raises.
- `belief_at(t, known_by=K)` between creation and supersession returns the old fact; the same for retraction.
- Backdated and cross-key supersession are rejected.
- Chain insertion of a statement equal to the head confirms instead of superseding (regression for finding 1).
- handoff, fail and need_input on a completed task are rejected; a non-addressee cannot claim a handed-off task; `next_open_task` honours priority.
- Case-variant entity names upsert without violation; out-of-order episode batches yield one linear NEXT chain.
- `remember_fact` with an existing id does not rewrite object or valid_from; a 384-d embedding raises.
- A tenant rw user cannot modify another tenant's registry row or published skill; the substrate rejects invalid slugs; an MCP call with slug "x y" fails cleanly.
- `fulltext` and `get_skill` carry no embedding on the wire; `ensure_schema` recovers from a FAILED constraint; `delete_tenant` removes commons skills.
- A `fact.superseded` payload contract test shared with the Scheduler; `subscribe()` survives a dropped connection.
- MCP: why, handoff, open_commitments, belief_at(entity) paths, invalid label, unknown tenant error shape.
- Two `snapshot()` calls in the same millisecond do not collide; a bench harness smoke run.
- impact: draft id reused for a second work item; manifest without a document; 201 items; baseline retracted; candidate dedup when SUPERSEDES is a DAG.

## 5. Feature gaps judges will probe

| # | Feature | Exists | Missing | Effort |
|---|---|---|---|---|
| 1 | Fix findings 1, 2, 3, 5 and 15 | — | The first things a memory, coordination and isolation judge will try | 6 to 8 h |
| 2 | Write-back of agent outcomes as precedent | PRECEDENT_FOR (API-only), Task-PRODUCED->Artifact, Agent-RAN->Skill | `record_precedent`, `Task-[:RESOLVED]->Fact`, outcome facts ranked by recall, an event | 3 h |
| 3 | MCP server completeness | 7 tools | remember_fact, active_facts, who_knows, next_open_task, complete and fail, task_trace, retrieve_skill and record_outcome, snapshot; slug validation; k cap | 2 to 3 h |
| 4 | Memory decay and forgetting with audit | recency term in hive.score | `archive_facts(tenant, older_than, max_confidence)` -> status archived, ForgetLog nodes, excluded from recall but kept for belief_at and why; UI badge | 4 to 6 h |
| 5 | GRAPH.COPY time-travel UX | snapshot, list_snapshots | restore(snapshot), belief_at and why against a snapshot, snapshot diff | 4 h |
| 6 | A2A-compliant task exposure | states follow A2A | agent card, tasks/send, tasks/get, tasks/cancel mapped to the board | 4 to 6 h |
| 7 | Consolidation and reflection job | none | per-entity summary facts (kind summary, DERIVED_FROM many), "what we learned this week" | 6 to 8 h |
| 8 | Community detection for topic memory | algo.WCC over CO_MENTIONED | Topic nodes with IN_TOPIC, used as a recall expansion hop | 3 to 4 h |
| 9 | Commons publishing round trip | publish_to_commons | list_commons_skills, adopt_from_commons, the ACL fix | 3 h |
| 10 | Per-tenant metering | usage() returns 0 | op counters per tenant, cached node and edge counts, `/tenants/{t}/usage` | 3 h |
| 11 | Export and import of a tenant graph | none | JSONL export, UNWIND import; doubles as backup | 4 h |
| 12 | Per-agent private versus shared graphs | none | `team_x__agent_y` graphs with promote(), or a visibility property | 6 h (2 h for the property variant) |

## 6. `impact.py` (new module from a teammate)

Explicit decision-impact tracking. `import_manifest` atomically MERGEs a Document, WorkItems and DEPENDS_ON, OWNED_BY and DOCUMENTED_IN edges, refusing the import if a baseline fact or owner is missing. `work_impacts` lists each work item with its baseline fact, the current active facts with the same key and the SUPERSEDES path. `save_draft` re-validates inside the write and MERGEs a FollowUpDraft, returning None when stale. `list_drafts` returns payloads newest first. Wired through `hive_adapter.py:692-704`, `impact_fake.py` and routes `GET /impact`, `GET /impact/drafts`, `POST /work-items/import`, `POST /impact/{id}/draft`; stale becomes 409 `impact_changed`. Quality is good: atomic import, version check inside the write, tenant scoping, no string formatting, six focused tests.

Issues: MEDIUM, `save_draft` passes the draft dict straight as Cypher params, so a missing key surfaces as a FalkorDB error and extra keys are shipped; MEDIUM, draft ids are caller-supplied and reusing one attaches a draft to two work items; LOW, a current fact appears twice when the SUPERSEDES chain is a DAG; LOW, `LIMIT 200` per overview with no per-tenant cap; LOW, no events published; style: inline json versus orjson, a literal 3000 timeout, missing docstrings.
