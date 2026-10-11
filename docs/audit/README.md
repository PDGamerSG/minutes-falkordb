# October 9 audit evidence

- `pytest-2026-10-09.txt`: final full test output, real FalkorDB 6.0.1 available on localhost:6389; no live LLM calls.
- `api-smoke-2026-10-09.json`: observed HTTP answers, source counts, graph-triggered task trace, simulated issue and 25-way claim race. Synthetic Orbit/Nimbus data, gold extraction replay, scripted agents and test embeddings. Historical source output was refreshed after its final provenance correction.

Frontend frozen install, typecheck, lint and production build also passed. The API image built, started against the same database and returned health, 15 stored benchmark runs and the corrected historical answer. No hosted performance measurement or real issue creation occurred.

See [the readiness report](../track3-readiness.md) for limitations, eligibility and research sources.

## October 10 interactive editor follow-up

- `pytest-impact-editor-2026-10-10.txt`: **234 passing backend tests**, including tenant-scoped owner choices and adopting current evidence while retaining draft history. Real FalkorDB 6.0.1 was available on port 6389; API/ingestion cases also use deterministic fakes.
- `impact-editor-smoke-2026-10-10.json`: browser-created synthetic work and independent HTTP checks across **Needs review → Aligned → Closed**. A versioned dependency note was created at each change; the original draft remained in history; an aligned draft request returned 409. The five-item Orbit fixture was preserved.
- Browser rehearsal: explicit Priya ownership, Razorpay baseline, PayU current value, local follow-up restored after reload, actual graph (5 nodes / 4 edges) and executed Cypher inspected, dependency note and current-decision transcript opened. At 390 × 844, the overview and form had no horizontal overflow; Tab moved from title to owner with visible focus, and Escape dismissed the dialog. This is focused coverage, not a complete accessibility audit.
- Final review found that the bounded 500-fact list could omit an existing item's evidence. The editor now retains its baseline/current facts and deduplicates by ID, preferring refreshed list data. A one-off Node assertion against the actual picker expression failed before the fix and passed afterward, including retracted-baseline handling. The graph-backed reproduction confirmed the list omitted both referenced facts. The native preview later encountered an Electron renderer error; the post-fix picker check was performed in Node, not claimed as a browser retest.
- Final frontend lint and production build (including TypeScript) passed. No live extraction evaluation, hosted deployment or external communication was performed.
- Mobile screenshots: [completed work](impact-editor-mobile-2026-10-10.png) and [edit dialog](impact-editor-form-mobile-2026-10-10.png).

## October 10 follow-up

- `pytest-impact-2026-10-10.txt`: 232 passing backend tests after decision impact and ACL restart recovery.
- `impact-smoke-2026-10-10.json`: current impact and draft persistence checks over real HTTP/FalkorDB.
- Frontend redesign verification and visual artifacts are recorded in [frontend-design.md](../frontend-design.md).
