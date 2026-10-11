# Backend review, 2026-10-12: consolidated findings and fix plan

Three read-only audits, one per layer, against FalkorDB 6.0.1: [substrate and Cypher](01-substrate.md) (27 findings), [ingestion and seed](02-ingest.md) (20 findings), [API, agents, LLM, operations](03-api.md) (30 findings). Baseline at review time: 44 substrate, 81 ingestion and 109 API tests pass. Every finding below cites a file and line in its report.

## What works, verified

Load-bearing FalkorDB use (no injection path, allow-listed labels, parameters everywhere); the gold-seeded graph is internally consistent (one active fact per single-valued key, no NEXT branches, UPI chain crosses meeting to meeting to email); compare-and-set claims hold under 50 concurrent threads; snapshots carry indexes and constraints; the free-form Cypher guard has no known bypass; cross-tenant graph reads are denied by ACL; audio path traversal is blocked; LLM failures degrade to grounded answers rather than 500s; the teammates' decision-impact routes are graph-backed and atomic.

## Priority 0: fix before any judge touches it (about one day)

| # | Finding | Why it matters on stage | Effort |
|---|---|---|---|
| P0-1 | Mid-chain insertion self-supersedes and deletes the current belief when a late import restates the head (substrate 1) | A live import of an older meeting can wipe the UPI answer | 1 h |
| P0-2 | Board state machine not enforced: completed tasks can be handed off or failed, non-addressees can claim handed-off tasks, priority ignored (substrate 5) | The coordination story is the Track 2 pitch | 1 h |
| P0-3 | Scheduler and FollowUp race for the same reschedule task; when FollowUp wins there is no handoff edge (API 3.3) | "Move it to Friday" breaks nondeterministically | 1 h |
| P0-4 | Event pump re-subscribes every 2 s and drops events in the gap (API 3.4) | The Scheduler sometimes never wakes for the button | 1 h |
| P0-5 | Tasks stuck in `working` forever after a restart; no lease or reaper (API 3.1) | A redeploy mid-demo leaves zombie tasks on the board | 2 h |
| P0-6 | Tenant rw ACL user can rewrite and delete other tenants' registry rows and published skills in commons (substrate 15, API 2.5) | Judges will probe isolation; the README claims it | 1 h |
| P0-7 | No auth; demo and admin endpoints mutate shared state; `POST /tenants` on an existing slug resets passwords (API 2.1, 2.2) | Any public URL is a shared sandbox anyone can pollute | 3 h for admin token plus per-tenant key |
| P0-8 | Historical imports with workers running fan out into reschedule tasks and simulated issues (API 3.2) | A judge importing a file through the UI triggers a cascade | 1 h |
| P0-9 | `belief_at(t, known_by)` ignores `expired_at` (substrate 3) | "What did we know on Sept 16" can be wrong | 30 min |
| P0-10 | Container downloads the 300 MB embedding model on every cold start; ONNX startup needs the network even when cached (API 5.1, ingest 17) | Deploy fails or the demo dies on hackathon Wi-Fi | 1 h |

## Priority 1: correctness that shows up with real data (about one day)

- Re-import rewrites existing facts in place because fact ids are positional (ingest 1); episode ids are positional too, so re-chunking corrupts the chain (ingest 2). Content-hash ids.
- `remember_fact` and `supersede_fact` are read-then-write across three queries; concurrent writers leave several active facts per key (substrate 2). One Cypher statement; raise on no-op supersede.
- Two incompatible `fact.superseded` payloads; production gets the one without `old_object`, so handoff summaries say "moved from ?" (substrate 4, ingest 4, API 3.5).
- Entity MERGE on name collides on case variants and aborts the batch (substrate 6); fuzzy subject snapping merges "Orbit launch" into "Orbit" and lets it supersede unrelated facts (ingest 9).
- Roster join collides on the email local part, attributing an external sender to an internal person (ingest 5); HTML-only emails keep CSS and quoted replies (ingest 7); mbox files with duplicate ids or clock skew are rejected whole (ingest 6).
- `GET /facts` silently caps at 500 and timeline, belief and impact build on it (API 1.2).
- Free-form Cypher results never reach the caller (API 1.3).
- No body size limit on imports (API 2.3); chat history readable tenant-wide including via Cypher (API 2.4).
- Wrong-dimension embeddings stored but invisible to recall; no record of which embedding model produced a tenant's vectors (substrate 10, ingest 18).
- Gold replay and live extraction follow different supersession paths, so the seeded demo never exercises the production logic (ingest 11).

## Priority 2: quality and hygiene

Unbounded reads versus `RESULTSET_SIZE 10000`; embeddings shipped on three hot read paths; `active_facts(entity)` ignores the entity index; workers write `last_seen` every 2 s; unbounded in-process lists; Dockerfile not frozen and runs as root; error envelope missing on unknown routes; health leaks a file path; simulated issues carry real-looking GitHub URLs; date handling (dayfirst, UTC midnight due dates, weekday correction applied to every item); `retrieve_skill` ranks success rate above similarity; `ensure_commons_schema` re-run on every snapshot.

## Extraction quality (the known weak spot)

v5 scores precision 0.42 and recall 0.59 strict, but 32 of 44 misses have a near-match in the same episode: about 45 percent are matching artefacts (paraphrase, plurals, number words), 25 percent taxonomy overlap, 25 percent wrong model output, 5 percent the pipeline's own filters (the standup routine episodes are skipped because "decisions since" is a read-back cue). Cheapest wins: dialogue-window extraction (3 to 5 episodes per call, 4x fewer calls), normalise the gold side the same way as the pipeline, drop the read-back cue, a yes/no verifier pass on local Gemma 4 E4B to cut false positives, and report a partial-credit metric alongside strict. Details in [02-ingest.md](02-ingest.md#3-extraction-quality-v5-tp-64-fp-88-fn-44).

## Features worth adding, ranked by value per hour

1. Per-tenant API key plus admin token (S). Unlocks a public deployment and makes the ACL probe an HTTP boundary too.
2. Task lease and reaper plus deterministic Scheduler claim (S). Makes the coordination demo survive restarts.
3. MCP over HTTP with the real embedder (S to M). An IDE assistant recalling team memory live over MCP is a strong Track 2 moment; today the MCP server is stdio-only and recalls with fake vectors.
4. Forgetting with audit: `retract_fact` exists in the substrate with no route; add `POST /facts/{id}/retract`, an archive job and a `GET /audit` (M). The Cognee hackathon winner won on exactly this.
5. Handoff visualisation data and an A2A task surface with an agent card (S each). The README already claims A2A states.
6. Streaming chat so the Why panel fills while the 7 to 17 s answer is written (M).
7. Per-tenant export and delete routes (S).
8. Write-back of agent outcomes as precedent facts that recall can rank (S to M).
9. Document chunks as a third episode source; GitHub issues as an input source (M each).
10. Consolidation job producing weekly summary facts; topic communities as a recall hop (M each).

## Decisions the team needs to make

- **Track emphasis.** The Oct 2 plan was Track 2 primary with Track 3 as a second entry. The Oct 9 to 10 teammate audit (`docs/track3-readiness.md`, `docs/demo-script.md`) re-aimed the demo at Track 3 around the decision-impact feature, with scripted (fake) answers. The pitch materials in `docs/pitch/` follow the Oct 2 plan. Pick one; both are defensible, and the same build enters both tracks either way.
- **Eligibility.** `track3-readiness.md` records that this is pre-event work and asks for an organiser ruling on reuse before the entry is represented as eligible. Nobody has contacted the organisers yet.
- **Demo mode.** Scripted answers are reproducible; Gemma 4 answers are real but take 7 to 17 s each on the free tier shared by both keys. The pitch script offers both modes.
- **Live database state.** `data/seed_work.py --tenants orbit` has not been run against the demo database, so the decision-impact view shows zero tracked work items right now.
