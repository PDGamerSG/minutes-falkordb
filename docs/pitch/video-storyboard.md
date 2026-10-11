# Minutes: video storyboard (3:00 screen recording)

The shots below line up with the timestamps in `pitch-script.md`. Every browser shot is captured at **1600x900** (Chrome, 100% zoom, light theme, bookmarks bar hidden, no extensions) and exported at 1920x1080. Web base: `http://localhost:3001`. API base: `http://localhost:8080`. For a hosted take, swap in the deployed web and API URLs. Seed and model mode are covered in the recording checklist in `pitch-script.md`.

Captions go in a lower-third: white text on a translucent navy band (`#182138` at 80%), Inter or Arial Semibold 34 px at 1080p, left-aligned, 64 px from the left edge. Highlight the cursor (OBS "cursor highlight" or PowerToys Mouse Highlighter) so clicks are easy to follow.

## Shot list

| # | Time | URL / source | Window | Action (click / type) | Hold | Caption overlay | Transition out |
|---|---|---|---|---|---|---|---|
| 1 | 0:00-0:15 | `apps/web/public/media/minutes-walkthrough.mp4` (24 s, silent, illustrative) | Full frame | Play the first 15 s, muted. It is an illustration, so do not narrate its specific dates (it shows Sept 24 → 28 and skips the 25th) | 15 s | 0:00 "Agents forget." · 0:07 "A memory that cannot explain itself is a liability." | Cross-dissolve, 12 frames |
| 2 | 0:15-0:20 | `/` | 1600x900 | Hero visible. Move the cursor to the workspace action in the header and click it | 5 s | "Minutes: meetings + email → one time-aware memory in FalkorDB" | Cut on click |
| 3 | 0:20-0:25 | `/workspaces` | 1600x900 | Show the Orbit, Nimbus and Quill cards. Click Orbit | 5 s | (continues) | Cut on click |
| 4 | 0:25-0:35 | `/t/orbit` | 1600x900 | Overview with source, decision and commitment counts and the 5 tracked items. Hover the counts slowly; keep the model-mode label in frame | 10 s | "Synthetic meetings and emails · reviewed labels replayed · real FalkorDB 6.0.1" | Cut |
| 5 | 0:35-0:41 | `/workspaces` | 1600x900 | Pan across the three workspace cards | 6 s | "One graph per team · ACL users per team" | Cut |
| 6 | 0:41-0:47 | `http://localhost:8080/tenants/orbit/acl-probe?target=nimbus` | 1600x900, Chrome JSON pretty-print on | Show `"allowed": false`, `"user": "team_orbit_ro"`, `"target_graph": "team_nimbus"` and the NOPERM error. Zoom 150% in the edit onto those lines | 6 s | "Cross-tenant read denied by FalkorDB ACL" | Cut |
| 7 | 0:47-1:00 | `/t/orbit/chat` | 1600x900 | Click the composer and type **Why is the UPI flow due on the 28th?** at a natural speed. Press Enter. Hold on the answer. In Mode B, cut the model wait | 13 s | "Sept 24 (kickoff, speech) → Sept 25 (standup, speech) → Sept 28 (email)" | None (same page) |
| 8 | 1:00-1:12 | same | 1600x900 | Click **Why this answer**. Scroll slowly: Router decision (`template`, `cypher/32_why_path.cypher`), Cypher that ran, Sources, Evidence episodes | 12 s | "Bi-temporal: valid_from / valid_to · SUPERSEDES across sources" | None |
| 9 | 1:12-1:20 | same | 1600x900 | Click the email source (Priya, "UPI flow: moving to Monday the 28th", Sept 17 14:02). Hold 3 s and close. Click the standup 1 source (play at 0:38). Hold on the transcript line | 8 s | "Every claim links to its source" | Cut |
| 10 | 1:20-1:32 | `/t/orbit/chat` (new conversation) | 1600x900 | Click the suggestion **Why did we choose the side drawer?** Open **Why this answer** and hover the design review evidence (orbit_003, Aditya, Meridian 56 dp) | 12 s | "Bottom tab bar (Sept 7) → side drawer (Sept 16): Meridian 56 dp rule" | Cut |
| 11 | 1:32-1:47 | `/t/orbit/board` | 1600x900 | Click **Simulate: "move it to Friday"**. Hold on the toast ("Moved it to Friday … due 2026-10-02 … Scheduler wakes next"). Watch the task move to working | 15 s | "PayU integration: Oct 1 → Fri Oct 2 · Scheduler wakes on Redis pub/sub" | None |
| 12 | 1:47-1:57 | same, task drawer | 1600x900 | Click the FollowUp task. In the drawer, hover the Trace rows claimed → handed_off → artifact → completed, then the **simulated** label on the artifact | 10 s | "HANDED_OFF {summary, subgraph_ids} · artifact simulated" | Close the drawer, cut |
| 13 | 1:57-2:05 | same | 1600x900 | Click **Induce double claim**. Hold on the toast "1 winner, 24 losers". Click **Open trace** | 8 s | "25 agents · 1 winner · 24 losers" | Cut |
| 14 | 2:05-2:13 | `/t/orbit/timeline?t=1789540200000` | 1600x900 | Page opens at "Belief at" Sept 16 2026, 12:00. Type `UPI` in the filter and hold on "Believed at T" (due 2026-09-25). Clear it, type `vendor`, hold on Razorpay | 8 s | "Belief at Sept 16: UPI due Sept 25 · vendor Razorpay" | Cut |
| 15 | 2:13-2:20 | `/t/orbit/skills` | 1600x900 | Hover the standup skill (steps, runs, success rate). Click **Run standup skill**, then **Accept outcome** on the row | 7 s | "Procedural memory: Skill + Steps + success rate" | Dissolve, 8 frames |
| 16 | 2:20-2:30 | `docs/pitch/minutes-pitch.pptx` slide 4, then slide 5 | Slideshow, 1920x1080 | Slide 4 holds 5 s (graph model). Slide 5 holds 5 s (bi-temporal chain and belief query) | 10 s | "team_<slug> graphs + commons · cypher/31_belief_at_time" | Cut |
| 17 | 2:30-2:37 | Slide 6 (CAS claim and handoff) | Slideshow | Hold. Optional: zoom in the edit onto the `MATCH (t:Task {… version: $v})` line | 7 s | "CAS claim: zero rows = another agent won · hive.score UDF" | Cut |
| 18 | 2:37-2:45 | `/bench` or slide 9 | 1600x900 / slideshow | Show the read and write latency charts and the compare-and-set contention section (or the slide 9 table) | 8 s | "6.0.1: ~1,800 ops/s vs ~1,360 on 4.22.0 · 200 agents × 20 graphs: 2,608 ops/s, 0 errors · one laptop" | Cut |
| 19 | 2:45-2:52 | Slide 11 (honest limits) | Slideshow | Hold | 7 s | "Live extraction (Gemma 4): P 0.42 / R 0.59 strict · no HTTP auth yet" | Cut |
| 20 | 2:52-3:00 | Slide 12 (tracks, stack, links, team) | Slideshow | Hold to the end. Fade the audio out over the last 0.5 s | 8 s | "github.com/Hydra-Of-Malice/FalkorDB · <LIVE_URL> · Team Vulcan" | Fade to black, 12 frames |

The total is exactly 3:00. Leave 1 to 2 s of slack by trimming shot 5 or shot 9 if the export runs over.

## How to produce it

1. **Capture.** Use OBS Studio (Display or Window Capture of Chrome, canvas 1920x1080, output scaled from the 1600x900 window, 30 fps), or Windows Game Bar (`Win+Alt+R`) if OBS is not available. Record each shot as its own clip so a fumble costs one shot, not the whole take. Mute desktop audio.
2. **Slides.** Present `minutes-pitch.pptx` full screen at 1920x1080 and capture it the same way, or export slides 4, 5, 6, 9, 11 and 12 as PNG (File → Export → PNG) and place them as stills.
3. **Narration, recorded separately.** Read the spoken column of `pitch-script.md` in a quiet room with a USB or headset mic, one paragraph per row, leaving a 1 s pause between rows. Record in Audacity at 48 kHz. Apply noise reduction, normalise to -16 LUFS and remove breaths. The presenter must read the eight speaking notes first.
4. **Align.** In DaVinci Resolve, Clipchamp or Shotcut, lay the narration on the timeline first. Then cut each shot to the row's time range, using the Hold column as the target. Add the caption overlays from the table. Burn in the captions, and also export an `.srt` with the spoken lines for YouTube.
5. **B-roll.** Open the hook with `apps/web/public/media/minutes-walkthrough.mp4` (24 s, silent, illustrative; a transcript is in `minutes-walkthrough.vtt`). Use the first 15 s only. Its dates are simplified (24 → 28), so the narration over it stays general.
6. **Export.** 1920x1080, 30 fps, H.264 (High profile), 12 to 16 Mbps VBR, AAC 192 kbps stereo, MP4. The duration must be under 3:00; check it in the player, not just the editor.
7. **Upload.** Upload to YouTube as **Unlisted**. Title: "Minutes: time-aware team memory for AI agents on FalkorDB (Team Vulcan, Graph Hacks 2026)". The description holds the repo link, the live URL, the tracks, a link to the README disclosure section, and the note that the demo data is synthetic and replays reviewed labels. Upload the `.srt` as subtitles. Paste the link into the README and the submission form.
