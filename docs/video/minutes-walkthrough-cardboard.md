# Minutes walkthrough — Cardboard production brief

Production status: Cardboard has **not** received this brief or exported a video. On 2026-10-10 the configured Mac answered Tailscale ping (4 ms), but SSH by hostname, IPv4, and IPv6 refused the connection during banner exchange, before authentication. The error was `banner exchange: Connection to UNKNOWN port -1: Connection refused`. No network or security settings were changed.

The alternate T3 route was also checked: its native MCP tools expose browser/device/PR actions, but no thread-creation action; no `t3` CLI is available on PATH. The installed desktop exposes connection management through Electron IPC and stores its catalog encrypted. Opening the existing local T3 web server at port 3773 in a separate native preview tab reached `/pair`, which requires a trusted pairing credential. That browser context is not paired. No Mac thread was created, no credentials were extracted, and no database or application internals were changed.

The website video is an original local render from `render_walkthrough.py`, using Pillow and FFmpeg. It is not a Cardboard export. The supplied Mem0 video informed pacing and the three-step demonstration format; none of its frames, artwork, branding, or footage are included.

Verified local export: 24.00 seconds, 720 frames, 1200×900, 30 fps, H.264 High profile, yuv420p, silent, web faststart, approximately 1.91 MiB. FFmpeg successfully decoded all frames. Review samples are at 6.6, 13.5, and 22.5 seconds.

## Ready-to-paste Cardboard prompt

```text
Create and export a finished, silent product walkthrough for Minutes in a new project named "Minutes — connected memory". You are a motion designer working inside Cardboard. Deliver the edited video, not an explanation of how to make it.

CONTEXT
Minutes connects meetings, follow-up emails, decisions, accountable people, and work. This walkthrough is an illustrative product scenario, not a recording of a live production account. Preserve the exact product name "minutes". The attached HIW.mp4 is a pacing/layout reference: a quiet, readable UI illustration that progresses from input to memory to a contextual answer. Create original Minutes artwork and animation; do not reuse the reference's footage, Mem0 name, purple palette, copy, or assets.

DELIVERABLE
24.000 seconds, exactly three 8-second chapters: Capture [0–8), Connect [8–16), Recall [16–24). 1200×900, 4:3, 30 fps, silent H.264 MP4, yuv420p, web faststart, no audio track. Aim below 5 MB without compromising text. Export minutes-walkthrough.mp4, a readable Capture poster named minutes-walkthrough-poster.jpg, and one review frame from each chapter. Keep the editable project.

VISUAL DIRECTION
Fixed camera. Very pale blue-white stage; subtle flowing blue contour/grid texture near the lower corners. Electric blue #3155ed for meaningful emphasis; dark ink #172239; secondary text #68758b. White UI cards with fine cool borders, restrained soft shadows, 20–26 px corners, generous internal space. Manrope or Inter, with 32–48 px primary copy at 1200×900 and 60–76 px for the current decision date. Keep metadata at least 24 px when possible. No stock footage, avatars, confetti, busy node cloud, 3D logo centerpiece, or decorative dashboards. Build text as real editable typography; spelling and legibility are essential.

STORYBOARD
0.00–2.70 — CAPTURE. A white meeting card is already visible on the first frame. Header: "Product kickoff"; type: "Meeting". Reveal the quote "Let's target September 24 for the UPI launch." in two readable lines, followed by "Priya · Product team". A small blue cursor illustrates the capture. Keep the complete sentence readable for at least 1 second.
2.70–6.40 — Slide a second, offset white email card into the foreground with a calm 350–500 ms ease. Header: "Payments follow-up"; type: "Email". Reveal "Sandbox access is delayed. Move the launch to September 28." Leave the meeting card's title and original date visible above it.
6.40–8.00 — Both source cards settle. Show a small blue check and "2 sources captured". Hold the completed state.

8.00–10.00 — CONNECT. Compress the two sources into distinct, readable chips: "Product kickoff" and "Payments follow-up". Animate a fine blue line from each chip into one decision card. Use a tiny travelling highlight to communicate connection; no particle shower.
10.00–13.20 — Decision card heading "UPI launch". Show "September 24" as the previous date and animate the current date into "September 28". Explicitly mark the previous date "Earlier decision" and the new date "Current decision". Do not introduce an intermediate date or source.
13.20–16.00 — Show "2 sources · History preserved". Keep both source chips connected and keep the previous date legible. Hold for comprehension.

16.00–18.30 — RECALL. In a clean question card, type "When are we launching UPI, and why?". The Minutes response begins beneath it.
18.30–21.20 — Answer: "September 28." followed by "Sandbox access was delayed, so the launch date moved." Reveal two source chips named "Product kickoff" and "Payments follow-up" with citation numbers 1 and 2. The chips refer to the two illustrated sources; they are not fabricated live links.
21.20–24.00 — Add a quiet, separate follow-up notice: "Release handoff · Needs Rahul's review". This signals a document still needing an owner to review it; do not imply automatic approval or an already-sent update. Hold the complete answer for at least 2 seconds, then prepare a seamless gentle reset into the initial Capture state.

MOTION
Use smooth ease-out translations of 12–28 px and 250–500 ms fades. The first frame must contain readable content. Keep readable pauses longer than transitions. Cursor movement has one clear purpose per chapter. Text typing is brief and only affects the question or source sentence. No flashing, camera zooms, spins, audio, or jitter. Distinguish the two sources with clear labels as well as icons/color. Keep a discreet "Illustrative walkthrough" label inside the video.

SCOPE AND VERIFICATION
Work only in the new Minutes video project and its export directory. Do not modify existing projects or publish/send anything. Use the current Cardboard tools actually available; do not claim unsupported automation or a completed export without a file. If an export or required editable typography operation is unavailable, report the specific limitation. Verify duration, dimensions, the 8s and 16s chapter boundaries, spellings, no clipping, readable frames on a 600×450 display, and the preserved earlier date. Return actual export paths plus the three review frames.
```

Target: **Cardboard**. The prompt locks the narrative, timings, and export criteria while leaving routine animation decisions to the editor.

Attach the supplied `HIW.mp4` before pasting. This prompt is for an agentic tool with real system access; confirm the new-project/export scope matches the actual Cardboard environment.

## Resume the Mac handoff

After SSH access is restored, this PowerShell command checks the configured connection and opens the installed Cardboard application:

```powershell
ssh -o BatchMode=yes mac 'sw_vers && open -a Cardboard'
```

The application name and a Cardboard automation/CLI interface have not been verified because remote access failed. Opening the app alone does not submit the prompt. Use Cardboard's actual agent input after verifying its UI; do not invent a CLI command. The local attachment path is Windows-specific and must be transferred or attached through the Mac's available UI.

## Reproduce the local fallback

From the repository root, with Pillow and imageio-ffmpeg installed:

```powershell
python docs/video/render_walkthrough.py
```

The script writes the MP4/poster to `apps/web/public/media/` and the three representative frames/contact sheet to `.video-work/`. Use `--stills-only` for a quick visual review without encoding all 720 frames.
