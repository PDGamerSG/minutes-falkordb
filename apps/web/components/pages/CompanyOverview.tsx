"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, ArrowUpRight, Check, ChevronDown, Copy, FileText, MessageSquare, Pencil, Plus, RefreshCw, Sparkles, Layers, GitBranch, CircleDot } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import type { ImpactDraft, ImpactItem } from "@/lib/types";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useOverlays } from "@/components/overlay-context";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorNote } from "@/components/Page";
import { DecisionCanvas } from "@/components/memory/DecisionCanvas";
import { WorkItemDialog } from "@/components/impact/WorkItemDialog";
import { GraphView } from "@/components/GraphView";
import { CypherBlock } from "@/components/CypherBlock";

function assessmentLabel(a: ImpactItem["assessment"]) {
  return a === "needs_review" ? "Needs review" : a[0].toUpperCase() + a.slice(1);
}
function nodeTitle(item: ImpactItem, id: string) {
  const n = item.path.nodes.find(n => n.id === id);
  return String(n?.props.title ?? n?.props.name ?? n?.props.text ?? n?.label ?? id);
}

function DraftCard({ draft }: { draft: ImpactDraft }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(draft.body); setCopied(true); toast.success("Draft copied"); }
    catch { toast.error("Copy is unavailable. Select and copy the draft text."); }
  };
  return <div className="draft-card">
    <div className="draft-label"><FileText size={16} /> Saved follow-up draft <span>{fmtDateTime(draft.created_at)}</span></div>
    <p>{draft.body}</p>
    <button onClick={copy}>{copied ? <Check size={15} /> : <Copy size={15} />}{copied ? "Copied" : "Copy draft"}</button>
    <small>Saved in Minutes. No message was sent.</small>
  </div>;
}

function ImpactRow({ tenant, item, onRefresh, onEdit }: { tenant: string; item: ImpactItem; onRefresh: () => void; onEdit: () => void }) {
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [documentOpen, setDocumentOpen] = useState(false);
  const [graphOpen, setGraphOpen] = useState(false);
  const { openWhy } = useOverlays();
  const prepare = async () => {
    if (!item.current) return;
    setBusy(true);
    try {
      await api.impact.draft(tenant, item.id, item.current.id);
      setExpanded(true);
      onRefresh();
      toast.success("Follow-up draft saved. Nothing sent.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
      if (e instanceof ApiError && e.status === 409) onRefresh();
    } finally { setBusy(false); }
  };
  return <article id={item.id} className={`impact-row impact-${item.assessment}`}>
    <div className="impact-row-main">
      <div className="impact-row-title"><span className="impact-status" />
        <h3><button className="impact-select" onClick={() => setExpanded(p => !p)} aria-expanded={expanded}>{item.title}<ChevronDown size={16} /></button></h3>
      </div>
      <div className="impact-meta"><span className="assessment-label">{assessmentLabel(item.assessment)}</span>{item.owner && <span className="impact-owner"><span aria-hidden="true">{item.owner.name.slice(0, 1)}</span>{item.owner.name}</span>}</div>
    </div>
    <div className="impact-change">
      <span className="impact-subject">{item.baseline.subject} · {item.baseline.predicate.replaceAll("_", " ")}</span>
      <div><span className="previous-value">{item.baseline.object}</span><ArrowRight size={15} /><span>{item.current?.object ?? "Unresolved"}</span></div>
    </div>
    <div className="impact-actions"><button className="evidence-action" onClick={() => setExpanded(p => !p)} aria-expanded={expanded}>{expanded ? "Close" : "Review"}<ArrowUpRight size={17} /></button><button className="impact-edit" onClick={onEdit} aria-label={`Edit ${item.title}`}><Pencil size={14} /></button></div>
    {expanded && <div className="impact-evidence">
      <div className="impact-evidence-heading"><h4>Why this work is connected</h4>{item.assessment === "needs_review" && item.current && !item.draft && <Button size="sm" onClick={prepare} disabled={busy}><MessageSquare size={15} />{busy ? "Preparing…" : "Prepare follow-up"}</Button>}</div>
      <p>{item.reason} {item.rationale}</p>
      <div className="impact-evidence-links"><button onClick={() => openWhy(tenant, item.baseline.id)}><FileText size={14} />Original decision</button>{item.current && <button onClick={() => openWhy(tenant, item.current!.id)}><FileText size={14} />Current decision</button>}<button onClick={() => setDocumentOpen(true)}><FileText size={14} />Dependency document</button></div>
      <details className="relationship-details" onToggle={e => setGraphOpen(e.currentTarget.open)}>
        <summary>Recorded graph relationships</summary>
        {graphOpen && <div className="impact-graph"><GraphView subgraph={item.path} tenant={tenant} height={300} /></div>}
        <ul className="relationship-trail" aria-label="Recorded relationships">{item.path.edges.map((e, i) => <li key={`${e.source}-${e.target}-${i}`}><span>{nodeTitle(item, e.source)}</span><b>{e.type.toLowerCase().replaceAll("_", " ")} →</b><span>{nodeTitle(item, e.target)}</span></li>)}</ul>
      </details>
      {item.draft && <DraftCard draft={item.draft} />}
    </div>}
    <Dialog open={documentOpen} onOpenChange={setDocumentOpen}><DialogContent className="max-h-[80dvh] overflow-y-auto"><DialogHeader><DialogTitle>{item.document.title}</DialogTitle><DialogDescription>{item.document.synthetic ? "Synthetic dependency document for this demo" : "Linked work document"}</DialogDescription></DialogHeader><p className="whitespace-pre-wrap text-sm leading-relaxed">{item.document.content}</p></DialogContent></Dialog>
  </article>;
}

type Filter = "all" | ImpactItem["assessment"];
export function CompanyOverview({ team }: { team: string }) {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [workDialog, setWorkDialog] = useState<{ item?: ImpactItem } | null>(null);
  const { data: tenants } = useResource(() => api.tenants.list(), []);
  const tenant = tenants?.find(t => t.slug === team);
  const { data: impact, error, loading, refetch } = useResource(() => api.impact.get(team), [team], { refreshMs: 30_000 });
  const { data: facts } = useResource(() => api.facts.list(team, { status: "active", kind: "decision" }), [team]);
  const { openWhy } = useOverlays();
  const items = (impact?.items ?? []).filter(item => filter === "all" || item.assessment === filter);
  const filters: { id: Filter; label: string; count: number | undefined }[] = [
    { id: "all", label: "All work", count: impact?.summary.tracked },
    { id: "needs_review", label: "Needs review", count: impact?.summary.needs_review },
    { id: "aligned", label: "Aligned", count: impact?.summary.aligned },
    { id: "closed", label: "Closed", count: impact?.summary.closed },
    { id: "unresolved", label: "Unresolved", count: impact?.summary.unresolved },
  ];
  return <div className="overview-page">
    <section className="overview-welcome">
      <div className="overview-heading"><span className="workspace-eyebrow"><span /> {tenant?.display_name ?? team} workspace</span><h1>The whole picture.</h1><p>Your team’s decisions, context, and next steps. All connected.</p>
        <form className="overview-question" onSubmit={e => { e.preventDefault(); if (question.trim()) router.push(`/t/${encodeURIComponent(team)}/chat?q=${encodeURIComponent(question.trim())}`); }}>
          <Sparkles size={19} /><input aria-label="Ask your company" placeholder="Ask anything about your company…" value={question} onChange={e => setQuestion(e.target.value)} /><button type="submit" disabled={!question.trim()} aria-label="Open question in chat"><ArrowUpRight size={19} /></button>
        </form>
        <div className="overview-prompts">{["What changed recently?", "What is still open?"].map(q => <Link key={q} href={`/t/${encodeURIComponent(team)}/chat?q=${encodeURIComponent(q)}`}>{q}<ArrowUpRight size={12} /></Link>)}</div>
      </div>
      <div className="overview-memory-symbol" aria-hidden="true"><div>{Array.from({ length: 36 }, (_, i) => <i key={i} style={{ opacity: .25 + (i % 6) * .14 }} />)}</div><span>Built from your collective knowledge</span></div>
    </section>
    <div className="memory-strip">{[{ label: "Source entries", value: tenant?.counts.episodes, route: "sources", icon: Layers }, { label: "Decisions", value: tenant?.counts.decisions, route: "timeline", icon: GitBranch }, { label: "Commitments", value: tenant?.counts.commitments, route: "board", icon: CircleDot }].map(({ icon: Icon, ...s }) => <Link key={s.label} href={`/t/${encodeURIComponent(team)}/${s.route}`}><span className="stat-icon"><Icon size={17} /></span><span>{s.label}</span><strong>{s.value === undefined ? "—" : fmtNum(s.value)}</strong><ArrowUpRight size={15} /></Link>)}</div>
    {!!impact?.items.length && <DecisionCanvas team={team} items={impact.items} onReview={id => { setFilter("all"); requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "center", behavior: "instant" })); }} />}
    <section className="impact-section" aria-labelledby="impact-title">
      <div className="impact-heading"><div><h2 id="impact-title">The ripple effect.</h2><p>{impact ? (impact.summary.tracked ? `${impact.summary.needs_review} open work ${impact.summary.needs_review === 1 ? "item depends" : "items depend"} on a changed decision.` : "Connect work to a decision to see what a change affects.") : "See what changed, who owns it, and why it matters."}</p></div><div className="impact-heading-actions"><button className="impact-connect" onClick={() => setWorkDialog({})}><Plus size={16} />Connect work</button><button className="refresh-impact" onClick={refetch} aria-label="Refresh impact"><RefreshCw size={16} /></button></div></div>
      <div className="impact-filters" role="group" aria-label="Filter work by assessment">{filters.map(f => <button key={f.id} aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>{f.label}<span>{f.count ?? "—"}</span></button>)}</div>
      {error && <div className="impact-unavailable"><ErrorNote error={`Impact could not be refreshed: ${error.message}`} /><Button variant="outline" size="sm" onClick={refetch}>Try again</Button></div>}
      {loading && !impact && <div className="impact-loading"><Skeleton className="h-24" /><Skeleton className="h-24" /></div>}
      {impact && items.length === 0 && <div className="impact-empty">{impact.summary.tracked ? "No work items in this view." : "No work dependencies have been imported into this workspace."}{!impact.summary.tracked && <Link href={`/t/${encodeURIComponent(team)}/sources`}>Explore the available sources</Link>}</div>}
      <div className="impact-list">{items.map(item => <ImpactRow key={item.id} tenant={team} item={item} onRefresh={refetch} onEdit={() => setWorkDialog({ item })} />)}</div>
      {impact?.cypher && <details className="relationship-details"><summary>How FalkorDB found the impact</summary><p className="my-3">This query follows explicit work dependencies and the recorded decision history in this team’s graph.</p><CypherBlock cypher={impact.cypher} label="Executed impact query" /></details>}
    </section>
    {!!facts?.length && <section className="recent-decisions"><div><h2>In the company memory.</h2><Link href={`/t/${encodeURIComponent(team)}/timeline`}>View timeline <ArrowUpRight size={16} /></Link></div>{[...facts].sort((a, b) => b.valid_from - a.valid_from).slice(0, 3).map(f => <button key={f.id} onClick={() => openWhy(team, f.id)}><span>{f.subject}</span><p>{f.text || `${f.subject} ${f.predicate.replaceAll("_", " ")} ${f.object}`}</p><ArrowUpRight size={17} /></button>)}</section>}
    {workDialog && <WorkItemDialog tenant={team} item={workDialog.item} onClose={() => setWorkDialog(null)} onSaved={() => { setWorkDialog(null); setFilter("all"); refetch(); }} />}
  </div>;
}
