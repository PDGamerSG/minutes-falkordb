"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Camera, Mail, Mic } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import type { Fact, TimelineEvent, TimelineEventType } from "@/lib/types";
import { fmtDateTime, fmtFull, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { CypherBlock } from "@/components/CypherBlock";
import { EmptyState, ErrorNote, PageHeader, Section } from "@/components/Page";
import { StateBadge } from "@/components/StateBadge";
import { NodeColorDot } from "@/components/GraphView";
import { useOverlays } from "@/components/overlay-context";

const EVENT_COLOR: Record<TimelineEventType, string> = {
  meeting: "var(--node-meeting)",
  email: "var(--node-emailthread)",
  "fact.created": "var(--node-fact)",
  decision: "var(--node-decision)",
  commitment: "var(--node-commitment)",
  "fact.superseded": "var(--fact-superseded)",
};

const KIND_LABEL: Record<Fact["kind"], string> = { fact: "Fact", decision: "Decision", commitment: "Commitment" };

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

function FactRow({ tenant, f, marker }: { tenant: string; f: Fact; marker?: "gone" | "new" }) {
  const { openWhy } = useOverlays();
  return (
    <button
      type="button"
      onClick={() => openWhy(tenant, f.id)}
      className={cn(
        "w-full rounded-md border bg-card p-2 text-left text-xs transition-colors hover:bg-muted/60",
        marker === "gone" && "border-(--fact-superseded)/50",
        marker === "new" && "border-(--fact-active)/50",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <NodeColorDot label={KIND_LABEL[f.kind]} />
        <span className="font-medium">
          {f.subject} <span className="text-muted-foreground">{f.predicate.replace(/_/g, " ")}</span> {f.object}
        </span>
        {marker === "gone" && <StateBadge state="superseded" label="superseded since" size="xs" />}
        {marker === "new" && <StateBadge state="active" label="new since T" size="xs" />}
        {!marker && f.status !== "active" && <StateBadge state={f.status} size="xs" />}
        <span className="ml-auto inline-flex items-center gap-1 font-mono text-[10px] text-muted-foreground tabular">
          {f.source?.kind === "email" ? <Mail className="size-3" /> : <Mic className="size-3" />}
          {fmtDateTime(f.valid_from)}
        </span>
      </div>
      <div className="mt-0.5 text-muted-foreground">
        {f.speaker?.name ? `${f.speaker.name} · ` : ""}
        {f.meeting?.title ?? f.source?.container.subject ?? ""}
      </div>
    </button>
  );
}

function SnapshotDialog({ tenant, onDone }: { tenant: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <Camera /> Take snapshot
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Take snapshot</DialogTitle>
          <DialogDescription>
            Runs <span className="font-mono">GRAPH.COPY team_{tenant} team_{tenant}__snap_&lt;ts&gt;</span> and records a Snapshot node in commons.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              const s = await api.snapshots.create(tenant, label.trim() || `manual ${new Date().toISOString().slice(0, 16)}`);
              toast.success("Snapshot taken", { description: `${s.name} · ${s.label}` });
              setOpen(false);
              setLabel("");
              onDone();
            } catch (err) {
              toast.error(err instanceof Error ? err.message : "Snapshot failed");
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="block space-y-1 text-xs">
            <span className="text-muted-foreground">Label</span>
            <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="before demo" />
          </label>
          <DialogFooter>
            <Button type="submit" disabled={busy}>
              {busy ? "Copying graph…" : "Snapshot"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function TimelinePage({ team }: { team: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const { openWhy } = useOverlays();

  // fetchedAt anchors the slider's right edge; Date.now() must not run during render.
  const timeline = useResource(async () => ({ ...(await api.timeline(team)), fetchedAt: Date.now() }), [team]);
  const nowFacts = useResource(() => api.facts.list(team, { status: "active" }), [team]);

  // Slider range: one hour before the first event up to now.
  const range = useMemo(() => {
    if (!timeline.data) return null;
    const ts = timeline.data.events.map((e) => e.t);
    const now = timeline.data.fetchedAt;
    const min = ts.length ? Math.min(...ts) - 3_600_000 : now - 30 * 86_400_000;
    return { min, max: now };
  }, [timeline.data]);

  const [tState, setT] = useState<number | null>(() => {
    const v = Number(sp.get("t"));
    return v && !Number.isNaN(v) ? v : null;
  });
  const t = range ? (tState != null ? Math.min(range.max, Math.max(range.min, tState)) : range.max) : null;

  const tDeb = useDebounced(t, 250);
  const belief = useResource(() => (tDeb != null ? api.belief(team, tDeb) : Promise.reject(new Error("no t"))), [team, tDeb], { enabled: tDeb != null });

  useEffect(() => {
    if (tDeb == null) return;
    const next = new URLSearchParams(sp.toString());
    next.set("t", String(Math.round(tDeb)));
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tDeb]);

  const events = useMemo(() => timeline.data?.events ?? [], [timeline.data]);
  const snapshots = useMemo(() => timeline.data?.snapshots ?? [], [timeline.data]);

  const pct = (x: number) => (range ? ((x - range.min) / Math.max(1, range.max - range.min)) * 100 : 0);

  const recent = useMemo(() => {
    if (t == null) return [] as TimelineEvent[];
    return events.filter((e) => e.t <= t).slice(-8).reverse();
  }, [events, t]);

  const diff = useMemo(() => {
    const atT = belief.data?.facts ?? [];
    const now = nowFacts.data ?? [];
    const nowIds = new Set(now.map((f) => f.id));
    const atIds = new Set(atT.map((f) => f.id));
    return {
      atT: atT.map((f) => ({ f, marker: nowIds.has(f.id) ? undefined : ("gone" as const) })),
      now: now.map((f) => ({ f, marker: atIds.has(f.id) ? undefined : ("new" as const) })),
    };
  }, [belief.data, nowFacts.data]);

  const loading = timeline.loading && !timeline.data;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Timeline"
        description="Scrub through the tenant's history. Facts are bi-temporal: what the team believed at T is a query, not a reconstruction."
        actions={<SnapshotDialog tenant={team} onDone={timeline.refetch} />}
      />

      {timeline.error && !timeline.data && <ErrorNote error={timeline.error} />}
      {loading && <Skeleton className="h-24" />}

      {range && t != null && (
        <div className="rounded-lg border bg-card p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <div className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Belief at</div>
              <div className="font-mono text-base font-semibold tabular">{fmtFull(t)}</div>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="tabular">{fmtRelative(t)}</span>
              <Button size="xs" variant="outline" onClick={() => setT(range.max)}>
                now
              </Button>
            </div>
          </div>

          <div className="mt-4">
            <Slider
              min={range.min}
              max={range.max}
              step={60_000}
              value={[t]}
              onValueChange={(v) => setT(Array.isArray(v) ? v[0] : (v as number))}
              aria-label="Time"
            />
            <div className="relative mt-1.5 h-6">
              {events.map((e, i) => (
                <button
                  key={`${e.id}-${e.type}-${i}`}
                  type="button"
                  title={`${fmtDateTime(e.t)} · ${e.type} · ${e.text}`}
                  onClick={() => setT(e.t + 1)}
                  className="absolute top-0 h-3 w-px -translate-x-1/2 hover:h-4"
                  style={{ left: `${pct(e.t)}%`, background: EVENT_COLOR[e.type] ?? "var(--muted-foreground)" }}
                />
              ))}
              {snapshots.map((s) => (
                <button
                  key={s.name}
                  type="button"
                  title={`snapshot · ${s.label} · ${fmtDateTime(s.taken_at)}`}
                  onClick={() => setT(s.taken_at)}
                  className="absolute top-3 -translate-x-1/2 text-muted-foreground hover:text-foreground"
                  style={{ left: `${pct(s.taken_at)}%` }}
                >
                  <Camera className="size-3" />
                </button>
              ))}
            </div>
            <div className="flex justify-between font-mono text-[10px] text-muted-foreground tabular">
              <span>{fmtDateTime(range.min)}</span>
              <span>{fmtDateTime(range.max)}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
              {(Object.keys(EVENT_COLOR) as TimelineEventType[]).map((k) => (
                <span key={k} className="inline-flex items-center gap-1">
                  <span className="inline-block h-2.5 w-px" style={{ background: EVENT_COLOR[k] }} />
                  {k}
                </span>
              ))}
              <span className="inline-flex items-center gap-1">
                <Camera className="size-2.5" /> snapshot
              </span>
            </div>
          </div>

          {recent.length > 0 && (
            <ol className="mt-4 divide-y rounded-md border text-xs">
              {recent.map((e, i) => (
                <li key={`${e.id}-${i}`} className={cn("flex flex-wrap items-center gap-x-2 gap-y-0.5 px-2.5 py-1.5", i === 0 && "bg-muted/50")}>
                  <span className="inline-block size-2 rounded-full" style={{ background: EVENT_COLOR[e.type] }} />
                  <span className="font-mono text-[10px] text-muted-foreground tabular">{fmtDateTime(e.t)}</span>
                  <span className="font-mono text-[10px] text-muted-foreground">{e.type}</span>
                  <button type="button" className="truncate text-left hover:underline" onClick={() => (e.type.startsWith("fact") || e.type === "decision" || e.type === "commitment" ? openWhy(team, e.id) : setT(e.t + 1))}>
                    {e.text}
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Section
          title={
            <span>
              Believed at T <span className="font-mono text-xs text-muted-foreground tabular">{belief.data ? `(${belief.data.facts.length})` : ""}</span>
            </span>
          }
          description="Active at the selected time. Orange: superseded or retracted since."
        >
          {belief.error && !belief.data && <ErrorNote error={belief.error} />}
          {belief.loading && !belief.data && <Skeleton className="h-40" />}
          {belief.data && belief.data.facts.length === 0 && <EmptyState title="Nothing believed yet" hint="Move the slider to the right." />}
          <div className="space-y-1.5">
            {diff.atT.map(({ f, marker }) => (
              <FactRow key={f.id} tenant={team} f={f} marker={marker} />
            ))}
          </div>
        </Section>
        <Section
          title={
            <span>
              Now <span className="font-mono text-xs text-muted-foreground tabular">{nowFacts.data ? `(${nowFacts.data.length})` : ""}</span>
            </span>
          }
          description="Active facts right now. Green: created after T."
        >
          {nowFacts.error && !nowFacts.data && <ErrorNote error={nowFacts.error} />}
          {nowFacts.loading && !nowFacts.data && <Skeleton className="h-40" />}
          <div className="space-y-1.5">
            {diff.now.map(({ f, marker }) => (
              <FactRow key={f.id} tenant={team} f={f} marker={marker} />
            ))}
          </div>
        </Section>
      </div>

      {belief.data && <CypherBlock cypher={belief.data.cypher} label={`31_belief_at_time.cypher · t = ${belief.data.t}`} />}

      <Section title="Snapshots" description="GRAPH.COPY of the tenant graph. Click one to jump the slider to when it was taken.">
        {snapshots.length === 0 && <EmptyState title="No snapshots yet" />}
        {snapshots.length > 0 && (
          <ul className="divide-y rounded-lg border bg-card text-xs">
            {snapshots.map((s) => (
              <li key={s.name} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                <Camera className="size-3.5 text-muted-foreground" />
                <span className="font-medium">{s.label}</span>
                <span className="font-mono text-[11px] text-muted-foreground">{s.name}</span>
                <span className="ml-auto font-mono text-[11px] text-muted-foreground tabular">{fmtFull(s.taken_at)}</span>
                <Button size="xs" variant="outline" onClick={() => setT(s.taken_at)}>
                  Jump
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
