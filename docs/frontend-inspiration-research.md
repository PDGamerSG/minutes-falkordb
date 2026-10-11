# Minutes: frontend inspiration research

Researched October 10, 2026. Scope: related companies, open-source projects, and interface references to inform a future frontend. These are proposed directions, not implemented changes.

## Recommendation

Build the most memorable experience around **a decision changing through time, with its evidence and work dependency visible**. Minutes already has the underlying story: meetings and emails become dated facts; a new fact supersedes an old one; explicitly connected work can need review; an accountable person and a local follow-up draft complete the investigation.

Study Sentra for the product story, Zep/Graphiti for temporal memory, Kumu for focused relationship exploration, Linear for task and agent activity, and Lusion for expressive 3D presentation.

The existing Chrome direction in `docs/frontend-design.md` is a useful starting point: graphite, reflective silver, a restrained copper selection, and large readable typography. Treat the three concepts below as alternatives to explore within that world; this research does not replace the established design record.

## Companies with related products

| Reference | What the public product describes | What to study for Minutes |
| --- | --- | --- |
| [Sentra](https://www.sentra.app/) | Managed organization memory connecting meetings, messages, documents, code, people, decisions, and open commitments. Its page explicitly discusses who said what and why decisions shifted. | Closest product-story match. Use concrete questions about changed assumptions and owners, then show the evidence that answers them. Its role-specific examples help explain value quickly. |
| [Zep](https://www.getzep.com/) | Shared context for agents built from business data, documents, and conversations. Its examples include dated facts, graph exploration, episodes, and source tracing. | Separate entities, facts, and source episodes in an inspector. Show the selected fact's date and source instead of presenting every graph element as an identical dot. |
| [Glean](https://www.glean.com/) | Enterprise AI spanning company knowledge, search, assistants, and agents. | Make company-wide questions easy to start. Study the relationship between a natural-language entry point, connected sources, and actionable results. |
| [Dust](https://dust.tt/) | Human-agent collaboration over shared company knowledge and connected tools. | Agent identity, shared conversations, reusable skills, activity, and human review. Useful for the coordination board and task handoffs. |
| [Granola](https://www.granola.ai/) | Meeting notes, actions, memory, meeting briefs, and chat across meeting context. | A readable meeting inspector, editable notes, visible action items, and direct follow-up actions. The before/during/after sequence is a strong source-to-work explanation. |
| [Tana](https://tana.inc/) | Agentic meetings that produce issues, email drafts, decisions, owners, and shared knowledge-graph context. | Put the discussion, decision, owner, and proposed action together. The public page shows concrete artifact states such as a draft and a filed issue. |
| [Hebbia](https://www.hebbia.com/) | Institutional intelligence across documents and financial data, including its Matrix workspace. | Structured comparisons across multiple sources. A compact comparison of old/current decision, date, source, owner, and affected work could be more useful than a long chat answer. |

Current-reference detail: Tana's main site now presents its agentic meeting product and distinguishes it from its outliner. Do not assume older Supertag-focused descriptions describe the current homepage.

## Open-source projects

These are primarily architecture and product-interaction references. A memory framework's repository is not automatically a polished frontend template.

| Project | Relevance | Frontend idea it suggests |
| --- | --- | --- |
| [Graphiti — Zep](https://github.com/getzep/graphiti) | Temporal context graphs, fact validity windows, provenance, and hybrid retrieval. Its README lists FalkorDB among supported graph backends. | A fact history view with current and previous values, validity dates, and direct access to the source episodes. This is the closest technical precedent for Minutes' time-aware memory. |
| [Cognee](https://github.com/topoteretes/cognee) | Persistent agent memory built from documents, code, and conversations. The README includes Company Brain examples, graph visualization, and a local UI entry point. | A visible ingestion journey: source content, extracted relationships, retrieved evidence, and an answer or action. |
| [Letta Code](https://github.com/letta-ai/letta-code) | Stateful agents with memory, identity, skills, and a history of experience. | An agent inspector with assigned work, remembered context, used skills, and activity over time. |
| [Mem0](https://github.com/mem0ai/mem0) | Persistent user, session, and agent memory, with library, self-hosted, and managed options. | A searchable memory browser with scope, entity, date, and source filters. Helpful for understanding which context belongs to which user or agent. |
| [FalkorDB GraphRAG SDK](https://github.com/FalkorDB/GraphRAG-SDK) | Graph-based retrieval, typed entities, retrieved context, and source provenance in Minutes' database ecosystem. | An evidence trail that makes the connected retrieval path inspectable, including an explicit insufficient-evidence state. |

Current-reference detail: [letta-ai/letta](https://github.com/letta-ai/letta) currently points active development to **letta-ai/letta-code**. Use the current repository for fresh ideas.

## Interfaces and expressive visual references

| Reference | What to explore | Translation to Minutes |
| --- | --- | --- |
| [Kumu tour](https://kumu.io/tour) | Relationship maps with filters, focus, showcase, element profiles, before/after views, and guided presentations. | Show a small relevant neighborhood around the selected decision. Fade unrelated nodes and explain each relationship in the side inspector. |
| [Kumu gallery](https://kumu.io/gallery) | A collection linked from Kumu's official tour. | Browse different ways to present networks and guided relationship stories. Individual gallery projects were not evaluated in this research. |
| [Obsidian Canvas](https://obsidian.md/canvas) | An infinite canvas combining connected notes with images, PDFs, audio, and other media. | An evidence canvas: meeting excerpts, emails, decisions, and work items arranged into a traceable investigation. |
| [Linear](https://linear.app/) | Dark product presentation, a readable app shell, issue activity, agent context, and human review. | Make the work list and agent trace crisp and quick to scan. Place the more expressive interactions around the investigation itself. |
| [Lusion](https://lusion.co/) | A studio presenting 3D visual storytelling and interactive web experiences. | A strong entrance with an authored metal form; a deliberate camera transition into the workspace; one memorable interaction per major story. |
| [Active Theory](https://activetheory.net/) | A creative digital experience portfolio with a canvas-based entry. | Explore it as a reference for spatial presentation and immersive navigation before committing to a particular effect. |

The studio sites reached animated loading screens during preview inspection. Their URLs and public page metadata/content were checked, but their complete interactive experiences were not validated. Linear, Obsidian Canvas, Sentra, and Zep were also inspected through screenshots. Product descriptions above are grounded in official pages and READMEs; vendor performance, security, and customer claims were not independently audited.

## Concept 1: Decision time machine — strongest recommendation

**Visitor job:** Understand what changed, why it changed, and which open work should be reviewed.

**Composition:** A focused decision in the center; a horizontal event timeline below; current/past value and source evidence beside it; affected work and owner nearby.

**Memorable interaction:** Scrubbing to a recorded change replaces the old decision value, reveals the superseding source, and highlights the existing work dependency. Selecting the work opens its owner, rationale, and dependency document.

**Concrete demo from the repository:**

1. Open the payment gateway decision.
2. Show the previous Razorpay choice with its evidence.
3. Advance to the PayU choice and reveal the supersession.
4. Highlight the explicitly dependent payment integration runbook.
5. Show Priya as its recorded owner.
6. Prepare a follow-up and display it as an **unsent local draft**.

This visualizes a real distinction in the product: changing a fact does not establish impact on every nearby work item. The authored dependency and actual supersession path establish which work needs review.

**Fit with existing contracts:** timeline, belief-at-time, Why/history, and decision-impact responses. Start with recorded event dates; do not imply that every unrelated screen has historical state.

## Concept 2: Connected company atlas

**Visitor job:** Explore how a person, decision, source, and work item connect.

**Composition:** A spatial map with Sources, Decisions, People, and Work filters; a prominent search field; a readable detail inspector; a list representation of the same selection.

**Memorable interaction:** Selecting a decision brings its relevant neighborhood into focus. A “Trace evidence” action highlights the source path in order. A “Show affected work” action uses the explicit dependency path.

**References:** Kumu's focus/showcase behavior, Obsidian's evidence canvas, and Zep's entity/fact/episode distinction.

**Fit with existing contracts:** chat subgraphs, Why subgraphs, and impact graphs already provide useful bounded investigation data. A company-wide graph browser may require additional fetching and pagination; the focused version has a clearer starting point.

**Visual discipline:** Keep labels and source excerpts in normal readable UI. Chrome materials can frame the experience, while the actual edges carry documented relationship meanings.

## Concept 3: Agent control room

**Visitor job:** Understand who is doing the work, what context they received, and where the task needs attention.

**Composition:** An agent roster, task queue, selected-task trace, handoff context, and produced artifacts. Important task states are named in text.

**Memorable interaction:** Replay a recorded handoff: the selected context travels to the receiving agent, followed by the task's next recorded state and artifact.

**References:** Dust's shared human-agent workflow, Linear's activity and review surfaces, and Letta's persistent agent identity and skills.

**Fit with existing contracts:** agent/task listings, task traces, skills, and SSE events. Keep scripted/demo behavior visible. Animation should follow recorded events.

## Recommended combination

Use the **decision time machine as the primary product experience**, with a focused atlas for evidence exploration and a separate agent control room for coordination.

| Surface | Main reference | Priority |
| --- | --- | --- |
| Entrance / landing | Lusion plus the existing Chrome direction | Express connected memory through a single authored visual. |
| Workspace overview | Sentra and Linear | Lead with decisions and work that need attention. |
| Decision investigation | Graphiti/Zep and Kumu | Show change through time and the exact evidence/dependency path. |
| Source inspector | Granola and Obsidian Canvas | Make the original meeting or email easy to read and open. |
| Agent coordination | Dust, Linear, and Letta | Make ownership, handoffs, review, and artifacts clear. |

The strongest demonstration is: **“This decision changed. Here is the source, the dependent work, its owner, and the draft to resolve it.”**

## Build implications for the next phase

- The existing frontend uses Next.js, React, Tailwind, and `react-force-graph-2d`; a focused graph interaction can start from the installed stack.
- Treat the decorative metal sculpture and the database graph as distinct surfaces. A sculpture is illustrative; investigation nodes and edges must come from actual graph results.
- Keep source text still and readable while using motion to explain selection, supersession, and handoffs.
- On small screens, prioritize the selected decision, evidence, and work; offer the map as an optional view.
- Preserve keyboard access, reduced-motion behavior, and a usable list alternative.
- Judge an early prototype by whether someone can find the changed value, open its source, identify the affected work and owner, and distinguish an unsent draft from a completed action.

Repository grounding: `README.md`, `PRODUCT.md`, `DESIGN.md`, `docs/frontend-design.md`, `docs/decision-impact.md`, `docs/contracts/http-api.md`, and `apps/web/package.json`. API fit was assessed from repository contracts, not through a live API test in this research.

