# Minutes workspace redesign

Implemented on `feat/workspace-theme`, based on `feat/minutes-experience` (`12808a7`).
The homepage reference was initially `main@be1e328`, then rechecked against the
latest pushed `main@8439c6f` on 2026-10-11. Its paper, navy, cobalt and Cal Sans
identity remains consistent. Homepage work is kept in its separate checkout.

## Research and decisions

| Reference | Finding applied to Minutes |
| --- | --- |
| [Linear: How we redesigned the UI](https://linear.app/now/how-we-redesigned-the-linear-ui) | Reduce visual noise; use consistent navigation, alignment and restrained chroma so actual work has the strongest emphasis. |
| [IBM Carbon: UI shell left panel](https://carbondesignsystem.com/components/UI-shell-left-panel/usage/) | Keep frequently visited workspace destinations visible on desktop. Below 1024px use the existing accessible navigation sheet to give content sufficient width. |
| [Nielsen Norman Group: Progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/) | Keep the current decision and affected work visible; expand rationale, original/current sources, graph relationships and query details on demand. |
| [WCAG 2.2: Target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) | Aim for 36–44px functional controls and clearly separated text actions, with visible keyboard focus. |
| [WCAG: Contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) | Use dark text on light surfaces, readable muted text and explicit labels alongside status colors. |
| [Cal.com](https://cal.com) and [Dub](https://dub.co) | Study typography, whitespace and restrained borders as supporting references. The actual Minutes homepage is the design authority. |
| [21st dashboard sidebar](https://21st.dev/@arunjdass/components/dashboard-sidebar) and [workspaces](https://21st.dev/@efferd/components/workspaces) | Study navigation and workspace-switching patterns. Reuse installed project components rather than importing a new component system. |

The 21st catalog was searched with `light workspace sidebar knowledge dashboard`
and automatic project context. No hosted AI generation, new UI library or
animation dependency was required.

## Implemented direction

- Paper canvas (`#f8faff`), white reading surfaces, navy text (`#182138`) and cobalt (`#3155ed`). Existing homepage variables are consumed when present, with matching fallbacks.
- Self-hosted Cal Sans headings and Inter body text. Separate font aliases and shell selectors isolate the workspace from homepage stylesheet changes.
- Persistent desktop navigation, linked workspace breadcrumb, keyboard command menu, a dedicated `/workspaces` directory and mobile navigation with a visible close control.
- Real source/decision/commitment counts, the existing source → decision → work relationship canvas, quieter impact rows and progressively revealed evidence.
- Consistent chat, source tables, dialogs, work forms, sheets, semantic graph colors and operational pages. Light surfaces remain coherent under a dark system preference.
- Existing API contracts, evidence links, drafts, work editing and conversation behavior are preserved. The new directory uses the existing tenant API and validation.

## Verification

The browser preview uses the real API application with the repository's explicit
in-memory test context, gold meeting/email fixtures, scripted LLM and fake
embeddings. Agent workers are disabled. The sidebar labels this as **In-memory
preview**, **Scripted answers · demo mode**, and **Test embeddings**. This does
not establish production database or external integration correctness.

Browser coverage:

- Desktop and mobile screenshots of the overview, directory, sources, chat and work dialog.
- Overview at 320, 390, 768 and 1440 CSS pixels; operational routes checked at 320px without page-level horizontal overflow.
- Original/current decision switching, impact assessment filtering and expandable evidence.
- Keyboard command menu: Cmd+K, query filtering, ArrowDown navigation and Enter routing to Sources.
- Mobile navigation, Escape dismissal, readable form fields and light dialogs under dark system appearance.
- Chat query handoff, scripted answer, conversation session URL and expandable source evidence.
- Workspace creation through the test API; the new workspace displays zero actual counts.
- Directory error and empty states exercised with temporary browser-only fetch responses; retry moves from an explicit error to the empty state. Reload restores the real test API.
- Legacy stylesheet removal simulation: removed 992 legacy rules in browser memory while keeping Tailwind, base styles and new workspace CSS. The overview and relationship layout remained functional. A reload restored the original stylesheets.

Project checks: `pnpm typecheck`, `pnpm lint`, `pnpm build`, `git diff --check`.
The 21st static review reports color-token information and the existing command
menu autofocus warning. Focus intentionally enters a user-opened modal; the
installed dialog primitive manages its focus trap. This is not a complete WCAG
conformance audit.

## Homepage integration

On the user's follow-up request, `origin/main@8439c6f` was fetched and merged
into `feat/workspace-theme`. The two histories were reconciled with an explicit
merge, preserving both sets of commits and creating a common ancestor for future
updates. The existing feature snapshot includes backend and impact-editor fixes
absent from `main`; those remain intact. Backend, data and Cypher trees are
unchanged by this integration.

- Latest homepage navigation, assistant, motion, media, favicon, global palette
  and root layout are taken from `main`.
- `AppShell.tsx` renders the latest landing navigation/provider on `/` and the
  workspace shell on operational routes, including `/workspaces`.
- The operational directory remains `components/workspace/WorkspaceDirectory.tsx`.
- Chat adopts the homepage question handoff limit, clears the draft query from
  saved session URLs and resets the composer for a new conversation.
- The old `experience.css` is no longer imported; workspace structure and tokens
  remain owned by `workspace.css`.
- Existing homepage design decisions, Cal Sans license and workspace research
  are retained. The original shared checkout's uncommitted files are untouched.

Integration validation: typecheck, lint, production build and whitespace checks;
browser checks of the homepage, assistant → Orbit chat handoff, saved-session
URL cleanup, workspace directory and overview on desktop/mobile. The explicit
in-memory preview backend described above was used for UI interactions.

The combined result is published to `origin/feat/workspace-theme`, leaving
`main` unchanged.
