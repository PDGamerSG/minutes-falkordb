# Minutes experience

The public entrance is a product story for Minutes, a FalkorDB-backed company memory workspace. It uses the supplied `we make devs.docx` screenshots and the referenced Mem0, Sentra, Zep, Linear, Kumu, Obsidian Canvas, and 21st Animated Beam patterns as visual and interaction references.

## Direction

- **Palette:** paper white and pale blue surfaces for clarity; cobalt for the connected memory thread; midnight panels for evidence-heavy product scenes; a dimensional blue interlude and footer.
- **Type:** self-hosted Manrope gives the entrance a spacious, editorial rhythm; Inter remains the application/workspace face.
- **Shape:** a relationship map replaces a generic hero illustration. The homepage then moves through a problem section, a three-state product walkthrough, decision time travel, source-backed role questions, agent handoff, workspaces, FAQs, and a monumental closing footer.
- **Motion:** map connection and node state respond to user input; walkthrough panels change in place; date history uses a keyboard-accessible range control; agent handoff advances through visible states; the existing Three.js sculpture is reused in the blue interlude with pause and reduced-motion support.

## Homepage sections

`CompanyMap` renders illustrative meeting, email, decision, work, person, agent, and company-memory nodes. The connection toggle changes between an explorable connected state and scattered state. `ProductTour` demonstrates source capture, a dated decision chain, and a local-only follow-up draft. `HistorySection` exposes the illustrative Sep 24 → Sep 25 → Sep 28 history. `AnswersSection` changes perspective for product, engineering, and team leads and opens source-specific illustrative excerpts. `AgentSection` makes the human review boundary explicit. The workspace directory uses live tenant counts and links to the existing application. Existing sources, board, chat, timeline, skills, evidence drawers, and editing flows remain application routes.

Illustrative dates, quotes, answer text, and map records on the entrance are labeled as such. Workspace counts and links come from the existing API client; no silent mock fallback was added.

## Constraints and verification

Keep `apps/web/AGENTS.md`, API contracts, explicit demo labeling, local-only follow-up drafts, keyboard focus, mobile layouts, reduced motion, and WebGL fallback. Validation run for this revision: `pnpm typecheck`, `pnpm lint`, `pnpm build`, `git diff --check`; desktop and 390px mobile preview checks covered overflow, section layout, map state, product walkthrough, and responsive navigation.
