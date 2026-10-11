# Minutes: audit and Track 3 readiness

**Audit date: October 9, 2026. Target: Company Brain.**

Minutes fits Track 3: it connects people, meetings, email, decisions and commitments; answers ownership and historical questions; and uses a changed graph fact to trigger agent coordination. It is a working local prototype, not yet a validated company deployment or a proven competitive submission. No audit can establish that every issue has been found.

The strongest pitch is: **“Who owns this, why did it change, and what should happen next?”** Demonstrate one complete chain from source evidence to changed decision to accountable follow-up. Multiple agents and benchmark charts support that story but should not displace it.

## Eligibility comes first

The [official rules](https://www.wemakedevs.org/hackathons/falkordb/rules), checked October 9, say in rule 8: “The main coding and design work must begin after the hackathon starts.” The allowed preparation includes ideas, notes, graph sketches and diagrams. Rule 9 says original work completed during the hackathon will be judged.

The repository already existed and this audit also occurred before October 15. These changes are **pre-event work**. The team needs an organizer ruling on permitted reuse before representing this as an eligible entry. No organizer has been contacted by the agent, and no permission has been inferred. Rules may change before the event; check again.

Rules 2–3 require FalkorDB to be central. Demonstrate the real database, not `HIVE_BACKEND=fake` or the frontend fixtures. Rules 10–13 require public source, setup/model/query documentation, a working demo video, deployment or complete local instructions, declared track, AI disclosure, and participant understanding. This workspace has no `.git` directory; this audit did not publish a repository, create commits, submit an entry or deploy a public service.

## Track 3 fit

| Track requirement | Evidence in Minutes | Limit |
|---|---|---|
| Connected organizational knowledge | Meeting/email episodes and an explicit delivery manifest connect people, decisions, commitments, work and provenance | No production Slack or ticket-ingestion connector |
| Who owns what / who knows what | Explicit ownership query separate from participation ranking | Ambiguous identities stay unresolved; ownership still depends on accurate extraction |
| Trace decisions to their source | `DERIVED_FROM`, `STATED_BY`, `SUPERSEDES`; Why panel opens source messages | Source-ID validation does not prove every sentence is entailed by its citation |
| Keep knowledge current | Supersession, completion filtering, historical queries | Real extraction accuracy remains below the existing target |
| Act on company context | Explicit work dependency + supersession → accountable local draft; changed date → Scheduler → FollowUp | Scripted demo agents; drafts stay local and issues are simulated |
| Remember across sessions | Conversations and facts persist in tenant graphs | HTTP authentication and tenant membership checks are absent |

## Issues fixed

| Issue | Result | Verification |
|---|---|---|
| An announcer could be presented as the owner despite an explicit assignment | Assignment facts take precedence; exact identity match; conflicting/unknown assignments do not fall back to the announcer | Real Cypher and API tests; Decision Log → Rahul, Payments Service → Priya |
| Fake ingestion lost `owner_id` | Test backend preserves ownership and mirrors the normal speaker fallback | Original failing ownership/session tests now pass |
| Historical answers could receive present-day dossier evidence | Time-selected facts bypass modern history expansion; original provenance is filled without replacing historical values | Future-leakage and real-row-shape regressions; Sep 10 answer cites kickoff and Sep 24 only |
| A repeated source import produced NEXT cycles | Predecessor lookup is bounded by the incoming episode sequence | Real database replay regression; normal append still works |
| A model could return uncited prose despite retrieved evidence | Missing/unknown citations trigger the existing grounded fallback | Missing and fabricated citation tests |
| Partial extraction failures looked completed | Jobs retain partial stats and report extraction failure; FactAgent fails the task | Job and worker regressions |
| FactAgent used an older default extraction prompt | Uses the current extractor factory | Agent tests; real-model quality not remeasured |
| Blank chat requests reached the agent | Whitespace is rejected and valid text is trimmed | HTTP validation regression |
| Database ping could be green while graph queries or startup failed | `/health` returns 503 and reports startup/query failure | Health tests |
| Requested embeddings silently changed to test or another backend on load failure | API/seed startup uses strict model initialization; explicit fake mode remains available | Startup failure and explicit-fake regressions |
| Chat state survived URL session changes | Chat is keyed by tenant and session; restoration errors surface; stale requests cannot redirect a new session | Browser reproduction and retest; persisted history restores |
| Tenant page state could remain from the old team | Main content remounts by tenant | Code review and frontend build |
| Demo/backend status was unclear; SSE loss marked data as mock | Visible scripted-answer/test-embedding labels; SSE loss preserves the selected data mode | Browser/API inspection and frontend checks |
| Broken setup details | Correct `6.0.1` image tag, synchronized pnpm lock, local API port 8080, platform-neutral cache example | Frozen install, real database launch, production web build |
| API image omitted stored benchmark results and sent unnecessary local files | Added build exclusions and packaged `docs/bench` | Image built and started against real DB; 15 stored benchmark runs returned |
| README/demo overclaimed deployment, security and live extraction | Rewritten Track 3 setup/demo, explicit limitations and AI/pre-event disclosure | Documentation checked against code, local behavior and rules |

The episode replay fix covers unchanged-source reimport and normal append. It does not reconcile arbitrary edits to an already imported sequence. Historical answers use source validity time; do not promise complete knowledge-at-ingestion-time behavior through every HTTP endpoint.

## Verification performed

- **220 tests passed** with `FALKORDB_URL=falkor://localhost:6389 uv run --all-packages pytest -q --tb=short --show-capture=no`. Hiveboard integration tests used real **FalkorDB 6.0.1**; API/ingestion tests also exercise deterministic fakes. These are not 220 live-model tests.
- **17 synthetic source files** seeded into Orbit, Nimbus and Quill without failures: 383 episodes, 20 facts, 46 decisions, 48 commitments, 13 supersessions reported by the seed. Extraction used gold-label replay and fake embeddings.
- Frontend **frozen install, typecheck, ESLint and production build passed**.
- Real HTTP checks: correct two owners; current and historical UPI answers; session reload; no Orbit owner in Nimbus; graph-triggered completed handoff with simulated artifact; **one winner / 24 losers** in a 25-way claim race.
- Native browser checks: send/restore conversation; switch session without retaining prior messages; expand Why/Cypher; open the original assignment email; no horizontal document overflow at 390 px for the tested chat/Why layout. This is focused interaction coverage, not a complete accessibility or all-page visual audit. Screenshot capture was unavailable in the native preview during this run.
- API Docker image built with repository-root context, started against the real database, and returned healthy status and stored benchmark results. The image was rebuilt after the final historical-provenance correction. Hosted operation was not tested.
- **Python Ruff is not clean:** 68 findings remain, largely existing FastAPI `Depends` defaults, mutable class annotations and style/logging rules. Do not represent this as a passing Python lint gate.

The final test output and synthetic HTTP smoke results are saved in [docs/audit](audit/). Models and hosted credentials were not exercised. No external issue, email or Slack message was sent.

## What past sponsor showcases suggest

Research used the official event/rules, FalkorDB's public blog index (queries `hack`, `hackathon`, `company`), two substantive event recaps, and linked project READMEs. This is a bounded search of public sources, **not a complete inventory of every event FalkorDB has attended**. A sponsor write-up shows what the sponsor chose to highlight; it is not a published scoring rubric or a guarantee of this jury's preferences.

| Primary source / project | Observed behavior | Implication for Minutes |
|---|---|---|
| [Memory Meets Motion recap](https://www.falkordb.com/blog/memory-meets-motion-the-falkordb-standouts/), Aug 18, describing Aug 3 event; [Atrium](https://github.com/nathansso/Atrium), first place overall | Models misconceptions as nodes; a two-hop query changes which students are taught together | Show a relationship changing an answer or action; a graph picture alone adds little |
| Same recap; [Drift](https://github.com/sharique2004/mmm-demo) | Later meeting decisions lead to governed updates on affected GitHub issues | Closest precedent. “Meeting changes → ticket update” alone is not a new idea |
| Same recap; [Continuum](https://github.com/vnmoorthy/continuum-memory-meets-motion) | Connects people/projects/decisions and unfinished work | Useful product framing; its mirrored-storage approach is not a template for this event's central-graph requirement |
| Same recap; AgentCourt and DealBench | Stored precedents affect later actions; DealBench explicitly avoids canned dialogue fallback in live runs | Prove memory changes later behavior and make simulated operation obvious |
| [Hack for Humanity recap](https://www.falkordb.com/blog/how-builders-at-hack-for-humanity-used-falkordb-to-solve-real-community-problems/), Sep 30, describing Sep 19 event; [Board of SuperVision](https://github.com/LabGuy94/boardofsupervision) | 66 public meetings connected to structured votes, quotes and timestamp evidence; bounded read-only queries and a published eval | Source verification and measured answer quality are directly relevant to a Company Brain |
| Same recap; LOCAL GACHA | Two-hop recommendations return the actual shared reason | Return the evidence path that justifies the recommendation |
| Same recap; Can I park here? | Graph finds eligible alternative curbs; readiness waits for import | Graph results should change an outcome; incomplete ingestion must not claim readiness. Its cited award was Best Use of Photon, not evidence of a FalkorDB prize |

The recurring pattern is a narrow user problem, meaningful graph relationships, persistent state, inspectable sources, and an action or answer changed by those relationships. Those observations support improving the existing decision-history workflow rather than copying a winner's UI or adding unrelated agents.

## Highest-value next work

1. **Resolve eligibility and preserve provenance of the work.** Obtain the organizer's interpretation of pre-event reuse. Retain the Oct 9 audit date and honest AI disclosure. During the allowed window, document what the team actually builds and verifies.
2. **Validate live extraction and answers.** The recorded [extraction evaluation](eval/extraction.md) is P **0.42**, R **0.59**, F1 **0.49**, below its targets. It also discloses gold-derived canonical subject lists. Build an unseen meeting/email test set with speaker-versus-owner cases, reversals, completion and unknown answers. Freeze labels before tuning; report strict extraction and task-level answer accuracy separately. Gold replay must remain labeled.
3. **Demonstrate the implemented decision-impact workflow.** The [explicit delivery manifest](decision-impact.md) links work to a baseline fact, owner and versioned document. Actual `SUPERSEDES` paths determine review status. The fixture yields 3 review items, 1 aligned item and 1 closed item. Local drafts persist and stale requests fail. This is now implemented, not a proposed feature.
4. **Extend evaluation with unseen dependency documents.** Automated tests cover atomic import, reimport, missing/cross-tenant references, multiple supersession hops, conflicting current facts, unrelated facts, closed/aligned work, stale drafts and owner changes. A broader unseen evaluation remains future work; no improved real-model accuracy is claimed.
5. **Protect any deployed API.** Add identity, tenant membership authorization, operation permissions and bounded uploads/queries before company use. Database ACLs alone do not cover an admin-backed public API. Keep hackathon data within the rules' allowed public/synthetic scope. Real side effects need deliberate configuration and controls.
6. **Prepare a reproducible submission.** A public repository, correct setup, declared Track 3, three-minute video, disclosed modes, unseen-case results, and source links that judges can inspect. Hosted deployment is optional under the current rules when complete local instructions are provided.

Suggested four-person split during the eligible window: graph/impact semantics; ingestion/evaluation; answer/source UI; integration/demo/verification. Team members should all be able to explain the key Cypher and the owner-versus-speaker distinction.

**Assessment:** credible Track 3 foundation, with substantial correctness repairs completed. The largest competitive gains now depend on permitted original work, reliable live extraction, and evaluated live-model behavior on the implemented cross-source impact path. There is no evidence sufficient to predict a win.

## October 10 implementation follow-up

- Added the explicit work/decision/document/owner model and version-checked local drafts described above.
- Recovered missing Redis runtime ACL users after restart without resetting existing credentials, disabled users or graph contents. API startup validates access and suppresses worker startup on preparation failure.
- Full backend suite: **232 passed**, against real FalkorDB 6.0.1 plus the existing deterministic API/ingestion fakes. No live-model evaluation was run. Original 220-test evidence above remains a record of the earlier audit.
- Replaced the rejected UI direction with the user-selected Chrome direction: graphite surfaces, self-hosted display type, original reflective 3D knot, responsive overview, impact filters and evidence inspection. See [design notes](frontend-design.md) for verification and screenshots.
- The earlier eligibility, authentication, real extraction and baseline Python lint limitations still apply. The changes are local; no publication or external communication occurred.

## October 10 interactive decision-impact follow-up

The overview now supports connecting work and editing its explicit owner, baseline, rationale and status. Adopting the current decision moves reviewed work to **Aligned**; completing it moves it to **Closed**. Previous local drafts remain in history. The actual impact subgraph and executed Cypher are inspectable from the overview. The graphite/chrome/copper design is preserved.

The backend suite now reports **234 passing tests**. The API-backed browser rehearsal verified create → review-needed → persisted follow-up → adopt current evidence → aligned → completed, using a disposable synthetic tenant and real FalkorDB with scripted answers/test embeddings. Mobile layout and keyboard checks covered the new form. The existing five-item Orbit fixture remains intact. See [audit evidence](audit/README.md) and the [interactive rehearsal script](demo-script.md#interactive-decision-impact-rehearsal). This improves the reproducible decision-impact demo; it does not change the reported live extraction accuracy or resolve the eligibility/authentication gaps.
