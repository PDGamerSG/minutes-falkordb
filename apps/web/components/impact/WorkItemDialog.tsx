"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";
import { Search } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { fmtDateTime } from "@/lib/format";
import type { ImpactItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export function WorkItemDialog({ tenant, item, onClose, onSaved }: {
  tenant: string;
  item?: ImpactItem;
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  const [title, setTitle] = useState(item?.title ?? "");
  const [ownerId, setOwnerId] = useState(item?.owner?.id ?? "");
  const [status, setStatus] = useState<ImpactItem["status"]>(item?.status ?? "open");
  const [baselineId, setBaselineId] = useState(item?.baseline.id ?? "");
  const [rationale, setRationale] = useState(item?.rationale ?? "");
  const [synthetic, setSynthetic] = useState(item?.document.synthetic ?? false);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Retain the ID after a failed/uncertain response so retrying upserts the same work.
  const workId = useRef(item?.id ?? "");
  const submitting = useRef(false);
  const { data, error: loadError, loading, refetch } = useResource(async () => {
    const [people, facts] = await Promise.all([api.people.list(tenant), api.facts.list(tenant, { status: "all" })]);
    return { people, facts };
  }, [tenant]);
  // The fact list is bounded. Keep this work's evidence available outside that window,
  // while preferring fresher list data when the same version is returned there.
  const facts = [...new Map([
    ...(item ? [item.baseline, ...(item.current ? [item.current] : [])] : []),
    ...(data?.facts ?? []),
  ].map(f => [f.id, f])).values()].filter(f => f.status !== "retracted" || f.id === item?.baseline.id);
  const selected = facts.find(f => f.id === baselineId);
  const matches = facts.filter(f => `${f.subject} ${f.predicate} ${f.object} ${f.text}`.toLowerCase().includes(search.trim().toLowerCase()));
  const owner = data?.people.find(p => p.id === ownerId);
  const ready = !!(title.trim() && owner && selected && rationale.trim() && !loadError);

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!ready || submitting.current || !selected || !owner) return;
    submitting.current = true;
    setBusy(true);
    setError(null);
    try {
      if (!workId.current) workId.current = `work_${crypto.randomUUID()}`;
      const id = workId.current;
      await api.work.save(tenant, {
        document: {
          title: `Dependency note: ${title.trim()}`.slice(0, 200),
          uri: `minutes://${encodeURIComponent(tenant)}/work/${id}`,
          synthetic,
          content: [
            "Dependency recorded explicitly in Minutes.",
            `Work: ${title.trim()}`,
            `Owner: ${owner.name} [${owner.id}]`,
            `Status: ${status}`,
            `Based on: ${selected.subject} · ${selected.predicate.replaceAll("_", " ")} · ${selected.object} [${selected.id}]`,
            `Dependency: ${rationale.trim()}`,
            ...(item ? [`Previous dependency document: [${item.document.id}]`] : []),
          ].join("\n\n"),
        },
        items: [{ id, title: title.trim(), status, owner_id: ownerId, baseline_fact_id: baselineId, rationale: rationale.trim() }],
      });
      toast.success(item ? "Work updated. Impact will be checked again." : "Work connected. Impact will be checked now.");
      onSaved(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };

  return <Dialog open onOpenChange={open => { if (!open && !submitting.current) onClose(); }}>
    <DialogContent className="work-dialog sm:max-w-2xl" showCloseButton={!busy}>
      <DialogHeader>
        <DialogTitle>{item ? "Update connected work" : "Connect work to a decision"}</DialogTitle>
        <DialogDescription>Record what the work relies on. Minutes checks that decision’s history to show when a review is needed.</DialogDescription>
      </DialogHeader>
      {loading && <p role="status" className="text-sm text-muted-foreground">Loading this team’s people and evidence…</p>}
      {loadError && <div role="alert" className="work-form-error"><p>Could not load people and evidence. {loadError.message}</p><Button variant="outline" size="sm" onClick={refetch}>Try again</Button></div>}
      {data && !loadError && (!data.people.length || !facts.length) ? <div className="work-form-empty">
        <p>Import a meeting or email with people and recorded decisions first.</p>
        <Link href={`/t/${encodeURIComponent(tenant)}/sources`} onClick={onClose}>Open sources</Link>
      </div> : data && !loadError && <form onSubmit={save} className="work-form">
        <fieldset disabled={busy} className="work-form-fields">
          <label htmlFor="work-title">Work to track<input id="work-title" required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. Update the payment integration runbook" /></label>
          <div className="work-form-pair">
            <label htmlFor="work-owner">Accountable owner<select id="work-owner" required value={ownerId} onChange={e => setOwnerId(e.target.value)}>
              <option value="" disabled>Choose a person</option>
              {data.people.map(p => <option key={p.id} value={p.id}>{p.name}{p.email ? ` (${p.email})` : ""}</option>)}
            </select></label>
            <label htmlFor="work-status">Work status<select id="work-status" value={status} onChange={e => setStatus(e.target.value as ImpactItem["status"])}>
              <option value="open">Open</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option>
            </select></label>
          </div>
          <fieldset className="work-evidence-picker">
            <legend>Decision or commitment the work is based on</legend>
            <p className="work-field-hint">Choose the version used to plan the work. Older versions can reveal a change that needs review.</p>
            {item?.current && item.current.id !== baselineId && <Button type="button" variant="outline" size="sm" onClick={() => { setBaselineId(item.current!.id); setSearch(""); }}>Use current decision: {item.current.object}</Button>}
            <div className="work-evidence-search"><Search size={16} aria-hidden="true" /><input aria-label="Search decisions and commitments" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search subject, value or evidence…" /></div>
            <div className="work-evidence-options" role="group" aria-label="Available evidence">
              {matches.map(f => <label key={f.id} className="work-evidence-option" data-selected={baselineId === f.id}>
                <input type="radio" name="work-evidence" value={f.id} checked={baselineId === f.id} onChange={() => setBaselineId(f.id)} />
                <span><strong>{f.subject} <span>· {f.predicate.replaceAll("_", " ")}</span></strong><span>{f.object}</span><small>{f.status === "active" ? "Current" : f.status === "superseded" ? "Earlier version" : "Retracted"} · {fmtDateTime(f.valid_from)}</small></span>
              </label>)}
              {!matches.length && <p className="work-field-hint">No matching evidence. Try a different search.</p>}
            </div>
            {selected && <div className="work-selected-evidence" aria-live="polite"><strong>Selected: {selected.object}</strong><p>{selected.text || `${selected.subject} ${selected.predicate.replaceAll("_", " ")} ${selected.object}`}</p><small>{selected.source?.container.title ?? selected.source?.container.subject ?? selected.meeting?.title ?? "Recorded evidence"}</small></div>}
          </fieldset>
          <label htmlFor="work-rationale">Why does this work depend on it?<textarea id="work-rationale" required maxLength={2000} rows={3} value={rationale} onChange={e => setRationale(e.target.value)} placeholder="e.g. The runbook contains vendor-specific API instructions that must change if the provider changes." /></label>
          <label className="work-synthetic"><input type="checkbox" checked={synthetic} onChange={e => setSynthetic(e.target.checked)} />This is synthetic demo work</label>
          <p className="work-field-hint">Your selection and explanation are saved as a versioned dependency note. {status !== "open" ? "Closed work will not receive new follow-up drafts." : "Selecting a decision records the work’s dependency; it does not change the decision."}</p>
        </fieldset>
        {error && <p role="alert" className="work-form-error">Could not save work. {error} Your entries are kept; you can retry.</p>}
        <div className="work-form-actions"><Button type="button" variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button><Button type="submit" disabled={!ready || busy}>{busy ? "Saving…" : item ? "Save work" : "Connect work"}</Button></div>
      </form>}
    </DialogContent>
  </Dialog>;
}
