"use client";

import { useMemo, useState } from "react";
import { Play } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import type { BenchResult, BenchTarget, Engine } from "@/lib/types";
import { fmtDateTime, fmtNum, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorNote, PageHeader, Section, Stat } from "@/components/Page";

// Fixed categorical order: 6.0.1 is always series 1 (blue), 4.22.0 series 2 (orange).
const SERIES: Array<{ engine: Engine; key: "e601" | "e4220"; color: string; label: string }> = [
  { engine: "6.0.1", key: "e601", color: "var(--chart-1)", label: "FalkorDB 6.0.1" },
  { engine: "4.22.0", key: "e4220", color: "var(--chart-3)", label: "FalkorDB 4.22.0" },
];
const TARGETS: BenchTarget[] = ["local", "railway"];
const PCTS = ["p50", "p95", "p99"] as const;

type Row = { pct: string; e601?: number; e4220?: number };

function rows(results: BenchResult[], target: BenchTarget, op: "read" | "write"): Row[] {
  return PCTS.map((p) => {
    const r: Row = { pct: p };
    for (const s of SERIES) {
      const hit = results.find((x) => x.target === target && x.engine === s.engine);
      if (hit) r[s.key] = hit[`${op}_${p}` as keyof BenchResult] as number;
    }
    return r;
  });
}

function LatencyTooltip({ active, payload, label }: { active?: boolean; payload?: ReadonlyArray<{ dataKey?: unknown; value?: unknown; color?: unknown }>; label?: unknown }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-sm">
      <div className="mb-1 font-mono font-medium">{String(label)}</div>
      {payload.map((p, i) => {
        const s = SERIES.find((x) => x.key === p.dataKey);
        return (
          <div key={i} className="flex items-center gap-2">
            <span className="inline-block size-2 rounded-sm" style={{ background: s?.color ?? String(p.color) }} />
            <span className="text-muted-foreground">{s?.label ?? String(p.dataKey)}</span>
            <span className="ml-auto font-mono tabular">{typeof p.value === "number" ? `${p.value.toFixed(1)} ms` : String(p.value)}</span>
          </div>
        );
      })}
    </div>
  );
}

function LatencyChart({ title, subtitle, data }: { title: string; subtitle: string; data: Row[] }) {
  const has = data.some((d) => d.e601 != null || d.e4220 != null);
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-2">
        <div className="text-sm font-medium">{title}</div>
        <div className="text-xs text-muted-foreground">{subtitle}</div>
      </div>
      {!has ? (
        <div className="flex h-52 items-center justify-center text-xs text-muted-foreground">No run for this target.</div>
      ) : (
        <div className="h-52 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 16, right: 8, left: 0, bottom: 0 }} barGap={2} barCategoryGap="28%">
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis dataKey="pct" tickLine={false} axisLine={{ stroke: "var(--border)" }} tick={{ fill: "var(--muted-foreground)", fontSize: 11, fontFamily: "var(--font-mono)" }} />
              <YAxis
                width={44}
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--muted-foreground)", fontSize: 11, fontFamily: "var(--font-mono)" }}
                tickFormatter={(v: number) => `${v}`}
                unit=""
                label={{ value: "ms", position: "insideTopLeft", fill: "var(--muted-foreground)", fontSize: 10, dy: -12 }}
              />
              <Tooltip cursor={{ fill: "var(--muted)", opacity: 0.6 }} content={<LatencyTooltip />} />
              {SERIES.map((s) => (
                <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[4, 4, 0, 0]} maxBarSize={26} isAnimationActive={false}>
                  <LabelList
                    dataKey={s.key}
                    position="top"
                    content={(props) => {
                      const { x, y, width, value, index } = props as { x?: number | string; y?: number | string; width?: number | string; value?: unknown; index?: number };
                      if (index !== 2 || typeof value !== "number") return null; // label p99 only
                      const cx = Number(x) + Number(width) / 2;
                      return (
                        <text x={cx} y={Number(y) - 4} textAnchor="middle" fontSize={10} fontFamily="var(--font-mono)" fill="var(--foreground)">
                          {value.toFixed(value >= 100 ? 0 : 1)}
                        </text>
                      );
                    }}
                  />
                </Bar>
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function RunBenchDialog({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState(200);
  const [tenants, setTenants] = useState(20);
  const [duration, setDuration] = useState(60);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <Play /> Run bench
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Run the harness</DialogTitle>
          <DialogDescription>
            <span className="font-mono">POST /bench/run</span> runs N agents × M tenants, 80/20 read/write, in-process against the configured FalkorDB. Dev only.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid grid-cols-3 gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              const r = await api.bench.run({ agents, tenants, duration_s: duration });
              toast.success("Bench started", { description: `run ${r.run_id} · results appear when the run finishes` });
              setOpen(false);
              window.setTimeout(onDone, (duration + 5) * 1000);
            } catch (err) {
              toast.error(err instanceof Error ? err.message : "Bench failed to start");
            } finally {
              setBusy(false);
            }
          }}
        >
          {[
            ["Agents", agents, setAgents],
            ["Tenants", tenants, setTenants],
            ["Duration (s)", duration, setDuration],
          ].map(([label, val, set]) => (
            <label key={String(label)} className="space-y-1 text-xs">
              <span className="text-muted-foreground">{String(label)}</span>
              <Input type="number" min={1} value={val as number} onChange={(e) => (set as (n: number) => void)(Number(e.target.value))} className="font-mono tabular" />
            </label>
          ))}
          <DialogFooter className="col-span-3">
            <Button type="submit" disabled={busy}>
              {busy ? "Starting…" : "Run"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function BenchPage() {
  const { data, error, loading, refetch } = useResource(() => api.bench.results(), []);

  // Compare engines at the same load; default to the largest agent count present.
  const configs = useMemo(() => {
    const set = new Map<string, { agents: number; tenants: number; duration_s: number }>();
    for (const r of data ?? []) set.set(`${r.agents}x${r.tenants}x${r.duration_s}`, { agents: r.agents, tenants: r.tenants, duration_s: r.duration_s });
    return [...set.entries()].sort((a, b) => b[1].agents - a[1].agents);
  }, [data]);
  const [config, setConfig] = useState<string | null>(null);
  const activeConfig = config ?? configs[0]?.[0] ?? null;
  const cfg = configs.find((c) => c[0] === activeConfig)?.[1];

  const selected = useMemo(() => {
    const all = data ?? [];
    if (!cfg) return all;
    // Latest run per (engine, target) for the chosen config.
    const byKey = new Map<string, BenchResult>();
    for (const r of all) {
      if (r.agents !== cfg.agents || r.tenants !== cfg.tenants || r.duration_s !== cfg.duration_s) continue;
      const k = `${r.engine}|${r.target}`;
      if (!byKey.has(k) || byKey.get(k)!.ts < r.ts) byKey.set(k, r);
    }
    return [...byKey.values()];
  }, [data, cfg]);

  const headline = (op: "read" | "write", target: BenchTarget) => {
    const a = selected.find((r) => r.engine === "6.0.1" && r.target === target);
    const b = selected.find((r) => r.engine === "4.22.0" && r.target === target);
    const k = `${op}_p99` as keyof BenchResult;
    const va = a ? (a[k] as number) : null;
    const vb = b ? (b[k] as number) : null;
    const delta = va != null && vb != null && vb > 0 ? (va - vb) / vb : null;
    return { va, vb, delta };
  };

  const subtitle = cfg ? `${cfg.agents} agents × ${cfg.tenants} tenants · ${cfg.duration_s} s` : "";

  return (
    <div className="space-y-5">
      <PageHeader
        title="Bench"
        description="Latency percentiles from packages/hiveboard/bench/harness.py: N agents over M tenant graphs, 80/20 read/write, plus compare-and-set contention. Reported as measured."
        actions={
          <>
            {configs.length > 1 && (
              <select aria-label="Load configuration" className="h-7 rounded-md border bg-background px-1.5 font-mono text-xs" value={activeConfig ?? ""} onChange={(e) => setConfig(e.target.value)}>
                {configs.map(([k, c]) => (
                  <option key={k} value={k}>
                    {c.agents} agents × {c.tenants} tenants · {c.duration_s}s
                  </option>
                ))}
              </select>
            )}
            <RunBenchDialog onDone={refetch} />
          </>
        }
      />

      {error && !data && <ErrorNote error={error} />}
      {loading && !data && <Skeleton className="h-64" />}
      {data && data.length === 0 && <EmptyState title="No bench results yet" hint="Run the harness, or POST /bench/run." />}

      {data && data.length > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {(["read", "write"] as const).flatMap((op) =>
              TARGETS.map((target) => {
                const h = headline(op, target);
                return (
                  <Stat
                    key={`${op}-${target}`}
                    label={`${op} p99 · ${target}`}
                    value={h.va != null ? `${h.va.toFixed(h.va >= 100 ? 0 : 1)} ms` : "—"}
                    sub={
                      h.vb != null ? (
                        <span className="tabular">
                          4.22.0: {h.vb.toFixed(h.vb >= 100 ? 0 : 1)} ms
                          {h.delta != null && (
                            <span className={cn("ml-1.5 font-medium", h.delta <= 0 ? "text-(--fact-active)" : "text-(--state-failed)")}>
                              {h.delta <= 0 ? "−" : "+"}
                              {fmtPct(Math.abs(h.delta))}
                            </span>
                          )}
                        </span>
                      ) : (
                        "no 4.22.0 run"
                      )
                    }
                  />
                );
              }),
            )}
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            {SERIES.map((s) => (
              <span key={s.key} className="inline-flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
                {s.label}
              </span>
            ))}
            <span className="text-muted-foreground">{subtitle}</span>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            {(["read", "write"] as const).flatMap((op) =>
              TARGETS.map((target) => <LatencyChart key={`${op}-${target}`} title={`${op === "read" ? "Read" : "Write"} latency · ${target}`} subtitle={`p50 / p95 / p99 in ms · ${subtitle}`} data={rows(selected, target, op)} />),
            )}
          </div>

          <Section title="Compare-and-set contention" description="Concurrent claims on contested tasks. Exactly one claim may win per task version; everyone else re-reads and moves on.">
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run</TableHead>
                    <TableHead>Engine</TableHead>
                    <TableHead>Target</TableHead>
                    <TableHead className="text-right">Attempts</TableHead>
                    <TableHead className="text-right">Winners</TableHead>
                    <TableHead className="text-right">Losers</TableHead>
                    <TableHead className="w-48">Share</TableHead>
                    <TableHead className="text-right">Errors</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {selected.map((r) => {
                    const w = r.cas.attempts ? r.cas.winners / r.cas.attempts : 0;
                    return (
                      <TableRow key={r.run_id}>
                        <TableCell className="font-mono text-xs">{r.run_id}</TableCell>
                        <TableCell className="font-mono text-xs">{r.engine}</TableCell>
                        <TableCell className="text-xs">{r.target}</TableCell>
                        <TableCell className="text-right font-mono tabular">{fmtNum(r.cas.attempts)}</TableCell>
                        <TableCell className="text-right font-mono tabular">{fmtNum(r.cas.winners)}</TableCell>
                        <TableCell className="text-right font-mono tabular">{fmtNum(r.cas.losers)}</TableCell>
                        <TableCell>
                          <div className="flex h-2 gap-0.5 overflow-hidden rounded-sm" title={`${fmtPct(w, 1)} of claims won`}>
                            <div className="rounded-l-sm bg-(--fact-active)" style={{ width: `${Math.max(2, w * 100)}%` }} />
                            <div className="flex-1 rounded-r-sm bg-muted" />
                          </div>
                        </TableCell>
                        <TableCell className={cn("text-right font-mono tabular", r.errors > 0 && "text-(--state-failed)")}>{r.errors}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </Section>

          <Section title="All runs" description="Every result returned by GET /bench/results.">
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run</TableHead>
                    <TableHead>When</TableHead>
                    <TableHead>Engine</TableHead>
                    <TableHead>Target</TableHead>
                    <TableHead className="text-right">Agents</TableHead>
                    <TableHead className="text-right">Tenants</TableHead>
                    <TableHead className="text-right">s</TableHead>
                    <TableHead className="text-right">R p50</TableHead>
                    <TableHead className="text-right">R p95</TableHead>
                    <TableHead className="text-right">R p99</TableHead>
                    <TableHead className="text-right">W p50</TableHead>
                    <TableHead className="text-right">W p95</TableHead>
                    <TableHead className="text-right">W p99</TableHead>
                    <TableHead className="text-right">Err</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...data]
                    .sort((a, b) => b.ts - a.ts)
                    .map((r) => (
                      <TableRow key={r.run_id}>
                        <TableCell className="font-mono text-xs">{r.run_id}</TableCell>
                        <TableCell className="text-xs tabular">{fmtDateTime(r.ts)}</TableCell>
                        <TableCell className="font-mono text-xs">{r.engine}</TableCell>
                        <TableCell className="text-xs">{r.target}</TableCell>
                        <TableCell className="text-right font-mono text-xs tabular">{r.agents}</TableCell>
                        <TableCell className="text-right font-mono text-xs tabular">{r.tenants}</TableCell>
                        <TableCell className="text-right font-mono text-xs tabular">{r.duration_s}</TableCell>
                        {[r.read_p50, r.read_p95, r.read_p99, r.write_p50, r.write_p95, r.write_p99].map((v, i) => (
                          <TableCell key={i} className="text-right font-mono text-xs tabular">
                            {v.toFixed(1)}
                          </TableCell>
                        ))}
                        <TableCell className={cn("text-right font-mono text-xs tabular", r.errors > 0 && "text-(--state-failed)")}>{r.errors}</TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
