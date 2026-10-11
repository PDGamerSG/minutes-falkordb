# Minutes: 3:00 pitch video script

Team Vulcan, Graph Hacks: Context for AI Agents (WeMakeDevs x FalkorDB, Oct 15-18 2026). Tracks 3 (Company Brain, primary) and 2 (Agent Memory and Coordination).

The narration runs 385 words, kept at or below 2.3 words per second in every row. The table below is the master timeline; `video-storyboard.md` gives the matching shot list and window sizes. Questions are typed exactly as written. Base URLs assume the local setup from the root `README.md`: web on `http://localhost:3001`, API on `http://localhost:8080`. For the hosted take, swap in the deployed URLs.

The story: a team changes a decision, and the people doing the work never find out. Minutes is a company memory in FalkorDB, built from meetings and email, that knows who owns what, why it changed, and what the change affects. The ripple effect carries the first minute; the Track 2 coordination work supports it.

## Script

| Time | On screen | Spoken line | Caption |
|---|---|---|---|
| 0:00-0:08 | Landing page `/`, hero visible, slow scroll | A team changes a decision in a meeting. The people doing the work never find out. | A decision changes. The people doing the work never find out. |
| 0:08-0:16 | Landing continues. Click the workspace action into `/workspaces`, then click Orbit | The runbook still says Razorpay. The test plan still assumes a tab bar. Nobody connected the change. | Changed decisions, stale work |
| 0:16-0:29 | Orbit overview `/t/orbit`: "The whole picture.", then the Source entries, Decisions and Commitments counts | This is Minutes: a company memory in FalkorDB, built from meetings and email. It knows who owns what, why it changed, and what the change affects. | Minutes: a company memory in FalkorDB, built from meetings + email |
| 0:29-0:38 | Hover the counts, then scroll to **The ripple effect.** Filters read All work 5, Needs review 3, Aligned 1, Closed 1 | Orbit is a synthetic team: six meetings, five email threads. Five work items are tracked, and three need review. | Synthetic meetings and emails · reviewed labels replayed · real FalkorDB 6.0.1 |
| 0:38-0:49 | Click **Review** on **Update the payment integration runbook**. The row reads payments service · uses vendor, Razorpay → PayU, Needs review, Priya | This is the ripple effect. The payment integration runbook needs review: the vendor moved from Razorpay to PayU, and Priya is the person responsible. | Needs review: Razorpay → PayU · owner Priya |
| 0:49-1:00 | Click **Original decision** (kickoff transcript line, Aditya, 2:13). Close. Click **Current decision** (customer call recap, Aditya, 3:07) | Original decision: Aditya at the kickoff, September seventh. Current decision: the customer call on the twenty-third, because Meridian's compliance team mandates PayU. | Kickoff, Sept 7: Razorpay → customer call, Sept 23: PayU |
| 1:00-1:10 | Click **Dependency document**. The dialog "Orbit delivery plan · dependency register" opens; hold on the runbook paragraph | This is not a keyword match. The dependency document says the runbook holds Razorpay API steps. That link was written down, not guessed. | Explicit DEPENDS_ON from an authored document · no co-mention, no similarity |
| 1:10-1:22 | Close the dialog. Expand **Recorded graph relationships** (graph and edge trail), then **How FalkorDB found the impact** (the executed Cypher) | FalkorDB follows the work to its baseline decision, then the supersedes chain back from the current one. Here is the path, and the query that ran. | WorkItem -DEPENDS_ON→ Razorpay ←SUPERSEDES- PayU · cypher/81_work_impacts |
| 1:22-1:32 | `/t/orbit/chat`. Type **Who owns the decision log?** and press Enter. The answer appears at once | In chat: who owns the decision log? Rahul, from Aditya's email on September twenty-ninth. Minutes keeps the owner apart from the announcer. | Ownership template (cypher/54_owners) · Rahul · email, Sept 29 |
| 1:32-1:44 | Type **Why is the UPI flow due on the 28th?** and press Enter. The answer appears | Why is the UPI flow due on the twenty-eighth? Priya said the twenty-fourth at kickoff, the twenty-fifth at standup, then wrote the twenty-eighth in email. | Sept 24 (kickoff, speech) → Sept 25 (standup, speech) → Sept 28 (email) |
| 1:44-1:54 | Click **Why this answer**: Router decision (`template`, `cypher/32_why_path.cypher`), Cypher that ran, Sources. Click **Open email** on Priya's Sept 17 message "UPI flow: moving to Monday the 28th" | The Why panel shows that chain across speech and email. Old dates are expired, not deleted. Open email shows Priya's actual message. | Bi-temporal facts · SUPERSEDES across sources · every claim links to its source |
| 1:54-2:05 | `/t/orbit/board`. Click **Simulate: "move it to Friday"**. Toast: "Moved it to Friday … Scheduler wakes next" | A change can also start work. On the board, I simulate "move it to Friday": the PayU integration moves from October first to the second. | PayU integration: Oct 1 → Fri Oct 2 |
| 2:05-2:15 | Cards move from submitted to working. Open the FollowUp task; the drawer Trace shows claimed → handed_off → artifact → completed, and the artifact carries the **simulated** label | The Scheduler agent claims the task and hands it to FollowUp, which drafts the follow-up. The GitHub issue is marked simulated. | Scheduler claims → HANDED_OFF → FollowUp · issue simulated (no GitHub token) |
| 2:15-2:23 | `/t/orbit/timeline?t=1789540200000` (Sept 16 2026, 12:00 IST). Type `UPI` in the fact filter, then clear it and type `vendor` | The timeline shows what we believed on September sixteenth: UPI due the twenty-fifth, vendor still Razorpay. | Belief at Sept 16: UPI due Sept 25 · vendor Razorpay |
| 2:23-2:32 | Board: click **Induce double claim**, hold on the toast "1 winner, 24 losers" (4 s). Cut to `/t/orbit/skills`, the standup skill row with steps, runs and success rate (5 s) | For Track two: twenty-five agents race for one task, and one compare-and-set wins. The standup became a learned skill. | Track 2 · 25 agents · 1 compare-and-set winner · standup learned as a Skill |
| 2:32-2:42 | Slide 9 of `minutes-pitch.pptx` (tenancy and ACLs, 5 s), then slide 7 (the UPI chain and the `belief_at_time` Cypher, 5 s) | Under the hood: one graph per team, with its own database users. Facts are bi-temporal; belief at any time is one query. | team_&lt;slug&gt; graph + ACL users per team · SUPERSEDES across sources · cypher/31_belief_at_time |
| 2:42-2:52 | Slide 10 (benchmarks) | On one laptop: about eighteen hundred operations a second, and two hundred agents across twenty graphs with zero errors, one winner per race. | 6.0.1: ~1,800 ops/s vs ~1,360 on 4.22.0 · 200 agents × 20 graphs: 2,608 ops/s, 0 errors · one laptop |
| 2:52-3:00 | Slide 12 (tracks, stack, links, team) | Synthetic data, a real FalkorDB, open Gemma models. Repo below. We're Team Vulcan: tracks three and two. | github.com/Hydra-Of-Malice/FalkorDB · Team Vulcan · Tracks 3 and 2 · synthetic data, reviewed labels replayed, no HTTP auth yet |

Word count of the spoken column: 385 words (about 2.1 words per second on average). The fastest rows are 1:00-1:10 and 2:42-2:52 (23 words in 10 s, 2.3 w/s); the longest are 0:16-0:29 (26 words in 13 s) and 1:10-1:22 (26 words in 12 s). Numbers are spelled out as spoken. If a row runs long, cut its last clause rather than speeding up.

### Cypher on screen at 1:10 (excerpt of `cypher/81_work_impacts.cypher`)

```cypher
// Only explicit dependencies count. No co-mention or vector similarity establishes impact.
MATCH (w:WorkItem)-[:DEPENDS_ON]->(baseline:Fact)
OPTIONAL MATCH (w)-[:OWNED_BY]->(owner:Person)
WITH w, baseline, owner
MATCH (w)-[:DOCUMENTED_IN]->(doc:Document)
WITH w, baseline, owner, doc
OPTIONAL MATCH (current:Fact {status: 'active'})
WHERE current.key = baseline.key
WITH w, baseline, owner, doc, current
OPTIONAL MATCH path=(current)-[:SUPERSEDES*0..24]->(baseline)
```

In words: start at each work item and the fact it depends on; find the active fact with the same key; follow SUPERSEDES back from it to the baseline. An open item with a path and a changed value needs review, an unchanged value is aligned, completed work is closed.

## Recording checklist

1. **Seed fresh, right before the take, including the work register.** The ripple-effect view is empty until `data/seed_work.py --tenants orbit` runs; afterwards `/t/orbit` must show **5 tracked work items: 3 need review, 1 aligned, 1 closed**. Each rehearsal of "move it to Friday" pushes the PayU date another week (Oct 2, then Oct 9), and every **Connect work** submission adds an item that a work reseed does not delete, so reseed everything with `--reset`.
   ```bash
   docker compose up -d falkordb
   uv run --package minutes-api python data/seed.py --tenants orbit,nimbus,quill --extract gold --reset
   uv run --package minutes-api python data/seed_work.py --tenants orbit
   uv run --package minutes-api uvicorn apps.api.main:app --port 8080
   cd apps/web && pnpm dev            # http://localhost:3001
   ```
   `--reset` deletes the selected tenants' data. Use it only on the demo database.
2. **Choose the model mode before recording and keep it on screen.**
   - Mode A, deterministic (the verified path): `LLM_BACKEND=fake EMBED_BACKEND=fake`. Answers are graph-evidence templates, so the ownership answer is instant. The sidebar shows "Scripted answers · demo mode". Keep that label visible and leave the 0:29 caption in.
   - Mode B, Gemma 4 answers: `LLM_BACKEND=gemini`, `GEMINI_API_KEY`, `EMBED_BACKEND=onnx` (EmbeddingGemma). Seeding and querying must use the same embedding backend. Answers take 7 to 17 s on the free tier, so trim the wait in the edit and pause between questions.
3. **Say nothing the data does not support.** The demo graph is synthetic and replays reviewed gold labels; one live import is shown separately and live extraction is scored on its own (P 0.42 / R 0.59 strict). The work dependencies come from an authored, synthetic delivery register, not from inference. There is no HTTP user auth yet.
4. **Do not click "Prepare follow-up" in the timed take.** The board's FollowUp agent drafts the follow-up in this script. If a rehearsal saved a local draft on the runbook, the row shows it; reseed to clear it.
5. **Leave `GITHUB_TOKEN` unset** so the FollowUp artifact shows **simulated**. Make sure `NEXT_PUBLIC_MOCK` is unset (no mock badge on screen).
6. **Rehearse the board twice before the take.** The Scheduler-to-FollowUp handoff and the Scheduler wake-up are being fixed (`docs/review/README.md`, P0-3 and P0-4). If the trace lacks `handed_off`, reseed and record that shot again. "Induce double claim" registers 25 throwaway agents; the board then shows them as one summary card, which is fine on camera.
7. **Health check:** `http://localhost:8080/health` returns 200. `/t/orbit` shows the 5 tracked items, and the runbook row reads Razorpay → PayU with Priya.
8. **Browser:** Chrome, window 1600x900, zoom 100%, light theme, a clean profile with no extensions, bookmarks bar hidden. Use one tab per URL below, opened in order.
9. **Tenant:** Orbit for everything.
10. **Exact URLs, in shot order:**
    - `http://localhost:3001/`
    - `http://localhost:3001/workspaces`
    - `http://localhost:3001/t/orbit` (the ripple-effect card is the "The ripple effect." section on this page)
    - `http://localhost:3001/t/orbit/chat`
    - `http://localhost:3001/t/orbit/board`
    - `http://localhost:3001/t/orbit/timeline?t=1789540200000` (Sept 16 2026 12:00 IST. For Sept 10, use `t=1789021800000`)
    - `http://localhost:3001/t/orbit/skills`
11. **Audio:** meeting `.wav` files are not in the repo. Without them, the evidence links show the transcript line at that offset. Say "transcript line", not "recording".
12. **Disclose in the submission:** synthetic data, gold-label replay with one live import, scripted versus Gemma answer modes, no HTTP auth, AI assistance, and the open question of pre-event reuse recorded in `docs/track3-readiness.md`.
13. **Do not show** any `.env` file, the FalkorDB Browser on port 3000, or the ACL passwords.

## Speaking notes: eight lines not to get wrong

1. **The ripple effect:** "Update the payment integration runbook" (owner Priya, open) depends on the kickoff vendor decision, Razorpay (Sept 7, `orbit_001` at 2:13, Aditya). The customer call recap (Sept 23, `orbit_005` at 3:07, Aditya) superseded it with PayU because Meridian's compliance team mandates PayU. The dependency is written in the synthetic delivery register; never say a model or similarity search found it.
2. **The overview counts:** 5 tracked items. Needs review: the payment runbook (Priya, Razorpay → PayU), navigation accessibility tests (Sana, bottom tab bar → side drawer), the UPI release handoff (Rahul, Sept 24 → Sept 28). Aligned: the October release checklist (Aditya, Oct 16 unchanged). Closed: the vendor sandbox spike (Priya, completed, no follow-up). The UPI flow itself is done; the handoff document needs review, not an overdue task.
3. **Ownership:** Rahul owns the decision log. Aditya assigned it in the Sept 29 email "Retro prep and action item: decision log (issue #42)", due Fri Oct 2. Aditya announced it; Rahul owns it. An explicit assignment beats the speaker fallback.
4. **UPI chain:** Sept 24 (kickoff, Sept 7, speech) → Sept 25 (standup 1, Sept 14, speech, "move it to Friday") → Sept 28 (Priya's email, Sept 17). Priya is the speaker at every hop. Standup 2 (Sept 21) confirms the 28th without a new SUPERSEDES edge. The flow was done Mon Sept 28.
5. **Board "move it to Friday"** moves the **PayU integration** (Oct 1 → Fri Oct 2), not the UPI flow. It is a source-state simulation, and the GitHub issue is **simulated**. It is separate from the overview's "Prepare follow-up", which saves a local draft and sends nothing.
6. **Timeline at Sept 16, 12:00 IST:** UPI due the 25th, vendor Razorpay. PayU arrives on Sept 23. If the navigation row shows side drawer, that is correct: the design review ran at 10:00 that morning.
7. **Race and benchmarks:** 25 agents, 1 winner, 24 losers. About 1,800 ops/s on FalkorDB 6.0.1 vs about 1,360 on 4.22.0 (20 agents × 4 graphs, 4 client processes). 2,608 ops/s at 200 agents × 20 graphs with zero errors, only after raising MAX_QUEUED_QUERIES to 1000; all 20 races had exactly one winner. One laptop, client on the same host: not server capacity.
8. **Models and security:** Gemma 4 26B scores **P 0.42 / R 0.59** (F1 0.49) strict on extraction; the demo graph replays hand-labelled facts. Gemma is the configured live model; if the take used scripted answers, say so. There is no HTTP user auth yet; graph isolation is enforced by FalkorDB ACL users with key patterns, and the shared commons graph is still writable by each team's read-write user. The three FalkorDB 6.0.1 findings are **drafted** as issues, not filed.
