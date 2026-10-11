# Minutes: 3:00 pitch video script

Team Vulcan, Graph Hacks: Context for AI Agents (WeMakeDevs x FalkorDB, Oct 15-18 2026). Tracks 2 (Agent Memory and Coordination, primary) and 3 (Company Brain).

The narration runs 378 words, kept at or below 2.3 words per second in every row. The table below is the master timeline; `video-storyboard.md` gives the matching shot list and window sizes. Questions are typed exactly as written. Base URLs assume the local setup from the root `README.md`: web on `http://localhost:3001`, API on `http://localhost:8080`. For the hosted take, swap in the deployed URLs.

## Script

| Time | On screen | Spoken line | Caption |
|---|---|---|---|
| 0:00-0:07 | B-roll: `apps/web/public/media/minutes-walkthrough.mp4`, first 7 s, muted | Agents forget. Every session starts from zero, and the team explains its decisions again. | Agents forget. |
| 0:07-0:15 | B-roll continues (7-15 s of the clip) | And a memory that cannot explain itself is a liability. Who said it? When? Is it still true? | A memory that cannot explain itself is a liability. |
| 0:15-0:25 | Landing page `/`, hero visible, then click the workspace action into `/workspaces` | This is Minutes. It turns what a team said in meetings and wrote in email into one shared, time-aware memory in FalkorDB. | Minutes: meetings + email → one time-aware memory in FalkorDB |
| 0:25-0:35 | Orbit overview `/t/orbit`, with real source, decision and commitment counts | Agents read it, write it and hand work through it, and every answer traces back to a speaker and a timestamp. | Synthetic meetings and emails · reviewed labels replayed · real FalkorDB 6.0.1 |
| 0:35-0:47 | `/workspaces` shows Orbit, Nimbus and Quill. Cut to a browser tab at `http://localhost:8080/tenants/orbit/acl-probe?target=nimbus`; JSON shows `"allowed": false` and the NOPERM error | Each team gets its own FalkorDB graph and its own database users. Here, Orbit's read-only user tries to read Nimbus's graph. FalkorDB refuses it. | One graph per team · ACL users per team · cross-tenant read denied |
| 0:47-1:00 | `/t/orbit/chat`. Type **Why is the UPI flow due on the 28th?** and press Enter. The answer appears | I ask: why is the UPI flow due on the 28th? Priya promised the 24th at kickoff, said the 25th at standup, then wrote the 28th in email. | Sept 24 (kickoff, speech) → Sept 25 (standup, speech) → Sept 28 (email) |
| 1:00-1:12 | Click **Why this answer**. Scroll through Router decision (`template`, `cypher/32_why_path.cypher`), Cypher that ran, Sources, Evidence episodes | The Why panel shows the Cypher that ran, the router's decision and the subgraph. Old facts are not deleted. They are expired and linked by SUPERSEDES. | Bi-temporal: valid_from / valid_to · SUPERSEDES across sources |
| 1:12-1:20 | In Sources, click the email source (opens Priya's Sept 17 message "UPI flow: moving to Monday the 28th"), close it, then click the play-at-timestamp source for standup 1 (0:38) | Open email shows Priya's message. Play at timestamp jumps to the exact line in the standup. | Every claim links to its source |
| 1:20-1:32 | Click the suggestion **Why did we choose the side drawer?** (or type it). Open **Why this answer** and point at the design review evidence episode | Why did we choose the side drawer? Meridian's accessibility checklist needs 56 dp touch targets. That reversed the kickoff's bottom tab bar on September 16. | Bottom tab bar (Sept 7) → side drawer (Sept 16): Meridian 56 dp rule |
| 1:32-1:47 | `/t/orbit/board`. Click **Simulate: "move it to Friday"**. Toast: "Moved it to Friday … Scheduler wakes next." Cards move from submitted to working | On the board I simulate Priya saying: move it to Friday. The PayU date is superseded. The Scheduler agent wakes over Redis pub/sub, claims the task and hands it to FollowUp. | PayU integration: Oct 1 → Fri Oct 2 · Scheduler wakes on Redis pub/sub |
| 1:47-1:57 | Open the FollowUp task. The drawer Trace shows claimed → handed_off → artifact → completed. Artifact shows the **simulated** label | The handoff is an edge in the graph, carrying the subgraph ids FollowUp needs. It produces a follow-up artifact, marked simulated. | HANDED_OFF {summary, subgraph_ids} · artifact simulated (no GitHub token) |
| 1:57-2:05 | Click **Induce double claim**. Toast: "1 winner, 24 losers". Click **Open trace** | Now twenty-five agents race for the same task. One compare-and-set query: one winner, twenty-four losers. | 25 agents · 1 winner · 24 losers |
| 2:05-2:13 | `/t/orbit/timeline?t=1789540200000` (Sept 16 2026, 12:00 IST). Type `UPI` in the fact filter, then clear it and type `vendor` | The timeline answers what we believed on September 16: UPI due the 25th, vendor still Razorpay. | Belief at Sept 16: UPI due Sept 25 · vendor Razorpay |
| 2:13-2:20 | `/t/orbit/skills`. The standup skill row shows steps, runs and success rate. Click **Run standup skill**, then accept the result so the success rate updates | The weekly standup became a learned skill, and every run updates its success rate. | Procedural memory: Skill + Steps + success rate |
| 2:20-2:30 | Slide 4 of `minutes-pitch.pptx` (graph model), then the `belief_at_time` Cypher | Under the hood: one graph per team, plus a commons graph. Facts are bi-temporal, so belief at any time is one Cypher query. | team_&lt;slug&gt; graphs + commons · cypher/31_belief_at_time |
| 2:30-2:37 | `cypher/20_claim_task.cypher` full screen (or slide 6), then `udf/score.js` | The claim is one atomic query, and retrieval ranking runs as a JavaScript UDF inside FalkorDB. | CAS claim: zero rows = another agent won · hive.score UDF |
| 2:37-2:45 | `/bench` page (or slide 9) | Eighteen hundred operations a second; two hundred agents over twenty graphs, zero errors, one winner per race. | 6.0.1: ~1,800 ops/s vs ~1,360 on 4.22.0 · 200 agents × 20 graphs: 2,608 ops/s, 0 errors · one laptop |
| 2:45-2:52 | Slide 11 (honest limits) | Honest note: this demo replays hand-labelled facts on synthetic data; live extraction is scored separately. | Live extraction (Gemma 4): P 0.42 / R 0.59 strict · no HTTP auth yet |
| 2:52-3:00 | Slide 12 (tracks, stack, links, team) | Tracks 2 and 3, open Gemma models, FalkorDB. Repo and live link below. We're Team Vulcan. | github.com/Hydra-Of-Malice/FalkorDB · &lt;LIVE_URL&gt; · Team Vulcan |

Word count of the spoken column: 378 words (about 2.1 words per second on average). The fastest row is 2:20-2:30 (23 words in 10 s, 2.3 w/s); the longest is 1:32-1:47 (31 words in 15 s). If a row runs long, cut its last clause rather than speeding up.

### Cypher on screen at 2:30

```cypher
// cypher/20_claim_task.cypher
MATCH (t:Task {id: $id, status: 'submitted', version: $v})
MATCH (a:Agent {id: $agent})
SET t.status = 'working', t.version = $v + 1, t.owner_agent = $agent, t.updated_at = $now
CREATE (t)-[:CLAIMED_BY {at: $now}]->(a)
RETURN t.version AS version
// zero rows = another agent won
```

## Recording checklist

1. **Seed fresh, right before the take.** Each rehearsal of "move it to Friday" pushes the PayU date another week (Oct 2, then Oct 9). Reseed so the toast reads Oct 1 → Oct 2.
   ```bash
   docker compose up -d falkordb
   uv run --package minutes-api python data/seed.py --tenants orbit,nimbus,quill --extract gold --reset
   uv run --package minutes-api python data/seed_work.py --tenants orbit
   uv run --package minutes-api uvicorn apps.api.main:app --port 8080
   cd apps/web && pnpm dev            # http://localhost:3001
   ```
   `--reset` deletes the selected tenants' data. Use it only on the demo database.
2. **Choose the model mode before recording and keep it on screen.**
   - Mode A, deterministic (the verified path): `LLM_BACKEND=fake EMBED_BACKEND=fake`. Answers are graph-evidence templates. The sidebar shows "Scripted answers · demo mode". Keep that label visible and leave the 0:25 caption in.
   - Mode B, Gemma 4 answers: `LLM_BACKEND=gemini`, `GEMINI_API_KEY`, `EMBED_BACKEND=onnx` (EmbeddingGemma). Seeding and querying must use the same embedding backend. Answers take 6 to 13 s, so trim the wait in the edit. The free tier is capped at 16k input tokens per minute, so pause between questions.
3. **Leave `GITHUB_TOKEN` unset** so the FollowUp artifact shows **simulated**. Make sure `NEXT_PUBLIC_MOCK` is unset (no mock badge on screen).
4. **Health check:** `http://localhost:8080/health` returns 200. `/t/orbit` shows 5 tracked work items (3 need review, 1 aligned, 1 closed).
5. **Browser:** Chrome, window 1600x900, zoom 100%, light theme, a clean profile with no extensions, bookmarks bar hidden. Use one tab per URL below, opened in order.
6. **Tenant:** Orbit for everything. Nimbus appears only as the ACL probe target.
7. **Exact URLs, in shot order:**
   - `http://localhost:3001/`
   - `http://localhost:3001/workspaces`
   - `http://localhost:3001/t/orbit`
   - `http://localhost:8080/tenants/orbit/acl-probe?target=nimbus` (raw JSON. The redesigned workspace has no ACL probe button, so show the endpoint)
   - `http://localhost:3001/t/orbit/chat`
   - `http://localhost:3001/t/orbit/board`
   - `http://localhost:3001/t/orbit/timeline?t=1789540200000` (Sept 16 2026 12:00 IST. For Sept 10, use `t=1789021800000`)
   - `http://localhost:3001/t/orbit/skills`
   - `http://localhost:3001/bench`
8. **Audio:** meeting `.wav` files are not in the repo. Without them, "play at timestamp" shows the transcript segment at that offset. Say "jumps to the exact line", as the script does, not "plays the recording", unless the audio has been dropped into `data/meetings/`.
9. **Rehearse the race once.** "Induce double claim" registers 25 throwaway agents. The board then shows them as one summary card, which is fine on camera.
10. **Do not show** any `.env` file, the FalkorDB Browser on port 3000, or the ACL passwords.

## Speaking notes: eight lines not to get wrong

1. **UPI chain:** Sept 24 (kickoff, Sept 7, speech) → Sept 25 (standup 1, Sept 14, speech, "move it to Friday") → Sept 28 (Priya's email, Sept 17). Priya is the speaker at every hop. Standup 2 (Sept 21) confirms the 28th without a new SUPERSEDES edge. The flow was done Mon Sept 28.
2. **Side drawer:** the kickoff (Sept 7) chose a bottom tab bar. The design review on **Sept 16** reversed it to a side drawer because of Meridian's **56 dp** minimum touch target. Farah (Meridian compliance) confirmed it by email on Sept 18.
3. **Vendor:** Razorpay → PayU at the **Sept 23** customer call, because Meridian's compliance team mandates PayU. On Sept 16 the vendor is still Razorpay.
4. **Board "move it to Friday"** moves the **PayU integration** (Oct 1 → Fri Oct 2), not the UPI flow. It is a source-state simulation, and the GitHub issue is **simulated**.
5. **Race:** 25 agents, 1 winner, 24 losers. In the 200 × 20 benchmark, all 20 races had exactly one winner (500 attempts).
6. **Benchmarks:** about 1,800 ops/s on FalkorDB 6.0.1 vs about 1,360 on 4.22.0 (20 agents × 4 graphs, 4 client processes). 2,608 ops/s at 200 agents × 20 graphs with zero errors, but only after raising MAX_QUEUED_QUERIES to 1000 (at the default of 25, 18 percent were rejected). One laptop, client on the same host: not server capacity.
7. **Extraction:** Gemma 4 26B scores **P 0.42 / R 0.59** (F1 0.49), strict match. The demo graph replays hand-labelled facts; one live extraction is shown separately. Never say the model built the demo graph.
8. **Security and findings:** there is no HTTP user auth yet; isolation is enforced by FalkorDB ACL users with key patterns. The three FalkorDB 6.0.1 findings are **drafted** as issues, not filed.
