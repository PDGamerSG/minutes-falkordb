// Typed client for docs/contracts/http-api.md (+ email-format.md additions).
// Mock data is available only through explicit NEXT_PUBLIC_MOCK=1 preview mode.
// Live failures propagate: an import or action must never report fabricated success.

import * as mock from "./mock";
import { isForcedMock, markLive, markMock } from "./mock-state";
import type {
  AclProbe,
  Agent,
  Belief,
  BenchResult,
  ChatResponse,
  ChatTurn,
  Cluster,
  Contradiction,
  DoubleClaimResponse,
  EmailMessage,
  EmailThread,
  Episode,
  Fact,
  Health,
  ImportResponse,
  Job,
  Meeting,
  Skill,
  Snapshot,
  SupersedeResponse,
  Task,
  TaskTrace,
  Tenant,
  Timeline,
  WhoKnows,
  WhyResponse,
} from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080").replace(/\/+$/, "");

// ---------- credentials ----------
// Per-tenant API key (X-API-Key) and admin token (Authorization: Bearer). The API only enforces them when
// TENANT_KEYS_REQUIRED / ADMIN_TOKEN are set; local development sends nothing. Anything in NEXT_PUBLIC_* is
// readable by every visitor, so NEXT_PUBLIC_API_KEY is for single-tenant public demos with synthetic data only.
// The admin token is never read from the build environment: an operator stores it in this browser.
const KEY_STORE = "minutes.apiKey";
const ADMIN_STORE = "minutes.adminToken";

function stored(name: string): string | undefined {
  try {
    return (typeof window !== "undefined" && window.localStorage.getItem(name)) || undefined;
  } catch {
    return undefined; // private mode / blocked storage
  }
}

function store(name: string, value: string | null) {
  try {
    if (typeof window === "undefined") return;
    if (value) window.localStorage.setItem(name, value);
    else window.localStorage.removeItem(name);
  } catch {
    // storage unavailable: the env value (if any) still applies
  }
}

export const getApiKey = (): string | undefined => stored(KEY_STORE) ?? (process.env.NEXT_PUBLIC_API_KEY || undefined);
export const setApiKey = (key: string | null) => store(KEY_STORE, key);
export const getAdminToken = (): string | undefined => stored(ADMIN_STORE);
export const setAdminToken = (token: string | null) => store(ADMIN_STORE, token);

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const key = getApiKey();
  const admin = getAdminToken();
  if (key) headers["X-API-Key"] = key;
  if (admin) headers["Authorization"] = `Bearer ${admin}`;
  return headers;
}

/** Append ?api_key= for browser-native consumers that cannot set headers (EventSource, <audio>). */
function withKey(url: string): string {
  const key = getApiKey();
  return key ? `${url}${url.includes("?") ? "&" : "?"}api_key=${encodeURIComponent(key)}` : url;
}

export class ApiError extends Error {
  status: number;
  code: string;
  /** Server log correlation id (X-Request-ID); present on 500s. */
  requestId?: string;
  /** Seconds to wait before retrying (503 llm_rate_limited). */
  retryAfter?: number;
  constructor(status: number, code: string, message: string, extra: { requestId?: string; retryAfter?: number } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = extra.requestId;
    this.retryAfter = extra.retryAfter;
  }
}

type ReqOpts = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  raw?: BodyInit;
  timeoutMs?: number;
  headers?: Record<string, string>;
};

/** A page of a paged route: the body array plus the X-Next-Cursor / X-Truncated response headers. */
type Paged<T> = { rows: T[]; nextCursor: string | null; truncated: boolean };

async function request<T>(path: string, opts: ReqOpts = {}): Promise<T> {
  return (await requestFull<T>(path, opts)).data;
}

async function requestFull<T>(path: string, opts: ReqOpts = {}): Promise<{ data: T; headers: Headers }> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 6000);
  try {
    const headers: Record<string, string> = { Accept: "application/json", ...authHeaders(), ...(opts.headers ?? {}) };
    let body: BodyInit | undefined = opts.raw;
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.body);
    }
    const res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      signal: ctrl.signal,
      cache: "no-store",
    });
    if (!res.ok) {
      let code = `http_${res.status}`;
      let message = res.statusText || `HTTP ${res.status}`;
      let requestId: string | undefined;
      let retryAfter: number | undefined;
      try {
        const j = (await res.json()) as {
          error?: { code?: string; message?: string; request_id?: string; retry_after?: number };
          detail?: unknown;
        };
        if (j?.error) {
          code = j.error.code ?? code;
          message = j.error.message ?? message;
          requestId = j.error.request_id;
          retryAfter = j.error.retry_after;
        } else if (j?.detail) {
          message = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
        }
      } catch {
        // non-JSON error body
      }
      throw new ApiError(res.status, code, message, { requestId: requestId ?? res.headers.get("X-Request-ID") ?? undefined, retryAfter });
    }
    if (res.status === 204) return { data: undefined as T, headers: res.headers };
    return { data: (await res.json()) as T, headers: res.headers };
  } finally {
    clearTimeout(timer);
  }
}

/** Run a live call, or an explicitly selected preview. `mock` returning null means 404. */
async function withMock<T>(route: string, live: () => Promise<T>, mockFn: () => T | null): Promise<T> {
  if (isForcedMock()) {
    markMock(route, "NEXT_PUBLIC_MOCK=1");
    return resolveMock(route, mockFn);
  }
  const r = await live();
  markLive(route);
  return r;
}

function resolveMock<T>(route: string, mockFn: () => T | null): T {
  const m = mockFn();
  if (m === null) throw new ApiError(404, "not_found", `No mock for ${route}`);
  return m;
}

const q = (params: Record<string, string | number | undefined | null>) => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
};

const enc = encodeURIComponent;

export const api = {
  base: API_BASE,

  // ---------- health ----------
  /** Not mocked unless forced: an unreachable API should show as such. */
  async health(): Promise<Health | null> {
    if (isForcedMock()) return mock.mockHealth();
    try {
      const h = await request<Health>("/health", { timeoutMs: 3000 });
      markLive("GET /health");
      return h;
    } catch {
      return null;
    }
  },

  // ---------- tenants ----------
  tenants: {
    list: () => withMock("GET /tenants", () => request<Tenant[]>("/tenants"), mock.mockTenants),
    /** Admin only when ADMIN_TOKEN is set. The response carries `api_key` exactly once; store it. */
    create: (body: { slug: string; display_name: string }) =>
      withMock("POST /tenants", () => request<Tenant & { api_key?: string }>("/tenants", { body }), () => ({
        slug: body.slug,
        display_name: body.display_name,
        graph: `team_${body.slug}`,
        usage_mb: 0,
        counts: { episodes: 0, facts: 0, decisions: 0, commitments: 0, tasks: 0, skills: 0 },
        acl: {
          rw_user: `team_${body.slug}_rw`,
          ro_user: `team_${body.slug}_ro`,
          rules: [
            `ACL SETUSER team_${body.slug}_rw on >*** +GRAPH.QUERY +GRAPH.RO_QUERY %RW~team_${body.slug} %R~commons`,
            `ACL SETUSER team_${body.slug}_ro on >*** +GRAPH.RO_QUERY %R~team_${body.slug} %R~commons`,
          ],
        },
      })),
    aclProbe: (tenant: string, target: string) =>
      withMock(
        "GET /tenants/{t}/acl-probe",
        () => request<AclProbe>(`/tenants/${enc(tenant)}/acl-probe${q({ target })}`),
        () => mock.mockAclProbe(tenant, target),
      ),
  },

  // ---------- meetings ----------
  meetings: {
    list: (tenant: string) =>
      withMock("GET /tenants/{t}/meetings", () => request<Meeting[]>(`/tenants/${enc(tenant)}/meetings`), mock.mockMeetings),
    import: (tenant: string, recorderJson: unknown) =>
      withMock(
        "POST /tenants/{t}/meetings/import",
        () => request<ImportResponse>(`/tenants/${enc(tenant)}/meetings/import`, { body: recorderJson, timeoutMs: 30000 }),
        () => mock.mockImport("meeting"),
      ),
    episodes: (tenant: string, meetingId: string) =>
      withMock(
        "GET /tenants/{t}/meetings/{id}/episodes",
        () => request<Episode[]>(`/tenants/${enc(tenant)}/meetings/${enc(meetingId)}/episodes`),
        () => mock.mockEpisodes(meetingId),
      ),
    audioUrl: (tenant: string, meetingId: string) => withKey(`${API_BASE}/tenants/${enc(tenant)}/meetings/${enc(meetingId)}/audio`),
    /** HEAD-ish probe: true only when the API serves audio for this meeting. */
    async hasAudio(tenant: string, meetingId: string): Promise<boolean> {
      if (isForcedMock()) return false;
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 3000);
      try {
        const res = await fetch(api.meetings.audioUrl(tenant, meetingId), {
          method: "GET",
          headers: { Range: "bytes=0-0" },
          signal: ctrl.signal,
        });
        await res.body?.cancel();
        return res.ok;
      } catch {
        return false;
      } finally {
        clearTimeout(t);
      }
    },
  },

  jobs: {
    get: (tenant: string, jobId: string) =>
      withMock("GET /tenants/{t}/jobs/{id}", () => request<Job>(`/tenants/${enc(tenant)}/jobs/${enc(jobId)}`), () => mock.mockJob(jobId)),
  },

  // ---------- email threads ----------
  threads: {
    list: (tenant: string) =>
      withMock("GET /tenants/{t}/threads", () => request<EmailThread[]>(`/tenants/${enc(tenant)}/threads`), mock.mockThreads),
    messages: (tenant: string, threadId: string) =>
      withMock(
        "GET /tenants/{t}/threads/{id}/messages",
        () => request<EmailMessage[]>(`/tenants/${enc(tenant)}/threads/${enc(threadId)}/messages`),
        () => mock.mockMessages(threadId),
      ),
    /** .json → JSON body; .eml/.mbox → multipart field `file`. */
    import: async (tenant: string, file: File) => {
      const isJson = /\.json$/i.test(file.name) || file.type === "application/json";
      if (isJson) {
        const text = await file.text();
        const body = JSON.parse(text) as unknown;
        return withMock(
          "POST /tenants/{t}/email/import",
          () => request<ImportResponse>(`/tenants/${enc(tenant)}/email/import`, { body, timeoutMs: 30000 }),
          () => mock.mockImport("email"),
        );
      }
      const fd = new FormData();
      fd.append("file", file, file.name);
      return withMock(
        "POST /tenants/{t}/email/import",
        () => request<ImportResponse>(`/tenants/${enc(tenant)}/email/import`, { method: "POST", raw: fd, timeoutMs: 30000 }),
        () => mock.mockImport("email"),
      );
    },
  },

  // ---------- memory ----------
  facts: {
    /** First page (API default 200, up to 1000 via `limit`). Use `page` / `all` when completeness matters. */
    list: (tenant: string, params: { status?: string; entity?: string; kind?: string; limit?: number; cursor?: string } = {}) =>
      withMock(
        "GET /tenants/{t}/facts",
        () => request<Fact[]>(`/tenants/${enc(tenant)}/facts${q(params)}`),
        () => mock.mockFacts(params),
      ),
    /** One page plus the X-Next-Cursor / X-Truncated headers. */
    async page(
      tenant: string,
      params: { status?: string; entity?: string; kind?: string; limit?: number; cursor?: string } = {},
    ): Promise<Paged<Fact>> {
      if (isForcedMock()) {
        markMock("GET /tenants/{t}/facts", "NEXT_PUBLIC_MOCK=1");
        return { rows: resolveMock("GET /tenants/{t}/facts", () => mock.mockFacts(params)), nextCursor: null, truncated: false };
      }
      const { data, headers } = await requestFull<Fact[]>(`/tenants/${enc(tenant)}/facts${q(params)}`);
      markLive("GET /tenants/{t}/facts");
      return { rows: data, nextCursor: headers.get("X-Next-Cursor"), truncated: headers.get("X-Truncated") === "true" };
    },
    /** Every matching fact, following cursors (bounded by `maxPages` pages of 1000). */
    async all(tenant: string, params: { status?: string; entity?: string; kind?: string } = {}, maxPages = 50): Promise<Fact[]> {
      const out: Fact[] = [];
      let cursor: string | undefined;
      for (let i = 0; i < maxPages; i++) {
        const page = await api.facts.page(tenant, { ...params, limit: 1000, cursor });
        out.push(...page.rows);
        if (!page.nextCursor) break;
        cursor = page.nextCursor;
      }
      return out;
    },
  },
  why: (tenant: string, nodeId: string) =>
    withMock("GET /tenants/{t}/why/{id}", () => request<WhyResponse>(`/tenants/${enc(tenant)}/why/${enc(nodeId)}`), () => mock.mockWhy(nodeId)),
  belief: (tenant: string, t: number, entity?: string) =>
    withMock(
      "GET /tenants/{t}/belief",
      () => request<Belief>(`/tenants/${enc(tenant)}/belief${q({ t: Math.round(t), entity })}`),
      () => mock.mockBelief(t, entity),
    ),
  timeline: (tenant: string) =>
    withMock("GET /tenants/{t}/timeline", () => request<Timeline>(`/tenants/${enc(tenant)}/timeline`), mock.mockTimeline),
  snapshots: {
    create: (tenant: string, label: string) =>
      withMock(
        "POST /tenants/{t}/snapshots",
        () => request<Snapshot>(`/tenants/${enc(tenant)}/snapshots`, { body: { label }, timeoutMs: 20000 }),
        () => mock.mockSnapshot(label),
      ),
  },
  analytics: {
    whoKnows: (tenant: string, entity: string) =>
      withMock(
        "GET /tenants/{t}/analytics/who-knows",
        () => request<WhoKnows[]>(`/tenants/${enc(tenant)}/analytics/who-knows${q({ entity })}`),
        () => mock.mockWhoKnows(entity),
      ),
    openCommitments: (tenant: string, person?: string) =>
      withMock(
        "GET /tenants/{t}/analytics/open-commitments",
        () => request<Fact[]>(`/tenants/${enc(tenant)}/analytics/open-commitments${q({ person })}`),
        () => mock.mockOpenCommitments(person),
      ),
    contradictions: (tenant: string) =>
      withMock(
        "GET /tenants/{t}/analytics/contradictions",
        () => request<Contradiction[]>(`/tenants/${enc(tenant)}/analytics/contradictions`),
        mock.mockContradictions,
      ),
    clusters: (tenant: string) =>
      withMock("GET /tenants/{t}/analytics/clusters", () => request<Cluster[]>(`/tenants/${enc(tenant)}/analytics/clusters`), mock.mockClusters),
  },
  impact: {
    get: (tenant: string) => withMock("GET /tenants/{t}/impact", () => request<import("./types").ImpactResponse>(`/tenants/${enc(tenant)}/impact`), () => null),
    draft: (tenant: string, workItemId: string, currentFactId: string) => request<import("./types").ImpactDraft>(`/tenants/${enc(tenant)}/impact/${enc(workItemId)}/draft`, { method: "POST", body: { current_fact_id: currentFactId }, timeoutMs: 15000 }),
    drafts: (tenant: string) => request<import("./types").ImpactDraft[]>(`/tenants/${enc(tenant)}/impact/drafts`),
  },
  people: {
    list: (tenant: string) => isForcedMock()
      ? Promise.reject(new ApiError(409, "preview_mode", "Connecting work requires a live workspace. This preview uses fixture data."))
      : request<import("./types").PersonRef[]>(`/tenants/${enc(tenant)}/people`),
  },
  work: {
    save: (tenant: string, body: import("./types").WorkManifest) => isForcedMock()
      ? Promise.reject(new ApiError(409, "preview_mode", "Connecting work requires a live workspace. This preview uses fixture data."))
      : request<{ imported: number; document_id: string }>(`/tenants/${enc(tenant)}/work-items/import`, { method: "POST", body, timeoutMs: 15000 }),
  },

  // ---------- chat ----------
  chat: {
    send: (tenant: string, message: string, session_id?: string) =>
      withMock(
        "POST /tenants/{t}/chat",
        () => request<ChatResponse>(`/tenants/${enc(tenant)}/chat`, { body: { message, session_id }, timeoutMs: 90000 }),
        () => mock.mockChat(message, session_id),
      ),
    history: (tenant: string, sessionId: string) =>
      withMock(
        "GET /tenants/{t}/chat/{session}",
        () => request<ChatTurn[]>(`/tenants/${enc(tenant)}/chat/${enc(sessionId)}`),
        () => mock.mockSession(sessionId),
      ),
  },

  // ---------- board ----------
  board: {
    agents: (tenant: string) => withMock("GET /tenants/{t}/agents", () => request<Agent[]>(`/tenants/${enc(tenant)}/agents`), mock.mockAgents),
    /** status: submitted | working | input_required | completed | failed | all. Bench tasks (kind bench*) are hidden unless includeBench. */
    tasks: (tenant: string, status?: string, includeBench = false) =>
      withMock(
        "GET /tenants/{t}/tasks",
        () => request<Task[]>(`/tenants/${enc(tenant)}/tasks${q({ status, include_bench: includeBench ? "true" : undefined })}`),
        () => mock.mockTasks(status),
      ),
    trace: (tenant: string, taskId: string) =>
      withMock(
        "GET /tenants/{t}/tasks/{id}/trace",
        () => request<TaskTrace>(`/tenants/${enc(tenant)}/tasks/${enc(taskId)}/trace`),
        () => mock.mockTrace(taskId),
      ),
    submit: (tenant: string, body: { kind: string; payload: Record<string, unknown>; requires: string[]; about_ids?: string[] }) =>
      withMock("POST /tenants/{t}/tasks", () => request<Task>(`/tenants/${enc(tenant)}/tasks`, { body }), () => mock.mockSubmitTask(body)),
  },
  demo: {
    supersede: (tenant: string, body: { fact_id?: string; new_object: string; speaker_id?: string }) =>
      withMock(
        "POST /tenants/{t}/demo/supersede",
        () => request<SupersedeResponse>(`/tenants/${enc(tenant)}/demo/supersede`, { body, timeoutMs: 30000 }),
        () => mock.mockSupersede(body),
      ),
    doubleClaim: (tenant: string, body: { task_id?: string } = {}) =>
      withMock(
        "POST /tenants/{t}/demo/double-claim",
        () => request<DoubleClaimResponse>(`/tenants/${enc(tenant)}/demo/double-claim`, { body, timeoutMs: 30000 }),
        () => mock.mockDoubleClaim(body),
      ),
  },
  eventsUrl: (tenant: string) => withKey(`${API_BASE}/tenants/${enc(tenant)}/events`),

  // ---------- skills ----------
  skills: {
    list: (tenant: string) => withMock("GET /tenants/{t}/skills", () => request<Skill[]>(`/tenants/${enc(tenant)}/skills`), mock.mockSkills),
    outcome: (tenant: string, skillId: string, body: { ok: boolean; agent_id?: string }) =>
      withMock(
        "POST /tenants/{t}/skills/{id}/outcome",
        () => request<Skill>(`/tenants/${enc(tenant)}/skills/${enc(skillId)}/outcome`, { body }),
        () => mock.mockSkillOutcome(skillId, body),
      ),
    run: (tenant: string, goal: string) =>
      withMock(
        "POST /tenants/{t}/skills/run",
        () => request<{ task_id: string }>(`/tenants/${enc(tenant)}/skills/run`, { body: { goal }, timeoutMs: 30000 }),
        () => mock.mockRunSkill(goal),
      ),
  },

  // ---------- bench ----------
  bench: {
    results: () => withMock("GET /bench/results", () => request<BenchResult[]>("/bench/results"), mock.mockBench),
    run: (body: { agents: number; tenants: number; duration_s: number }) =>
      withMock("POST /bench/run", () => request<{ run_id: string }>("/bench/run", { body, timeoutMs: 20000 }), () => ({
        run_id: `run_mock_${Date.now()}`,
      })),
  },
};

export type Api = typeof api;
