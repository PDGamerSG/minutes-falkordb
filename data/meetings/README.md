# Scripted corpus: meetings and email threads

Everything in `data/meetings/` and `data/gold/` is synthetic and written by us. Three fictional teams, no real people, no real companies (`*.example` domains throughout). The meeting JSON follows `docs/contracts/recorder-format.md`; the email JSON follows `docs/contracts/email-format.md`; the gold labels follow the shapes at the bottom of each contract.

Audio: every meeting carries an `audio_uri` of `data/meetings/<slug>.wav`. The files are not in the repo yet (they are gitignored) and will be dropped in after recording. Until then `GET /meetings/{id}/audio` returns 404 and "play at timestamp" shows the transcript segment instead.

## Files

| Pattern | What | Count |
|---|---|---|
| `<tenant>_NNN.json` | meeting (recorder export: `meeting`, `speakers`, `segments`) | 10 |
| `<tenant>_thread_NNN.json` | email thread (`thread`, `people`, `messages`) | 7 |
| `<tenant>_roster.json` | `[{id, name, role, email}]`, the join key between sources; a seed file, never inferred | 3 |
| `../gold/<same slug>.json` | gold labels for every meeting and thread | 17 |
| `../generator/*.py` | the scripts that produced all of the above (not part of the app) | 5 |

The seed and the import endpoints should dispatch on the top-level key (`meeting` vs `thread`) or on the filename pattern; a plain `glob("data/meetings/*.json")` will also pick up rosters and threads.

## Who the people are

Speaker ids are stable across every file of a tenant. Emails are `<first name>@<tenant>.example`.

**orbit** (4 people, shipping the Orbit mobile app for an October 16 release)

| id | name | role | voice |
|---|---|---|---|
| `spk_aditya` | Aditya | lead | runs every meeting, says "Decision:" out loud, reads dates back at the end |
| `spk_priya` | Priya | backend | owns the payments service and the UPI flow; precise, admits slips early |
| `spk_rahul` | Rahul | mobile | owns offline mode and the app shell; casual, pushes back then agrees |
| `spk_sana` | Sana | design | owns onboarding; brings the accessibility checklist that reverses a decision |

External people appear only in email threads (not in the roster): `ext_meridian_compliance` Farah Siddiqui, `compliance@meridianbank.example` (thread 003) and `ext_razorpay_am` Nikhil Rao, `am@razorpay.example` (thread 004).

**nimbus** (3-person data team, warehouse migration): `spk_meera` Meera (data lead), `spk_dev` Dev (data engineer), `spk_anika` Anika (analyst).

**quill** (2-person content team, a newsletter): `spk_tara` Tara (editor), `spk_omar` Omar (writer).

nimbus and quill exist to show tenant isolation. Each has two meetings and one thread, with at least one supersession in each file after the first.

## Orbit timeline (all meetings at 10:00 +05:30)

| Date | Source | Title | What happens |
|---|---|---|---|
| Sep 07 | `orbit_001` | Kickoff | scope, owners, release date Oct 16, Razorpay, bottom tab bar, local-first offline; 7 dated commitments incl. UPI flow by Sep 24 |
| Sep 09 | `orbit_thread_001` | Onboarding wireframes | Sana shares five screens; Aditya approves with one change (tour: five cards to three) |
| Sep 14 | `orbit_002` | Standup 1 | routine shape; "move it to Friday": UPI flow Thu Sep 24 to Fri Sep 25; spike done; two new commitments; offline-payments question left open |
| Sep 16 | `orbit_003` | Design review | tab bar reversed to side drawer (Meridian 56 dp rule); the checklist becomes the baseline; 56 dp buttons follow the same precedent; last-write-wins per field |
| Sep 17 | `orbit_thread_002` | UPI flow timeline | Priya moves the UPI flow Fri Sep 25 to Mon Sep 28 by email (KYC lead time); Aditya acknowledges and sets a condition |
| Sep 18 | `orbit_thread_003` | Drawer vs checklist | Rahul asks Meridian compliance; Farah confirms 56 dp is hard, approves the drawer mockup; Aditya's sign-off commitment completes |
| Sep 21 | `orbit_004` | Standup 2 | same routine; onboarding screens done; Priya confirms the 28th in speech; code freeze Oct 9; stale open question |
| Sep 23 | `orbit_005` | Customer call recap | new entities (Meridian compliance team, Kestrel Logistics); Rahul restates Razorpay, Aditya reveals Meridian mandates PayU; decision supersedes the kickoff vendor |
| Sep 24 | `orbit_thread_004` | Switching to PayU | Priya tells Razorpay's AM; Aditya restates the PayU decision for the record; Rahul removes the SDK a day early |
| Sep 29 | `orbit_thread_005` | Retro prep, issue #42 | Aditya assigns the decision log to Rahul, due Fri Oct 2, tracked at `https://github.com/orbit-app/mobile/issues/42`; Priya reports the UPI flow done on Mon Sep 28 |
| Sep 30 | `orbit_006` | Retro | "why did we choose the side drawer again?", wrong answer from memory, corrected; three lessons; November scope |

nimbus: `nimbus_001` Sep 08 kickoff (BigQuery, dbt, nightly job 02:00, pipeline by Sep 18), `nimbus_002` Sep 15 sync (pipeline to Sep 23, job to 03:00), `nimbus_thread_001` Sep 22 (pipeline to Sep 25, dashboard to Sep 29).
quill: `quill_001` Sep 09 planning (Thursdays, Ghost, launch post Sep 22), `quill_002` Sep 16 sync (launch post to Sep 25, Tuesdays), `quill_thread_001` Sep 21 (launch post to Sep 29).

Weekdays: orbit standups are Mondays (Sep 7, 14, 21), the design review, customer recap and retro are Wednesdays (Sep 16, 23, 30); nimbus syncs are Tuesdays (Sep 8, 15); quill syncs are Wednesdays (Sep 9, 16). Every weekday spoken or written in the corpus matches the real 2026 calendar.

## The two chains the demo relies on

**UPI flow, `due`** (subject `UPI flow`, predicate `due`; speaker is Priya at every hop)

| Hop | Object | Source | Index | Kind of hop |
|---|---|---|---|---|
| 1 | 2026-09-24 (Thu) | `orbit_001` segment 23 (2:35) | speech | original commitment |
| 2 | 2026-09-25 (Fri) | `orbit_002` segment 6 (0:38) | speech | supersedes hop 1: "move it to Friday. Friday the 25th" |
| 3 | 2026-09-28 (Mon) | `orbit_thread_002` message 0 (Sep 17 14:02) | email | supersedes hop 2, crosses sources: "Monday the 28th" |
| 4 | 2026-09-28 (Mon) | `orbit_004` segment 16 (1:33) | speech | confirms hop 3 (same object, `confirms` hint, no new SUPERSEDES edge) |
| end | completed | `orbit_thread_005` message 2 (sent Sep 29, "done as of last night, Monday the 28th") and `orbit_006` segment 2 (Sep 30) | email, speech | `status = completed` |

**payments service, `uses_vendor`**

| Hop | Object | Source | Index | Kind of hop |
|---|---|---|---|---|
| 1 | Razorpay | `orbit_001` segment 20 (2:13), Aditya | speech | decision with rationale (fastest UPI SDK, prior experience) |
| restated | Razorpay | `orbit_005` segment 12 (1:15), Rahul | speech | the contradiction trigger: an active fact restated seconds before it is overturned |
| 2 | PayU | `orbit_005` segment 29 (3:07), Aditya | speech | supersedes hop 1, `reverses_meeting: mtg_orbit_001`, rationale: Meridian compliance mandate |
| restated | PayU | `orbit_thread_004` message 0 (Priya) and 2 (Aditya) | email | told to the vendor; message 0 carries `supersedes` for the cross-source eval, message 2 carries `confirms` |

**Orbit navigation, `uses_pattern`**: bottom tab bar (`orbit_001` seg 40, Aditya, rationale discoverability) reversed to side drawer (`orbit_003` seg 14, Aditya, rationale Meridian 56 dp minimum touch target), `reverses_meeting: mtg_orbit_001`. The drawer decision is then the precedent for two more decisions in the same meeting (`follows_precedent`). Farah states the underlying requirement herself in `orbit_thread_003` message 1.

## Gold label conventions

Shape per contract: `{"meeting_id" | "thread_id", "items": [{kind, subject, predicate, object, speaker_id, segment_index | message_index, ...}]}`. Indices are 0-based. Optional hints, ignored by the matching rule but used by the chain checks and the demo:

- `supersedes: {subject, predicate}` on the item that replaces an earlier active item with the same key and a different object.
- `reverses_meeting: "mtg_orbit_001"` on decisions that explicitly reverse a decision from a named earlier meeting.
- `follows_precedent: {subject, predicate}` on decisions that cite an earlier decision as their rationale (the `PRECEDENT_FOR` edge, pointing the other way).
- `confirms: {subject, predicate}` on restatements that carry the same object as the active item (no supersession should be created).

Predicates are a closed set: `due`, `owner`, `scope_includes`, `uses_vendor`, `uses_pattern`, `status`, `requires`, `customer`, `decided`, `lesson`. Dates are ISO `YYYY-MM-DD`. Subjects are normalised, consistent across files (`UPI flow`, `payments service`, `Orbit navigation`, `October release`, `offline mode`, `onboarding screens`, `side drawer`, `PayU integration`, ...). Completions are `kind: commitment, predicate: status, object: completed`, stated by whoever reports them.

Deliberately not labelled: open questions (the offline-payments question in `orbit_002`), Aditya's end-of-meeting read-backs (the owner's own statement carries the label), and Sana's incorrect recollection in `orbit_006` segment 13 (it is a question that gets corrected; Priya's correction at segment 16 is labelled).

Totals: 100 gold items across the 10 meetings (40 decisions, 44 commitments, 16 facts) and 29 across the 7 threads.

| file | segments / messages | gold items |
|---|---|---|
| orbit_001 | 66 segments, 6:43 | 21 (13 decisions, 7 commitments, 1 fact) |
| orbit_002 | 46 segments, 4:33 | 10 |
| orbit_003 | 52 segments, 6:01 | 6 |
| orbit_004 | 43 segments, 4:27 | 8 |
| orbit_005 | 51 segments, 5:41 | 15 |
| orbit_006 | 52 segments, 5:54 | 14 |
| nimbus_001 / 002 | 30 / 22 segments | 8 / 5 |
| quill_001 / 002 | 27 / 25 segments | 7 / 6 |
| orbit_thread_001..005 | 5, 4, 5, 5, 5 messages | 4, 4, 5, 7, 4 |
| nimbus_thread_001 / quill_thread_001 | 4 / 3 messages | 2 / 3 |

## Planted events

Index = `segment_index` for meetings, `message_index` for threads. Time = offset into the meeting, or send time for email.

| Source | Index | Time | Speaker | Demonstrates | Item |
|---|---|---|---|---|---|
| orbit_001 | 5 | 0:27 | Aditya | entity (customer) | Orbit `customer` Meridian Bank |
| orbit_001 | 20 | 2:13 | Aditya | decision with rationale, later superseded | payments service `uses_vendor` Razorpay |
| orbit_001 | 23 | 2:35 | Priya | start of the UPI chain | UPI flow `due` 2026-09-24 |
| orbit_001 | 40 | 4:25 | Aditya | decision with rationale, later reversed | Orbit navigation `uses_pattern` bottom tab bar |
| orbit_001 | 51 | 5:31 | Aditya | routine anchor (weekly cadence) | Orbit standup `decided` Mondays 10:00 |
| orbit_002 | 0 | 0:00 | Aditya | routine (first occurrence of the standup shape) | Orbit standup `uses_pattern` done, next, blockers, decisions since last, stale commitments |
| orbit_002 | 1 | 0:08 | Priya | completion | payments service API spec `status` completed |
| orbit_002 | 6 | 0:38 | Priya | supersession ("move it to Friday") | UPI flow `due` 2026-09-25 |
| orbit_002 | 12 | 1:10 | Rahul | completion (early) | offline mode spike `status` completed |
| orbit_002 | 18 | 1:43 | Rahul | new commitment | sync conflict resolution proposal `due` 2026-09-16 |
| orbit_002 | 22-25 | 2:05 | Rahul, Priya, Aditya | open question, left open (not in gold) | does offline mode cover payments? |
| orbit_002 | 32 | 3:09 | Sana | new commitment | navigation accessibility review `due` 2026-09-16 |
| orbit_002 | 35 | 3:29 | Aditya | completion | Meridian requirements call `status` completed |
| orbit_003 | 3 | 0:21 | Sana | the requirement behind the reversal (clip) | 56 dp, single landmark |
| orbit_003 | 14 | 1:44 | Aditya | reversal with rationale, references the kickoff explicitly | Orbit navigation `uses_pattern` side drawer |
| orbit_003 | 22 | 2:39 | Aditya | precedent (cites the drawer decision) | Orbit `requires` Meridian accessibility checklist |
| orbit_003 | 28 | 3:24 | Aditya | precedent (cites the drawer decision) | onboarding buttons `uses_pattern` 56dp full width |
| orbit_004 | 0 | 0:00 | Aditya | routine (second occurrence; StandupAgent learns the Skill after this meeting) | same shape as orbit_002 |
| orbit_004 | 1 | 0:07 | Sana | completion | onboarding screens `status` completed |
| orbit_004 | 8 | 0:46 | Rahul | new commitment | offline mode demo `due` 2026-09-28 |
| orbit_004 | 16 | 1:33 | Priya | confirmation of the email supersession, in speech | UPI flow `due` 2026-09-28 (`confirms`) |
| orbit_004 | 30 | 3:08 | Aditya | completion | drawer mockup sign-off `status` completed |
| orbit_004 | 34-35 | 3:30 | Aditya | stale commitment surfaced by the routine | offline payments question open since the 14th |
| orbit_005 | 2 | 0:12 | Aditya | completion | Meridian test devices request `status` completed |
| orbit_005 | 4 | 0:22 | Aditya | open question closed | offline payments `status` out of scope |
| orbit_005 | 7 | 0:39 | Aditya | new entity | Meridian compliance team `owner` Farah |
| orbit_005 | 12 | 1:15 | Rahul | contradiction: restates the active fact | payments service `uses_vendor` Razorpay |
| orbit_005 | 13 | 1:23 | Aditya | contradiction: the new fact | Meridian Bank `requires` PayU as payment provider |
| orbit_005 | 26 | 2:45 | Priya | target of the board's "move it to Friday" button | PayU integration `due` 2026-10-01 |
| orbit_005 | 29 | 3:07 | Aditya | supersession + reversal (vendor), rationale | payments service `uses_vendor` PayU |
| orbit_005 | 36 | 3:49 | Aditya | new entity (second customer) | Orbit `customer` Kestrel Logistics |
| orbit_006 | 2 | 0:13 | Priya | completion (end of the UPI chain) | UPI flow `status` completed |
| orbit_006 | 12 | 1:32 | Rahul | the question the Why panel answers | "Why did we choose the side drawer again?" |
| orbit_006 | 13 | 1:40 | Sana | incorrect recollection (not in gold) | "tab bar couldn't fit five sections" |
| orbit_006 | 14-16 | 1:47 | Priya | correction from memory | side drawer `decided` because of Meridian accessibility checklist, 56dp |
| orbit_006 | 23 | 2:52 | Aditya | lesson 1 | Orbit `lesson` confirm vendor constraints with the customer's compliance team before choosing a vendor |
| orbit_006 | 30 | 3:40 | Aditya | lesson 2 | Orbit `lesson` a commitment that slips twice gets a scope cut, not a third date |
| orbit_006 | 34 | 4:05 | Aditya | lesson 3 | Orbit `lesson` record the rationale with every decision |
| orbit_thread_001 | 1 | Sep 09 13:40 | Aditya | approval with one change (email) | onboarding tour `uses_pattern` three cards |
| orbit_thread_002 | 0 | Sep 17 14:02 | Priya | cross-source supersession (email replaces a spoken commitment) | UPI flow `due` 2026-09-28 |
| orbit_thread_002 | 1 | Sep 17 14:35 | Aditya | acknowledgement, conditional decision | UPI autopay mandates `status` cut if the UPI flow slips again |
| orbit_thread_003 | 1 | Sep 18 12:48 | Farah (external) | the requirement, stated by the customer | Meridian accessibility checklist `requires` 56dp minimum primary navigation target |
| orbit_thread_003 | 2 | Sep 18 13:05 | Aditya | completion (email) | drawer mockup sign-off `status` completed |
| orbit_thread_004 | 0 | Sep 24 10:15 | Priya | cross-source restatement of the vendor supersession, told to the vendor | payments service `uses_vendor` PayU |
| orbit_thread_004 | 4 | Sep 24 13:41 | Rahul | completion (email, a day early) | Razorpay SDK removal `status` completed |
| orbit_thread_005 | 0 | Sep 29 09:20 | Aditya | action item with a GitHub issue URL (Artifact link) | decision log `owner` Rahul, `due` 2026-10-02 |
| orbit_thread_005 | 2 | Sep 29 11:05 | Priya | completion (email, the day before the retro) | UPI flow `status` completed |
| nimbus_001 | 14, 16 | 1:26, 1:35 | Meera, Dev | facts to be superseded | nightly events job `decided` 02:00 IST; events pipeline `due` 2026-09-18 |
| nimbus_002 | 3, 12 | 0:14, 1:16 | Dev, Meera | supersession x2 | events pipeline `due` 2026-09-23; nightly events job `decided` 03:00 IST |
| nimbus_thread_001 | 0, 2 | Sep 22 | Dev, Anika | supersession x2 (email) | events pipeline `due` 2026-09-25; Lumen dashboard `due` 2026-09-29 |
| quill_001 | 6, 13 | 0:28, 1:06 | Tara, Omar | facts to be superseded | newsletter `decided` weekly on Thursdays; launch post `due` 2026-09-22 |
| quill_002 | 3, 8 | 0:11, 0:43 | Omar, Tara | supersession x2 | launch post `due` 2026-09-25; newsletter `decided` weekly on Tuesdays |
| quill_thread_001 | 0 | Sep 21 10:30 | Omar | supersession (email) | launch post `due` 2026-09-29 |

## What the graph should believe at a few timestamps (orbit)

| At | UPI flow due | payments vendor | navigation | onboarding tour |
|---|---|---|---|---|
| 2026-09-10 | Sep 24 (Priya, kickoff) | Razorpay | bottom tab bar | three cards (thread 001) |
| 2026-09-15 | Sep 25 (Priya, standup 1) | Razorpay | bottom tab bar | three cards |
| 2026-09-20 | Sep 28 (Priya, email Sep 17) | Razorpay | side drawer (design review, approved by Meridian Sep 18) | three cards |
| 2026-09-25 | Sep 28 (confirmed in standup 2) | PayU (Sep 23) | side drawer | three cards |
| 2026-10-03 | completed (Sep 28) | PayU | side drawer | three cards |

## Regenerating

The JSON here is the source of truth. It was produced by `data/generator/` (see its README): dialogue as data, offsets and gold indices computed. Edit there and run `python data/generator/build.py` from the repo root; then refresh the indices and timestamps in the tables above from the planted-events table it prints.
