"use client";

import type { Fact, GraphNode, WhyResponse } from "@/lib/types";
import { fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CypherBlock } from "@/components/CypherBlock";
import { GraphView, NodeColorDot } from "@/components/GraphView";
import { StateBadge } from "@/components/StateBadge";
import { fromSourceRef, SourceRow, type Provenance } from "@/components/SourceLink";

function factLine(f: Fact) {
  return `${f.subject} ${f.predicate.replace(/_/g, " ")} ${f.object}`;
}

export function HistoryList({ history, currentId, className }: { history: Fact[]; currentId?: string; className?: string }) {
  if (!history.length) return null;
  return (
    <ol className={cn("space-y-1.5", className)}>
      {history.map((h, i) => (
        <li key={`${h.id}-${i}`} className={cn("rounded-md border p-2 text-xs", h.id === currentId && "border-primary/40 bg-primary/5")}>
          <div className="flex flex-wrap items-center gap-2">
            <StateBadge state={h.status} size="xs" />
            <span className="font-medium">{factLine(h)}</span>
            <span className="ml-auto font-mono text-[11px] text-muted-foreground tabular">
              {fmtDateTime(h.valid_from)}
              {h.valid_to != null ? ` → ${fmtDateTime(h.valid_to)}` : ""}
            </span>
          </div>
          <div className="mt-1 text-muted-foreground">
            {h.speaker?.name ? `${h.speaker.name}: ` : ""}
            {h.text}
          </div>
          {i < history.length - 1 && <div className="mt-1 font-mono text-[10px] text-muted-foreground">SUPERSEDES ↓</div>}
        </li>
      ))}
    </ol>
  );
}

/** The API returns the fact record itself as `node` ({id, kind, labels, text, status, ...}); mocks use {id, label, props}. */
function normalizeNode(raw: WhyResponse["node"] | Record<string, unknown>): GraphNode {
  const r = raw as Record<string, unknown>;
  if (typeof r.label === "string" && r.props && typeof r.props === "object") return raw as GraphNode;
  const labels = Array.isArray(r.labels) ? (r.labels as string[]) : [];
  const kind = typeof r.kind === "string" ? r.kind : null;
  const label = labels.find((l) => l !== "Fact") ?? (kind ? kind.charAt(0).toUpperCase() + kind.slice(1) : labels[0]) ?? "Node";
  return { id: String(r.id ?? ""), label, props: r };
}

export function WhyPanel({ tenant, why, showGraph = true, className }: { tenant: string; why: WhyResponse; showGraph?: boolean; className?: string }) {
  const node = normalizeNode(why.node);
  const text = (node.props?.text as string | undefined) ?? (node.props?.name as string | undefined) ?? node.id;
  const prov: Provenance | null = why.source
    ? fromSourceRef(why.source, why.speaker?.name)
    : why.meeting
      ? {
          kind: "utterance",
          speaker: why.speaker?.name,
          containerId: why.meeting.id,
          containerTitle: why.meeting.title,
          t_start: why.episode?.t_start ?? 0,
        }
      : null;

  return (
    <div className={cn("space-y-4 text-sm", className)}>
      <div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <NodeColorDot label={node.label} />
          {node.label}
          <span className="font-mono">{node.id}</span>
          {typeof node.props?.status === "string" && <StateBadge state={node.props.status} size="xs" />}
        </div>
        <p className="mt-1 leading-snug font-medium">{text}</p>
      </div>

      {prov && (
        <section>
          <h4 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Source</h4>
          <SourceRow tenant={tenant} source={prov} />
          {why.episode?.text && (
            <blockquote className="mt-2 border-l-2 pl-3 text-xs text-muted-foreground italic">“{why.episode.text}”</blockquote>
          )}
        </section>
      )}

      {why.history.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            History {why.history.length > 1 ? `(${why.history.length} versions)` : ""}
          </h4>
          <HistoryList history={why.history} currentId={node.id} />
        </section>
      )}

      <details className="query-details"><summary>View the query behind this evidence</summary><div className="mt-3"><CypherBlock cypher={why.cypher} label="Cypher that ran" /></div></details>

      {showGraph && (
        <section>
          <h4 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Subgraph</h4>
          <GraphView subgraph={why.subgraph} tenant={tenant} height={260} panel={false} highlightIds={[node.id]} />
        </section>
      )}
    </div>
  );
}
