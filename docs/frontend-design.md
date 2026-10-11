# Frontend design record

Updated October 10, 2026 after the user rejected the first sparse graphite landing and asked for a stronger, reference-led homepage using the supplied `we make devs.docx`.

## Product direction

Minutes is a company memory workspace. It follows a decision from source evidence to an accountable person and the work it affects. The entrance should make that connected context tangible, then lead people into the real workspace. Counts and workspace links remain live API data. Homepage map cards, dates, quotes, and answer excerpts are labeled illustrative examples.

## Chosen visual system

- Paper `#fafbfe` and white surfaces for the entrance and evidence readability.
- Cobalt `#3155ed` is the connected-memory signal, with pale blue graph lines and a deep midnight `#10141e` for detailed product scenes.
- A blue dimensional interlude and oversized footer provide the expressive finish seen in the Sentra and DOCX references.
- Self-hosted Manrope gives the entrance an editorial rhythm; Inter remains the application/workspace face.
- Small labels use darkened muted tones for accessible contrast. Controls keep visible focus rings and readable text labels.

## Reference translation

- Mem0 and the light DOCX screenshots inform the spacious hero and high-contrast entry point.
- Kumu and Obsidian Canvas inform the clickable relationship map and explorable context cards.
- Linear and the DOCX dark panels inform the product walkthrough, evidence inspector, and focused task surfaces.
- Zep and Graphiti inform the dated decision history.
- Sentra and the blue DOCX sections inform the dimensional interlude and monumental footer.
- 21st Animated Beam was retrieved as a pattern for measured SVG connections; Minutes uses a native implementation without a new animation dependency.

## Motion and accessibility

The relationship map changes between connected and scattered states. Product tour, source citations, history slider, and agent handoff expose state through native buttons, labels, and live updates. The existing Three.js block sculpture is reused in the blue interlude with pause/play, IntersectionObserver suspension, WebGL fallback, resource disposal, and reduced-motion support. CSS respects `prefers-reduced-motion`.

## Verification record

- `pnpm typecheck`, `pnpm lint`, and `pnpm build` pass in `apps/web`.
- `git diff --check` passes.
- T3 preview checks cover desktop 1440×1000 and mobile 390×844, map state, product walkthrough stages, history slider, answer citations, agent handoff, workspace links, and no horizontal overflow.
- Existing workspace sources, board, chat, timeline, skills, evidence drawers, editors, and local-only follow-up drafts remain available.
