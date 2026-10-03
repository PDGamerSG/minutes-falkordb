"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Play, ThumbsDown, ThumbsUp } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import type { Skill, TaskTrace } from "@/lib/types";
import { fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorNote, PageHeader } from "@/components/Page";
import { StateBadge } from "@/components/StateBadge";
import { useOverlays } from "@/components/overlay-context";
import { ArtifactView } from "@/components/ArtifactView";

/** Goal sent to /skills/run: the learned standup skill's own goal when there is one (vector match is then exact). */
function standupGoal(team: string, skills: Skill[] | undefined): string {
  const learned = skills?.find((s) => s.status !== "deprecated" && /standup/i.test(s.goal));
  return learned?.goal ?? `Run the ${team} standup routine`;
}

/** Follows the run task on the board (poll the trace) and shows its artifact here. */
function RunResult({ tenant, taskId }: { tenant: string; taskId: string }) {
  const [trace, setTrace] = useState<TaskTrace | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let stop = false;
    let timer = 0;
    const started = Date.now();
    const tick = async () => {
      try {
        const t = await api.board.trace(tenant, taskId);
        if (stop) return;
        setTrace(t);
        if (t.task.status === "completed" || t.task.status === "failed") return;
      } catch (e) {
        if (!stop) setErr(e instanceof Error ? e.message : String(e));
      }
      if (!stop && Date.now() - started < 180_000) timer = window.setTimeout(tick, 1500);
    };
    timer = window.setTimeout(tick, 500);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [tenant, taskId]);

  const status = trace?.task.status ?? "submitted";
  const artifacts = (trace?.events ?? []).filter((e) => e.artifact).map((e) => e.artifact!);
  const failure = (trace?.events ?? []).find((e) => e.type === "failed");
  return (
    <div className="space-y-2 rounded-lg border bg-card p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium">Last run</span>
        <StateBadge state={status} size="xs" pulse={status === "submitted" || status === "working"} />
        <span className="font-mono text-muted-foreground">{taskId}</span>
        {trace?.task.owner_agent && <span className="text-muted-foreground">by {trace.task.owner_agent}</span>}
      </div>
      {err && !trace && <ErrorNote error={err} />}
      {failure?.summary && <ErrorNote error={failure.summary} />}
      {artifacts.map((a, i) => (
        <ArtifactView key={i} artifact={a} className="max-h-[28rem] overflow-auto" />
      ))}
      {status !== "completed" && status !== "failed" && artifacts.length === 0 && <p className="text-xs text-muted-foreground">StandupAgent is running the skill’s steps…</p>}
    </div>
  );
}

function RateBar({ rate }: { rate: number }) {
  const tone = rate >= 0.75 ? "var(--fact-active)" : rate >= 0.5 ? "var(--fact-superseded)" : "var(--state-failed)";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full" style={{ width: `${Math.round(rate * 100)}%`, background: tone }} />
      </div>
      <span className="font-mono text-xs tabular">{fmtPct(rate)}</span>
    </div>
  );
}

function Steps({ tenant, skill }: { tenant: string; skill: Skill }) {
  const { openWhy } = useOverlays();
  return (
    <div className="space-y-3 p-3">
      <div className="overflow-hidden rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">#</TableHead>
              <TableHead>Tool</TableHead>
              <TableHead>Args template</TableHead>
              <TableHead>Guard</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...skill.steps]
              .sort((a, b) => a.order - b.order)
              .map((s) => (
                <TableRow key={s.order}>
                  <TableCell className="font-mono text-xs tabular">{s.order}</TableCell>
                  <TableCell className="font-mono text-xs font-medium">{s.tool}</TableCell>
                  <TableCell className="max-w-md font-mono text-[11px] break-all text-muted-foreground">{s.args_template}</TableCell>
                  <TableCell className="font-mono text-[11px] text-muted-foreground">{s.guard ?? "—"}</TableCell>
                </TableRow>
              ))}
            {skill.steps.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-xs text-muted-foreground">
                  No steps recorded.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted-foreground">learned from</span>
        {skill.learned_from.length === 0 && <span className="text-muted-foreground">—</span>}
        {skill.learned_from.map((id) => (
          <button key={id} type="button" onClick={() => openWhy(tenant, id)} className="rounded border bg-card px-1.5 py-0.5 font-mono text-[11px] hover:bg-muted">
            {id}
          </button>
        ))}
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">{skill.id}</span>
      </div>
    </div>
  );
}

export function SkillsPage({ team }: { team: string }) {
  const router = useRouter();
  const { data, error, loading, setData } = useResource(() => api.skills.list(team), [team]);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runTask, setRunTask] = useState<string | null>(null);

  const outcome = async (skill: Skill, ok: boolean) => {
    setBusy(skill.id);
    try {
      const updated = await api.skills.outcome(team, skill.id, { ok, agent_id: "ui" });
      setData((prev) => prev?.map((s) => (s.id === skill.id ? { ...s, ...updated } : s)));
      toast.success(`${ok ? "Accepted" : "Rejected"} ${skill.id}`, {
        description: `runs ${updated.runs} · success ${fmtPct(updated.success_rate)}`,
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Outcome failed");
    } finally {
      setBusy(null);
    }
  };

  const run = async () => {
    setRunning(true);
    try {
      const r = await api.skills.run(team, standupGoal(team, data));
      setRunTask(r.task_id);
      toast.success("Standup skill running", {
        description: `task ${r.task_id} submitted for StandupAgent`,
        action: { label: "Open board", onClick: () => router.push(`/t/${encodeURIComponent(team)}/board`) },
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Run failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Skills"
        description="Procedural memory. Routines the agents learned from repeated work, ranked by PageRank over USED edges. Accept or reject an outcome to update the success rate."
        actions={
          <Button size="sm" onClick={run} disabled={running}>
            <Play /> {running ? "Submitting…" : "Run standup skill"}
          </Button>
        }
      />
      {error && !data && <ErrorNote error={error} />}
      {runTask && <RunResult key={runTask} tenant={team} taskId={runTask} />}
      {loading && !data && <Skeleton className="h-64" />}
      {data && data.length === 0 && <EmptyState title="No skills learned yet" hint="The StandupAgent distils a routine after two meetings with a weekly cadence." />}
      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Goal</TableHead>
                <TableHead className="text-right">Runs</TableHead>
                <TableHead>Success rate</TableHead>
                <TableHead className="text-right">PageRank</TableHead>
                <TableHead className="text-right">Outcome</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((s) => {
                const isOpen = !!open[s.id];
                return (
                  <Fragment key={s.id}>
                    <TableRow className="cursor-pointer" onClick={() => setOpen((o) => ({ ...o, [s.id]: !o[s.id] }))} data-state={isOpen ? "selected" : undefined}>
                      <TableCell className="text-muted-foreground">{isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className={cn("font-medium", s.status === "deprecated" && "text-muted-foreground line-through")}>{s.goal}</span>
                          <span className="font-mono text-[11px] text-muted-foreground">v{s.version}</span>
                          <StateBadge state={s.status} size="xs" />
                          <span className="font-mono text-[11px] text-muted-foreground tabular">{s.steps.length} steps</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular">{s.runs}</TableCell>
                      <TableCell>
                        <RateBar rate={s.success_rate} />
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
                            <div className="h-full bg-primary" style={{ width: `${Math.min(100, Math.round(s.pagerank * 100))}%` }} />
                          </div>
                          <span className="font-mono text-xs tabular">{s.pagerank.toFixed(3)}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="inline-flex gap-1">
                          <Button size="xs" variant="outline" disabled={busy === s.id || s.status === "deprecated"} onClick={() => outcome(s, true)} aria-label="Accept outcome">
                            <ThumbsUp /> Accept
                          </Button>
                          <Button size="xs" variant="outline" disabled={busy === s.id || s.status === "deprecated"} onClick={() => outcome(s, false)} aria-label="Reject outcome">
                            <ThumbsDown /> Reject
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={6} className="bg-muted/30 p-0">
                          <Steps tenant={team} skill={s} />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Outcomes post to <span className="font-mono">/skills/{"{id}"}/outcome</span>; the run button posts the standup goal to <span className="font-mono">/skills/run</span> and the StandupAgent picks it up on the{" "}
        <Link href={`/t/${encodeURIComponent(team)}/board`} className="underline underline-offset-2">
          board
        </Link>
        .
      </p>
    </div>
  );
}
