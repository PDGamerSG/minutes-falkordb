# Demo script (3:00), Minutes on FalkorDB

Status: v1, written against the contracts in `docs/contracts/` and the corpus in `data/meetings/`. Rehearse three times on the live URL (Day 3). Every expected answer below is traceable to a segment or a message index listed in `data/meetings/README.md`.

## Before you press record

Seed state (`data/seed.py`, Stream B):

- `nimbus` and `quill`: both meetings and the thread ingested.
- `orbit`: `orbit_001`, `orbit_003`, `orbit_004`, `orbit_005`, `orbit_006` and all five threads ingested. **`orbit_002` is held back** and imported live in step 2. Ingestion is bi-temporal (`valid_from` = `t_occurred`), so the Sep 14 facts slot between the Sep 7 and Sep 17 facts and the UPI chain reads 24 to 25 to 28 after the import.
- Agents registered for `orbit`: `fact`, `scheduler`, `followup`, `standup`, `answer`. The standup Skill exists (StandupAgent learned it after `orbit_004`, the second standup).
- `GET /bench/results` has at least two runs (6.0.1 and 4.22.0, local and Railway).
- Browser: 1440x900, two tabs open on `/` and `/bench`; API warm (hit `/health` once).

Plan B if mid-chain insertion is not ready: seed all six orbit meetings and import `nimbus_002` live in step 2 instead (its stats panel shows `superseded: 2`); everything else is unchanged.

The chat page shows the Why panel on the right: router decision, Cypher, subgraph, sources with "play at timestamp" (microphone icon) for utterances and "open email" (envelope icon) for emails.

---

## 0:00 to 0:20  Tenants and isolation

**Click:** `/` (tenant switcher). Three cards: orbit, nimbus, quill, each with graph name, usage in MB, counts.

**Say:** "Minutes is a shared, time-aware memory for a team of agents, built from what people actually said. One FalkorDB graph per team. This is orbit, four people shipping a mobile app."

**Click:** on the orbit card, the ACL rule line (`%RW~team_orbit %R~commons`), then the button **"Try to read nimbus as orbit"** (`GET /tenants/orbit/acl-probe?target=nimbus`).

**Expected:** a red toast with the FalkorDB permission error, `allowed: false`. **Say:** "The database enforces tenancy, not our code."

## 0:20 to 0:45  Import a meeting live

**Click:** orbit card, then **Sources**, tab **Meetings**. Five meetings listed with episode and fact counts; standup 1 is missing.

**Click:** **Import**, pick `data/meetings/orbit_002.json`. Progress bar runs through stages: episodes, entities, facts.

**Expected stats when done:** `episodes` about 20 (46 segments merged into 30 to 60 s same-speaker chunks), `facts` about 10, `superseded: 1`. **Say:** "Forty-six segments of a Monday standup. The fact agent found ten facts and one of them replaced something we already believed. Let's see which."

## 0:45 to 1:15  Chat: a date that moved three times

**Click:** **Chat**. **Type:** `When is the UPI flow due?`

**Expected answer:** "The UPI flow was due **Monday, September 28** and is now completed. It moved twice: Priya committed to Thursday Sep 24 at the kickoff (Sep 7), moved it to Friday Sep 25 at standup 1 (Sep 14, 'move it to Friday'), then to Monday Sep 28 by email on Sep 17, which she confirmed at standup 2 (Sep 21). She reported it done on Sep 29 by email and at the retro on Sep 30."

**Why panel should show:**
- Router: `intent: when`, entities `[UPI flow]`, route `template`, template `51_open_commitments` plus `32_why_path`.
- Chain, newest first, as `SUPERSEDES` hops: `2026-09-28` (email, Priya, `thr_orbit_002` message `msg_orbit_002_1` = message index 0, Sep 17 14:02, **open email**) to `2026-09-25` (Priya, Orbit standup 1, segment 6 at 0:38, **play**) to `2026-09-24` (Priya, Orbit kickoff, segment 23 at 2:35, **play**). Plus the confirmation from standup 2 (segment 16 at 1:33) attached to the 28th, not as a new hop.
- Cypher visible and copyable.

**Click:** **play** on the 0:38 hop. Transcript segment highlights: "So I need to move it to Friday. Friday the 25th, instead of the 24th." (Audio plays if the wav is present.)

**Click:** **open email** on the 28th hop. Drawer shows Priya's message: "So I'm moving the UPI flow from Friday the 25th to Monday the 28th."

**Say:** "Three sources, two media, one chain. Every hop has a who and a when, and the email hop is a first-class episode in the same graph."

## 1:15 to 1:40  Chat: why

**Type:** `Why did we choose the side drawer?`

**Expected answer:** "Because of Meridian Bank's accessibility checklist: primary navigation targets must be at least 56 dp on their 5-inch rugged devices, and the bottom tab bar measured about 48 dp. Aditya recorded the reversal at the design review on Sep 16, explicitly overriding the kickoff decision (Sep 7, bottom tab bar, rationale: discoverability). Meridian compliance (Farah) confirmed 56 dp is a hard minimum and approved the drawer mockup by email on Sep 18."

**Why panel should show:**
- `Decision: side drawer` (Aditya, Orbit design review, 1:44) with `SUPERSEDES` to `Decision: bottom tab bar` (Aditya, Orbit kickoff, 4:25); `PRECEDENT_FOR` edges out to "checklist is the baseline" (2:39) and "56 dp buttons" (3:24).
- Sources: design review segment 3 at 0:21 (Sana states the rule), segment 14 at 1:44 (Aditya's decision), thread 003 message index 1 (Farah, **open email**).

**Click:** **play** at 1:44: "We're reversing that. Decision: navigation is a side drawer. Rationale is Meridian's accessibility requirement..."

**Say (optional, if ahead of time):** "At the retro two weeks later, Sana remembered this wrong, 'the tab bar couldn't fit five sections', and Priya corrected her. The graph never had the wrong version."

## 1:40 to 1:55  Chat: who knows

**Type:** `Who knows about PayU?`

**Expected answer (from `50_who_knows`, counting SPOKEN_BY, SENT_BY and SENT_TO):** Aditya (13 mentions, last Sep 30), Priya (12, last Sep 30), Rahul (3), Sana (2), and one external: Nikhil Rao, Razorpay account manager (2, received, Sep 24). **Say:** "Ask Aditya or Priya. And yes, the Razorpay account manager knows, because Priya told him by email."

## 1:55 to 2:20  Board: agents hand work to each other

**Click:** **Board**. Five agents idle. Open commitments listed; **PayU integration, due Thu Oct 1 (Priya)** is at the top with a button **"Move it to Friday"**.

**Click:** the button. It calls `POST /tenants/orbit/demo/supersede` with `{fact_id: <PayU integration | due>, new_object: "2026-10-02", speaker_id: "spk_priya"}`.

**Expected, live over SSE, within about 5 seconds:**
1. `fact.superseded` event; the commitment row flips to Oct 2 with a `SUPERSEDES` badge.
2. SchedulerAgent wakes (`task.claimed`, CAS version 1 to 2), updates the commitment's `due_at`, submits a `followup` task and **hands it off** (`task.handed_off`) with `subgraph_ids` = the two facts and Priya's Person node.
3. FollowUpAgent claims it, calls `open_commitments(Priya)` and `create_issue`, produces an **Artifact**: a nudge "PayU integration moved to Fri Oct 2; code freeze is Oct 9" that links to `https://github.com/orbit-app/mobile/issues/42` (the decision log issue from thread 005).
4. `task.completed`. Trace view shows claimed, handed_off, completed in order.

**Click:** **"Induce double claim"** if there is time: `winners: 1, losers: 24`. **Say:** "Claims are compare-and-set in Cypher. Twenty-five agents, one winner, no locks in our code."

## 2:20 to 2:40  Timeline: what we believed on Sep 10

**Click:** **Timeline**. Drag the scrubber to **Sep 10, 2026**.

**Expected belief-at-T panel (`31_belief_at_time`):** UPI flow due **Sep 24** (Priya, kickoff), payments vendor **Razorpay**, navigation **bottom tab bar**, onboarding tour **three cards** (Aditya's email of Sep 9). Facts created after Sep 10 are greyed out; the Sep 14 fact imported five minutes ago sits in the right place because `valid_from` came from the meeting time, not the import time.

**Drag** to **today**: UPI flow completed (Sep 28), PayU, side drawer. **Say:** "Bi-temporal: when it was true, and when we learned it."

## 2:40 to 2:55  Skills: the standup routine the agents learned

**Click:** **Skills**. One skill: `goal: run the Monday standup`, `version 1`, `runs 1`, learned from `mtg_orbit_002` and `mtg_orbit_004`. Steps: `open_commitments(person)` for each attendee, `decisions_since(last standup)`, `stale_commitments(older than 7 days)`, `compose_summary`.

**Click:** **Run**. StandupAgent retrieves the skill by vector match on the goal, runs the steps, posts an Artifact: per-person status, open commitments (PayU integration Oct 2, Kestrel onboarding variant Oct 7, decision log Oct 2, retro notes Oct 1), decisions since the last standup (PayU, Kestrel pilot uses PayU, November scope), stale: none.

**Click:** **Accept**. `success_rate` updates, `runs: 2`, PageRank column visible. **Say:** "Procedural memory. It learned the shape of a standup from two of them."

## 2:55 to 3:00  Bench

**Switch tab** to `/bench`. Chart: read p50/p95/p99 and write p50/p95/p99 for FalkorDB 6.0.1 vs 4.22.0, local vs Railway, 200 agents over 20 tenant graphs; CAS panel `attempts 25, winners 1, losers 24` per task.

**Say:** "Reads under 300 ms at p99 on a one-gigabyte Railway box, 200 agents, twenty tenants. Remove FalkorDB and nothing here works. Thanks."

---

## Questions to have ready if judges type their own

| Question | Expected | Source |
|---|---|---|
| `What did we decide about offline mode?` | local-first SQLite cache with sync queue (kickoff); last-write-wins per field, server timestamp (design review); forms and inspections only, no payments (customer call) | orbit_001 seg 32, orbit_003 seg 38, orbit_005 seg 4 |
| `Who owns payments?` | Priya | orbit_001 seg 15 |
| `What is still open for Priya?` | PayU integration (Oct 1, or Oct 2 after the board demo) | orbit_005 seg 26, thread 004 message index 3 |
| `What did Meridian's compliance team require?` | PayU, 7-year audit log of payment attempts, India data residency, 56 dp navigation targets | orbit_005 segs 9, 13; thread 003 message index 1 |
| `Who is Kestrel?` | second customer, 120 drivers, iOS, pilot Nov 16, uses PayU | orbit_005 segs 36-38, orbit_006 seg 42 |
| `What lessons did we record?` | the three lessons from the retro | orbit_006 segs 23, 30, 34 |
| `When is the newsletter sent?` (switch to quill) | Tuesdays, superseding Thursdays | quill_002 seg 8 |
| any orbit question while on nimbus | no results; the Why panel shows the Cypher ran against `team_nimbus` only | tenancy |

## Timing notes from rehearsal

- The import in step 2 must finish in under 25 s. If extraction is slower on the free tier, start it at 0:10 while talking about tenants.
- Ask the UPI question **before** pressing "Move it to Friday"; the button targets the PayU integration commitment precisely so the UPI chain stays clean, but do not tempt fate.
- If audio files are not in place, "play at timestamp" shows the highlighted transcript segment; say "transcript" instead of "clip".
