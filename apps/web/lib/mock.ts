// Realistic mock data for the `orbit` tenant (plus two thin tenants), used when
// the API is unreachable, returns 5xx, or NEXT_PUBLIC_MOCK=1. The store is
// mutable so demo actions (supersede, double claim, import, outcomes) change
// what the pages show and publish events on the local bus.

import { busPublish } from "./bus";
import type {
  AclProbe,
  Agent,
  Belief,
  BenchResult,
  ChatResponse,
  ChatSource,
  ChatTurn,
  Cluster,
  Contradiction,
  DoubleClaimResponse,
  EmailMessage,
  EmailThread,
  Episode,
  Fact,
  FactKind,
  GraphEdge,
  GraphNode,
  Health,
  ImportResponse,
  Job,
  Meeting,
  PersonRef,
  Skill,
  Snapshot,
  Subgraph,
  SupersedeResponse,
  Task,
  TaskTrace,
  Tenant,
  Timeline,
  TimelineEvent,
  TraceEvent,
  WhoKnows,
  WhyResponse,
} from "./types";

// ---------- time helpers (IST = UTC+5:30) ----------
const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
function ist(y: number, m: number, d: number, h = 0, min = 0, s = 0): number {
  return Date.UTC(y, m - 1, d, h, min, s) - IST_OFFSET_MS;
}
const MIN = 60_000;

let seq = 1000;
function nextId(prefix: string) {
  seq += 1;
  return `${prefix}_${seq.toString(36)}`;
}

// ---------- people ----------
export const PEOPLE: Record<string, PersonRef & { role: string }> = {
  spk_aditya: { id: "spk_aditya", name: "Aditya", role: "lead", email: "aditya@orbit.example" },
  spk_priya: { id: "spk_priya", name: "Priya", role: "backend", email: "priya@orbit.example" },
  spk_rahul: { id: "spk_rahul", name: "Rahul", role: "mobile", email: "rahul@orbit.example" },
  spk_sana: { id: "spk_sana", name: "Sana", role: "product", email: "sana@orbit.example" },
};
const P = (id: string): PersonRef => {
  const p = PEOPLE[id];
  return { id: p.id, name: p.name, email: p.email };
};
const byEmail = (email: string): PersonRef =>
  P(Object.values(PEOPLE).find((p) => p.email === email)?.id ?? "spk_aditya");

// ---------- meetings and episodes ----------
type RawSeg = [speaker: string, start: number, end: number, text: string];

type MeetingDef = {
  id: string;
  title: string;
  started_at: number;
  ended_at: number;
  source_uri: string | null;
  segs: RawSeg[];
};

const MEETING_DEFS: MeetingDef[] = [
  {
    id: "mtg_orbit_001",
    title: "Orbit kickoff",
    started_at: ist(2026, 9, 7, 10, 0),
    ended_at: ist(2026, 9, 7, 10, 8, 30),
    source_uri: "data/meetings/orbit_001.wav",
    segs: [
      ["spk_aditya", 0, 6400, "Alright, let's lock the scope for the October release. Payments first, then onboarding polish. Offline mode is out unless someone fights for it."],
      ["spk_priya", 6400, 15200, "Payments go first. I can have the UPI flow done by the 24th, assuming the PSP sandbox credentials land this week."],
      ["spk_rahul", 15200, 24000, "Onboarding screens are mostly done. I'll have the remaining three by the 18th."],
      ["spk_sana", 24000, 36000, "For the checkout I want a custom modal. We control the animation and it matches the brand."],
      ["spk_aditya", 36000, 45000, "Fine, custom modal for checkout. Offline mode is deferred to November; we do not have the capacity."],
      ["spk_aditya", 45000, 56000, "Pilot customer is Northwind. They want to test payments on the 29th, so the 24th date matters."],
      ["spk_priya", 56000, 64000, "Understood. Razorpay is the PSP; sandbox first, live keys after the security review."],
    ],
  },
  {
    id: "mtg_orbit_002",
    title: "Orbit standup 1",
    started_at: ist(2026, 9, 14, 9, 30),
    ended_at: ist(2026, 9, 14, 9, 36),
    source_uri: "data/meetings/orbit_002.wav",
    segs: [
      ["spk_aditya", 0, 5000, "Quick round. Priya, where is the UPI flow?"],
      ["spk_priya", 5000, 21000, "Intent flow is built, the collect flow is half done. The sandbox credentials only landed yesterday, so I lost four days. I need to move it to Friday, the 26th."],
      ["spk_aditya", 21000, 27000, "OK. Move it to Friday. Sana, can you tell Northwind the test slot shifts?"],
      ["spk_sana", 27000, 34000, "Yes. I'll push their test to the 30th."],
      ["spk_rahul", 34000, 45000, "Onboarding screens shipped on the 18th as promised. I'm picking up the QA plan for payments next."],
    ],
  },
  {
    id: "mtg_orbit_003",
    title: "Design review",
    started_at: ist(2026, 9, 16, 15, 0),
    ended_at: ist(2026, 9, 16, 15, 9),
    source_uri: "data/meetings/orbit_003.wav",
    segs: [
      ["spk_sana", 0, 12000, "We tested the custom modal with five users. Two could not dismiss it with the screen reader. I want to reverse the checkout decision."],
      ["spk_rahul", 12000, 22000, "Native bottom sheet gets us accessibility for free, and it is platform-consistent on both OSes."],
      ["spk_aditya", 22000, 31000, "Agreed. We switch checkout to the native bottom sheet. Rationale: accessibility and platform consistency. Record that it supersedes the kickoff decision."],
      ["spk_sana", 31000, 38000, "Done. I'll update the design file by Friday."],
      ["spk_rahul", 38000, 50000, "On QA: I'll have the payments sign-off by the 28th, two days after Priya's date."],
      ["spk_priya", 50000, 58000, "That works if the collect flow holds. Razorpay sandbox webhooks are flaky in the evenings."],
    ],
  },
  {
    id: "mtg_orbit_004",
    title: "Orbit standup 2",
    started_at: ist(2026, 9, 21, 9, 30),
    ended_at: ist(2026, 9, 21, 9, 35),
    source_uri: null,
    segs: [
      ["spk_aditya", 0, 4000, "Round two. Priya?"],
      ["spk_priya", 4000, 14000, "UPI flow is in code review. Both flows pass in the sandbox. On track for Friday."],
      ["spk_rahul", 14000, 22000, "QA plan is written. I start the payments pass the moment the review lands."],
      ["spk_aditya", 22000, 32000, "Good. I'll brief Northwind on the timeline by the 23rd. Sana, the customer call is Wednesday?"],
      ["spk_sana", 32000, 38000, "Wednesday at eleven. I'll bring the recap here."],
    ],
  },
  {
    id: "mtg_orbit_005",
    title: "Customer call recap",
    started_at: ist(2026, 9, 23, 11, 0),
    ended_at: ist(2026, 9, 23, 11, 7),
    source_uri: "data/meetings/orbit_005.wav",
    segs: [
      ["spk_sana", 0, 14000, "Recap of the Meridian call. They are the pilot now; Northwind paused their evaluation last week."],
      ["spk_aditya", 14000, 22000, "So the pilot customer is Meridian. Noted, and that contradicts what we said at kickoff."],
      ["spk_sana", 22000, 36000, "Meridian requires SSO for the pilot. Without it their security team will not approve the install."],
      ["spk_aditya", 36000, 48000, "Then SSO goes into the October release scope. Payments stays first; SSO is the second milestone."],
      ["spk_priya", 48000, 56000, "SSO is a week of work if we use the identity provider's SDK. I can start after the UPI flow lands."],
    ],
  },
  {
    id: "mtg_orbit_006",
    title: "Retro",
    started_at: ist(2026, 9, 30, 16, 0),
    ended_at: ist(2026, 9, 30, 16, 8),
    source_uri: "data/meetings/orbit_006.wav",
    segs: [
      ["spk_aditya", 0, 12000, "Retro. What went well, what slipped. The one slip was the UPI flow, and the cause was the PSP credential delay, not the code."],
      ["spk_priya", 12000, 24000, "Agreed. Going forward we request sandbox credentials in the kickoff week, before any dates are promised."],
      ["spk_rahul", 24000, 34000, "QA sign-off landed on the 30th as revised. The bottom sheet decision saved us a week of accessibility fixes."],
      ["spk_sana", 34000, 44000, "Why did we choose the bottom sheet again? For the record: two of five users could not dismiss the custom modal with a screen reader."],
      ["spk_aditya", 44000, 52000, "Sana, can you circulate the retro summary by the 2nd?"],
      ["spk_sana", 52000, 56000, "Yes, by Friday the 2nd."],
    ],
  },
];

const EPISODES: Record<string, Episode[]> = {};
for (const m of MEETING_DEFS) {
  EPISODES[m.id] = m.segs.map(([spk, s, e, text], i) => ({
    id: `ep_${m.id.replace("mtg_", "")}_${String(i + 1).padStart(2, "0")}`,
    seq: i + 1,
    speaker: P(spk),
    text,
    t_start: s,
    t_end: e,
    t_occurred: m.started_at + s,
  }));
}
const epId = (meeting: string, n: number) =>
  `ep_${meeting.replace("mtg_", "")}_${String(n).padStart(2, "0")}`;

// ---------- email threads ----------
type MsgDef = {
  id: string;
  sent_at: number;
  from: string;
  to: string[];
  cc: string[];
  in_reply_to: string | null;
  text: string;
};
type ThreadDef = { id: string; subject: string; started_at: number; messages: MsgDef[] };

const THREAD_DEFS: ThreadDef[] = [
  {
    id: "thr_orbit_001",
    subject: "UPI flow timeline",
    started_at: ist(2026, 9, 16, 14, 2),
    messages: [
      {
        id: "msg_orbit_001_1",
        sent_at: ist(2026, 9, 16, 14, 2),
        from: "priya@orbit.example",
        to: ["aditya@orbit.example"],
        cc: ["rahul@orbit.example"],
        in_reply_to: null,
        text: "Aditya, quick heads-up on the UPI flow. The Razorpay sandbox credentials arrived on the 13th, so the Friday the 26th date from standup stands. Collect-flow webhooks are flaky after 18:00 IST; I am adding a retry.",
      },
      {
        id: "msg_orbit_001_2",
        sent_at: ist(2026, 9, 16, 14, 31),
        from: "aditya@orbit.example",
        to: ["priya@orbit.example"],
        cc: ["rahul@orbit.example"],
        in_reply_to: "msg_orbit_001_1",
        text: "Thanks. Keep the 26th. If the webhooks stay flaky, tell Rahul so the QA plan covers retries.",
      },
      {
        id: "msg_orbit_001_3",
        sent_at: ist(2026, 9, 16, 15, 12),
        from: "rahul@orbit.example",
        to: ["priya@orbit.example", "aditya@orbit.example"],
        cc: [],
        in_reply_to: "msg_orbit_001_2",
        text: "Adding webhook retry cases to the QA plan today.",
      },
    ],
  },
  {
    id: "thr_orbit_002",
    subject: "Re: QA sign-off for payments",
    started_at: ist(2026, 9, 22, 18, 40),
    messages: [
      {
        id: "msg_orbit_002_1",
        sent_at: ist(2026, 9, 22, 18, 40),
        from: "rahul@orbit.example",
        to: ["aditya@orbit.example"],
        cc: ["priya@orbit.example", "sana@orbit.example"],
        in_reply_to: null,
        text: "Aditya, the payments QA pass started today after the review merged. With the webhook retry cases added I need two more days. QA sign-off for payments moves from the 28th to the 30th.",
      },
      {
        id: "msg_orbit_002_2",
        sent_at: ist(2026, 9, 22, 19, 5),
        from: "aditya@orbit.example",
        to: ["rahul@orbit.example"],
        cc: ["priya@orbit.example", "sana@orbit.example"],
        in_reply_to: "msg_orbit_002_1",
        text: "Fine. The 30th. Meridian's test is after that anyway.",
      },
    ],
  },
  {
    id: "thr_orbit_003",
    subject: "Meridian onboarding notes",
    started_at: ist(2026, 9, 24, 9, 15),
    messages: [
      {
        id: "msg_orbit_003_1",
        sent_at: ist(2026, 9, 24, 9, 15),
        from: "sana@orbit.example",
        to: ["aditya@orbit.example", "priya@orbit.example"],
        cc: ["rahul@orbit.example"],
        in_reply_to: null,
        text: "Notes from the Meridian call. SSO is required before the pilot. They use Okta. Their security review also needs the data retention note updated.",
      },
      {
        id: "msg_orbit_003_2",
        sent_at: ist(2026, 9, 24, 10, 2),
        from: "priya@orbit.example",
        to: ["sana@orbit.example"],
        cc: ["aditya@orbit.example", "rahul@orbit.example"],
        in_reply_to: "msg_orbit_003_1",
        text: "Okta works with the IdP SDK. I will scope SSO after the UPI flow lands on the 26th.",
      },
    ],
  },
  {
    id: "thr_orbit_004",
    subject: "Retro agenda and summary",
    started_at: ist(2026, 9, 29, 17, 30),
    messages: [
      {
        id: "msg_orbit_004_1",
        sent_at: ist(2026, 9, 29, 17, 30),
        from: "aditya@orbit.example",
        to: ["priya@orbit.example", "rahul@orbit.example", "sana@orbit.example"],
        cc: [],
        in_reply_to: null,
        text: "Agenda for tomorrow's retro: UPI slip root cause, bottom sheet outcome, Meridian scope change. Sana owns the written summary.",
      },
      {
        id: "msg_orbit_004_2",
        sent_at: ist(2026, 9, 29, 18, 4),
        from: "sana@orbit.example",
        to: ["aditya@orbit.example"],
        cc: ["priya@orbit.example", "rahul@orbit.example"],
        in_reply_to: "msg_orbit_004_1",
        text: "Acknowledged. Summary by Friday the 2nd.",
      },
    ],
  },
];

const MESSAGES: Record<string, EmailMessage[]> = {};
for (const t of THREAD_DEFS) {
  MESSAGES[t.id] = t.messages.map((m, i) => ({
    id: m.id,
    seq: i + 1,
    sender: byEmail(m.from),
    to: m.to.map(byEmail),
    cc: m.cc.map(byEmail),
    sent_at: m.sent_at,
    text: m.text,
    in_reply_to: m.in_reply_to,
  }));
}
const threadOfMessage = (msgId: string) =>
  THREAD_DEFS.find((t) => t.messages.some((m) => m.id === msgId));

// ---------- entities ----------
export const ENTITIES: Record<string, GraphNode> = {};
const ent = (id: string, name: string, type: string) => {
  ENTITIES[id] = { id, label: "Entity", props: { name, type } };
};
ent("ent_upi_flow", "UPI flow", "feature");
ent("ent_october_release", "October release", "project");
ent("ent_payments", "Payments", "feature");
ent("ent_psp_sandbox", "PSP sandbox credentials", "system");
ent("ent_razorpay", "Razorpay", "system");
ent("ent_checkout", "Checkout", "feature");
ent("ent_onboarding", "Onboarding screens", "feature");
ent("ent_offline_mode", "Offline mode", "feature");
ent("ent_northwind", "Northwind", "customer");
ent("ent_meridian", "Meridian", "customer");
ent("ent_sso", "SSO", "feature");
ent("ent_qa_signoff", "QA sign-off for payments", "milestone");

// ---------- facts ----------
type FactDef = {
  id: string;
  kind: FactKind;
  speaker: string;
  /** episode id (meeting) or message id (email) */
  from: string;
  subject: string;
  predicate: string;
  object: string;
  text: string;
  confidence: number;
  due_at?: number;
  supersedes?: string;
  entities: string[];
};

const FACT_DEFS: FactDef[] = [
  { id: "fact_001", kind: "decision", speaker: "spk_aditya", from: epId("mtg_orbit_001", 1), subject: "October release", predicate: "scope_includes", object: "payments", text: "Payments first for the October release; onboarding polish after.", confidence: 0.92, entities: ["ent_october_release", "ent_payments"] },
  { id: "fact_002", kind: "commitment", speaker: "spk_priya", from: epId("mtg_orbit_001", 2), subject: "UPI flow", predicate: "due", object: "2026-09-24", text: "UPI flow done by the 24th, assuming the PSP sandbox credentials land this week.", confidence: 0.9, due_at: ist(2026, 9, 24, 18, 0), entities: ["ent_upi_flow", "ent_psp_sandbox"] },
  { id: "fact_003", kind: "commitment", speaker: "spk_rahul", from: epId("mtg_orbit_001", 3), subject: "Onboarding screens", predicate: "due", object: "2026-09-18", text: "Remaining three onboarding screens by the 18th.", confidence: 0.88, due_at: ist(2026, 9, 18, 18, 0), entities: ["ent_onboarding"] },
  { id: "fact_004", kind: "decision", speaker: "spk_sana", from: epId("mtg_orbit_001", 4), subject: "Checkout", predicate: "uses", object: "custom modal", text: "Checkout uses a custom modal: controlled animation, matches the brand.", confidence: 0.85, entities: ["ent_checkout"] },
  { id: "fact_005", kind: "decision", speaker: "spk_aditya", from: epId("mtg_orbit_001", 5), subject: "Offline mode", predicate: "scheduled_for", object: "November", text: "Offline mode deferred to November for capacity reasons.", confidence: 0.9, entities: ["ent_offline_mode"] },
  { id: "fact_006", kind: "fact", speaker: "spk_aditya", from: epId("mtg_orbit_001", 6), subject: "Pilot customer", predicate: "is", object: "Northwind", text: "Pilot customer is Northwind; they test payments on the 29th.", confidence: 0.9, entities: ["ent_northwind", "ent_payments"] },
  { id: "fact_007", kind: "fact", speaker: "spk_priya", from: epId("mtg_orbit_001", 7), subject: "Payments", predicate: "psp", object: "Razorpay", text: "Razorpay is the PSP; sandbox first, live keys after the security review.", confidence: 0.93, entities: ["ent_payments", "ent_razorpay"] },
  { id: "fact_008", kind: "fact", speaker: "spk_priya", from: epId("mtg_orbit_002", 2), subject: "UPI flow", predicate: "blocked_on", object: "PSP sandbox credentials", text: "UPI flow lost four days waiting for sandbox credentials.", confidence: 0.86, entities: ["ent_upi_flow", "ent_psp_sandbox"] },
  { id: "fact_009", kind: "commitment", speaker: "spk_priya", from: epId("mtg_orbit_002", 2), subject: "UPI flow", predicate: "due", object: "2026-09-26", text: "Move it to Friday, the 26th. The sandbox credentials only landed yesterday.", confidence: 0.94, due_at: ist(2026, 9, 26, 18, 0), supersedes: "fact_002", entities: ["ent_upi_flow"] },
  { id: "fact_022", kind: "commitment", speaker: "spk_sana", from: epId("mtg_orbit_002", 4), subject: "Northwind test slot", predicate: "due", object: "2026-09-30", text: "Push Northwind's payments test to the 30th.", confidence: 0.8, due_at: ist(2026, 9, 30, 18, 0), entities: ["ent_northwind"] },
  { id: "fact_010", kind: "decision", speaker: "spk_aditya", from: epId("mtg_orbit_003", 3), subject: "Checkout", predicate: "uses", object: "native bottom sheet", text: "Switch checkout to the native bottom sheet. Rationale: accessibility and platform consistency.", confidence: 0.95, supersedes: "fact_004", entities: ["ent_checkout"] },
  { id: "fact_011", kind: "commitment", speaker: "spk_rahul", from: epId("mtg_orbit_003", 5), subject: "QA sign-off for payments", predicate: "due", object: "2026-09-28", text: "Payments QA sign-off by the 28th, two days after Priya's date.", confidence: 0.88, due_at: ist(2026, 9, 28, 18, 0), entities: ["ent_qa_signoff", "ent_payments"] },
  { id: "fact_018", kind: "fact", speaker: "spk_priya", from: "msg_orbit_001_1", subject: "PSP sandbox credentials", predicate: "arrived", object: "2026-09-13", text: "Razorpay sandbox credentials arrived on the 13th.", confidence: 0.9, entities: ["ent_psp_sandbox", "ent_razorpay"] },
  { id: "fact_012", kind: "fact", speaker: "spk_priya", from: epId("mtg_orbit_004", 2), subject: "UPI flow", predicate: "status", object: "in code review", text: "UPI flow is in code review; both flows pass in the sandbox.", confidence: 0.9, entities: ["ent_upi_flow"] },
  { id: "fact_013", kind: "commitment", speaker: "spk_aditya", from: epId("mtg_orbit_004", 4), subject: "Northwind timeline brief", predicate: "due", object: "2026-09-23", text: "Brief Northwind on the timeline by the 23rd.", confidence: 0.82, due_at: ist(2026, 9, 23, 18, 0), entities: ["ent_northwind"] },
  { id: "fact_017", kind: "commitment", speaker: "spk_rahul", from: "msg_orbit_002_1", subject: "QA sign-off for payments", predicate: "due", object: "2026-09-30", text: "QA sign-off for payments moves from the 28th to the 30th (webhook retry cases added).", confidence: 0.91, due_at: ist(2026, 9, 30, 18, 0), supersedes: "fact_011", entities: ["ent_qa_signoff"] },
  { id: "fact_016", kind: "fact", speaker: "spk_sana", from: epId("mtg_orbit_005", 1), subject: "Pilot customer", predicate: "is", object: "Meridian", text: "Meridian is the pilot now; Northwind paused their evaluation.", confidence: 0.89, entities: ["ent_meridian", "ent_northwind"] },
  { id: "fact_014", kind: "fact", speaker: "spk_sana", from: epId("mtg_orbit_005", 3), subject: "Meridian", predicate: "requires", object: "SSO", text: "Meridian requires SSO for the pilot; security will not approve without it.", confidence: 0.93, entities: ["ent_meridian", "ent_sso"] },
  { id: "fact_015", kind: "decision", speaker: "spk_aditya", from: epId("mtg_orbit_005", 4), subject: "October release", predicate: "scope_includes", object: "SSO", text: "SSO added to the October release as the second milestone after payments.", confidence: 0.9, entities: ["ent_october_release", "ent_sso"] },
  { id: "fact_021", kind: "fact", speaker: "spk_aditya", from: epId("mtg_orbit_006", 1), subject: "UPI flow slip", predicate: "caused_by", object: "PSP credential delay", text: "The UPI flow slip was caused by the PSP credential delay, not the code.", confidence: 0.88, entities: ["ent_upi_flow", "ent_psp_sandbox"] },
  { id: "fact_019", kind: "decision", speaker: "spk_priya", from: epId("mtg_orbit_006", 2), subject: "Sandbox credentials", predicate: "requested_in", object: "kickoff week", text: "Request sandbox credentials in the kickoff week, before any dates are promised.", confidence: 0.9, entities: ["ent_psp_sandbox"] },
  { id: "fact_020", kind: "commitment", speaker: "spk_sana", from: epId("mtg_orbit_006", 6), subject: "Retro summary", predicate: "due", object: "2026-10-02", text: "Circulate the retro summary by Friday the 2nd.", confidence: 0.87, due_at: ist(2026, 10, 2, 18, 0), entities: [] },
];

function occurredAt(from: string): number {
  if (from.startsWith("msg_")) {
    for (const t of THREAD_DEFS) {
      const m = t.messages.find((x) => x.id === from);
      if (m) return m.sent_at;
    }
  }
  for (const eps of Object.values(EPISODES)) {
    const e = eps.find((x) => x.id === from);
    if (e) return e.t_occurred;
  }
  return ist(2026, 9, 1);
}

function containerOf(from: string): { kind: "utterance" | "email"; id: string; title: string } {
  if (from.startsWith("msg_")) {
    const t = threadOfMessage(from)!;
    return { kind: "email", id: t.id, title: t.subject };
  }
  for (const m of MEETING_DEFS) {
    if (EPISODES[m.id].some((e) => e.id === from)) return { kind: "utterance", id: m.id, title: m.title };
  }
  return { kind: "utterance", id: "unknown", title: "Unknown" };
}

function buildFacts(): Fact[] {
  const facts: Fact[] = FACT_DEFS.map((d) => {
    const c = containerOf(d.from);
    const t = occurredAt(d.from);
    const source =
      c.kind === "utterance"
        ? {
            kind: "utterance" as const,
            container: { id: c.id, title: c.title },
            t_start: EPISODES[c.id]?.find((e) => e.id === d.from)?.t_start ?? 0,
          }
        : {
            kind: "email" as const,
            container: { id: c.id, subject: c.title },
            sent_at: t,
            message_id: d.from,
          };
    return {
      id: d.id,
      kind: d.kind,
      subject: d.subject,
      predicate: d.predicate,
      object: d.object,
      text: d.text,
      confidence: d.confidence,
      valid_from: t,
      valid_to: null,
      status: "active",
      speaker: P(d.speaker),
      meeting: c.kind === "utterance" ? { id: c.id, title: c.title } : null,
      episode_id: d.from,
      due_at: d.due_at ?? null,
      source,
      supersedes: d.supersedes ?? null,
    };
  });
  for (const f of facts) {
    if (f.supersedes) {
      const old = facts.find((x) => x.id === f.supersedes);
      if (old) {
        old.valid_to = f.valid_from;
        old.status = "superseded";
      }
    }
  }
  return facts;
}

const FACT_ENTITIES: Record<string, string[]> = Object.fromEntries(
  FACT_DEFS.map((d) => [d.id, d.entities]),
);

// ---------- agents ----------
const T_RETRO_END = ist(2026, 9, 30, 16, 8);
const AGENTS: Agent[] = [
  { id: "agent_fact", name: "FactAgent", model: "gemma-4-26b-a4b-it", capabilities: ["extract"], last_seen: T_RETRO_END + 2 * MIN, state: "idle" },
  { id: "agent_scheduler", name: "SchedulerAgent", model: "gemma-4-26b-a4b-it", capabilities: ["schedule"], last_seen: T_RETRO_END + 40 * MIN, state: "idle" },
  { id: "agent_followup", name: "FollowUpAgent", model: "gemma-4-26b-a4b-it", capabilities: ["followup"], last_seen: T_RETRO_END + 41 * MIN, state: "idle" },
  { id: "agent_standup", name: "StandupAgent", model: "gemma-4-26b-a4b-it", capabilities: ["standup"], last_seen: T_RETRO_END + 55 * MIN, state: "working" },
  { id: "agent_answer", name: "AnswerAgent", model: "gemma-4-31b-it", capabilities: ["answer"], last_seen: T_RETRO_END + 50 * MIN, state: "idle" },
];

// ---------- tasks and traces ----------
const T_STANDUP1 = ist(2026, 9, 14, 9, 30);
const T_EMAIL_QA = ist(2026, 9, 22, 18, 40);

function buildTasks(): { tasks: Task[]; traces: Record<string, TraceEvent[]> } {
  const tasks: Task[] = [];
  const traces: Record<string, TraceEvent[]> = {};

  const t1 = T_STANDUP1 + 21_000 + 3_000;
  tasks.push({
    id: "task_001", kind: "followup", status: "completed", version: 5, owner_agent: "agent_followup", priority: 3,
    created_at: t1, updated_at: t1 + 48_000,
    payload: { reason: "commitment date moved", commitment: "UPI flow due 2026-09-26", previous: "2026-09-24" },
    about: ["fact_009", "fact_002"],
  });
  traces.task_001 = [
    { t: t1, type: "submitted", agent: "agent_scheduler", summary: "Woke on fact.superseded (UPI flow due 24th → 26th)" },
    { t: t1 + 1_200, type: "claimed", agent: "agent_scheduler", summary: "CAS claim won at version 1" },
    { t: t1 + 9_000, type: "handed_off", agent: "agent_followup", summary: "Due date moved to 26 Sep; Northwind test slot depends on it. Open a tracking issue and nudge Sana.", subgraph_ids: ["fact_002", "fact_009", "ent_upi_flow", "ent_northwind", "spk_priya"] },
    { t: t1 + 10_400, type: "claimed", agent: "agent_followup", summary: "CAS claim won at version 3" },
    { t: t1 + 22_000, type: "skill_used", agent: "agent_followup", summary: "skill_followup_issue v1" },
    { t: t1 + 48_000, type: "completed", agent: "agent_followup", summary: "Issue opened and nudge drafted.", artifact: { kind: "github_issue", uri: "https://github.com/orbit-demo/app/issues/42", title: "Update UPI flow milestone to 26 Sep", simulated: true } },
  ];

  const t2 = T_STANDUP1 + 21_000 + 2_000;
  tasks.push({
    id: "task_002", kind: "schedule", status: "completed", version: 3, owner_agent: "agent_scheduler", priority: 2,
    created_at: t2, updated_at: t2 + 6_000,
    payload: { commitment_id: "fact_009", due_at: "2026-09-26" },
    about: ["fact_009"],
  });
  traces.task_002 = [
    { t: t2, type: "submitted", agent: "agent_scheduler", summary: "fact.superseded with a date predicate" },
    { t: t2 + 800, type: "claimed", agent: "agent_scheduler" },
    { t: t2 + 6_000, type: "completed", agent: "agent_scheduler", summary: "commitment fact_009 due_at set to 2026-09-26", artifact: { kind: "commitment_update", text: "due_at 2026-09-24 → 2026-09-26" } },
  ];

  const t3 = T_RETRO_END + 50 * MIN;
  tasks.push({
    id: "task_003", kind: "standup", status: "working", version: 2, owner_agent: "agent_standup", priority: 5,
    created_at: t3, updated_at: t3 + 3 * MIN,
    payload: { goal: "Produce the weekly Orbit standup summary", meetings: ["mtg_orbit_004", "mtg_orbit_006"] },
    about: ["mtg_orbit_006"],
  });
  traces.task_003 = [
    { t: t3, type: "submitted", agent: "agent_standup", summary: "Weekly cadence detected after 2 standups" },
    { t: t3 + 2_000, type: "claimed", agent: "agent_standup" },
    { t: t3 + 3 * MIN, type: "skill_used", agent: "agent_standup", summary: "skill_standup v2 (success 83%)" },
  ];

  const t4 = T_EMAIL_QA + 90_000;
  tasks.push({
    id: "task_004", kind: "followup", status: "submitted", version: 3, owner_agent: "agent_followup", priority: 4,
    created_at: t4, updated_at: t4 + 7_000,
    payload: { reason: "commitment date moved (email)", commitment: "QA sign-off for payments due 2026-09-30", previous: "2026-09-28" },
    about: ["fact_017", "fact_011"],
  });
  traces.task_004 = [
    { t: t4, type: "submitted", agent: "agent_scheduler", summary: "Woke on fact.superseded from an email episode" },
    { t: t4 + 1_000, type: "claimed", agent: "agent_scheduler" },
    { t: t4 + 7_000, type: "handed_off", agent: "agent_followup", summary: "QA sign-off moved 28th → 30th in thread 'Re: QA sign-off for payments'. Update the milestone.", subgraph_ids: ["fact_011", "fact_017", "ent_qa_signoff", "thr_orbit_002"] },
  ];

  const t5 = ist(2026, 9, 23, 11, 7) + 4 * MIN;
  tasks.push({
    id: "task_005", kind: "answer", status: "input_required", version: 3, owner_agent: "agent_answer", priority: 4,
    created_at: t5, updated_at: t5 + 30_000,
    payload: { question: "Which customer is the pilot?", issue: "Two active facts disagree" },
    about: ["fact_006", "fact_016"],
  });
  traces.task_005 = [
    { t: t5, type: "submitted", agent: "agent_fact", summary: "Contradiction detected on key 'pilot customer|is'" },
    { t: t5 + 1_500, type: "claimed", agent: "agent_answer" },
    { t: t5 + 30_000, type: "input_required", agent: "agent_answer", summary: "Northwind (kickoff, Aditya) vs Meridian (customer call recap, Sana). Retract the kickoff fact?" },
  ];

  const t6 = ist(2026, 9, 27, 9, 0);
  tasks.push({
    id: "task_006", kind: "followup", status: "failed", version: 3, owner_agent: "agent_followup", priority: 6,
    created_at: t6, updated_at: t6 + 14_000,
    payload: { reason: "nudge owner before due date", commitment: "QA sign-off for payments due 2026-09-28" },
    about: ["fact_011"],
  });
  traces.task_006 = [
    { t: t6, type: "submitted", agent: "agent_scheduler", summary: "Due in 24h" },
    { t: t6 + 900, type: "claimed", agent: "agent_followup" },
    { t: t6 + 14_000, type: "failed", agent: "agent_followup", summary: "create_issue failed: GITHUB_TOKEN not configured; retried once, then failed loudly" },
  ];

  const t7 = T_RETRO_END + 30_000;
  tasks.push({
    id: "task_007", kind: "extract", status: "completed", version: 3, owner_agent: "agent_fact", priority: 1,
    created_at: t7, updated_at: t7 + 95_000,
    payload: { meeting_id: "mtg_orbit_006", title: "Retro" },
    about: ["mtg_orbit_006"],
  });
  traces.task_007 = [
    { t: t7, type: "submitted", agent: "agent_fact", summary: "meetings/import" },
    { t: t7 + 500, type: "claimed", agent: "agent_fact" },
    { t: t7 + 95_000, type: "completed", agent: "agent_fact", summary: "6 episodes, 3 facts (1 decision, 1 commitment), 0 superseded", artifact: { kind: "ingest_stats", text: "episodes 6 · entities 3 · facts 3 · superseded 0" } },
  ];

  return { tasks, traces };
}

// ---------- skills ----------
const SKILLS: Skill[] = [
  {
    id: "skill_standup_v2",
    goal: "Produce the weekly Orbit standup summary",
    version: 2,
    runs: 6,
    success_rate: 0.83,
    status: "active",
    pagerank: 0.42,
    learned_from: ["mtg_orbit_002", "mtg_orbit_004", "task_003"],
    steps: [
      { order: 1, tool: "open_commitments", args_template: '{"person": null, "since_days": 7}', guard: "result.count > 0" },
      { order: 2, tool: "recall", args_template: '{"query": "blocked OR slipped OR waiting", "k": 8}', guard: null },
      { order: 3, tool: "who_knows", args_template: '{"entity": "{{blocked_item.entity}}"}', guard: "blocked_item != null" },
      { order: 4, tool: "compose", args_template: '{"template": "standup_summary_v2", "sections": ["done", "due", "blocked"]}', guard: null },
      { order: 5, tool: "write_artifact", args_template: '{"kind": "standup_summary", "text": "{{summary}}"}', guard: "summary.length < 2000" },
    ],
  },
  {
    id: "skill_followup_issue",
    goal: "Open a tracking issue when a commitment date moves",
    version: 1,
    runs: 4,
    success_rate: 1.0,
    status: "active",
    pagerank: 0.31,
    learned_from: ["task_001"],
    steps: [
      { order: 1, tool: "why", args_template: '{"node_id": "{{fact_id}}"}', guard: null },
      { order: 2, tool: "open_commitments", args_template: '{"person": "{{speaker_id}}"}', guard: null },
      { order: 3, tool: "create_issue", args_template: '{"title": "Update {{subject}} milestone to {{object}}", "body": "{{why.history}}"}', guard: "object is a date" },
      { order: 4, tool: "complete", args_template: '{"artifact": {"kind": "github_issue", "uri": "{{issue.url}}"}}', guard: null },
    ],
  },
  {
    id: "skill_contradiction_triage",
    goal: "Flag contradicting active facts for a human",
    version: 1,
    runs: 2,
    success_rate: 0.5,
    status: "active",
    pagerank: 0.15,
    learned_from: ["task_005"],
    steps: [
      { order: 1, tool: "contradictions", args_template: "{}", guard: null },
      { order: 2, tool: "why", args_template: '{"node_id": "{{pair.a}}"}', guard: null },
      { order: 3, tool: "need_input", args_template: '{"question": "{{pair.a.text}} vs {{pair.b.text}}. Retract one?"}', guard: null },
    ],
  },
  {
    id: "skill_standup_v1",
    goal: "Produce the weekly Orbit standup summary",
    version: 1,
    runs: 3,
    success_rate: 0.33,
    status: "deprecated",
    pagerank: 0.12,
    learned_from: ["mtg_orbit_002"],
    steps: [
      { order: 1, tool: "recall", args_template: '{"query": "standup", "k": 20}', guard: null },
      { order: 2, tool: "compose", args_template: '{"template": "standup_summary_v1"}', guard: null },
    ],
  },
];

// ---------- bench ----------
const BENCH: BenchResult[] = [
  { run_id: "run_601_local_200", ts: ist(2026, 10, 1, 11, 10), engine: "6.0.1", target: "local", agents: 200, tenants: 20, duration_s: 300, read_p50: 2.1, read_p95: 6.8, read_p99: 14.2, write_p50: 3.4, write_p95: 11.2, write_p99: 27.5, errors: 0, cas: { attempts: 2000, winners: 80, losers: 1920 } },
  { run_id: "run_4220_local_200", ts: ist(2026, 10, 1, 11, 40), engine: "4.22.0", target: "local", agents: 200, tenants: 20, duration_s: 300, read_p50: 2.6, read_p95: 8.9, read_p99: 21.7, write_p50: 4.1, write_p95: 14.8, write_p99: 39.3, errors: 0, cas: { attempts: 2000, winners: 80, losers: 1920 } },
  { run_id: "run_601_railway_200", ts: ist(2026, 10, 1, 14, 5), engine: "6.0.1", target: "railway", agents: 200, tenants: 20, duration_s: 300, read_p50: 38, read_p95: 112, read_p99: 243, write_p50: 52, write_p95: 148, write_p99: 301, errors: 3, cas: { attempts: 2000, winners: 80, losers: 1920 } },
  { run_id: "run_4220_railway_200", ts: ist(2026, 10, 1, 14, 50), engine: "4.22.0", target: "railway", agents: 200, tenants: 20, duration_s: 300, read_p50: 44, read_p95: 131, read_p99: 296, write_p50: 61, write_p95: 177, write_p99: 388, errors: 7, cas: { attempts: 2000, winners: 80, losers: 1920 } },
  { run_id: "run_601_local_50", ts: ist(2026, 10, 1, 10, 20), engine: "6.0.1", target: "local", agents: 50, tenants: 5, duration_s: 120, read_p50: 1.4, read_p95: 3.9, read_p99: 7.1, write_p50: 2.2, write_p95: 6.3, write_p99: 12.8, errors: 0, cas: { attempts: 500, winners: 20, losers: 480 } },
  { run_id: "run_4220_local_50", ts: ist(2026, 10, 1, 10, 35), engine: "4.22.0", target: "local", agents: 50, tenants: 5, duration_s: 120, read_p50: 1.7, read_p95: 4.8, read_p99: 9.6, write_p50: 2.6, write_p95: 7.9, write_p99: 17.4, errors: 0, cas: { attempts: 500, winners: 20, losers: 480 } },
];

// ---------- mutable store ----------
type JobState = Job & { kind: "meeting" | "email"; created: number; polls: number };

type Store = {
  facts: Fact[];
  tasks: Task[];
  traces: Record<string, TraceEvent[]>;
  agents: Agent[];
  skills: Skill[];
  snapshots: Snapshot[];
  jobs: Record<string, JobState>;
  extraEvents: TimelineEvent[];
  sessions: Record<string, ChatTurn[]>;
  meetings: Meeting[];
  threads: EmailThread[];
};

function buildMeetings(facts: Fact[]): Meeting[] {
  return MEETING_DEFS.map((m) => ({
    id: m.id,
    title: m.title,
    started_at: m.started_at,
    ended_at: m.ended_at,
    source_uri: m.source_uri,
    episodes: EPISODES[m.id].length,
    facts: facts.filter((f) => f.meeting?.id === m.id).length,
    status: "ingested",
  }));
}

function buildThreads(facts: Fact[]): EmailThread[] {
  return THREAD_DEFS.map((t) => ({
    id: t.id,
    subject: t.subject,
    started_at: t.started_at,
    messages: t.messages.length,
    facts: facts.filter((f) => f.source?.kind === "email" && f.source.container.id === t.id).length,
    status: "ingested",
  }));
}

function initStore(): Store {
  const facts = buildFacts();
  const { tasks, traces } = buildTasks();
  return {
    facts,
    tasks,
    traces,
    agents: AGENTS.map((a) => ({ ...a })),
    skills: SKILLS.map((s) => ({ ...s, steps: s.steps.map((x) => ({ ...x })) })),
    snapshots: [
      { name: "team_orbit__snap_1757229600000", taken_at: ist(2026, 9, 7, 10, 30), label: "after kickoff" },
      { name: "team_orbit__snap_1758019200000", taken_at: ist(2026, 9, 16, 14, 50), label: "before design review" },
      { name: "team_orbit__snap_1759230300000", taken_at: ist(2026, 9, 30, 15, 55), label: "pre-retro" },
    ],
    jobs: {},
    extraEvents: [],
    sessions: {},
    meetings: buildMeetings(facts),
    threads: buildThreads(facts),
  };
}

const store: Store = initStore();

// ---------- tenants ----------
export function mockTenants(): Tenant[] {
  const f = store.facts;
  const orbit: Tenant = {
    slug: "orbit",
    display_name: "Orbit",
    graph: "team_orbit",
    usage_mb: 12.6,
    counts: {
      episodes: Object.values(EPISODES).reduce((n, e) => n + e.length, 0) + Object.values(MESSAGES).reduce((n, m) => n + m.length, 0),
      facts: f.filter((x) => x.kind === "fact").length,
      decisions: f.filter((x) => x.kind === "decision").length,
      commitments: f.filter((x) => x.kind === "commitment").length,
      tasks: store.tasks.length,
      skills: store.skills.length,
    },
    acl: {
      rw_user: "team_orbit_rw",
      ro_user: "team_orbit_ro",
      rules: [
        "ACL SETUSER team_orbit_rw on >*** +GRAPH.QUERY +GRAPH.RO_QUERY %RW~team_orbit %R~commons",
        "ACL SETUSER team_orbit_ro on >*** +GRAPH.RO_QUERY %R~team_orbit %R~commons",
      ],
    },
  };
  const nimbus: Tenant = {
    slug: "nimbus",
    display_name: "Nimbus",
    graph: "team_nimbus",
    usage_mb: 4.1,
    counts: { episodes: 18, facts: 7, decisions: 3, commitments: 4, tasks: 2, skills: 1 },
    acl: {
      rw_user: "team_nimbus_rw",
      ro_user: "team_nimbus_ro",
      rules: [
        "ACL SETUSER team_nimbus_rw on >*** +GRAPH.QUERY +GRAPH.RO_QUERY %RW~team_nimbus %R~commons",
        "ACL SETUSER team_nimbus_ro on >*** +GRAPH.RO_QUERY %R~team_nimbus %R~commons",
      ],
    },
  };
  const quill: Tenant = {
    slug: "quill",
    display_name: "Quill",
    graph: "team_quill",
    usage_mb: 2.3,
    counts: { episodes: 9, facts: 4, decisions: 1, commitments: 2, tasks: 1, skills: 0 },
    acl: {
      rw_user: "team_quill_rw",
      ro_user: "team_quill_ro",
      rules: [
        "ACL SETUSER team_quill_rw on >*** +GRAPH.QUERY +GRAPH.RO_QUERY %RW~team_quill %R~commons",
        "ACL SETUSER team_quill_ro on >*** +GRAPH.RO_QUERY %R~team_quill %R~commons",
      ],
    },
  };
  return [orbit, nimbus, quill];
}

export function mockAclProbe(tenant: string, target: string): AclProbe {
  return {
    allowed: false,
    error: `NOPERM User team_${tenant}_ro has no permissions to run the 'GRAPH.RO_QUERY' command on key 'team_${target}'`,
  };
}

// ---------- meetings / threads ----------
export const mockMeetings = (): Meeting[] => store.meetings;
export const mockEpisodes = (meetingId: string): Episode[] => EPISODES[meetingId] ?? [];
export const mockThreads = (): EmailThread[] => store.threads;
export const mockMessages = (threadId: string): EmailMessage[] => MESSAGES[threadId] ?? [];

const STAGES = ["parsing", "chunking", "embedding", "extracting", "writing"];

export function mockImport(kind: "meeting" | "email"): ImportResponse {
  const job_id = nextId("job");
  store.jobs[job_id] = {
    kind,
    status: "queued",
    stage: "queued",
    progress: 0,
    stats: { episodes: 0, entities: 0, facts: 0, decisions: 0, commitments: 0, superseded: 0 },
    created: Date.now(),
    polls: 0,
  };
  const id = nextId(kind === "meeting" ? "mtg" : "thr");
  return kind === "meeting" ? { meeting_id: id, job_id } : { thread_id: id, job_id };
}

export function mockJob(jobId: string): Job | null {
  const j = store.jobs[jobId];
  if (!j) return null;
  j.polls += 1;
  const p = Math.min(1, j.polls * 0.18);
  if (p >= 1) {
    j.status = "done";
    j.stage = "done";
    j.progress = 1;
    j.stats = { episodes: 7, entities: 5, facts: 4, decisions: 1, commitments: 2, superseded: 1 };
  } else {
    j.status = "running";
    j.progress = p;
    j.stage = STAGES[Math.min(STAGES.length - 1, Math.floor(p * STAGES.length))];
    j.stats = {
      episodes: Math.round(7 * Math.min(1, p * 2.5)),
      entities: Math.round(5 * Math.min(1, Math.max(0, p - 0.3) * 2)),
      facts: Math.round(4 * Math.min(1, Math.max(0, p - 0.5) * 2.5)),
      decisions: p > 0.7 ? 1 : 0,
      commitments: p > 0.6 ? Math.min(2, Math.round((p - 0.6) * 6)) : 0,
      superseded: p > 0.85 ? 1 : 0,
    };
  }
  const { status, stage, progress, stats } = j;
  return { status, stage, progress, stats };
}

// ---------- memory ----------
export function mockFacts(q: { status?: string; entity?: string; kind?: string }): Fact[] {
  return store.facts
    .filter((f) => !q.status || f.status === q.status)
    .filter((f) => !q.kind || f.kind === q.kind)
    .filter((f) => !q.entity || (FACT_ENTITIES[f.id] ?? []).includes(q.entity) || f.subject.toLowerCase() === q.entity.toLowerCase())
    .sort((a, b) => b.valid_from - a.valid_from);
}

function factNode(f: Fact): GraphNode {
  const label = f.kind === "decision" ? "Decision" : f.kind === "commitment" ? "Commitment" : "Fact";
  return {
    id: f.id,
    label,
    props: {
      subject: f.subject,
      predicate: f.predicate,
      object: f.object,
      text: f.text,
      status: f.status,
      confidence: f.confidence,
      valid_from: f.valid_from,
      valid_to: f.valid_to,
      ...(f.due_at ? { due_at: f.due_at } : {}),
    },
  };
}
function personNode(p: PersonRef): GraphNode {
  const full = PEOPLE[p.id];
  return { id: p.id, label: "Person", props: { name: p.name, role: full?.role, email: full?.email } };
}
function containerNode(f: Fact): GraphNode {
  if (f.source?.kind === "email") {
    const t = THREAD_DEFS.find((x) => x.id === f.source!.container.id)!;
    return { id: t.id, label: "EmailThread", props: { subject: t.subject, started_at: t.started_at } };
  }
  const m = MEETING_DEFS.find((x) => x.id === f.meeting?.id)!;
  return { id: m.id, label: "Meeting", props: { title: m.title, started_at: m.started_at, source_uri: m.source_uri } };
}
function episodeNode(f: Fact): GraphNode {
  if (f.source?.kind === "email") {
    const msg = MESSAGES[f.source.container.id]?.find((m) => m.id === f.episode_id);
    return { id: f.episode_id, label: "Episode", props: { source_kind: "email", text: msg?.text, t_occurred: msg?.sent_at } };
  }
  const ep = EPISODES[f.meeting?.id ?? ""]?.find((e) => e.id === f.episode_id);
  return { id: f.episode_id, label: "Episode", props: { source_kind: "utterance", text: ep?.text, t_start: ep?.t_start, t_end: ep?.t_end, t_occurred: ep?.t_occurred } };
}

function chainFor(f: Fact): Fact[] {
  const out: Fact[] = [f];
  let cur = f;
  for (let i = 0; i < 6; i++) {
    const older = cur.supersedes ? store.facts.find((x) => x.id === cur.supersedes) : undefined;
    if (!older) break;
    out.push(older);
    cur = older;
  }
  return out;
}

export function mockSubgraphForFacts(facts: Fact[], opts: { chain?: boolean; entities?: boolean } = {}): Subgraph {
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];
  const add = (n: GraphNode) => {
    if (!nodes.has(n.id)) nodes.set(n.id, n);
  };
  const addFact = (f: Fact) => {
    add(factNode(f));
    add(personNode(f.speaker));
    edges.push({ source: f.id, target: f.speaker.id, type: "STATED_BY" });
    add(episodeNode(f));
    edges.push({ source: f.id, target: f.episode_id, type: "DERIVED_FROM" });
    const c = containerNode(f);
    add(c);
    edges.push({ source: c.id, target: f.episode_id, type: "HAS_EPISODE" });
    edges.push({ source: f.episode_id, target: f.speaker.id, type: f.source?.kind === "email" ? "SENT_BY" : "SPOKEN_BY" });
    if (opts.entities !== false) {
      for (const e of FACT_ENTITIES[f.id] ?? []) {
        if (ENTITIES[e]) {
          add(ENTITIES[e]);
          edges.push({ source: f.id, target: e, type: "ABOUT" });
        }
      }
    }
  };
  for (const f of facts) {
    const list = opts.chain === false ? [f] : chainFor(f);
    list.forEach((x, i) => {
      addFact(x);
      if (i > 0) edges.push({ source: list[i - 1].id, target: x.id, type: "SUPERSEDES" });
    });
  }
  const seen = new Set<string>();
  const uniq = edges.filter((e) => {
    const k = `${e.source}|${e.type}|${e.target}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  return { nodes: [...nodes.values()], edges: uniq };
}

const WHY_CYPHER = `MATCH (f {id: $id})-[:DERIVED_FROM]->(ep:Episode)
OPTIONAL MATCH (ep)-[:SPOKEN_BY|SENT_BY]->(p:Person)
OPTIONAL MATCH (c)-[:HAS_EPISODE]->(ep) WHERE c:Meeting OR c:EmailThread
OPTIONAL MATCH chain = (f)-[:SUPERSEDES*0..5]->(older)
RETURN f, p, c, ep,
       [x IN nodes(chain) | x] AS history,
       ep.source_kind AS kind, ep.t_start AS t_start, ep.t_occurred AS sent_at`;

export function mockWhy(nodeId: string): WhyResponse | null {
  const f = store.facts.find((x) => x.id === nodeId);
  if (f) {
    const sg = mockSubgraphForFacts([f]);
    const ep = episodeNode(f);
    return {
      node: factNode(f),
      speaker: f.speaker,
      meeting: f.meeting,
      episode: {
        id: f.episode_id,
        text: String(ep.props.text ?? ""),
        t_start: (ep.props.t_start as number | undefined) ?? null,
        t_end: (ep.props.t_end as number | undefined) ?? null,
      },
      history: chainFor(f),
      cypher: WHY_CYPHER,
      subgraph: sg,
      source: f.source,
    };
  }
  const e = ENTITIES[nodeId];
  if (e) {
    const facts = store.facts.filter((x) => (FACT_ENTITIES[x.id] ?? []).includes(nodeId));
    const sg = mockSubgraphForFacts(facts, { chain: false });
    return {
      node: e,
      speaker: null,
      meeting: null,
      episode: null,
      history: facts,
      cypher: `MATCH (f)-[:ABOUT]->(e:Entity {id: $id})
MATCH (f)-[:DERIVED_FROM]->(ep:Episode)-[:SPOKEN_BY|SENT_BY]->(p:Person)
RETURN e, f, ep, p ORDER BY f.valid_from DESC`,
      subgraph: sg,
    };
  }
  const p = PEOPLE[nodeId];
  if (p) {
    const facts = store.facts.filter((x) => x.speaker.id === nodeId);
    return {
      node: personNode(P(nodeId)),
      speaker: P(nodeId),
      meeting: null,
      episode: null,
      history: facts,
      cypher: `MATCH (f)-[:STATED_BY]->(p:Person {id: $id}) RETURN f ORDER BY f.valid_from DESC`,
      subgraph: mockSubgraphForFacts(facts, { chain: false, entities: false }),
    };
  }
  return null;
}

const BELIEF_CYPHER = `MATCH (f)
WHERE (f:Fact OR f:Decision OR f:Commitment)
  AND f.valid_from <= $t
  AND (f.valid_to IS NULL OR f.valid_to > $t)
  AND f.created_at <= $t
OPTIONAL MATCH (f)-[:ABOUT]->(e:Entity) WHERE $entity IS NULL OR e.id = $entity
RETURN f ORDER BY f.valid_from DESC`;

export function mockBelief(t: number, entity?: string): Belief {
  const facts = store.facts
    .filter((f) => f.valid_from <= t && (f.valid_to == null || f.valid_to > t))
    .filter((f) => !entity || (FACT_ENTITIES[f.id] ?? []).includes(entity))
    .sort((a, b) => b.valid_from - a.valid_from)
    .map((f) => ({ ...f, status: "active" as const, valid_to: null }));
  return { t, facts, cypher: BELIEF_CYPHER.replace("$t", `${t} /* $t */`).replace("$entity IS NULL OR e.id = $entity", entity ? `e.id = '${entity}'` : "true") };
}

export function mockTimeline(): Timeline {
  const events: TimelineEvent[] = [];
  for (const m of MEETING_DEFS) events.push({ t: m.started_at, type: "meeting", id: m.id, text: m.title });
  for (const th of THREAD_DEFS) events.push({ t: th.started_at, type: "email", id: th.id, text: th.subject });
  for (const f of store.facts) {
    const type = f.kind === "fact" ? "fact.created" : f.kind;
    events.push({ t: f.valid_from, type, id: f.id, text: `${f.subject} ${f.predicate.replace(/_/g, " ")} ${f.object}` });
    if (f.status === "superseded" && f.valid_to != null) {
      const by = store.facts.find((x) => x.supersedes === f.id);
      events.push({ t: f.valid_to, type: "fact.superseded", id: f.id, text: `${f.subject} ${f.predicate.replace(/_/g, " ")} ${f.object} → ${by?.object ?? "?"}` });
    }
  }
  events.push(...store.extraEvents);
  events.sort((a, b) => a.t - b.t);
  return { events, snapshots: [...store.snapshots].sort((a, b) => a.taken_at - b.taken_at) };
}

export function mockSnapshot(label: string): Snapshot {
  const taken_at = Date.now();
  const snap = { name: `team_orbit__snap_${taken_at}`, taken_at, label };
  store.snapshots.push(snap);
  busPublish("orbit", "snapshot.taken", { name: snap.name, label });
  return snap;
}

export function mockWhoKnows(entity: string): WhoKnows[] {
  const id = Object.keys(ENTITIES).find((k) => k === entity || String(ENTITIES[k].props.name).toLowerCase() === entity.toLowerCase());
  const counts = new Map<string, { mentions: number; last_at: number }>();
  for (const f of store.facts) {
    if (id && !(FACT_ENTITIES[f.id] ?? []).includes(id)) continue;
    const c = counts.get(f.speaker.id) ?? { mentions: 0, last_at: 0 };
    c.mentions += 1;
    c.last_at = Math.max(c.last_at, f.valid_from);
    counts.set(f.speaker.id, c);
  }
  return [...counts.entries()].map(([pid, c]) => ({ person: P(pid), ...c })).sort((a, b) => b.mentions - a.mentions);
}

export function mockOpenCommitments(person?: string): Fact[] {
  return store.facts.filter((f) => f.kind === "commitment" && f.status === "active" && (!person || f.speaker.id === person));
}

export function mockContradictions(): Contradiction[] {
  const groups = new Map<string, Fact[]>();
  for (const f of store.facts) {
    if (f.status !== "active" || f.predicate === "scope_includes") continue;
    const k = `${f.subject}|${f.predicate}`.toLowerCase();
    groups.set(k, [...(groups.get(k) ?? []), f]);
  }
  const out: Contradiction[] = [];
  for (const [key, fs] of groups) {
    if (fs.length >= 2 && new Set(fs.map((f) => f.object)).size > 1) out.push({ key, facts: [fs[0], fs[1]] });
  }
  return out;
}

export function mockClusters(): Cluster[] {
  return [
    { component: 0, entities: ["ent_upi_flow", "ent_payments", "ent_psp_sandbox", "ent_razorpay", "ent_qa_signoff"].map((k) => ENTITIES[k]) },
    { component: 1, entities: ["ent_meridian", "ent_northwind", "ent_sso", "ent_october_release"].map((k) => ENTITIES[k]) },
    { component: 2, entities: ["ent_checkout", "ent_onboarding", "ent_offline_mode"].map((k) => ENTITIES[k]) },
  ];
}

// ---------- chat ----------
function sourceFor(f: Fact): ChatSource {
  if (f.source?.kind === "email") {
    return {
      fact_id: f.id,
      speaker: f.speaker.name,
      meeting: f.source.container.subject ?? "",
      t_start: null,
      kind: "email",
      thread: f.source.container.subject,
      sent_at: f.source.sent_at ?? f.valid_from,
      message_id: f.source.message_id ?? f.episode_id,
      container_id: f.source.container.id,
    };
  }
  return {
    fact_id: f.id,
    speaker: f.speaker.name,
    meeting: f.meeting?.title ?? "",
    t_start: f.source?.t_start ?? 0,
    kind: "utterance",
    container_id: f.meeting?.id,
  };
}

const F = (id: string) => store.facts.find((f) => f.id === id)!;

export function mockChat(message: string, session_id?: string): ChatResponse {
  const q = message.toLowerCase();
  const sid = session_id ?? nextId("sess");
  const started = performance.now();
  let res: Omit<ChatResponse, "session_id" | "model" | "latency_ms">;

  if (/(why|how come|reason).*(bottom sheet|modal|checkout)|(bottom sheet|modal).*(why|reason)/.test(q)) {
    const facts = [F("fact_010")];
    res = {
      answer:
        "The checkout uses the native bottom sheet because of accessibility and platform consistency. In the Design review (16 Sep) Sana reported that two of five users could not dismiss the custom modal with a screen reader, Rahul noted the native sheet is platform-consistent on both OSes, and Aditya recorded the switch as superseding the kickoff decision for a custom modal (7 Sep, Sana). Sana restated the rationale in the Retro on 30 Sep.",
      router: { intent: "why_decision", entities: ["Checkout", "bottom sheet"], route: "template", template: "32_why_path" },
      cypher: [WHY_CYPHER.replace("$id", "'fact_010'")],
      subgraph: mockSubgraphForFacts(facts),
      sources: [sourceFor(F("fact_010")), sourceFor(F("fact_004")), { ...sourceFor(F("fact_021")), fact_id: "ep_orbit_006_04", speaker: "Sana", meeting: "Retro", t_start: 34000 }],
    };
  } else if (/upi|friday|when.*due|due date|deadline/.test(q)) {
    const facts = [F("fact_009")];
    res = {
      answer:
        "The UPI flow is due Friday the 26th (2026-09-26). Priya moved it in Orbit standup 1 on 14 Sep because the PSP sandbox credentials only landed the day before; the original commitment from the kickoff was the 24th. On 16 Sep she confirmed the date by email in 'UPI flow timeline', and in standup 2 (21 Sep) the flow was in code review and on track.",
      router: { intent: "commitment_status", entities: ["UPI flow"], route: "template", template: "51_open_commitments" },
      cypher: [
        `MATCH (c:Commitment {status: 'active'})-[:ABOUT]->(e:Entity {name: $entity})
MATCH (c)-[:STATED_BY]->(p:Person)
OPTIONAL MATCH (c)-[:SUPERSEDES*1..5]->(old)
RETURN c, p, collect(old) AS history ORDER BY c.valid_from DESC`,
      ],
      subgraph: mockSubgraphForFacts(facts),
      sources: [sourceFor(F("fact_009")), sourceFor(F("fact_002")), sourceFor(F("fact_018")), sourceFor(F("fact_012"))],
    };
  } else if (/qa|sign-?off/.test(q)) {
    const facts = [F("fact_017")];
    res = {
      answer:
        "QA sign-off for payments is due on the 30th (2026-09-30). Rahul committed to the 28th in the Design review on 16 Sep, then moved it to the 30th by email on 22 Sep ('Re: QA sign-off for payments') after adding webhook retry cases; Aditya accepted in the same thread. The supersession crosses sources: the original is a meeting utterance, the replacement is an email.",
      router: { intent: "commitment_status", entities: ["QA sign-off for payments"], route: "graph" },
      cypher: [
        `MATCH (new:Commitment {status: 'active'})-[:SUPERSEDES]->(old:Commitment)
MATCH (new)-[:DERIVED_FROM]->(e1:Episode), (old)-[:DERIVED_FROM]->(e2:Episode)
WHERE e1.source_kind <> e2.source_kind
RETURN new, old, e1.source_kind, e2.source_kind`,
      ],
      subgraph: mockSubgraphForFacts(facts),
      sources: [sourceFor(F("fact_017")), sourceFor(F("fact_011"))],
    };
  } else if (/who knows|who.*(know|owns|expert)/.test(q)) {
    const entity = /meridian/.test(q) ? "ent_meridian" : /upi|payment/.test(q) ? "ent_upi_flow" : /sso/.test(q) ? "ent_sso" : "ent_psp_sandbox";
    const wk = mockWhoKnows(entity);
    const facts = store.facts.filter((f) => (FACT_ENTITIES[f.id] ?? []).includes(entity)).slice(0, 4);
    res = {
      answer: `${wk.map((w) => `${w.person.name} (${w.mentions} mention${w.mentions === 1 ? "" : "s"})`).join(", ")} have spoken or written about ${ENTITIES[entity].props.name}. ${wk[0]?.person.name ?? "Nobody"} is the most frequent source.`,
      router: { intent: "who_knows", entities: [String(ENTITIES[entity].props.name)], route: "template", template: "50_who_knows" },
      cypher: [
        `MATCH (e:Entity {name: $entity})<-[:MENTIONS]-(ep:Episode)-[:SPOKEN_BY|SENT_BY|SENT_TO]->(p:Person)
RETURN p, count(ep) AS mentions, max(ep.t_occurred) AS last_at ORDER BY mentions DESC`,
      ],
      subgraph: mockSubgraphForFacts(facts, { chain: false }),
      sources: facts.map(sourceFor),
    };
  } else if (/pilot|customer|northwind|meridian|contradict/.test(q)) {
    const facts = [F("fact_016"), F("fact_006")];
    res = {
      answer:
        "Two active facts disagree. At the kickoff (7 Sep) Aditya said the pilot customer is Northwind; in the Customer call recap (23 Sep) Sana said Meridian is the pilot now and Northwind paused their evaluation. The newer statement is more likely current, but the kickoff fact has not been retracted. Task task_005 is waiting for a human to resolve it.",
      router: { intent: "contradiction", entities: ["Pilot customer"], route: "template", template: "52_contradictions" },
      cypher: [
        `MATCH (a {status: 'active'}), (b {status: 'active'})
WHERE a.subject = b.subject AND a.predicate = b.predicate AND a.object <> b.object AND a.id < b.id
RETURN a, b`,
      ],
      subgraph: mockSubgraphForFacts(facts, { chain: false }),
      sources: facts.map(sourceFor),
    };
  } else if (/sso|okta/.test(q)) {
    const facts = [F("fact_014"), F("fact_015")];
    res = {
      answer:
        "SSO is in scope for the October release as the second milestone after payments. Meridian requires it for the pilot (Sana, Customer call recap, 23 Sep); they use Okta, and Priya scoped it at about a week using the identity provider's SDK, starting after the UPI flow lands.",
      router: { intent: "scope_question", entities: ["SSO", "Meridian"], route: "vector" },
      cypher: [
        `CALL db.idx.vector.queryNodes('Fact', 'embedding', 20, vecf32($q)) YIELD node AS f, score
WHERE f.status = 'active'
OPTIONAL MATCH (f)-[:ABOUT]->(e:Entity)<-[:ABOUT]-(g {status: 'active'})
WITH f, score, collect(DISTINCT g)[0..5] AS neighbours
RETURN f, neighbours, hive.score(f.valid_from, f.confidence, score, $now) AS rank
ORDER BY rank DESC LIMIT 8`,
      ],
      subgraph: mockSubgraphForFacts(facts, { chain: false }),
      sources: facts.map(sourceFor),
    };
  } else {
    const facts = store.facts.filter((f) => f.status === "active").slice(0, 3);
    res = {
      answer:
        "I could not match that to a template, so I ran a hybrid recall over active facts. The most relevant items are listed in the sources; ask about a decision ('why did we choose the bottom sheet?'), a commitment ('when is the UPI flow due?'), or a person ('who knows about Meridian?') for a traced answer.",
      router: { intent: "freeform", entities: [], route: "vector" },
      cypher: [
        `CALL db.idx.vector.queryNodes('Fact', 'embedding', 20, vecf32($q)) YIELD node AS f, score
WHERE f.status = 'active'
RETURN f, hive.score(f.valid_from, f.confidence, score, $now) AS rank ORDER BY rank DESC LIMIT 8`,
      ],
      subgraph: mockSubgraphForFacts(facts, { chain: false }),
      sources: facts.map(sourceFor),
    };
  }

  const full: ChatResponse = {
    ...res,
    session_id: sid,
    model: "gemma-4-26b-a4b-it",
    latency_ms: Math.round(380 + Math.random() * 420 + (performance.now() - started)),
  };
  const turns = store.sessions[sid] ?? [];
  const now = Date.now();
  turns.push({ role: "user", text: message, t: now }, { role: "assistant", text: full.answer, t: now + full.latency_ms, response: full });
  store.sessions[sid] = turns;
  return full;
}

export const mockSession = (sid: string): ChatTurn[] => store.sessions[sid] ?? [];

// ---------- board ----------
export const mockAgents = (): Agent[] => store.agents;
export const mockTasks = (status?: string): Task[] =>
  store.tasks.filter((t) => !status || t.status === status).sort((a, b) => b.updated_at - a.updated_at);
export function mockTrace(taskId: string): TaskTrace | null {
  const task = store.tasks.find((t) => t.id === taskId);
  if (!task) return null;
  return { task, events: [...(store.traces[taskId] ?? [])].sort((a, b) => a.t - b.t) };
}

export function mockSubmitTask(body: { kind: string; payload: Record<string, unknown>; requires: string[]; about_ids?: string[] }): Task {
  const now = Date.now();
  const task: Task = {
    id: nextId("task"),
    kind: body.kind,
    status: "submitted",
    version: 1,
    owner_agent: null,
    priority: 5,
    created_at: now,
    updated_at: now,
    payload: body.payload,
    about: body.about_ids ?? [],
  };
  store.tasks.push(task);
  store.traces[task.id] = [{ t: now, type: "submitted", agent: "ui", summary: `requires ${body.requires.join(", ")}` }];
  busPublish("orbit", "task.submitted", { task_id: task.id, kind: task.kind });
  return task;
}

function setAgentState(id: string, state: Agent["state"]) {
  const a = store.agents.find((x) => x.id === id);
  if (a) {
    a.state = state;
    a.last_seen = Date.now();
  }
}

function later(ms: number, fn: () => void) {
  if (typeof window === "undefined") return fn();
  window.setTimeout(fn, ms);
}

export function mockSupersede(body: { fact_id?: string; new_object?: string; speaker_id?: string }): SupersedeResponse {
  const old =
    (body.fact_id && store.facts.find((f) => f.id === body.fact_id)) ||
    store.facts.find((f) => f.subject === "UPI flow" && f.predicate === "due" && f.status === "active") ||
    store.facts.find((f) => f.kind === "commitment" && f.status === "active")!;
  const now = Date.now();
  const newObject = body.new_object ?? "2026-10-02";
  const speaker = P(body.speaker_id && PEOPLE[body.speaker_id] ? body.speaker_id : old.speaker.id);
  const nf: Fact = {
    ...old,
    id: nextId("fact"),
    object: newObject,
    text: `Move it to Friday. ${old.subject} ${old.predicate.replace(/_/g, " ")} ${newObject}.`,
    confidence: 0.9,
    valid_from: now,
    valid_to: null,
    status: "active",
    speaker,
    due_at: /^\d{4}-\d{2}-\d{2}$/.test(newObject) ? Date.parse(`${newObject}T12:30:00Z`) : old.due_at,
    supersedes: old.id,
  };
  old.valid_to = now;
  old.status = "superseded";
  store.facts.push(nf);
  FACT_ENTITIES[nf.id] = FACT_ENTITIES[old.id] ?? [];
  store.extraEvents.push({ t: now, type: "fact.superseded", id: old.id, text: `${old.subject} ${old.predicate} ${old.object} → ${newObject}` });
  busPublish("orbit", "fact.superseded", { old_fact_id: old.id, new_fact_id: nf.id, subject: old.subject, new_object: newObject });

  // Scheduler wakes, submits a follow-up, claims, hands off; FollowUp completes.
  const task: Task = {
    id: nextId("task"),
    kind: "followup",
    status: "submitted",
    version: 1,
    owner_agent: null,
    priority: 3,
    created_at: now + 300,
    updated_at: now + 300,
    payload: { reason: "commitment date moved", commitment: `${old.subject} due ${newObject}`, previous: old.object },
    about: [nf.id, old.id],
  };
  later(300, () => {
    store.tasks.push(task);
    store.traces[task.id] = [{ t: Date.now(), type: "submitted", agent: "agent_scheduler", summary: `Woke on fact.superseded (${old.subject} ${old.object} → ${newObject})` }];
    busPublish("orbit", "task.submitted", { task_id: task.id, kind: task.kind, about: task.about });
  });
  later(1_000, () => {
    task.status = "working";
    task.version = 2;
    task.owner_agent = "agent_scheduler";
    task.updated_at = Date.now();
    setAgentState("agent_scheduler", "working");
    store.traces[task.id].push({ t: Date.now(), type: "claimed", agent: "agent_scheduler", summary: "CAS claim won at version 1" });
    busPublish("orbit", "task.claimed", { task_id: task.id, agent: "agent_scheduler", version: 2 });
  });
  later(1_900, () => {
    task.status = "submitted";
    task.version = 3;
    task.owner_agent = "agent_followup";
    task.updated_at = Date.now();
    setAgentState("agent_scheduler", "idle");
    const ids = [old.id, nf.id, ...(FACT_ENTITIES[nf.id] ?? []), speaker.id];
    store.traces[task.id].push({ t: Date.now(), type: "handed_off", agent: "agent_followup", summary: `${old.subject} moved ${old.object} → ${newObject}. Open a tracking issue and nudge ${speaker.name}.`, subgraph_ids: ids });
    busPublish("orbit", "task.handed_off", { task_id: task.id, from: "agent_scheduler", to: "agent_followup", subgraph_ids: ids });
  });
  later(2_700, () => {
    task.status = "working";
    task.version = 4;
    task.updated_at = Date.now();
    setAgentState("agent_followup", "working");
    store.traces[task.id].push({ t: Date.now(), type: "claimed", agent: "agent_followup", summary: "CAS claim won at version 3" });
    busPublish("orbit", "task.claimed", { task_id: task.id, agent: "agent_followup", version: 4 });
  });
  later(3_400, () => {
    store.traces[task.id].push({ t: Date.now(), type: "skill_used", agent: "agent_followup", summary: "skill_followup_issue v1" });
    busPublish("orbit", "skill.ran", { skill_id: "skill_followup_issue", task_id: task.id });
  });
  later(4_300, () => {
    task.status = "completed";
    task.version = 5;
    task.updated_at = Date.now();
    setAgentState("agent_followup", "idle");
    const art = { kind: "github_issue", uri: `https://github.com/orbit-demo/app/issues/${43 + (seq % 50)}`, title: `Update ${old.subject} milestone to ${newObject}`, simulated: true };
    store.traces[task.id].push({ t: Date.now(), type: "completed", agent: "agent_followup", summary: "Issue opened (simulated) and nudge drafted.", artifact: art });
    busPublish("orbit", "task.completed", { task_id: task.id, agent: "agent_followup", artifact: art });
    const sk = store.skills.find((s) => s.id === "skill_followup_issue");
    if (sk) {
      sk.success_rate = (sk.success_rate * sk.runs + 1) / (sk.runs + 1);
      sk.runs += 1;
    }
  });

  return { old_fact_id: old.id, new_fact_id: nf.id };
}

export function mockDoubleClaim(body: { task_id?: string }): DoubleClaimResponse {
  let task = body.task_id ? store.tasks.find((t) => t.id === body.task_id) : undefined;
  if (!task) task = store.tasks.find((t) => t.status === "submitted");
  if (!task) {
    task = mockSubmitTask({ kind: "followup", payload: { reason: "double-claim demo" }, requires: ["followup"] });
  }
  const winner = task.owner_agent ?? "agent_followup";
  const before = task.version;
  task.status = "working";
  task.version = before + 1;
  task.owner_agent = winner;
  task.updated_at = Date.now();
  setAgentState(winner, "working");
  store.traces[task.id] = [
    ...(store.traces[task.id] ?? []),
    { t: Date.now(), type: "claimed", agent: winner, summary: `25 concurrent claims at version ${before}: 1 won (version ${before} → ${before + 1}), 24 lost the compare-and-set and re-read.` },
  ];
  busPublish("orbit", "task.claimed", { task_id: task.id, agent: winner, version: task.version, contenders: 25 });
  return { winners: 1, losers: 24, task_id: task.id, winner_agent: winner };
}

// ---------- skills ----------
export const mockSkills = (): Skill[] => [...store.skills].sort((a, b) => b.pagerank - a.pagerank);

export function mockSkillOutcome(id: string, body: { ok: boolean; agent_id?: string }): Skill | null {
  const s = store.skills.find((x) => x.id === id);
  if (!s) return null;
  s.success_rate = (s.success_rate * s.runs + (body.ok ? 1 : 0)) / (s.runs + 1);
  s.runs += 1;
  busPublish("orbit", "skill.ran", { skill_id: id, ok: body.ok, agent: body.agent_id ?? "ui" });
  return s;
}

export function mockRunSkill(goal: string): { task_id: string } {
  const task = mockSubmitTask({ kind: "standup", payload: { goal }, requires: ["standup"] });
  later(900, () => {
    task.status = "working";
    task.version = 2;
    task.owner_agent = "agent_standup";
    task.updated_at = Date.now();
    setAgentState("agent_standup", "working");
    store.traces[task.id].push({ t: Date.now(), type: "claimed", agent: "agent_standup" });
    busPublish("orbit", "task.claimed", { task_id: task.id, agent: "agent_standup", version: 2 });
  });
  later(1_800, () => {
    store.traces[task.id].push({ t: Date.now(), type: "skill_used", agent: "agent_standup", summary: "skill_standup v2" });
    busPublish("orbit", "skill.ran", { skill_id: "skill_standup_v2", task_id: task.id });
  });
  later(3_600, () => {
    task.status = "completed";
    task.version = 3;
    task.updated_at = Date.now();
    setAgentState("agent_standup", "idle");
    const art = {
      kind: "standup_summary",
      text: "Done: onboarding screens (Rahul), UPI flow in review (Priya). Due: UPI flow Fri 26, QA sign-off 30th. Blocked: none. Pending human input: pilot customer contradiction.",
    };
    store.traces[task.id].push({ t: Date.now(), type: "completed", agent: "agent_standup", summary: "Standup summary written. Accept or reject on the Skills page.", artifact: art });
    busPublish("orbit", "task.completed", { task_id: task.id, agent: "agent_standup", artifact: art });
  });
  return { task_id: task.id };
}

// ---------- bench / health ----------
export const mockBench = (): BenchResult[] => BENCH;
export const mockHealth = (): Health => ({
  ok: true,
  falkordb: { version: "6.0.1", graphs: 4 },
  llm: { backend: "ollama", model: "gemma4:e4b" },
  embeddings: { model: "embeddinggemma-300m", dim: 768 },
});

export const mockPeople = (): PersonRef[] => Object.values(PEOPLE).map((p) => P(p.id));
