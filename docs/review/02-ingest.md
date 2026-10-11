# Backend review 2: ingestion pipeline and seed (2026-10-12, read-only)

Scope: `packages/ingest/**`, `data/seed.py`, and their callers in `apps/api/ingest_service.py`, `routes/meetings.py`, `routes/email.py`. Baseline: 81 tests pass; scratch graph seeded from gold with EmbeddingGemma. No Gemini calls were made.

Verified good: chunker merge, window and gap math; `t_occurred = started_at + start_ms`; timezone-aware timestamps enforced; the seeded graph is consistent (no single-valued key with more than one active fact, no superseded fact without an incoming SUPERSEDES, no NEXT branches, no episode without a speaker or sender, no case-duplicate entities; the UPI chain crosses meeting -> meeting -> email correctly; 14 CONFIRMED_BY, 2 PRECEDENT_FOR); `jobs.py:76-81` already marks a job failed when `failed_episodes` is non-empty; API startup is strict about embeddings (`main.py:39`).

## 1. Correctness

1. **HIGH. Re-import with changed extraction output silently rewrites existing facts in place (id collision).** `pipeline.py:466` builds `fact_<episode>_<index>`; `cypher/11_ingest_fact.cypher` MERGEs by id then SETs subject, predicate, object and key. Evidence: import episode 0 with item A, re-import with item B at index 0: the same node now holds an unrelated triple, the old decision is gone, no event says so; in FalkorDB it keeps its SUPERSEDES edges and status. Triggers: the "retry the import" advice after failed episodes, a prompt-version change, non-deterministic model output. Fix: content-derived ids (`fact_<episode>_<hash(key|object)>`), or check the existing node's key and allocate a fresh id on mismatch.
2. **HIGH. Positional episode ids `ep_<container>_<seq>` make re-chunking corrupt the episode chain.** `chunker.py:67-69`, `cypher/10_ingest_episode.cypher`. Evidence: two 25 s segments chunked at 10/20 then re-imported at 30/60: `_000` becomes the merged text, `_001` survives as a stale duplicate, facts DERIVED_FROM `_000` now point at different text. Fix: include the first segment index and a text hash in the id, or delete the container's episodes (and tombstone their facts) when the segment set differs.
3. **MEDIUM. `episode.ingested` is published N+1 times against the real hive, with two payload shapes.** `pipeline.py:190-201, 261-272` publish per episode directly; `hiveboard/memory.py:121-127` publishes once per batch; `publishes_memory_events` only suppresses fact events. Fix: one publisher.
4. **MEDIUM. `fact.superseded` payload differs between FakeHive and RealHive; mid-chain inserts emit "created" events for facts born superseded.** `workers.py:66` checks `head_changed`, never present with RealHive; `insert_fact_in_chain` publishes `fact.created` and `commitment.created`. Fix: single publisher, payload parity test.
5. **MEDIUM. Roster join collides on the email local part.** `email_format.py:153-158` synthesises `spk_<local>`; a message from `priya@gmail.com` resolves to the roster's `spk_priya`, attributing an external sender to the internal person. Fix: ids from the full address (`ext_<hash>`), join only on exact email.
6. **MEDIUM. mbox edge cases reject the whole upload; no threading.** Duplicate Message-ID (sent plus received copy) and a reply dated before its parent both raise; every mbox becomes exactly one thread with the earliest subject because `References` is never read. Fix: dedupe, null `in_reply_to` on clock skew, group by References/In-Reply-To then subject.
7. **MEDIUM. HTML-only bodies keep CSS, entities and the quoted reply.** `email_format.py:207-219` strips tags with a regex: style text leaks, entities are not decoded, blockquotes collapse so `strip_quoted` cannot fire and the quoted text is attributed to the sender. Fix: `html.parser`, drop style and script, newlines for block tags, `> ` prefix for blockquotes, `html.unescape`.
8. **LOW. `strip_quoted` over- and under-strips.** "On balance I agree with what Rahul wrote:" strips everything; a bare `--` line drops the rest; a Gmail header wrapped over three lines is not detected. Fix: require a date token, allow a 3-line lookahead, treat only `-- ` as a signature.
9. **MEDIUM. Fuzzy subject snapping merges distinct subjects into one supersession key.** `vocab.py:207-217`: "Orbit launch", "Orbit retro", "Orbit roadmap" all snap to "Orbit"; "payments service spec" to "payments service". Because `due`, `owner` and `status` are single-valued, "Orbit launch due Nov 1" would supersede any `orbit|due` fact. Fix: snap only on qualifier words or when the known name has two or more words.
10. **LOW. Canonical display names diverge from the vocabulary the prompt asks the model to copy.** `models.py:309-318` title-cases ("Payments Service" stored, "payments service" in the prompt). Fix: keep vocabulary spelling when snapped.
11. **MEDIUM. Gold replay and real extraction disagree on supersession hints.** `gold.py:504` emits a JSON hint; `pipeline.py:599-606 _hinted_target` expects the old object text; the hint resolves to the latest active fact rather than the named one. The demo graph gets the right answer only because chain order happens to match; live extraction uses `judge_supersession` instead, so the demo never exercises the production path. Fix: same hint format in both, or accept both.
12. **LOW. Validation quirks.** List objects joined into one fact; confidence defaults to 0.8 and v5 never asks for one, so `hive.score`'s importance term is a constant (gold facts 0.95).
13. **LOW. Date handling.** `dayfirst=False` for an IST team (`12/09/2026` becomes Dec 9); `date_to_ms` stores due dates at UTC midnight (05:30 IST) so "overdue" fires early; `correct_weekday` rewrites every `due` object in an episode that names one weekday; `is_readback` skips a whole episode on "to recap" even when new information follows. Fix: tenant timezone and dayfirst policy, per-item weekday correction, per-item read-back filter.
14. **LOW. A single zero-length or blank STT segment rejects the whole recorder file.** `recorder_format.py:171-180`. Fix: drop with a warning.
15. **LOW. The 30 to 60 s episode contract is nominal.** Scratch graph: 258 utterance episodes, average 7.2 s, 257 under 30 s, because speaker changes always split. Consequence: one LLM call per 7-second line (261 calls for 326 episodes), and a question and its answer land in different calls.
16. **LOW. Prior-fact context is silently truncated; entity matching is quadratic; `known_entities` is never populated from the graph.** `pipeline.py:358` uses the default `limit=200`; `list_entities` per episode; the prompt's "Known entities" slot only sees the hard-coded lists for orbit, nimbus and quill, so a new tenant gets "none yet".

## 2. Embedder

17. **HIGH. ONNX startup needs the network even when the model is fully cached.** `embed.py:132` calls `list_repo_files` before any cache lookup; with `HF_HUB_OFFLINE=1` and a warm cache it raises, and because API startup is strict the API refuses to start without internet (hackathon Wi-Fi failure mode). Fix: `local_files_only=True` first, list the repo only on a miss.
18. **MEDIUM. No guard against mixing embedding spaces.** Nothing records which model produced the stored vectors; a fake-seeded graph queried with ONNX returns noise with no error. The library default is still `strict=False`. Fix: record `embedding_model` on the tenant row and refuse mismatches; flip the library default to strict.

Verified OK: prefixes match the EmbeddingGemma card (query vs relevant doc 0.655, irrelevant 0.214), L2 norm 1.0, dimension check raises on != 768, 6 concurrent threads on one session ran clean. Silent truncation at 1024 tokens is fine for emails, would cut document chunks.

## 3. Extraction quality (v5: TP 64, FP 88, FN 44)

32 of the 44 misses have a spurious item in the same episode: the model saw the fact and the triple failed strict equality. Rough split: 45 percent matching artefacts (paraphrase, plural, spacing, number words), 25 percent taxonomy or gold granularity (`decided` vs `status`, `requires` vs `uses_pattern` vs `scope_includes`, sibling entities), 25 percent wrong model output, 5 percent caused by the pipeline's own filters. Two guaranteed misses: the standup routine episodes contain "decisions since", which is in `_READBACK_CUES`, so `is_readback` skips them. One eval artefact: `canonicalize_object` writes digits but `eval.normalize_text` does not, so gold "three cards" can never match "3 cards". On the false-positive side, 20 of 88 are statements by non-leads that gold treats as not-facts.

Fairer secondary metric: slot-wise precision and recall per field; partial-credit triples (same episode, same canonical subject, predicate equivalence groups, object token-F1 >= 0.5); episode detection rate. All computable from the existing JSON.

Cheap levers, by expected gain per cost: (a) dialogue-window extraction (3 to 5 consecutive episodes per call, speaker-tagged) for 4x fewer calls and the lead's ratification next to the member's proposal; (b) apply `canonicalize_object` to the gold side in the eval; (c) drop "decisions since" from the read-back cues or make read-back per item; (d) predicate equivalences by object shape; (e) umbrella demotion to the more specific known entity; (f) a cheap verifier pass on local gemma4:e4b ("does this speaker state this as new and settled here?") to cut false positives; (g) ask for confidence and calibrate it.

## 4. Robustness and performance

19. **MEDIUM. Partial failures leave episodes stored and force a full re-extract that hits finding 1.** `_extract_and_store` has no per-item try/except; a conflict from `supersede_fact` (two imports racing on one key) aborts the job after episodes and some facts are written; the retry re-runs every LLM call. LLM calls are strictly sequential. Fix: catch per-item exceptions into `failed_episodes`, skip episodes that already have facts on retry, bound upload size.
20. **LOW. Housekeeping.** `seed.py:576` sorts `started_at` as strings (mixed offsets sort wrong); `--skip` ignores unknown slugs silently; `routes/meetings.py:194` and `routes/email.py:338` create asyncio tasks without keeping a reference; `routes/board.py` writes a demo fact with object `'Friday'` without running `normalize_date`.

## 5. Test gaps

- Re-import with a different extraction result must not change an existing fact id's key or object.
- Re-import after a segmentation change leaves no stale episodes or NEXT branches.
- `episode.ingested` published exactly once per episode with the real hive; `fact.superseded` payload parity between the two hives.
- `synthesize_person` never collides with a roster id for a different address.
- mbox with duplicate Message-ID, a reply dated before its parent, and two unrelated subjects.
- HTML-only `.eml` with blockquote, style and entities; `strip_quoted` with a wrapped Gmail header, "wrote:" mid-sentence, a bare `--` line.
- `canonicalize_subject("Orbit launch")` stays "Orbit launch"; `_hinted_target` with a gold-style hint selects the named old object.
- `correct_weekday` with two due items changes only the weekday one; read-back filter keeps a new dated commitment inside a recap.
- `OnnxEmbedder` loads with `HF_HUB_OFFLINE=1` from a warm cache; ingest and recall refuse a different embedding model than the tenant's.
- `_store_item` raising on episode k: job failed, earlier episodes stored, `failed_episodes == [k]`.
- Prior facts still include the key under test with more than 200 active facts; eval matches "three cards" against "3 cards".
- Blank or zero-length segments are dropped, not fatal; dayfirst and timezone policy tests; concurrent imports touching one key produce one active head.

## 6. Feature gaps judges may probe

| Gap | Status | Effort |
|---|---|---|
| Live audio upload (server-side STT plus diarization) | Missing; `audio_uri` is only served back | Cloud STT with diarization mapped to the recorder format: 4 to 6 h; local faster-whisper plus pyannote: 12 to 16 h |
| Document chunks (`doc_chunk`) | Schema only | 6 h: markdown, PDF and text chunker reusing Episode, a Document source container, why() source kind, UI icon |
| GitHub issues as a third source | Missing; `github_issue` is an output only | 6 to 8 h: REST fetch issues and comments into a thread-shaped container |
| Incremental re-sync of a changed source | Missing, and currently unsafe (findings 1 and 2) | 6 h: content-hash ids, diff by segment, tombstones, re-extract changed episodes only |
| PII redaction before storage | Missing | 4 h with presidio or regex plus a roster allow-list, before embedding and before the LLM call |
| Speaker identification across tenants | Missing by design | 4 h for a commons identity table keyed by email hash |
| Extraction confidence calibration | Missing (constant 0.8 live, 0.95 gold) | 3 h to request and bucket confidence; about a day for a verifier probability |

Worth a sentence to judges: the demo graph is gold replay, and three mechanisms differ between replay and live extraction (hint format, confidence, the judge function), so a live import on stage exercises code paths the seeded data never did.
