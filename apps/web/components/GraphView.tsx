"use client";

import dynamic from "next/dynamic";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import type { GraphNode, Subgraph } from "@/lib/types";
import { fmtClock, fmtFull } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOverlays } from "@/components/overlay-context";
import type { GLink, GNode, Palette } from "@/components/graph/ForceGraphInner";

const ForceGraphInner = dynamic(() => import("@/components/graph/ForceGraphInner"), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full rounded-none" />,
});

const LABELS = [
  "Person",
  "Meeting",
  "EmailThread",
  "Episode",
  "Entity",
  "Fact",
  "Decision",
  "Commitment",
  "Task",
  "Agent",
  "Skill",
  "Step",
  "Artifact",
  "Snapshot",
];

function readPalette(): Palette {
  const cs = getComputedStyle(document.documentElement);
  const get = (k: string) => cs.getPropertyValue(k).trim();
  const p: Record<string, string> = {};
  for (const l of LABELS) p[l] = get(`--node-${l.toLowerCase()}`) || get("--node-default");
  return { ...p, link: get("--graph-link"), text: get("--graph-text"), default: get("--node-default") } as Palette;
}

export function usePalette() {
  const [palette, setPalette] = useState<Palette | null>(null);
  useEffect(() => {
    const update = () => setPalette(readPalette());
    update();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return palette;
}

export function nodeName(n: GraphNode): string {
  const p = n.props ?? {};
  const cand = [p.name, p.title, p.subject, p.goal, p.text, p.kind, p.tool].find((v) => typeof v === "string" && v.length > 0);
  if (typeof cand === "string") return cand.length > 60 ? `${cand.slice(0, 58)}…` : cand;
  return n.id;
}

function fmtProp(key: string, v: unknown): string {
  if (v == null) return "null";
  if (typeof v === "number") {
    if (key === "t_start" || key === "t_end") return `${fmtClock(v)} (${v} ms)`;
    if (/(_at|_from|_to|^t_occurred|^ts|^t)$/.test(key) && v > 1e11) return fmtFull(v);
    return Number.isInteger(v) ? String(v) : v.toFixed(3);
  }
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

/** /why/{id} explains facts (provenance and supersession); other nodes have no Why. */
const WHY_LABELS = new Set(["Fact", "Decision", "Commitment"]);

export function NodeColorDot({ label, className }: { label: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 shrink-0 rounded-full", className)}
      style={{ background: `var(--node-${String(label ?? "default").toLowerCase()}, var(--node-default))` }}
    />
  );
}

type Props = {
  subgraph: Subgraph;
  tenant?: string;
  height?: number;
  className?: string;
  /** Show the side panel with node props and the Why link. */
  panel?: boolean;
  highlightIds?: string[];
  onNodeSelect?: (node: GraphNode | null) => void;
  emptyText?: string;
};

export function GraphView({ subgraph, tenant, height = 320, className, panel = true, highlightIds, onNodeSelect, emptyText }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const palette = usePalette();
  const { openWhy } = useOverlays();

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.floor(entries[0]?.contentRect.width ?? 0);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    setWidth(Math.floor(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);

  const { nodes, links } = useMemo(() => {
    const ids = new Set(subgraph.nodes.map((n) => n.id));
    const nodes: GNode[] = subgraph.nodes.map((n) => ({ id: n.id, label: n.label, props: n.props ?? {}, name: nodeName(n) }));
    const links: GLink[] = subgraph.edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, type: e.type }));
    return { nodes, links };
  }, [subgraph]);

  const labelsPresent = useMemo(() => [...new Set(nodes.map((n) => n.label))], [nodes]);
  const hl = useMemo(() => (highlightIds && highlightIds.length ? new Set(highlightIds) : undefined), [highlightIds]);

  const select = (n: GNode | null) => {
    const gn = n ? (subgraph.nodes.find((x) => x.id === n.id) ?? null) : null;
    setSelected(gn);
    onNodeSelect?.(gn);
  };

  const empty = nodes.length === 0;

  return (
    <div className={cn("flex overflow-hidden rounded-lg border bg-card", className)} style={{ minHeight: height }}>
      <div className="relative min-w-0 flex-1" ref={containerRef} style={{ height }}>
        {empty ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">{emptyText ?? "No subgraph returned."}</div>
        ) : width > 0 && palette ? (
          <ForceGraphInner
            nodes={nodes}
            links={links}
            width={width}
            height={height}
            palette={palette}
            selectedId={selected?.id ?? null}
            highlightIds={hl}
            onSelect={select}
          />
        ) : (
          <Skeleton className="h-full w-full rounded-none" />
        )}
        {!empty && (
          <div className="pointer-events-none absolute right-2 bottom-1.5 left-2 flex flex-wrap gap-x-2.5 gap-y-1 text-[10px] text-muted-foreground">
            {labelsPresent.map((l) => (
              <span key={l} className="inline-flex items-center gap-1">
                <NodeColorDot label={l} />
                {l}
              </span>
            ))}
            <span className="tabular">
              {nodes.length} nodes · {links.length} edges
            </span>
          </div>
        )}
      </div>
      {panel && selected && (
        <aside className="hidden w-64 shrink-0 flex-col border-l bg-background text-xs sm:flex">
          <div className="flex items-start justify-between gap-2 border-b p-2.5">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 font-medium">
                <NodeColorDot label={selected.label} />
                {selected.label}
              </div>
              <div className="truncate font-mono text-[11px] text-muted-foreground" title={selected.id}>
                {selected.id}
              </div>
            </div>
            <Button size="icon-xs" variant="ghost" onClick={() => select(null)} aria-label="Close node panel">
              <X />
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-2.5">
            <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1">
              {Object.entries(selected.props ?? {}).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="font-mono text-[11px] text-muted-foreground">{k}</dt>
                  <dd className="min-w-0 break-words [overflow-wrap:anywhere]">{fmtProp(k, v)}</dd>
                </div>
              ))}
            </dl>
          </div>
          {tenant && WHY_LABELS.has(selected.label) && (
            <div className="border-t p-2">
              <Button size="sm" variant="outline" className="w-full" onClick={() => openWhy(tenant, selected.id)}>
                <Search /> Why
              </Button>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}
