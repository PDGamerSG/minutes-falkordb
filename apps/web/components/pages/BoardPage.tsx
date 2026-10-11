"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot, CalendarClock, ChevronDown, ChevronRight, Shuffle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useEvents } from "@/lib/useEvents";
import { useResource } from "@/lib/useResource";
import { TASK_STATUSES, type Agent, type Fact, type SSEEvent, type Task, type TaskStatus, type TraceEvent } from "@/lib/types";
import { fmtDateTime, fmtFull, fmtRelative, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, KeyValue, PageHeader } from "@/components/Page";
import { StateBadge, StateDot, toneFor } from "@/components/StateBadge";
import { ArtifactView } from "@/components/ArtifactView";
import { useOverlays } from "@/components/overlay-context";

const TRACE_TONE: Record<string, string> = {
  submitted: "submitted",
  claimed: "working",
  handed_off: "input_required",
  completed: "completed",
  failed: "failed",
  input_required: "input_required",
  skill_used: "active",
};

/** The Friday after `from` (a Friday moves a week), as YYYY-MM-DD in UTC (due dates are UTC midnights). */
function nextFridayIso(from: number = Date.now()): string {
  const d = new Date(from);
  const delta = ((5 - d.getUTCDay() + 7) % 7) || 7;
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

/** The commitment the demo button moves: the open "PayU integration | due" (the API's default target). */
function demoTarget(commitments: Fact[] | undefined): Fact | undefined {
  return commitments?.find((c) => /payu integration/i.test(c.subject) && c.predicate === "due" && c.due_at != null);
}

function OpenCommitments({ tenant, data, error, loading, flashIds }: { tenant: string; data?: Fact[]; error?: Error | null; loading: boolean; flashIds: Set<string> }) {
  const { openWhy } = useOverlays();
  const rows = (data ?? []).filter((c) => c.predicate === "due" || c.due_at != null);
  return (
    <section>
      <h2 className="mb-2 text-sm font-medium">
        Open commitments <span className="font-mono text-xs text-muted-foreground tabular">{data ? `(${rows.length})` : ""}</span>
      </h2>
      {error && !data && <ErrorNote error={error} />}
      {loading && !data && <Skeleton className="h-16" />}
      {data && rows.length === 0 && <EmptyState title="No open commitments" />}
      {rows.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {rows.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => openWhy(tenant, c.id)}
              className={cn("rounded-md border bg-card p-2.5 text-left text-xs transition-colors hover:bg-muted/60", flashIds.has(c.id) && "ring-2 ring-primary/40")}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{c.subject}</span>
                <span className="font-mono tabular">{c.object}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
                <span>{c.owner?.name ?? c.speaker?.name ?? "—"}</span>
                {c.supersedes && (
                  <Badge variant="secondary" className="h-4 px-1.5 font-mono text-[10px]">
                    SUPERSEDES
                  </Badge>
                )}
                <span className="ml-auto font-mono text-[10px]">{c.id}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/** The 25 throwaway agents the double-claim demo registers; shown as one summary card. */
function isDemoClaimer(a: Agent): boolean {
  return a.id.startsWith("demo_claimer") || (a.capabilities.length === 1 && a.capabilities[0] === "demo");
}

function agentName(agents: Agent[] | undefined, id: string | null | undefined) {
  if (!id) return "—";
  return agents?.find((a) => a.id === id)?.name ?? id;
}

function TaskCard({ task, agents, onOpen, flash }: { task: Task; agents?: Agent[]; onOpen: () => void; flash: boolean }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "w-full rounded-md border bg-card p-2.5 text-left text-xs transition-colors hover:bg-muted/60",
        flash && "ring-2 ring-primary/40",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{titleCase(task.kind)}</span>
        <span className="font-mono text-[10px] text-muted-foreground tabular">v{task.version}</span>
      </div>
      <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">{task.id}</div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
        <span className="inline-flex items-center gap-1 text-muted-foreground">
          <Bot className="size-3" /> {agentName(agents, task.owner_agent)}
        </span>
        <span className="text-muted-foreground tabular">p{task.priority}</span>
        <span className="ml-auto text-muted-foreground tabular" title={fmtFull(task.updated_at)}>
          {fmtRelative(task.updated_at)}
        </span>
      </div>
      {task.about.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {task.about.slice(0, 3).map((id) => (
            <span key={id} className="rounded bg-muted px-1 font-mono text-[10px] text-muted-foreground">
              {id}
            </span>
          ))}
          {task.about.length > 3 && <span className="text-[10px] text-muted-foreground">+{task.about.length - 3}</span>}
        </div>
      )}
    </button>
  );
}

function TraceTimeline({ tenant, events, agents }: { tenant: string; events: TraceEvent[]; agents?: Agent[] }) {
  const { openWhy } = useOverlays();
  if (events.length === 0) return <EmptyState title="No trace events" />;
  return (
    <ol className="relative ml-1.5 space-y-3 border-l pl-4">
      {events.map((e, i) => (
        <li key={`${e.t}-${i}`} className="relative">
          <span className="absolute top-1 -left-[21.5px] rounded-full ring-4 ring-background">
            <StateDot state={TRACE_TONE[e.type] ?? "submitted"} className="size-2.5" />
          </span>
          <div className="flex flex-wrap items-baseline gap-x-2 text-xs">
            <span className="font-medium" style={{ color: toneFor(TRACE_TONE[e.type] ?? "submitted") }}>
              {e.type.replace(/_/g, " ")}
            </span>
            <span className="inline-flex items-center gap-1 text-muted-foreground">
              <Bot className="size-3" /> {agentName(agents, e.agent)}
            </span>
            <span className="ml-auto font-mono text-[10px] text-muted-foreground tabular" title={fmtFull(e.t)}>
              {fmtDateTime(e.t)}
            </span>
          </div>
          {e.summary && <p className="mt-0.5 text-xs text-foreground/90">{e.summary}</p>}
          {e.subgraph_ids && e.subgraph_ids.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {e.subgraph_ids.map((id) => (
                <button key={id} type="button" onClick={() => openWhy(tenant, id)} className="rounded border bg-muted/50 px-1 font-mono text-[10px] text-muted-foreground hover:bg-muted hover:text-foreground">
                  {id}
                </button>
              ))}
            </div>
          )}
          {e.artifact && <ArtifactView artifact={e.artifact} className="mt-1.5" />}
        </li>
      ))}
    </ol>
  );
}

function TaskDrawer({ tenant, taskId, agents, onClose, version }: { tenant: string; taskId: string | null; agents?: Agent[]; onClose: () => void; version: number }) {
  const { openWhy } = useOverlays();
  const { data, error, loading } = useResource(
    () => (taskId ? api.board.trace(tenant, taskId) : Promise.reject(new Error("no task"))),
    [tenant, taskId, version],
    { enabled: !!taskId },
  );
  const t = data?.task;
  return (
    <Sheet open={!!taskId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-hidden sm:max-w-lg">
        <SheetHeader className="border-b">
          <SheetTitle className="flex flex-wrap items-center gap-2">
            {t ? titleCase(t.kind) : "Task"}
            {t && <StateBadge state={t.status} />}
          </SheetTitle>
          <SheetDescription className="font-mono text-xs">{taskId}</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4 text-sm">
          {loading && !data && <Skeleton className="h-40" />}
          {error && !data && <ErrorNote error={error} />}
          {t && (
            <>
              <KeyValue
                rows={[
                  ["owner", <span key="o" className="inline-flex items-center gap-1"><Bot className="size-3" /> {agentName(agents, t.owner_agent)} <span className="font-mono text-muted-foreground">{t.owner_agent ?? ""}</span></span>],
                  ["version", <span key="v" className="font-mono tabular">{t.version}</span>],
                  ["priority", <span key="p" className="tabular">{t.priority}</span>],
                  ["created", <span key="c" className="tabular">{fmtFull(t.created_at)}</span>],
                  ["updated", <span key="u" className="tabular">{fmtFull(t.updated_at)}</span>],
                  [
                    "about",
                    <div key="a" className="flex flex-wrap gap-1">
                      {t.about.length === 0 && <span className="text-muted-foreground">—</span>}
                      {t.about.map((id) => (
                        <button key={id} type="button" onClick={() => openWhy(tenant, id)} className="rounded border bg-muted/50 px-1 font-mono text-[11px] hover:bg-muted">
                          {id}
                        </button>
                      ))}
                    </div>,
                  ],
                ]}
              />
              <section>
                <h4 className="mb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Payload</h4>
                <pre className="overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-[11px] leading-relaxed">{JSON.stringify(t.payload, null, 2)}</pre>
              </section>
              <section>
                <h4 className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Trace</h4>
                <TraceTimeline tenant={tenant} events={data.events} agents={agents} />
              </section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function EventLog({ events, status }: { events: SSEEvent[]; status: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border bg-card">
      <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        <span className="font-medium">Event stream</span>
        <StateBadge state={status} size="xs" pulse={status === "connecting" || status === "reconnecting"} />
        <span className="ml-auto font-mono text-[10px] text-muted-foreground tabular">{events.length} recent</span>
      </button>
      {open && (
        <div className="max-h-64 overflow-auto border-t">
          {events.length === 0 && <div className="p-3 text-xs text-muted-foreground">No events yet. Press a demo button, or wait for agents to act.</div>}
          <ul className="divide-y font-mono text-[11px]">
            {events.map((e, i) => (
              <li key={`${e.ts}-${i}`} className="grid grid-cols-[auto_auto_1fr] gap-x-3 px-3 py-1">
                <span className="text-muted-foreground tabular">{new Date(e.ts).toLocaleTimeString("en-GB")}</span>
                <span className="font-medium">{e.event}</span>
                <span className="truncate text-muted-foreground" title={JSON.stringify(e.payload)}>
                  {JSON.stringify(e.payload)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function BoardPage({ team }: { team: string }) {
  const agents = useResource(() => api.board.agents(team), [team], { refreshMs: 30_000 });
  const tasks = useResource(() => api.board.tasks(team), [team], { refreshMs: 20_000 });
  const commitments = useResource(() => api.analytics.openCommitments(team), [team], { refreshMs: 60_000 });
  const [openTask, setOpenTask] = useState<string | null>(null);
  const [traceVersion, setTraceVersion] = useState(0);
  const [flash, setFlash] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState<"supersede" | "claim" | null>(null);
  const refetchTimer = useRef<number | null>(null);

  const scheduleRefetch = useCallback(() => {
    if (refetchTimer.current) return;
    refetchTimer.current = window.setTimeout(() => {
      refetchTimer.current = null;
      tasks.refetch();
      agents.refetch();
      setTraceVersion((v) => v + 1);
    }, 250);
  }, [tasks, agents]);

  const onEvent = useCallback(
    (e: SSEEvent) => {
      if (e.event.startsWith("task.") || e.event.startsWith("skill.")) {
        scheduleRefetch();
        const id = typeof e.payload.task_id === "string" ? e.payload.task_id : null;
        if (id) setFlash((f) => ({ ...f, [id]: Date.now() }));
      } else if (e.event === "fact.superseded") {
        toast.info("fact.superseded", { description: `${String(e.payload.old_fact_id ?? "")} → ${String(e.payload.new_fact_id ?? "")}` });
        commitments.refetch();
        const id = typeof e.payload.new_fact_id === "string" ? e.payload.new_fact_id : null;
        if (id) setFlash((f) => ({ ...f, [id]: Date.now() }));
      } else if (e.event.startsWith("commitment.")) {
        commitments.refetch();
      }
    },
    [scheduleRefetch, commitments],
  );
  const { status, events } = useEvents(team, onEvent);

  useEffect(() => {
    const id = window.setInterval(() => {
      const cutoff = Date.now() - 4000;
      setFlash((f) => {
        const next = Object.fromEntries(Object.entries(f).filter(([, t]) => t > cutoff));
        return Object.keys(next).length === Object.keys(f).length ? f : next;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  const byStatus = useMemo(() => {
    const m: Record<TaskStatus, Task[]> = { submitted: [], working: [], input_required: [], completed: [], failed: [] };
    for (const t of tasks.data ?? []) (m[t.status] ?? m.submitted).push(t);
    return m;
  }, [tasks.data]);

  const supersede = async () => {
    setBusy("supersede");
    try {
      // "Move it to Friday": the Friday after the commitment's current due date (Thu Oct 1 -> Fri Oct 2).
      const target = demoTarget(commitments.data);
      const friday = nextFridayIso(target?.due_at ?? Date.now());
      const r = await api.demo.supersede(team, { fact_id: target?.id, new_object: friday, speaker_id: "spk_priya" });
      toast.success("Moved it to Friday", {
        description: `${r.old_fact_id} superseded by ${r.new_fact_id} (due ${friday}). Scheduler wakes next.`,
      });
      scheduleRefetch();
      commitments.refetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Supersede failed");
    } finally {
      setBusy(null);
    }
  };

  const doubleClaim = async () => {
    setBusy("claim");
    try {
      const r = await api.demo.doubleClaim(team, {});
      toast.success(`${r.winners} winner, ${r.losers} losers`, {
        description: `${r.winner_agent} won the compare-and-set on ${r.task_id}.`,
        action: { label: "Open trace", onClick: () => setOpenTask(r.task_id) },
      });
      setFlash((f) => ({ ...f, [r.task_id]: Date.now() }));
      scheduleRefetch();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Double claim failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Work in motion."
        description="Follow your agents from the first task to the final handoff. Shared context, visible progress, and a clear trail of what happened."
        actions={
          <>
            <StateBadge state={status} label={status === "open" ? "live" : status} pulse={status === "connecting" || status === "reconnecting"} />
            <Button size="sm" variant="outline" onClick={supersede} disabled={busy !== null}>
              <CalendarClock /> {busy === "supersede" ? "Superseding…" : "Simulate: “move it to Friday”"}
            </Button>
            <Button size="sm" variant="outline" onClick={doubleClaim} disabled={busy !== null}>
              <Shuffle /> {busy === "claim" ? "Claiming…" : "Induce double claim"}
            </Button>
          </>
        }
      />

      <section>
        <h2 className="mb-2 text-sm font-medium">Agents</h2>
        {agents.error && !agents.data && <ErrorNote error={agents.error} />}
        {agents.loading && !agents.data && <Skeleton className="h-16" />}
        {agents.data && (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {agents.data.filter((a) => !isDemoClaimer(a)).map((a) => (
              <div key={a.id} className="rounded-md border bg-card p-2.5 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 font-medium">
                    <Bot className="size-3.5 text-muted-foreground" /> {a.name}
                  </span>
                  <StateBadge state={a.state} size="xs" pulse={a.state === "working"} />
                </div>
                <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">{a.model}</div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {a.capabilities.map((c) => (
                    <Badge key={c} variant="secondary" className="h-4 px-1.5 text-[10px]">
                      {c}
                    </Badge>
                  ))}
                  <span className="ml-auto text-[10px] text-muted-foreground tabular" title={fmtFull(a.last_seen)}>
                    seen {fmtRelative(a.last_seen)}
                  </span>
                </div>
              </div>
            ))}
            {agents.data.some(isDemoClaimer) && (
              <div className="flex items-center gap-2 rounded-md border border-dashed bg-card/50 p-2.5 text-xs text-muted-foreground">
                <Shuffle className="size-3.5" />
                <span>
                  <span className="font-medium text-foreground tabular">{agents.data.filter(isDemoClaimer).length}</span> demo claimers (registered by “Induce double claim”)
                </span>
              </div>
            )}
            {agents.data.length === 0 && <EmptyState title="No agents registered" className="sm:col-span-2 lg:col-span-3 xl:col-span-5" />}
          </div>
        )}
      </section>

      <OpenCommitments tenant={team} data={commitments.data} error={commitments.error} loading={commitments.loading} flashIds={new Set(Object.keys(flash))} />

      <section>
        <h2 className="mb-2 text-sm font-medium">Tasks</h2>
        {tasks.error && !tasks.data && <ErrorNote error={tasks.error} />}
        {tasks.loading && !tasks.data && <Skeleton className="h-48" />}
        {tasks.data && (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {TASK_STATUSES.map((s) => (
              <div key={s} className="min-w-0 rounded-lg border bg-muted/30 p-2">
                <div className="mb-2 flex items-center justify-between px-0.5">
                  <StateBadge state={s} />
                  <span className="font-mono text-[11px] text-muted-foreground tabular">{byStatus[s].length}</span>
                </div>
                <div className="space-y-2">
                  {byStatus[s].map((t) => (
                    <TaskCard key={t.id} task={t} agents={agents.data} onOpen={() => setOpenTask(t.id)} flash={!!flash[t.id]} />
                  ))}
                  {byStatus[s].length === 0 && <div className="rounded-md border border-dashed p-3 text-center text-[11px] text-muted-foreground">none</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <EventLog events={events} status={status} />

      <TaskDrawer tenant={team} taskId={openTask} agents={agents.data} onClose={() => setOpenTask(null)} version={traceVersion} />
    </div>
  );
}
