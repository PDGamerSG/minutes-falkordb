# Frontend agent prompt

🎯 Target: frontend implementation in a separate thread.
💡 Optimized for an original, working 3D Company Brain interface, with isolated file ownership and verifiable behavior.

```text
Goal
Act as the frontend design lead and implementation engineer for Minutes. Transform its existing Next.js app into a distinctive, elegant Company Brain with a genuinely rendered, interactive 3D visual identity. Implement it in the shared workspace, not just a mockup. The user explicitly authorizes frontend implementation in this separate agent thread.

Context (carry forward)
- Workspace: /Users/admin/Data/Projects/Hackathon project/FalkorDB. No git repository; do not reset or overwrite others' changes.
- Stack: Next.js 16 App Router, React 19, TypeScript, Tailwind, existing accessible UI primitives. Read apps/web/AGENTS.md and relevant bundled Next documentation first.
- Product: connected meetings, emails, people, decisions and commitments in FalkorDB. Users ask who owns work, why a decision changed and what the team knew then. Why panels expose source evidence; a board shows agent handoffs.
- Preserve repaired tenant/session isolation, source links, current-vs-historical answers, and honest demo/error states. Existing frontend typecheck, lint and build pass.
- You own apps/web/** plus docs/frontend-design.md. Root owns backend, Cypher, seed data, tests and all other docs. Send API needs to root; do not edit backend files. Do not spawn further agents.

Research and art direction
Inspect these actual references in the native collaborative browser:
https://design.pallabdas.me/#/design/monolith
https://design.pallabdas.me/#/design/chrome
Root inspected both: Monolith uses a warm studio-lit layered ribbon sculpture; Chrome uses graphite black, large precise grotesk typography, brushed/chrome looping forms and small orange accents. Use their material quality, restraint, whitespace and composition as inspiration; create original geometry and layouts. Also inspect at least two relevant public design examples discovered through internet search, such as Awwwards WebGL examples and Lusion. Record the URLs and specific observations in docs/frontend-design.md; do not invent observations or copy source assets. Search engines' AI summaries are not design evidence.

Direction: a living archive. Interlocking metallic record-like ribbons or plates become a connected sculptural form. Three visual layers can represent sources, decisions and actions. Give the sculpture purpose: user selection highlights the corresponding layer and opens a real product entry point. Keep its illustrative nature clear; do not pass procedural geometry off as actual database nodes.

Use a restrained graphite/silver palette with a precise warm signal accent, confident typography, architectural spacing and quiet borders. Put the visual boldness in the sculpture and composition. Avoid generic bento-card spam, fake business metrics, gradient-text slogans, particle galaxies, animated backgrounds behind reading surfaces, or copying either reference. Make the actual workspace feel as considered as the first screen.

Scope
1. Redesign the home/tenant entrance and shared application shell. Provide a clear path into a real tenant workspace.
2. Deliver an excellent tenant overview showing real source/decision/work counts, a current knowledge briefing, decision impact and direct actions. Preserve Sources, Chat, Board, Timeline, Skills and Bench navigation, restyling them coherently through shared components/tokens where appropriate.
3. Refine Chat and Why/source evidence into a legible decision investigation surface; preserve its functioning data flow.
4. Integrate the new backend contract root will send: a GET /tenants/{team}/impact endpoint plus local follow-up drafts. Until that contract arrives, structure the visual panel and type seam; never substitute fake successful data for a failing API.
5. Use a lazily loaded client-only WebGL scene with original geometry and studio lighting. You may add only necessary frontend rendering dependencies and keep the lockfile synchronized. Prefer a small direct Three.js scene or existing suitable dependencies over an elaborate engine. Dispose resources, cap pixel ratio, pause offscreen, respect reduced motion, include a usable fallback when WebGL is absent, and keep forms/navigation accessible without the canvas. No external HDRI or model dependency that can break the demo.

Autonomy and boundaries
Proceed with local research, edits, dependency install, builds and preview; the user has authorized this work. Do not wait for repeated design approvals. Coordinate file ownership. Do not deploy, publish, send messages, use paid generation, overwrite data, or introduce new external services. If model/image generation is unavailable, original procedural 3D is acceptable and preferred here. Preserve explicit scripted-model and test-embedding indicators without putting implementation clutter into the main product flow.

Verification and done
Run pnpm install --frozen-lockfile, pnpm typecheck, pnpm lint and pnpm build from apps/web. Use the native preview tools (first preview_status, then preview_open if needed); do not switch to standalone browser automation. Inspect and improve screenshots at desktop (1440px) and mobile (390px), including reduced motion and WebGL fallback where feasible. Verify tenant entry, chat send/history, Why/source opening, impact selection and drafting, keyboard focus and error states. Document only observed checks. Stop when the coherent working redesign passes these checks; report changed files, visual decisions, performance/fallback measures and any remaining limitation. Send root progress and a preview URL after the first complete visual pass.

This prompt is for an agentic tool with real system access. Review the scope locks, forbidden actions, and stop conditions before pasting. Confirm file paths, directories, and permissions match the actual project.
```


## Accepted revisions — October 10

The user explicitly selected **Chrome: dark, cinematic, reflective metal**, then rejected the first typography/button treatment and requested visible motion. These corrections override the original prompt's remaining aesthetic latitude.

```text
Continue the existing Minutes implementation. Keep the dark Chrome direction, real graph data, evidence views and tenant/session behavior. Use the original procedural metal knot as an integrated sculpture, with clearly visible continuous rotation, drag interaction, pause/play and a static fallback. Start paused under reduced-motion preferences; an explicit play action may override that preference.

Use the self-hosted variable Inter family for a restrained, professional type hierarchy. Avoid the previously rejected wide Syne display and tiny functional text. Standardize buttons across the shell, overview, chat and dialogs: neutral primary surfaces, readable labels, 36/40/44px controls, 7–8px corners and clear hover/focus/disabled states. Reserve copper for the sculpture and semantic highlights. Do not restore oversized pill CTAs or pale boxed 3D panels.

Verify desktop/mobile layouts and actual animation movement in the native browser, plus source inspection, persistent local drafts and restored chat. Run the existing typecheck, lint and build. Preserve honest scripted-model labels and all backend corrections. Do not deploy or send external communications.
```
