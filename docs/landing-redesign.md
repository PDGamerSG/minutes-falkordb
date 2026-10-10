# Minutes landing redesign

The page follows a short product story: company memory, a silent walkthrough, one animated decision change, a question-led assistant section, and a scroll-driven memory sculpture. This change is scoped to the landing experience; workspace screens and backend work remain separate.

## Visual direction

- Preserve the original blue identity (`#3155ed`) and silver/blue sculpture, with cooler neutral surfaces and a continuous navy ending.
- Cal.com informed the locally served Cal Sans display type. Latitude informed precise spacing; Dub informed product framing and fine page rails.
- T3 Code and 100xDevs informed measured ambient motion. The hero uses flowing SVG threads at its edges, with a staged headline entrance and restrained light gradients.
- Stripe informed the shallow angled transition into the ending. Drizzle informed the existing compact assistant entry.
- The header contains the brand, an animated miniature tile sculpture, and the workspace action. Section links and context status are removed. Calls to action remain in the header and hero, with ordinary navigation in the footer.

The assistant launcher uses a compact navy speech shape with the Minutes mark and one directional affordance. The browser favicon, scalable SVG icon, and Apple touch icon use the same nine-tile identity.

## Product story

"Know what changed" shows one payments message, a September 24 to September 28 date change, and one handoff note. There are no numbered steps, tabs, chapter bars, repeated product headings, or workspace buttons inside the scene.

A 22-second loop brings in the message, updates the date, then reveals Rahul's handoff. The completed result remains visible for over eleven seconds. The draft opens only on request and never sends a message. Interaction holds the sequence. The clock and ambient signal pause offscreen or in a hidden document; reduced motion shows the completed result immediately.

## Catching up

The new "Walk in with the context" section uses three full-width, unnumbered questions rather than cards. Each opens the existing bottom assistant with the selected question prefilled. It does not submit a chat message. This gives the page a practical next step without repeating workspace calls to action.

## Video and sculpture

- The original 24-second video is silent, inline and looping, with no play/pause controls. Versioned URLs prevent stale posters. Playback resumes after readiness, seeking and viewport changes, and pauses when offscreen or hidden. Reduced motion uses the still poster. A transcript remains available.
- The larger sculpture progresses through scattered blocks, a connected ring, and an organized cube using native scroll. Blocks assemble in a staggered wave, with a subtle travelling light across the connected structure. Mouse movement and dragging remain interactive; touch scrolling is not intercepted.
- Sculpture mode controls, progress labels and scroll instructions are removed. Reduced motion shows a static organized memory, and unavailable WebGL uses an SVG fallback.
- Headings and the footer enter as they come into view. Ambient loops and entrance transitions honor reduced motion.

## Validation

Targeted ESLint passed for the landing components and Three.js scene. Browser verification covers the automatic decision sequence, stable layout, responsive widths, video playback, draft interaction, and the scroll sequence. The release is built from an isolated checkout to exclude concurrent workspace/backend edits and Syncthing conflict files.

## Video production

The Mac/Cardboard path was attempted but unavailable: the Mac responded over Tailscale, while SSH was refused before authentication and the alternative T3 interface required pairing. No Cardboard project or Mac thread was created. The walkthrough was rendered locally. Its reproducible renderer and production brief are in `docs/video/`.
