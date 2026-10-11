// JSON shapes from docs/contracts/http-api.md and docs/contracts/email-format.md.
// All timestamps are epoch milliseconds. Ids are strings.

export type ApiErrorBody = { error: { code: string; message: string } };

// ---------- Tenants ----------
export type TenantCounts = {
  episodes: number;
  facts: number;
  decisions: number;
  commitments: number;
  tasks: number;
  skills: number;
};

export type Tenant = {
  slug: string;
  display_name: string;
  graph: string;
  /** GRAPH.MEMORY USAGE total; FalkorDB 6.0.1 reports 0, so only show it when > 0. */
  usage_mb: number;
  /** Node count of the tenant graph (`MATCH (n) RETURN count(n)`). Optional for older APIs. */
  nodes?: number;
  /** Edge count of the tenant graph (`MATCH ()-[r]->() RETURN count(r)`). Optional for older APIs. */
  edges?: number;
  counts: TenantCounts;
  acl: { rw_user: string; ro_user: string; rules: string[] };
};

export type ImpactDraft = { id: string; title: string; body: string; status: "draft" | string; created_at: number; work_item_id: string; current_fact_id: string };
export type ImpactItem = { id: string; title: string; status: "open" | "completed" | "cancelled"; owner: PersonRef | null; assessment: "needs_review" | "aligned" | "closed" | "unresolved"; reason: string; baseline: Fact; current: Fact | null; document: { id: string; title: string; uri: string; content: string; synthetic: boolean }; rationale: string; path: Subgraph; draft: ImpactDraft | null };
export type ImpactResponse = { summary: { tracked: number; needs_review: number; aligned: number; closed: number; unresolved: number }; items: ImpactItem[]; cypher: string };
export type WorkManifest = {
  document: { title: string; uri: string; content: string; synthetic: boolean };
  items: { id: string; title: string; status: ImpactItem["status"]; owner_id: string; baseline_fact_id: string; rationale: string }[];
};

export type AclProbe = { allowed: boolean; error: string };

// ---------- People / sources ----------
export type PersonRef = { id: string; name: string; email?: string };

export type SourceKind = "utterance" | "email";

/** Provenance pointer returned by /why and attached to chat sources. */
export type SourceRef = {
  kind: SourceKind;
  container: { id: string; title?: string; subject?: string };
  t_start?: number | null;
  sent_at?: number | null;
  message_id?: string | null;
};

// ---------- Meetings and ingestion ----------
export type Meeting = {
  id: string;
  title: string;
  started_at: number;
  ended_at: number | null;
  source_uri: string | null;
  episodes: number;
  facts: number;
  status: string;
};

export type ImportResponse = { meeting_id?: string; thread_id?: string; job_id: string };

export type JobStatus = "queued" | "running" | "done" | "failed";

export type JobStats = {
  episodes: number;
  entities: number;
  facts: number;
  decisions: number;
  commitments: number;
  superseded: number;
  // The API adds pipeline details (container_id, source_kind, duplicates, errors, ...).
  [extra: string]: unknown;
};

export type Job = {
  status: JobStatus;
  stage: string;
  progress: number;
  stats: JobStats;
  error?: string;
};

export type Episode = {
  id: string;
  seq: number;
  speaker: PersonRef;
  text: string;
  t_start: number;
  t_end: number;
  t_occurred: number;
};

// ---------- Email threads ----------
export type EmailThread = {
  id: string;
  subject: string;
  started_at: number;
  messages: number;
  facts: number;
  status: string;
};

export type EmailMessage = {
  id: string;
  seq: number;
  sender: PersonRef;
  to: PersonRef[];
  cc: PersonRef[];
  sent_at: number;
  text: string;
  in_reply_to: string | null;
  /** Original message id from the export (msg_*); `id` is the Episode id. Why/chat sources carry this one. */
  message_id?: string | null;
};

// ---------- Memory ----------
export type FactKind = "fact" | "decision" | "commitment";
export type FactStatus = "active" | "superseded" | "retracted";

export type Fact = {
  id: string;
  kind: FactKind;
  subject: string;
  predicate: string;
  object: string;
  text: string;
  confidence: number;
  valid_from: number;
  valid_to: number | null;
  status: FactStatus;
  speaker: PersonRef;
  meeting: { id: string; title: string } | null;
  episode_id: string;
  due_at?: number | null;
  /** Present when the API has the email-format delta applied. */
  source?: SourceRef;
  /** Id of the fact this one supersedes, when known. */
  supersedes?: string | null;
  /** Commitment owner (open-commitments only). */
  owner?: PersonRef | null;
};

export type GraphNode = { id: string; label: string; props: Record<string, unknown> };
export type GraphEdge = {
  source: string;
  target: string;
  type: string;
  props?: Record<string, unknown>;
};
export type Subgraph = { nodes: GraphNode[]; edges: GraphEdge[] };

export type WhyResponse = {
  node: GraphNode;
  speaker: PersonRef | null;
  meeting: { id: string; title: string } | null;
  episode: { id: string; text: string; t_start: number | null; t_end: number | null } | null;
  history: Fact[];
  cypher: string;
  subgraph: Subgraph;
  source?: SourceRef;
};

export type Belief = { t: number; facts: Fact[]; cypher: string };

export type TimelineEventType =
  | "fact.created"
  | "fact.superseded"
  | "decision"
  | "commitment"
  | "meeting"
  | "email";

export type TimelineEvent = { t: number; type: TimelineEventType; id: string; text: string };
export type Snapshot = { name: string; taken_at: number; label: string };
export type Timeline = { events: TimelineEvent[]; snapshots: Snapshot[] };

export type WhoKnows = { person: PersonRef; mentions: number; last_at: number };
export type Contradiction = { key: string; facts: [Fact, Fact] };
export type Cluster = { component: number; entities: GraphNode[] };

// ---------- Chat ----------
export type Route = "vector" | "graph" | "template" | "freeform_ro";

export type RouterDecision = {
  intent: string;
  entities: string[];
  route: Route;
  template?: string;
};

export type ChatSource = {
  fact_id: string;
  speaker: string;
  meeting: string;
  t_start: number | null;
  kind?: SourceKind;
  thread?: string;
  sent_at?: number | null;
  message_id?: string | null;
  container_id?: string;
};

/** Raw utterance or email retrieved by episode recall and shown to the model as evidence. */
export type ChatEpisode = {
  episode_id: string;
  kind: SourceKind;
  speaker: string;
  container_id: string;
  text: string;
  t: number;
  meeting?: string;
  t_start?: number | null;
  thread?: string;
  sent_at?: number | null;
  score?: number;
};

export type ChatResponse = {
  answer: string;
  session_id: string;
  router: RouterDecision;
  cypher: string[];
  subgraph: Subgraph;
  sources: ChatSource[];
  episodes?: ChatEpisode[];
  model: string;
  latency_ms: number;
};

/** Shape of GET /chat/{session_id}; the contract only says "prior turns". */
export type ChatTurn = {
  role: "user" | "assistant";
  text: string;
  t: number;
  response?: ChatResponse;
};

// ---------- Board ----------
export type AgentState = "idle" | "working";

export type Agent = {
  id: string;
  name: string;
  model: string;
  capabilities: string[];
  last_seen: number;
  state: AgentState;
};

export type TaskStatus = "submitted" | "working" | "input_required" | "completed" | "failed";
export const TASK_STATUSES: TaskStatus[] = [
  "submitted",
  "working",
  "input_required",
  "completed",
  "failed",
];

export type Task = {
  id: string;
  kind: string;
  status: TaskStatus;
  version: number;
  owner_agent: string | null;
  priority: number;
  created_at: number;
  updated_at: number;
  payload: Record<string, unknown>;
  about: string[];
};

export type Artifact = {
  kind: string; // "github_issue" | "nudge" | "standup_summary" | ...
  uri?: string;
  text?: string;
  title?: string;
  simulated?: boolean;
};

export type TraceEventType =
  | "submitted"
  | "claimed"
  | "handed_off"
  | "completed"
  | "failed"
  | "input_required"
  | "skill_used";

export type TraceEvent = {
  t: number;
  type: TraceEventType;
  agent: string;
  summary?: string;
  subgraph_ids?: string[];
  artifact?: Artifact;
};

export type TaskTrace = { task: Task; events: TraceEvent[] };

export type SupersedeResponse = { old_fact_id: string; new_fact_id: string };
export type DoubleClaimResponse = {
  winners: number;
  losers: number;
  task_id: string;
  winner_agent: string;
};

export type EventName =
  | "episode.ingested"
  | "fact.created"
  | "fact.superseded"
  | "commitment.created"
  | "commitment.updated"
  | "task.submitted"
  | "task.claimed"
  | "task.handed_off"
  | "task.completed"
  | "task.failed"
  | "task.input_required"
  | "skill.learned"
  | "skill.ran"
  | "snapshot.taken";

export const EVENT_NAMES: EventName[] = [
  "episode.ingested",
  "fact.created",
  "fact.superseded",
  "commitment.created",
  "commitment.updated",
  "task.submitted",
  "task.claimed",
  "task.handed_off",
  "task.completed",
  "task.failed",
  "task.input_required",
  "skill.learned",
  "skill.ran",
  "snapshot.taken",
];

export type SSEEvent = {
  event: EventName | string;
  payload: Record<string, unknown>;
  ts: number;
};

// ---------- Skills ----------
export type SkillStep = {
  order: number;
  tool: string;
  args_template: string;
  guard: string | null;
};

export type Skill = {
  id: string;
  goal: string;
  version: number;
  runs: number;
  success_rate: number;
  status: "active" | "deprecated" | "draft";
  steps: SkillStep[];
  learned_from: string[];
  pagerank: number;
};

// ---------- Bench ----------
export type Engine = "6.0.1" | "4.22.0";
/** "local", "railway", or a harness label such as "local-p4" / "local-p8-q1000" (procs, queue size). */
export type BenchTarget = string;

export type BenchResult = {
  run_id: string;
  ts: number;
  engine: Engine;
  target: BenchTarget;
  agents: number;
  tenants: number;
  duration_s: number;
  read_p50: number;
  read_p95: number;
  read_p99: number;
  write_p50: number;
  write_p95: number;
  write_p99: number;
  errors: number;
  cas: { attempts: number; winners: number; losers: number };
  // Optional fields written by newer harness runs (packages/hiveboard/bench/harness.py).
  ops?: { total?: number; reads?: number; writes?: number; per_second?: number; read_ratio?: number };
  cas_violations?: unknown[];
  client?: { procs?: number; mode?: string; python?: string };
  server?: { THREAD_COUNT?: number; MAX_QUEUED_QUERIES?: number; [k: string]: unknown };
  cpu?: { server_cores_busy?: number; client_cores_busy?: number; [k: string]: unknown };
  usage_mb?: number | Record<string, number>;
  note?: string;
  source?: string;
};

// ---------- Health ----------
export type Health = {
  ok: boolean;
  falkordb: { version: string; graphs: string[]; kind?: string };
  llm: { backend: string; model: string };
  embeddings: { model: string; dim: number; backend?: string };
};
