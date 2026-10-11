"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, Plus, Network, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { fmtNum } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote } from "@/components/Page";
function NewTenantDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const valid =
    /^[a-z0-9][a-z0-9_]{0,62}$/.test(slug) && name.trim().length > 0;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <Plus /> New workspace
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create a workspace</DialogTitle>
          <DialogDescription>
            A separate knowledge archive for your team, with its own sources and
            conversations.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!valid || busy) return;
            setBusy(true);
            try {
              await api.tenants.create({ slug, display_name: name.trim() });
              toast.success(`Workspace ${slug} created`);
              setOpen(false);
              setSlug("");
              setName("");
              onCreated();
            } catch (err) {
              toast.error(
                err instanceof Error ? err.message : "Failed to create tenant",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="space-y-1 text-xs">
            <label htmlFor="workspace-slug" className="text-muted-foreground">Workspace ID</label>
            <Input
              id="workspace-slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase())}
              placeholder="orbit"
              className="font-mono"
              aria-describedby="slug-hint"
            />
            <span
              id="slug-hint"
              className="block text-[11px] text-muted-foreground"
            >
              1–63 lowercase letters, numbers, or underscores. Start with a
              letter or number.
            </span>
          </div>
          <label className="block space-y-1 text-xs">
            <span className="text-muted-foreground">Display name</span>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Orbit"
            />
          </label>
          <DialogFooter>
            <Button type="submit" disabled={!valid || busy}>
              {busy ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function WorkspaceDirectory() {
  const { data, error, loading, refetch } = useResource(() => api.tenants.list(), []);
  return <div className="ws-directory">
    <header className="ws-directory-heading">
      <div><span className="ws-directory-eyebrow"><Network size={15} /> Your connected company</span><h1>A place for every team.</h1><p>Pick up the conversations, decisions, and work that matter.</p></div>
      <NewTenantDialog onCreated={refetch} />
    </header>
    {error && <div className="space-y-3"><ErrorNote error={`Workspaces could not be loaded: ${error.message}`} /><Button variant="outline" onClick={refetch}>Try again</Button></div>}
    {loading && !data && <div className="space-y-3" aria-busy="true" aria-label="Loading workspaces"><Skeleton className="h-28" /><Skeleton className="h-28" /></div>}
    {data?.length === 0 && <EmptyState title="Your first workspace starts here" hint="Create a workspace, then bring in a meeting or an email thread." />}
    <div className="ws-directory-list">{data?.map(t => <Link key={t.slug} className="ws-directory-row" href={`/t/${encodeURIComponent(t.slug)}`}>
      <span className="ws-directory-avatar" aria-hidden="true">{t.display_name.slice(0, 1)}</span>
      <div className="ws-directory-name"><h2>{t.display_name}</h2><span>Company workspace</span></div>
      <dl className="ws-directory-counts">{[["Source entries", t.counts.episodes], ["Decisions", t.counts.decisions], ["Commitments", t.counts.commitments]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{fmtNum(Number(value))}</dd></div>)}</dl>
      <span className="ws-directory-open"><span>Open workspace</span><ArrowUpRight size={18} /></span>
    </Link>)}</div>
    <p className="ws-directory-note"><ShieldCheck size={16} /> Each team keeps its own sources, decisions, and conversations.</p>
  </div>;
}
