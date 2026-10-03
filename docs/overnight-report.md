# Overnight report, 2026-10-03 (07:23 to 10:40 IST)

All nine items were worked. Eight met their acceptance criteria. Extraction quality (item 2) missed its target, so the demo database stays on gold-label replay (item 3, by design).

| # | Item | Result |
|---|---|---|
| 1 | Answer prompt | Done. All acceptance questions pass on Gemma 4 26B. |
| 2 | Extraction prompt | Target missed: P 0.42, R 0.59 (goal 0.80 / 0.70). |
| 3 | Reseed with real extraction | Not done, as planned when P < 0.70. Gold seed on 6379 re-run and verified. |
| 4 | Episode recall | Done. "What slipped because the sandbox was down?" finds the UPI slip and Priya's utterance. |
| 5 | Tenant cards | Done. Node and edge counts; MB only when FalkorDB reports it. |
| 6 | Live-import path | Done, no code changes needed. Mid-chain insertion is correct. |
| 7 | Full UI walkthrough | Done. Every page on live data; 19 bugs fixed. |
| 8 | Benchmarks | Done. 4.22.0 vs 6.0.1, single-graph contention, 200 x 20. |
| 9 | FalkorDB issue drafts | Done, in `docs/falkordb-issues.md` (not posted). |

## 1 and 4: answers

The answer agent now gives the model every version of a fact oldest first, the source as "spoken in the meeting" or "written in the email thread", who said it, the utterances around each change, and any stated reason. Episode recall (vector plus full-text on raw utterances and emails, fused by reciprocal rank) adds the original words as evidence. Sample answer, real Gemma 4 26B:

> The UPI flow was first due on 2026-09-24, which Priya stated in the Orbit kickoff meeting on Sept 07. Then, Priya moved the due date to 2026-09-25 in the Orbit standup 1 meeting on Sept 14 because the Razorpay sandbox did not reliably fire UPI collect callbacks. Now, the due date is 2026-09-28, as stated by Priya in her email "UPI flow: moving to Monday the 28th" on Sept 17. The work was completed on 2026-09-28.

The vendor question says PayU replaced Razorpay at the Sept 23 customer call because Meridian's compliance team mandates PayU. The side-drawer question explains the reversal from the kickoff's bottom tab bar on Meridian's 56 dp touch-target rule. No answer calls an email a meeting. Latency 6 to 13 s per answer including the model.

Also added: a guard that rewrites model-written Cypher of the shape `MATCH … WHERE … MATCH` (see finding 3 below), with tests.

## 2 and 3: extraction

Five prompt versions, a closed predicate vocabulary, a per-tenant entity registry, a calendar table, few-shot examples (from `orbit_001`, excluded from scoring) and rule-based post-processing. Final strict score on 16 files, 108 gold items, `gemma-4-26b-a4b-it`: precision 0.42, recall 0.59, F1 0.49 (dev subset went 0.13 → 0.44 F1 across versions). Per-file table, error analysis and method: `docs/eval/extraction.md`.

Why it stalled: the same fact phrased with a different subject or kind counts as one miss plus one false positive under strict matching; the model extracts detail the gold set does not label; and Gemma follows closed lists but not "do not extract" instructions reliably. Caveat: the canonical subject list was derived from the gold subjects, so the score assumes a known entity registry.

Consequence: the seed keeps replaying gold labels (`data/seed.py --extract gold`, the default). Real extraction is available with `--extract real`, and API imports now use the v5 extractor.

Rate limit, measured: the Gemini free tier caps `gemma-4-26b-a4b-it` at 16,000 input tokens per minute, shared across both keys. Requests per minute are not the constraint. The full evaluation took 261 calls, 749k input tokens and 65 minutes with token pacing.

Pipeline fix found along the way: multi-valued predicates (`lesson`, `requires`, `scope_includes`, `customer`, `decided`) no longer supersede each other.

## 6: live import

Seeded without `orbit_002`, then imported it through the API. The UPI chain went from 24 → 28 to 24 → 25 → 28, with the 28th still active and still sourced from the email. Belief at Sept 10, 16 and 20 returns the 24th, 25th and 28th. No spurious supersession event fired.

## 7: UI walkthrough

Every page on live data, no mock badge. Fixed: play-at buttons without audio, email-list overflow, import stats showing NaN, wrong message highlighted in the email drawer, evidence episodes not shown, Why-sheet crash on the timeline, bench grouping and labels, standup artifact shown as raw JSON, a new open-commitments panel on the board, "move it to Friday" targeting the right date, closed commitments hidden, Gemini 429s now wait for the server's retry hint instead of dropping facts. Tests: API 85, ingest 81, hiveboard 30, all passing; web lint and build clean.

## 8: benchmarks

One laptop (i9-13900HX), client and server on the same host. Full table and method in `docs/bench/README.md`; summary in the README.

- 20 agents over 4 graphs: 6.0.1 does about 1,800 ops/s vs 1,360 on 4.22.0, read p50 8.5 vs 11 ms.
- 100 agents on one graph: write p50 rises to 260 to 360 ms on both engines (per-graph write serialization), which is the case for graph-per-tenant.
- 200 agents over 20 graphs on 6.0.1: 2,600 ops/s, zero errors, exactly one winner in every compare-and-set race, but only after raising MAX_QUEUED_QUERIES; at the default of 25, 18 percent of requests were rejected.

## 9: FalkorDB findings (drafts, not posted)

1. `GRAPH.MEMORY USAGE` truncates to whole MB and never counts index memory (both engines).
2. The documented `%R~graph` ACL selector rejects `GRAPH.RO_QUERY` (both engines); `%RW~` and `~` work.
3. On 6.0.1 only, `MATCH … WHERE …` followed directly by another `MATCH` silently drops the first filter; 4.22.0 is correct. None of our `cypher/` files has that shape, and model-written Cypher is now guarded.

## Left for the team

- Extraction quality is the main open problem. Options: a larger model (the 31B was overloaded on the free tier), a looser eval match (semantic rather than strict), or presenting gold replay plus one live extraction in the demo.
- The `hiveboard` supersede event carries `old_object: null` and a title-cased subject; cosmetic.
- Test leftovers on the scratch database 6382: tenant `vega` and one snapshot graph. The main database on 6379 is clean and freshly seeded.
- Not started, needs you: Railway and Vercel deployment, project name, demo video, blog, LinkedIn Post B.
