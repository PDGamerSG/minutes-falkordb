# Minutes · web

Next.js 16 (App Router) front end for Minutes: a shared, time-aware memory for agent teams on FalkorDB. It consumes the HTTP API in `docs/contracts/http-api.md` (plus the email additions in `docs/contracts/email-format.md`) and falls back to realistic mock data for the `orbit` tenant whenever the API is unreachable.

## Run

```bash
cd apps/web
pnpm install
pnpm dev          # http://localhost:3001  (port 3000 is taken by FalkorDB Browser)
pnpm build && pnpm start
pnpm lint
```

Docker (standalone output, `node:20-alpine`):

```bash
docker build -t minutes-web apps/web --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000
docker run -p 3001:3000 minutes-web
```

The repo-level `docker-compose.yml` builds this image and maps `3001:3000`.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of `apps/api`. Inlined at build time. |
| `NEXT_PUBLIC_MOCK` | unset | `1` forces mock data even when the API is up. |

## Mock data and live data

`lib/api.ts` is the typed client for every route in the contract. Each call runs against the API and falls back to `lib/mock.ts` when the request fails at the network level, times out, or returns 5xx; 4xx errors propagate to the UI. Routes that fell back are recorded in `lib/mock-state.ts` and the shell shows a **mock data** badge (hover it to see which routes and why). As soon as a route answers, its entry clears. `GET /health` is never mocked: the nav shows "API offline" when it cannot be reached.

The mock store is stateful. Demo actions (supersede, double claim, imports, skill outcomes, snapshots, chat) mutate it and publish events on a local bus (`lib/bus.ts`) that `lib/useEvents.ts` merges with the server's SSE stream, so the Board animates the Scheduler → FollowUp hand-off even with no API running.

## Pages

| Route | What it shows |
|---|---|
| `/` | Tenant switcher: one card per tenant with counts, usage MB, ACL users and rules, an **ACL probe** that reads another tenant's graph with this tenant's read-only user and shows the refusal, and a create-tenant dialog. |
| `/t/[team]/sources` | **Meetings** tab: list, recorder-JSON import with job polling (stage, progress, stats), episodes with speaker chips and timestamps, `<audio>` with play-at-timestamp when the API serves audio. **Email threads** tab: list, `.json` / `.eml` / `.mbox` import, thread view with sender, to, cc, sent time and text. Deep links: `?meeting=&t=` and `?thread=&message=`. `/t/[team]/meetings` redirects here. |
| `/t/[team]/chat` | Conversation with the AnswerAgent (`session_id` kept in the URL). Each answer has a collapsible **Why** panel: router decision (intent, entities, route, template), the Cypher that ran (copyable), sources with **Play at** (utterance) or **Open email** (email), and a force-graph of the returned subgraph. |
| `/t/[team]/board` | Agents and tasks in five A2A state columns, live via SSE. Task drawer with payload and the trace timeline (submitted, claimed, handed off with summary and subgraph ids, completed, failed; artifacts such as simulated GitHub issues). Demo buttons: **Simulate "move it to Friday"** (`POST /demo/supersede`) and **Induce double claim** (`POST /demo/double-claim`). |
| `/t/[team]/timeline` | Time slider across the tenant's events with coloured markers and snapshots. Shows `GET /belief?t=` (believed at T) beside the facts active now, with superseded-since / new-since markers, the Cypher that ran, the snapshot list and **Take snapshot**. |
| `/t/[team]/skills` | Skills table (goal, version, runs, success-rate bar, PageRank), expandable steps (order, tool, args template, guard), **Accept** / **Reject** outcome buttons and **Run standup skill**. |
| `/bench` | Read and write p50/p95/p99 by engine (6.0.1 vs 4.22.0) and target (local, Railway), compare-and-set winners and losers, all runs, and a dev-only run dialog. |

Shared: `components/AppShell.tsx` (left nav, tenant, API status from `/health`, mock badge), `components/GraphView.tsx` (react-force-graph-2d, node colour by label, click → props panel → **Why** calls `/why/{id}`), `components/CypherBlock.tsx`, `components/StateBadge.tsx`, `components/WhyPanel.tsx`, `components/EmailThreadView.tsx`, `components/ArtifactView.tsx`.

## Design notes

Dark and light follow `prefers-color-scheme`. One accent colour; semantic colours for task states (submitted, working, input_required, completed, failed) and fact status (active, superseded, retracted) live as CSS tokens in `app/globals.css`. Monospace for Cypher and ids; tabular numerals for latencies.
