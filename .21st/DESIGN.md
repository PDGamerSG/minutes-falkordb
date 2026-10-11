# Minutes design context

Minutes connects conversations, decisions, people, work, and agents. The frontend makes a changed decision traceable to evidence and affected work.

## Visual direction

Graphite `#101114`, silver sculpture, off-white `#f0f0f4`, violet `#b5a0f4`. Self-hosted Inter. Spacious entrance, quiet workspace navigation, readable evidence surfaces. Canonical shared tokens: `apps/web/app/globals.css`. Experience layouts: `apps/web/app/experience.css`.

## Reference use

The user’s `we make devs.docx` contains 16 screenshots emphasizing block assembly, hover response, interactive dark panels, connected maps, and dimensional animation. Mem0 informs the sculpture behavior; Kumu and Obsidian inform the evidence canvas; Linear informs navigation and reading surfaces; Sentra and Zep inform context and history.

21st’s [Animated Beam](https://21st.dev/@dillionverma/components/animated-beam) was retrieved as a reference for measuring SVG connections against actual DOM cards. The implementation uses native SVG and CSS without another animation library. 21st AI generation is not enabled on this account.

## Constraints

Use installed Base UI primitives. Preserve API contracts, source links, editor behavior, explicit demo labels, and local-only follow-up drafts. Respect reduced motion, keyboard operation, mobile layouts, WebGL fallback, and resource disposal. See `docs/minutes-experience.md` for implementation and verification details.
