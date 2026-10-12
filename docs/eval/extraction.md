# Extraction eval: Gemma 4 against the gold labels

Model: `gemma-4-26b-a4b-it` on the Gemini API (free tier), `thinking_level="minimal"`, temperature 0.1, JSON mode.
Final prompt: `extract_v5` / `extract_email_v5` (`packages/ingest/ingest/prompts/`), `ingest.extract.CURRENT_VERSION = "v5"`.
Scored on 16 of the 17 gold files (108 gold items). `orbit_001` is left out because the few-shot examples come from it.

**Result: precision 0.42, recall 0.59, F1 0.49 (strict matching). That misses the target (P >= 0.80, R >= 0.70).**
Precision is also under the 0.70 bar for reseeding, so the demo database on `falkor://localhost:6379` was seeded from the gold labels (`--extract gold`), not from real extraction.

## Method

Matching rule (`ingest/eval.py`, from `docs/contracts/recorder-format.md`): an extracted item matches a gold item only when `kind`, speaker, normalised `subject`, normalised `predicate` and the date-normalised `object` are all equal. Matching is greedy and one-to-one. There is no partial credit: `"audit log retained for 7 years"` against gold `"audit log retained 7 years"`, or subject `Orbit` against gold `payments service`, counts as one false positive plus one miss.

Pipeline under test: the production path, one model call per episode (a run of segments by one speaker, 30 to 60 s, or one email message). It uses the same `EpisodeContext` and post-processing that `pipeline.run` uses. "Facts already recorded" holds only the items extracted earlier from the same file, because the eval runs without a database.

What v2 to v5 add over v1:

| Piece | Where |
|---|---|
| Closed predicate vocabulary (the 10 gold predicates) with definitions in the prompt; synonyms mapped, anything else dropped | `ingest/vocab.py` `PREDICATES`, `PREDICATE_SYNONYMS`; prompt section "predicate" |
| Canonical subject list per tenant (orbit 49, nimbus 9, quill 8 names), passed into the prompt as "Known entities"; snapping on case, articles, plurals, a trailing parenthetical, or one extra word | `vocab.CANONICAL_SUBJECTS`, `canonicalize_subject` |
| Calendar table (kept, extended to four weeks) plus a correction for weekday names: when an episode names one weekday and no day number, the date becomes that weekday | `dates.calendar_table`, `extract.correct_weekday` |
| Context lines: the 3 previous episodes or messages, marked "do NOT extract" | `build_user_prompt_v2` |
| 5 few-shot examples from `orbit_001` (segments 7-8, 14-15, 23, 24, 50-51): scope list, owners, a commitment resolved through context, acknowledgement ignored, cadence | `extract_v5.md` |
| Explicit "do not extract": questions, small talk, restatements, read-backs, rationale as its own item, progress chatter | prompt |
| Schema rules in code: a commitment is `due` or `status = completed`; only the lead decides in a meeting (a member's "decision" becomes a fact); completions only of tracked subjects; `status`/`lesson`/`customer` kind conventions; read-back filter (same kind, subject, predicate and object earlier in the meeting); "because ..." rationale only after a why-question; number words as digits | `extract.postprocess_v2` |
| No model call for trivial utterances (< 6 words, no digit, no completion or decision word; the shortest labelled episode has 9 words) or for read-back episodes ("let me read it back", "to recap", "decisions since") | `is_trivial_utterance`, `is_readback` |

Leakage caveat: the canonical subject lists were written from the subjects in `data/gold/*.json`, including the scored files. The scores therefore measure extraction given a known entity registry (in production this slot is filled from the tenant graph's Entity nodes), not open-ended entity discovery. Gold labels were not edited.

Iteration protocol: the dev subset was `orbit_002`, `orbit_005`, `orbit_thread_002` and `nimbus_002` (34 gold items). There were 4 iterations on it (v2 to v5), then one full run on all files except `orbit_001`.

## Prompt version history (dev subset, 34 gold items)

| Version | Change | TP | FP | FN | P | R | F1 |
|---|---|---|---|---|---|---|---|
| v1 | original open-vocabulary prompt (baseline) | 8 | 85 | 26 | 0.09 | 0.24 | 0.13 |
| v2 | closed predicates, known entities, context lines, 5 few-shots, do-not-extract list, post-processing (canonical subject/predicate, completion kind, read-back filter, due must be a date); compressed to ~2.6k input tokens per call for the TPM quota | 17 | 49 | 17 | 0.26 | 0.50 | 0.34 |
| v3 | the lead-only-decides rule, commitment = due or completion, importance test ("would the lead put this in the decision log?"), rationale only when asked, glosses never copied into subjects, fuzzy subject snapping | 17 | 36 | 17 | 0.32 | 0.50 | 0.39 |
| v4 | ratification of a member's proposal is the lead's decision, "on track / still holds" is not a commitment, weekday correction, number words to digits, completion phrases to `completed`, rationale filter | 19 | 40 | 15 | 0.32 | 0.56 | 0.41 |
| v5 | read-back episodes skipped, completions only of tracked subjects, `requires` = an imposed mandate (not checklist contents), `approved by <external party>` | 18 | 30 | 16 | 0.38 | 0.53 | 0.44 |

What moved the numbers: the closed vocabulary plus known entities (v1 to v2: precision x3, recall x2; most v1 items used free predicates such as `uses`, `start_date` or `role`, which can never match). Next came the schema rules in code (member decisions, commitment shape) and skipping read-backs; the end-of-meeting recap in `orbit_005` alone produced 10 false positives in v4. Prompt wording on its own moved little. Gemma follows the closed lists well, but it does not follow negative instructions ("do not extract details") reliably.

## Final run (v5, 16 files, `gemma-4-26b-a4b-it`)

| File | Gold | Extracted | TP | FP | FN | P | R | F1 |
|---|---|---|---|---|---|---|---|---|
| nimbus_001 | 8 | 10 | 5 | 5 | 3 | 0.50 | 0.62 | 0.56 |
| nimbus_002 | 5 | 11 | 4 | 7 | 1 | 0.36 | 0.80 | 0.50 |
| nimbus_thread_001 | 2 | 2 | 2 | 0 | 0 | 1.00 | 1.00 | 1.00 |
| orbit_002 | 10 | 12 | 6 | 6 | 4 | 0.50 | 0.60 | 0.55 |
| orbit_003 | 6 | 17 | 4 | 13 | 2 | 0.24 | 0.67 | 0.35 |
| orbit_004 | 8 | 13 | 3 | 10 | 5 | 0.23 | 0.38 | 0.29 |
| orbit_005 | 15 | 19 | 8 | 11 | 7 | 0.42 | 0.53 | 0.47 |
| orbit_006 | 14 | 16 | 10 | 6 | 4 | 0.62 | 0.71 | 0.67 |
| orbit_thread_001 | 4 | 3 | 1 | 2 | 3 | 0.33 | 0.25 | 0.29 |
| orbit_thread_002 | 4 | 4 | 1 | 3 | 3 | 0.25 | 0.25 | 0.25 |
| orbit_thread_003 | 5 | 6 | 2 | 4 | 3 | 0.33 | 0.40 | 0.36 |
| orbit_thread_004 | 7 | 10 | 5 | 5 | 2 | 0.50 | 0.71 | 0.59 |
| orbit_thread_005 | 4 | 4 | 3 | 1 | 1 | 0.75 | 0.75 | 0.75 |
| quill_001 | 7 | 11 | 5 | 6 | 2 | 0.45 | 0.71 | 0.56 |
| quill_002 | 6 | 10 | 3 | 7 | 3 | 0.30 | 0.50 | 0.37 |
| quill_thread_001 | 3 | 4 | 2 | 2 | 1 | 0.50 | 0.67 | 0.57 |
| **Total** | **108** | **152** | **64** | **88** | **44** | **0.42** | **0.59** | **0.49** |

Meetings: 48 TP / 71 FP / 31 FN (P 0.40, R 0.61). Email threads: 16 / 17 / 13 (P 0.48, R 0.55).
The full item lists (matched, missed, spurious) are in `docs/eval/extraction_v5_full.json`.
Cost of the run: 261 model calls for 326 episodes (about 66 trivial or read-back episodes skipped, one JSON retry), 749k input tokens, 23k output tokens, 65 min wall time, no 429s with the pacing below.

Reproduce:

```bash
set -a; . ./.env; set +a
UV_CACHE_DIR=D:/uv-cache uv run --package ingest python -m ingest.eval --backend gemini --prompt-version v5 --tpm 7900 --show-misses
# subset: --files orbit_002,orbit_005  ·  local model: --backend ollama --model gemma4:e4b  ·  JSON: --out path.json
```

## Typical remaining errors

1. **Same fact, different wording (about a third of the false positives come paired with a miss).** Examples: `Orbit | requires | audit log retained for 7 years` against gold `payments service | requires | audit log retained 7 years`, `onboarding tour | scope_includes | 3 cards` against `uses_pattern | three cards`, `newsletter | status | no sponsors until 5000 subscribers` against `decided`, and `launch post | status | cut from launch post if legal slips` against `decided | publish without the pricing paragraph if legal slips again`. Under the strict rule each is FP + FN. A lenient matcher (same subject and predicate family, object token overlap) would score these as hits. We kept the strict contract.
2. **Details and side facts the gold does not label.** These are the contents of the accessibility checklist (orbit_003: 4 `requires` items from Sana's explanation), "agents share territories", "cost estimate requires BigQuery numbers", and vendor sandbox timings. Gemma treats "facts to remember" broadly. Neither the importance test nor the `requires` definition fixed it.
3. **Restatements across meetings.** In the eval, "Facts already recorded" covers only the current file, so a member restating a kickoff date ("onboarding screens due the 19th" in orbit_003, "UPI flow due the 25th" in orbit_003) looks new. In the pipeline these become confirmations, not new facts, so the eval overstates this error.
4. **Kind disagreements.** A member restating a decision is a `fact` in the gold (Rahul's Razorpay restatement), but the lead's restatement in email is a `decision`. A lead's report that something arrived is a completion. External approvals are facts. We encode the rules we could state cleanly; the remainder is noise from a rule-by-rule gold.
5. **Model date errors despite the calendar.** "the pilot starts October 20th ... so the 16th really is the date" became 2026-10-16. Spoken weekday-only dates are now corrected in code.
6. **Bug found after the final run (fixed, not re-scored):** Gemma sometimes emits `"kind": "lesson"`. The item failed validation and was dropped, so all 3 lessons in `orbit_006` were lost (the model did extract them). `models._KIND_SYNONYMS` now maps `lesson` to `decision` (and `requirement`/`customer` to `fact`, `completion` to `commitment`). The object wording would still need to match exactly ("confirm vendor constraints with customer compliance team" against the gold's longer sentence), so the expected gain is 0 to 3 items. Per the protocol this was not re-scored.

Honest assessment: with strict exact-match scoring, a 26B model at about 2.6k tokens per episode, and a gold set where wording and kind follow conventions that are not always derivable from the text, we reached P 0.42 / R 0.59. The demo depends on two chains: UPI `due` (24 to 25 to 28) and the payments vendor (Razorpay to PayU). Both need the right subject and predicate on 6 specific items. Gold replay guarantees that. Real extraction could get there, but it would also add many extra active facts.

## Rate limit observed

- A burst of 16 tiny calls on one key at about 56 requests/min gave zero 429s, so requests per minute do not bind at this scale.
- Every 429 named `GenerateContentInputTokensPerModelPerMinute-FreeTier` with `quotaValue` 16000: 16k input tokens per minute for the model, shared across both keys (they hit their limits together). The other agent's report agreed.
- `ingest/llm_client.py` paces on estimated input tokens per key (`--tpm`, default `LLM_TPM` or 15000). With two keys, `--tpm 7600` to `7900` keeps the pair under 16k. Result: 0 to 3 429s per run, about 4 calls/min at 2.6 to 2.9k input tokens per call.
- Without token pacing (v1/v2 runs at `--rpm 15` only), 9 and 38 429s and about 5.6 calls/min with long cooldowns.

## Seeding

- `data/seed.py --extract gold` (default) replays the gold labels whatever `LLM_BACKEND` is. `--extract real` runs `make_extractor` (v5) with the model supersession judge. On Gemini it uses the paced `GeminiClient` with the same keys. It refuses to run with `LLM_BACKEND=fake`.
- Because the final precision (0.42) is under 0.70, the real-extraction reseed was **not** run. The main DB was re-seeded at the end with `LLM_BACKEND=fake EMBED_BACKEND=onnx ... seed.py --tenants orbit,nimbus,quill --reset` (17 files, 0 failures).
- Verified on 6379 (orbit): the `UPI flow | due` chain is 2026-09-24 (superseded) to 2026-09-25 (superseded) to 2026-09-28 (active, valid from the 2026-09-17 14:02 email), and `payments service | uses_vendor` is Razorpay (superseded) to PayU (active).
- The seed now prints a warning for every episode whose extraction call failed (`stats.failed_episodes`) and exits non-zero, so a real-extraction seed cannot lose facts silently.

## Pipeline fix made alongside (supersession of multi-valued predicates)

Facts with the same `subject|predicate` used to supersede each other for every predicate. For example, the three `Orbit | lesson` facts replaced one another, and `Orbit | requires | data residency` replaced the accessibility checklist. Now only `due`, `owner`, `uses_vendor`, `uses_pattern` and `status` are single-valued (`pipeline.SINGLE_VALUED_PREDICATES`). Every other predicate (`lesson`, `requires`, `scope_includes`, `customer`, `decided`) adds a value next to the others, and supersedes only when the item carries a `supersedes_hint`. The hinted target is the active fact whose object the hint names, otherwise the latest one. In the gold seed, all three lessons and both `Orbit | requires` facts are active. `newsletter | decided` still moves Thursdays to Tuesdays, while "no sponsors until 5000 subscribers" stays active beside it. Tests: `test_ingest_pipeline.py::test_multi_valued_*`, `test_lessons_and_requirements_do_not_supersede_each_other`.

## Open items for other owners

- **Resolved by Oct 9 audit:** `51_open_commitments` now returns both the resolved `owner` and original `speaker`. Earlier finding: the query returned `owner` but no speaker. The ingest side already passes `speaker_id` for every fact, commitments included. In the seeded DB each commitment has both `STATED_BY` and `OWNED_BY` edges (checked: `upi flow|due` gives spk_priya / spk_priya). The query needs to project the `STATED_BY` person if the UI wants it.
- **Resolved:** API imports use `make_extractor(llm)`; the Oct 9 audit also switched FactAgent to that current-version factory. Extraction scores above were not remeasured.
- `offline mode | uses_pattern`: "SQLite cache with sync queue" to "last-write-wins per field" is recorded as a supersession by the heuristic judge in gold replay. It is arguably a refinement (conflict handling added to the cache design). It is unchanged here because `uses_pattern` is single-valued by request.

## v5 rescored with normalised matching (2026-10-12, offline, no model calls)

The v5 items saved in `extraction_v5_full.json` were re-scored with the current matcher
(`python -m ingest.eval --rescore docs/eval/extraction_v5_full.json`). Two things changed in the eval:
the gold side now goes through the pipeline's own `canonicalize_object` (number words to digits,
completion words, articles) before comparison, and a partial-credit view was added next to strict.

**Strict** (kind, speaker, subject, predicate and canonicalised object all equal): TP 64, FP 88, FN 44,
**P 0.42, R 0.59, F1 0.49**: unchanged. Every near-miss that the object normalisation repairs ("three
cards" against "3 cards") also disagrees on predicate or kind, so the strict count does not move.

**Partial credit** (same episode, same canonical subject, predicate within `{decided, status}` or
`{requires, uses_pattern, scope_includes}`, object token-F1 >= 0.5; dates must be equal; kind and
speaker free): TP 75, FP 77, FN 33, **P 0.49, R 0.69, F1 0.58**.

| File | Strict P / R | Partial P / R |
|---|---|---|
| nimbus_001 | 0.50 / 0.62 | 0.60 / 0.75 |
| nimbus_002 | 0.36 / 0.80 | 0.36 / 0.80 |
| nimbus_thread_001 | 1.00 / 1.00 | 1.00 / 1.00 |
| orbit_002 | 0.50 / 0.60 | 0.58 / 0.70 |
| orbit_003 | 0.24 / 0.67 | 0.35 / 1.00 |
| orbit_004 | 0.23 / 0.38 | 0.23 / 0.38 |
| orbit_005 | 0.42 / 0.53 | 0.42 / 0.53 |
| orbit_006 | 0.62 / 0.71 | 0.69 / 0.79 |
| orbit_thread_001 | 0.33 / 0.25 | 0.67 / 0.50 |
| orbit_thread_002 | 0.25 / 0.25 | 0.25 / 0.25 |
| orbit_thread_003 | 0.33 / 0.40 | 0.67 / 0.80 |
| orbit_thread_004 | 0.50 / 0.71 | 0.60 / 0.86 |
| orbit_thread_005 | 0.75 / 0.75 | 0.75 / 0.75 |
| quill_001 | 0.45 / 0.71 | 0.45 / 0.71 |
| quill_002 | 0.30 / 0.50 | 0.50 / 0.83 |
| quill_thread_001 | 0.50 / 0.67 | 0.50 / 0.67 |
| **Total** | **0.42 / 0.59** | **0.49 / 0.69** |

Slot-wise agreement (an extracted item's field value occurs in a gold item of the same episode; P over
152 extracted, R over 108 gold):

| Slot | Hits | P | R |
|---|---|---|---|
| kind | 86 | 0.57 | 0.80 |
| speaker_id | 95 | 0.62 | 0.88 |
| subject | 80 | 0.53 | 0.74 |
| predicate | 80 | 0.53 | 0.74 |
| object | 70 | 0.46 | 0.65 |

Reading: 11 of the 44 strict misses are the same statement with a different predicate label or a
paraphrased object in the right episode; 33 are real misses. Kind is the weakest agreed slot after
object (members' restatements labelled as decisions, completions labelled as facts), which is the
rule-by-rule part of the gold. The pipeline changes made alongside (dialogue-window extraction,
per-item read-back filter, "decisions since" no longer a skip cue, qualifier-only subject snapping)
were not re-measured against the model; the fake-backend replay stays 129/129 strict and partial.
