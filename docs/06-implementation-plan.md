# Implementation plan: Minutes (working name), built on the Hive Board substrate

Status: DRAFT for review, 2026-10-02. Nothing in this document has been built.
Tracks: 2 (primary) and 3. Models: Gemma 4 + EmbeddingGemma. Database: FalkorDB. Budget: $0 to $20.

Working name "Minutes": meeting minutes, and the unit of time the memory is indexed by. Rename freely.

One-line pitch: *Minutes turns what a team actually said in meetings and wrote in email into a shared, time-aware memory that a team of agents reads, writes and hands work through, with every answer traceable to who said it and when.*

Sources, in build priority: 1. meetings (the spine), 2. email threads (same extraction path; see `docs/contracts/email-format.md` for the graph-model delta: `Episode.source_kind`, `EmailThread`, `SENT_BY` / `SENT_TO` / `REPLIES_TO`, `Person.email`), 3. GitHub issues as tickets (Artifact nodes, already planned). Upload-only for email (`.json`, `.eml`, `.mbox`); no mailbox connectors; synthetic corpus following the meeting characters.

---

## 0. Rules compliance and the calendar

| When | What is allowed | What we do |
|---|---|---|
| Now to Oct 14 | Ideas, notes, graph model, diagrams, data you own, accounts, reading. Reusing general libraries, templates and infrastructure. | Everything in Phase 0 below: schema frozen, diagrams, meeting scripts recorded and diarized, gold facts labelled, accounts and keys, local environment, prompt drafts, test cases written as specs, this plan. **No application code in the submission repo.** |
| Oct 15 (Day 1) | Coding starts 00:01 IST | **Build day.** Teammates drive Claude Code through Phases 1 to 6 in parallel streams. Target: end-to-end working by evening. |
| Oct 16 to 18 | Build continues | Hardening: tests, extraction eval, load test, demo rehearsal, video, README, blog, LinkedIn, submit Oct 18 by 9 PM IST. |

Why this still fits your constraint: the build is mostly Claude Code executing a plan that is already specified to the file level. Your teammates need to run it, review it and answer design questions; you can join when the interview is done. Days 2 to 4 are the rigorous testing you want.

AI disclosure (goes in the README): "Claude Code was used for implementation, test generation and documentation under the team's direction; the graph model, architecture, Cypher and all design decisions are the team's and every member can explain them."

---

## 1. Architecture

```
[Recorder app (on-device STT + diarization)] --export JSON--> [apps/api: FastAPI on Railway]
                                                                     |  Gemma 4 (Gemini API, OpenRouter fallback)
                                                                     |  EmbeddingGemma 768-d (ONNX, CPU)
                                                                     v
[apps/web: Next.js on Vercel] <--REST + SSE-->  [packages/hiveboard]  <--falkordb-py-->  [FalkorDB on Railway]
                                                      |  remember / recall / claim / handoff / reflect       one graph per team
                                                      |  Redis pub/sub on the same server (agent wake-ups)   + commons graph
                                                      v                                                     + ACL user per team
                                               [packages/hiveboard/mcp_server.py]  (MCP: memory-semantic tools for Claude / Cursor)
```

Design rules (what judges have praised, in writing):
1. The LLM never holds database credentials. Tools run parameterised Cypher. Free-form Cypher only through a read-only user with a 3 s timeout.
2. Every write goes through a Pydantic schema, then idempotent `UNWIND ... MERGE`.
3. Every answer returns the Cypher it ran, the nodes and edges it touched, and the router decision.
4. Fail loudly. No canned fallbacks when the graph is unavailable.
5. Remove FalkorDB and nothing works: memory, tasks, skills, tenancy and answers all live in the graph.

---

## 2. Repository layout (monorepo, public, MIT)

```
minutes/
  README.md                     setup, data model, Cypher index, AI disclosure, tracks
  LICENSE
  docker-compose.yml            falkordb + api + web for local and for judges
  .env.example
  cypher/                       every query the product depends on (rule 10), one file each, numbered
    00_schema.cypher            indexes, constraints
    10_ingest_episode.cypher
    11_ingest_fact.cypher
    12_supersede_fact.cypher
    20_claim_task.cypher        compare-and-set
    21_handoff_task.cypher
    22_complete_task.cypher
    30_recall_hybrid.cypher
    31_belief_at_time.cypher
    32_why_path.cypher
    40_skill_retrieve.cypher
    41_skill_outcome.cypher
    50_who_knows.cypher
    51_open_commitments.cypher
    52_contradictions.cypher
    60_pagerank_skills.cypher
    61_wcc_entities.cypher
  packages/
    hiveboard/                  the substrate (pip installable)
      hiveboard/
        __init__.py
        config.py               env: FALKORDB_URL, tenant list, model names
        db.py                   connection pool, select_graph(tenant), ro(tenant), rw(tenant)
        schema.py               ensure_schema(graph): indexes, constraints, vector + fulltext
        tenancy.py              create_tenant(slug): graph + ACL users; delete_tenant; usage()
        temporal.py             now_ms(), bi-temporal helpers, belief_at(t)
        memory.py               remember_episode(), remember_fact(), supersede(), recall(), why()
        board.py                submit_task(), claim(), handoff(), complete(), fail(); A2A states
        skills.py               learn_skill(), retrieve_skill(), record_outcome(), pagerank()
        events.py               Redis pub/sub publish/subscribe wrappers
        udf/score.js            retrieval policy UDF (recency x importance x similarity)
        udf/loader.py           GRAPH.UDF LOAD on startup
        mcp_server.py           FastMCP: recall, why, belief_at, claim, handoff, list_tasks (read tools use ro user)
      tests/                    pytest, fresh graph per test
      bench/
        harness.py              N agents x M tenants, latency percentiles, CAS contention
        report.py               JSON -> chart data
    ingest/
      ingest/
        recorder_format.py      Pydantic model of the recorder export
        chunker.py              merge segments into 30 to 60 s same-speaker chunks
        embed.py                EmbeddingGemma ONNX, 768-d, batch
        extract.py              Gemma 4 -> facts/decisions/commitments JSON (schema in models.py)
        models.py               Pydantic: ExtractedFact, ExtractedDecision, ExtractedCommitment
        pipeline.py             run(meeting_json, tenant) -> stats
        prompts/extract_v1.md
      tests/
  apps/
    api/                        FastAPI
      main.py                   routes + SSE + lifespan (schema, UDF, agent workers)
      routes/{tenants,meetings,chat,board,timeline,skills,bench}.py
      agents/
        base.py                 tool-calling loop on Gemma 4, JSON validation, one retry
        fact_agent.py           ingestion-time extraction + supersession detection
        followup_agent.py
        scheduler_agent.py
        standup_agent.py        learns and runs the routine (procedural memory)
        answer_agent.py         hybrid router (CEO's five steps) + template selection
        tools.py                recall, claim_task, write_fact, hand_off, create_issue, ...
        prompts/*.md
      llm/
        gemma.py                google-genai client; function calling; OpenRouter fallback; model switch
      Dockerfile
    web/                        Next.js 15, App Router, Tailwind, shadcn
      app/
        page.tsx                tenant switcher + usage per tenant
        t/[team]/meetings/      list, upload, ingestion progress
        t/[team]/chat/          conversation + Why panel + play-at-timestamp
        t/[team]/board/         agents, tasks, claims, handoffs (live via SSE), demo buttons
        t/[team]/timeline/      belief-at-T scrubber, snapshot diff
        t/[team]/skills/        skills, steps, success rates, PageRank
        bench/                  benchmark charts
      components/GraphView.tsx  react-force-graph-2d (or falkordb-canvas; verify package)
  data/
    meetings/                   our scripted, recorded, diarized meetings (JSON + audio)
    gold/                       hand-labelled facts per meeting for the extraction eval
    seed.py                     idempotent seed of 3 tenants
  infra/
    railway/                    service config notes
    vercel.json
  docs/
    data-model.md + data-model.svg
    demo-script.md
    blog-draft.md
```

---

## 3. Graph model (frozen before Oct 15; this is allowed pre-work)

One FalkorDB graph per team: `team_<slug>`. One shared graph: `commons` (vetted skills published across teams, read-only for team users). All timestamps are epoch milliseconds (FalkorDB has no timezone-aware types).

### Nodes

| Label | Properties | Notes |
|---|---|---|
| Person | id, name, role | from the recorder's speaker labels, resolved by name |
| Meeting | id, title, started_at, ended_at, source_uri | |
| Episode | id, seq, text, t_start, t_end, t_occurred, t_ingested, embedding | one per 30 to 60 s same-speaker chunk; episodic memory |
| Entity | id, name, type, embedding | project, system, customer, topic, person-as-topic |
| Fact | id, subject, predicate, object, text, valid_from, valid_to, created_at, expired_at, confidence, status | semantic memory, bi-temporal; status active / superseded / retracted |
| Decision | id, text, decided_at, status, rationale | Context Graphs vocabulary |
| Commitment | id, text, due_at, status | who promised what by when |
| Task | id, kind, status, version, owner_agent, priority, payload, created_at, updated_at | A2A states: submitted, working, input_required, completed, failed |
| Agent | id, name, model, last_seen | |
| Capability | name | followup, schedule, standup, answer, extract |
| Skill | id, goal, version, runs, success_rate, status, embedding | procedural memory |
| Step | id, order, tool, args_template, guard | |
| FailureMode | id, text | |
| Artifact | id, kind, uri, created_at | github issue, nudge message, standup summary |
| Snapshot | id, graph_name, taken_at, label | metadata for GRAPH.COPY snapshots |

### Edges

```
(Meeting)-[:HAS_EPISODE]->(Episode)        (Episode)-[:NEXT]->(Episode)
(Episode)-[:SPOKEN_BY]->(Person)           (Person)-[:ATTENDED]->(Meeting)
(Episode)-[:MENTIONS]->(Entity)
(Fact)-[:ABOUT]->(Entity)                  (Fact)-[:DERIVED_FROM]->(Episode)
(Fact)-[:STATED_BY]->(Person)              (Fact)-[:SUPERSEDES]->(Fact)
(Decision)-[:DECIDED_IN]->(Meeting)        (Decision)-[:MADE_BY]->(Person)
(Decision)-[:DERIVED_FROM]->(Episode)      (Decision)-[:ABOUT]->(Entity)
(Decision)-[:SUPERSEDES]->(Decision)       (Decision)-[:PRECEDENT_FOR]->(Decision)
(Commitment)-[:OWNED_BY]->(Person)         (Commitment)-[:DERIVED_FROM]->(Episode)
(Commitment)-[:SUPERSEDES]->(Commitment)   (Commitment)-[:ABOUT]->(Entity)
(Task)-[:REQUIRES]->(Capability)           (Agent)-[:HAS]->(Capability)
(Task)-[:CLAIMED_BY {at}]->(Agent)         (Task)-[:HANDED_OFF {at, summary, subgraph_ids}]->(Agent)
(Task)-[:ABOUT]->(Commitment|Decision|Fact) (Task)-[:PRODUCED]->(Artifact)
(Task)-[:USED]->(Skill)                    (Agent)-[:RAN {at, outcome}]->(Skill)
(Skill)-[:STEP {order}]->(Step)            (Skill)-[:RECOVERS_FROM]->(FailureMode)
(Skill)-[:LEARNED_FROM]->(Episode|Task)    (Skill)-[:DEPRECATED_BY]->(Skill)
```

### Indexes and constraints (`cypher/00_schema.cypher`)

```cypher
CREATE INDEX FOR (n:Episode) ON (n.id)
CREATE INDEX FOR (n:Episode) ON (n.t_occurred)
CREATE INDEX FOR (n:Fact) ON (n.id)
CREATE INDEX FOR (n:Fact) ON (n.valid_from)
CREATE INDEX FOR (n:Fact) ON (n.valid_to)
CREATE INDEX FOR (n:Fact) ON (n.status)
CREATE INDEX FOR (n:Task) ON (n.status)
CREATE INDEX FOR (n:Entity) ON (n.name)
CREATE INDEX FOR (n:Skill) ON (n.status)
CREATE FULLTEXT INDEX FOR (n:Episode) ON (n.text)
CREATE FULLTEXT INDEX FOR (n:Fact) ON (n.text)
CREATE VECTOR INDEX FOR (n:Episode) ON (n.embedding) OPTIONS {dimension:768, similarityFunction:'cosine'}
CREATE VECTOR INDEX FOR (n:Fact) ON (n.embedding) OPTIONS {dimension:768, similarityFunction:'cosine'}
CREATE VECTOR INDEX FOR (n:Skill) ON (n.embedding) OPTIONS {dimension:768, similarityFunction:'cosine'}
CREATE VECTOR INDEX FOR (n:Entity) ON (n.embedding) OPTIONS {dimension:768, similarityFunction:'cosine'}
-- plus GRAPH.CONSTRAINT CREATE team_x UNIQUE NODE <Label> PROPERTIES 1 id for every label with an id (needs the exact-match index first)
```

### Tenancy and ACL (`tenancy.py`)

```
ACL SETUSER team_acme_rw on >pw +GRAPH.QUERY +GRAPH.RO_QUERY %RW~team_acme %R~commons
ACL SETUSER team_acme_ro on >pw +GRAPH.RO_QUERY %R~team_acme %R~commons
```
Verify exact syntax against docs.falkordb.com/commands/acl.html on Day 1. The API holds one rw connection per tenant; the answer agent's free-form path uses the ro user. The UI shows the ACL rule for the active tenant and a "try to read another tenant" button that fails on purpose.

---

## 4. Core Cypher (goes in `cypher/`, all parameterised)

Claim with compare-and-set (the handoff primitive; one atomic serialized write per graph):
```cypher
MATCH (t:Task {id:$id, status:'submitted', version:$v})
MATCH (a:Agent {id:$agent})
SET t.status='working', t.version=$v+1, t.owner_agent=$agent, t.updated_at=$now
CREATE (t)-[:CLAIMED_BY {at:$now}]->(a)
RETURN t.version AS version
-- zero rows: another agent won. Caller re-reads and moves on.
```

Hand off with a subgraph reference, not a summary string only:
```cypher
MATCH (t:Task {id:$id, owner_agent:$from, version:$v})
MATCH (to:Agent {id:$to})
SET t.owner_agent=$to, t.status='submitted', t.version=$v+1, t.updated_at=$now
CREATE (t)-[:HANDED_OFF {at:$now, summary:$summary, subgraph_ids:$ids}]->(to)
RETURN t.version
```

Supersede a fact (bi-temporal):
```cypher
MATCH (old:Fact {id:$old_id}) WHERE old.valid_to IS NULL
SET old.valid_to=$now, old.expired_at=$now, old.status='superseded'
WITH old
CREATE (new:Fact {id:$new_id, subject:$s, predicate:$p, object:$o, text:$text,
                  valid_from:$now, valid_to:NULL, created_at:$now, expired_at:NULL,
                  confidence:$c, status:'active', embedding:vecf32($emb)})
CREATE (new)-[:SUPERSEDES]->(old)
WITH new MATCH (e:Episode {id:$episode_id}) CREATE (new)-[:DERIVED_FROM]->(e)
RETURN new.id
```

What did we believe at time T:
```cypher
MATCH (f:Fact)-[:ABOUT]->(e:Entity {id:$entity})
WHERE f.valid_from <= $t AND (f.valid_to IS NULL OR f.valid_to > $t) AND f.created_at <= $t
RETURN f ORDER BY f.valid_from DESC
```

Why path (who said it, when, play the audio):
```cypher
MATCH (f:Fact {id:$id})-[:DERIVED_FROM]->(ep:Episode)-[:SPOKEN_BY]->(p:Person),
      (m:Meeting)-[:HAS_EPISODE]->(ep)
OPTIONAL MATCH chain=(f)-[:SUPERSEDES*0..5]->(older:Fact)
RETURN p.name, m.title, m.source_uri, ep.t_start, ep.text, [x IN nodes(chain) | x.text] AS history
```

Hybrid recall (vector, then structure, then policy score in a UDF):
```cypher
CALL db.idx.vector.queryNodes('Fact', 'embedding', 20, vecf32($q)) YIELD node AS f, score
WHERE f.status='active'
OPTIONAL MATCH (f)-[:ABOUT]->(e:Entity)<-[:ABOUT]-(g:Fact {status:'active'})
WITH f, score, collect(DISTINCT g)[0..5] AS neighbours
RETURN f, neighbours, hive.score(f.valid_from, f.confidence, score, $now) AS rank
ORDER BY rank DESC LIMIT 8
-- verify the direction of `score` (distance vs similarity) on Day 1 and flip inside the UDF if needed
```

Skill retrieval and outcome:
```cypher
CALL db.idx.vector.queryNodes('Skill', 'embedding', 3, vecf32($goal)) YIELD node AS s, score
WHERE s.status='active'
MATCH (s)-[st:STEP]->(step:Step)
RETURN s, collect({order:st.order, tool:step.tool, args:step.args_template, guard:step.guard}) AS steps
ORDER BY s.success_rate DESC, score LIMIT 1
```
```cypher
MATCH (s:Skill {id:$id})
SET s.runs = s.runs + 1,
    s.success_rate = ((s.success_rate * (s.runs)) + $ok) / (s.runs + 1)
-- compute with the pre-increment runs; implement as two SET clauses with WITH to keep ordering explicit
```

Track 3 queries: who knows about X (`50_who_knows`), open commitments per person (`51`), contradictions between active facts (`52`), PageRank over Skills via USED edges (`60`), WCC over Entities for topic clusters (`61`).

---

## 5. Models and prompts

| Use | Model ID (verify in AI Studio on Day 1) | Fallback |
|---|---|---|
| Extraction, agents, answers | `gemma-4-26b-a4b-it` on Gemini API (free tier) | `google/gemma-4-26b-a4b-it` on OpenRouter; `gemini-2.5-flash` switch for the demo recording if needed (disclosed) |
| Cheap steps (chunk titles, entity canonicalisation) | `gemma-4-12b-it` | local `gemma4:12b` via Ollama during development |
| Embeddings | EmbeddingGemma 300M via ONNX Runtime, 768-d (`onnx-community/embeddinggemma-300m-ONNX`, verify) | `gemini-embedding-001` with `output_dimensionality=768` |

Day 1 check before building agents on it: does the Gemini API expose function calling and JSON schema for Gemma 4 models, or only for Gemini models? If only Gemini, use prompt-based JSON with a strict schema and validation, or call Gemma 4 through OpenRouter, which exposes tools in the OpenAI format. Both are free or cents.

Extraction schema (`ingest/models.py`):
```python
class ExtractedFact(BaseModel):
    subject: str; predicate: str; object: str; text: str
    speaker: str; confidence: float = Field(ge=0, le=1)
    kind: Literal["fact","decision","commitment"]
    due_at: str | None = None          # ISO date if commitment
    supersedes_hint: str | None = None # free text: what earlier statement this replaces, if any
    episode_id: str
```
Prompt `extract_v1.md`: given the meeting title, attendees, prior active facts about mentioned entities (so the model can flag supersession), and one chunk, return a JSON array. Temperature 0.1. Validate; drop invalid items; log drop rate.

Supersession detection (FactAgent): key = (subject, predicate). For each extracted fact, look up active facts with the same key. If object differs, ask Gemma 4 "contradiction or refinement?" with both texts; on contradiction, run `12_supersede_fact`; on refinement, add as a new fact with `PRECEDENT_FOR`. Publish `fact.superseded` on the tenant's channel.

Agent loop (`agents/base.py`): system prompt + tool schemas → model call → validate tool args with Pydantic → execute → append result → repeat, max 6 steps, one retry on invalid JSON, then fail the task loudly (status `failed`, reason stored).

Agents and their tools:
- FollowUpAgent (capability `followup`): `recall(entity)`, `open_commitments(person)`, `create_issue(title, body)` (writes an Artifact node; optional real GitHub issue on a demo repo), `complete(task)`.
- SchedulerAgent (`schedule`): wakes on `fact.superseded` where predicate is a date; `update_commitment(id, due_at)`, `submit_task(kind='followup', about=commitment)`, `hand_off(task, to='followup', subgraph_ids=[...])`.
- StandupAgent (`standup`): after 2 meetings with a weekly cadence, `learn_skill(goal, steps)` distils the routine; each run `retrieve_skill(goal)`, executes the steps as tool calls, produces an Artifact (standup summary); the human clicks accept or reject in the UI, which calls `record_outcome(skill, ok)`.
- AnswerAgent (`answer`): router (count entities, intent) → vector lookup, graph traversal, or template; templates are the numbered Cypher files with parameters; free-form Cypher only via ro user and a 3 s timeout; returns answer + cypher + subgraph + router decision.

---

## 6. Build day (Oct 15): three parallel streams, hour by hour (IST)

Each stream is a teammate driving Claude Code with this document open. Streams own disjoint directories to avoid merge conflicts.

| Hour | Stream A: substrate (`packages/hiveboard`) | Stream B: ingestion + agents (`packages/ingest`, `apps/api`) | Stream C: web + ops (`apps/web`, `infra`, `docs`) |
|---|---|---|---|
| 00:01 to 01:00 | Repo init, monorepo skeleton, `docker-compose.yml` with FalkorDB pinned tag, `.env.example`, CI (pytest + lint). Test 6.0 vs 4.22 against the schema file; pick one. | Verify Gemma 4 model IDs, function calling and JSON mode on the Gemini API; verify EmbeddingGemma ONNX loads and returns 768-d. | Railway project: FalkorDB template with volume; Vercel project linked to `apps/web`; Next.js scaffold with Tailwind and shadcn. |
| 01:00 to 03:00 | `db.py`, `schema.py` (indexes, constraints, vector, fulltext), `tenancy.py` (graph + ACL users), `temporal.py`. Tests: schema idempotent, ACL isolation fails across tenants. Verify vector `score` direction. | `recorder_format.py`, `chunker.py`, `embed.py`, `models.py`, `extract_v1.md`. Run extraction on one meeting locally, compare with gold. | Tenant switcher page, meetings page with upload, API client, SSE hook. |
| 03:00 to 05:00 | `memory.py`: remember_episode, remember_fact, supersede, belief_at, why, recall (with UDF `score.js` loaded on startup). Tests for supersession and belief-at-T. | `pipeline.py` end to end: meeting JSON → Episodes → Entities → Facts/Decisions/Commitments with provenance. Seed script with 3 tenants. | Chat page + Why panel (GraphView, Cypher shown, router decision, play-at-timestamp from `source_uri` + `t_start`). |
| 05:00 to 07:00 | `board.py`: submit, claim (CAS), handoff, complete, fail; `events.py` pub/sub. Test: 50 concurrent claims on one task, exactly one wins. | `agents/base.py`, `tools.py`, FollowUpAgent, SchedulerAgent; workers started in FastAPI lifespan; routes `/board`. | Board page: agents, tasks, claims, handoffs live; demo buttons "simulate supersession" and "induce double claim". |
| 07:00 to 09:00 | `skills.py`: learn, retrieve, record_outcome, pagerank. `mcp_server.py` with FastMCP (recall, why, belief_at, claim, handoff). | StandupAgent (learns the routine after 2 meetings; runs it; outcome from UI). AnswerAgent with router + templates. | Timeline page (belief-at-T scrubber; snapshot list via `GRAPH.COPY`), Skills page. |
| 09:00 to 11:00 | `bench/harness.py`: N agents × M tenants, 80/20 read/write, p50/p95/p99, queue depth; CAS contention test; JSON output. | Integration test: ingest 5 meetings → ask 10 questions → assert answers carry provenance. | Bench page with charts. Deploy API to Railway, web to Vercel, run seed against production. |
| 11:00 to 13:00 | Run harness locally on 4.22 and 6.0, and against Railway. Save results to `docs/bench/`. | Extraction eval over all gold meetings; tune prompt once; log precision/recall. | README skeleton: setup, data model diagram, Cypher index, AI disclosure, tracks. |
| 13:00 to 15:00 | Buffer and bug fixes across streams. | | |
| 15:00 onward | **Full demo path on the live URL**: upload meeting 1 to 5, ask "why did we choose X", trigger "move it to Friday", watch Scheduler wake and hand off to FollowUp, open the Why panel, scrub the timeline, run the standup skill, show the benchmark. Record screen for internal review. | | |

Definition of done for Day 1: the demo path above runs on the live URL without manual intervention.

---

## 7. Days 2 to 4: hardening and submission

### Day 2 (Oct 16): correctness
- Unit tests to green across `hiveboard` and `ingest` (target: every Cypher file has at least one test).
- Extraction eval: precision and recall against gold for all meetings; target ≥ 0.80 precision, ≥ 0.70 recall; iterate the prompt at most twice; record numbers in README.
- Supersession and contradiction tests with adversarial scripts (same entity, three changes in one meeting).
- ACL test: ro user of team A attempts `GRAPH.QUERY team_b` → error; shown in UI.
- Time travel: belief-at-T for five timestamps per meeting matches the script.
- Agent failure modes: invalid tool args, model timeout, double claim, handoff to a missing agent → tasks end in `failed` with reasons, nothing hangs.

### Day 3 (Oct 17): load, UX, content
- Load test on Railway: 200 simulated agents over 20 tenant graphs for 5 minutes; capture p50/p95/p99, errors, `GRAPH.MEMORY USAGE` per tenant; chart on `/bench` and in README. Run the same on 4.22 vs 6.0 locally and report honestly.
- Keep-warm job (cron ping every 10 minutes) if Railway idles anything.
- UX pass: empty states, loading states, mobile width, Why panel readability, copyable Cypher.
- Demo script frozen (`docs/demo-script.md`), rehearsed 3 times on the live URL.
- Blog draft (`docs/blog-draft.md`) in FalkorDB's recap voice: the traversal vectors cannot do, the exact Cypher, the benchmark, the limits.
- File any FalkorDB 6.0 issues found, with repro, on GitHub.

### Day 4 (Oct 18): ship by 9 PM IST
- Demo video 2:30 to 3:00 on the live URL (before and after memory, supersession, handoff, Why panel, timeline, benchmark). Upload to YouTube.
- README final: architecture diagram, data model diagram, Cypher index with one-line purpose each, setup (docker compose and Railway), AI disclosure, team, tracks 2 and 3.
- Blog published (Medium or dev.to). LinkedIn Post B. Submit on WeMakeDevs with repo, live URL, video, blog, post, both tracks.

---

## 8. Test matrix

| Layer | Tool | What |
|---|---|---|
| Cypher and substrate | pytest + docker FalkorDB (fresh graph per test; `falkordblite` where it works) | schema idempotency, CAS claim races (asyncio.gather of 50 claims), handoff version bumps, supersession chain, belief-at-T, UDF score ordering, ACL isolation, tenant delete |
| Ingestion | pytest + gold labels | recorder format validation, chunking boundaries, embedding dimension, extraction precision/recall, supersession detection |
| Agents | pytest with a recorded-response fake model + live smoke | tool arg validation, retry once then fail, max steps, no raw Cypher from the model, wake-up on events |
| API | pytest + httpx | every route, SSE stream, error shapes |
| Web | Playwright | tenant switch, upload, chat with Why panel, board live update, timeline scrub, skills accept/reject |
| Load | `bench/harness.py` | 200 agents × 20 tenants; p99 under 300 ms for reads on Railway is the target; CAS: exactly one winner per task |
| Demo | manual, 3 rehearsals + recorded run | the frozen script end to end on the live URL |

---

## 9. Data (Phase 0, allowed now): our own meetings

- 6 scripted meetings for a fictional team ("Orbit", shipping a mobile app), 4 to 8 minutes each, 3 to 4 speakers (us), recorded with the recorder app:
  1. Kickoff: scope decisions, owners, dates.
  2. Standup 1: progress, one commitment slips ("move it to Friday").
  3. Design review: a decision reversed with rationale (precedent).
  4. Standup 2: routine repeats (the StandupAgent learns the Skill after this one).
  5. Customer call recap: new entities, a contradiction with an earlier fact.
  6. Retro: references earlier decisions by name (tests "why did we choose X").
- Gold labels: for each meeting, the list of facts, decisions, commitments with speaker and timestamps, written from the script. This is what the extraction eval scores against.
- Export format from the recorder (confirm against the app): `{meeting: {title, started_at, audio_uri}, speakers: [{id, name}], segments: [{start_ms, end_ms, speaker_id, text}]}`.

---

## 10. Phase 0 checklist (today to Oct 14, all rule-compliant)

- [ ] All teammates registered on WeMakeDevs and in the team; Discord joined
- [ ] This plan reviewed; owners assigned to streams A, B, C
- [ ] Schema diagram drawn (`docs/data-model.svg`) from section 3
- [ ] 6 meeting scripts written, recorded, diarized, gold-labelled
- [ ] Accounts: Google AI Studio (key), OpenRouter (key, $0 until used), Railway, Vercel, FalkorDB Cloud free tier, GitHub org, YouTube
- [ ] Local environment per teammate: Docker, Python 3.12 + uv, Node 20, Ollama with `gemma4:12b` and `gemma4:e4b`, FalkorDB images `v4.22.0` and `latest`
- [ ] Read: FalkorDB concurrency, vector index, ACL, GRAPH.COPY, UDF docs; FalkorDB skills repo; Gemma 4 function-calling guide
- [ ] Prompt drafts and tool schemas written as documents (not code)
- [ ] Demo script v0 written
- [ ] LinkedIn Post A scheduled for the week of Oct 6

---

## 11. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Gemini API lacks tools/JSON for Gemma 4 | medium | prompt-based JSON with validation, or OpenRouter (OpenAI tool format); decided in the first hour of Day 1 |
| Free-tier rate limits hit during load test | medium | load test uses no LLM (pure graph traffic); agents run at demo pace; OpenRouter fallback for bursts |
| FalkorDB 6.0 edge cases | medium | pin after the first-hour test; 4.22 fallback; file issues |
| Extraction quality on our recordings | medium | we wrote the scripts, so gold is exact; two prompt iterations max; show the drop rate honestly |
| Railway cost creep | low | one 1 GB container, keep-warm every 10 min, budget $15; Oracle VM as the $0 escape |
| Team member unavailable on Day 1 | known | streams are independent; Claude Code executes; the plan is file-level |
| Scope creep | high | Definition of done is the Day-1 demo path; everything else is stretch |

---

## 12. Stretch (only after Day-1 definition of done)

- Real GitHub issues from FollowUpAgent on a demo repo.
- LangGraph `BaseStore` implementation over Hive Board (an integration FalkorDB lacks).
- Live audio upload transcribed with Gemma 4 E4B audio input, diarized with pyannote in the backend.
- Snapshot diff view (two `GRAPH.COPY` snapshots, added/expired facts).
- Commons graph: publish a vetted Skill from one team to `commons` with the ACL making it read-only for others.
