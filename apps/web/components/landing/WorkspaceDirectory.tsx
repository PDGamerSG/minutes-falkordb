"use client";
import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, ArrowUpRight, Plus, Network } from "lucide-react";
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
      <DialogContent className="m-workspace-create">
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
            if (!valid) return;
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
          <label className="block space-y-1 text-xs">
            <span className="text-muted-foreground">Workspace ID</span>
            <Input
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
          </label>
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
  return <div className="minutes-home m-directory">
    <Link href="/" className="m-directory-back"><ArrowLeft size={15} /> Back to the story</Link>
      <section
        className="m-workspaces m-container"
        id="workspaces"
        aria-labelledby="workspaces-heading"
      >
        <div className="m-section-heading">
          <div>
            <span className="m-eyebrow">
              <Network size={14} /> Your connected company
            </span>
            <h1 id="workspaces-heading">
              Pick up where your team left off.
            </h1>
            <p>Your conversations, decisions, and next steps. Together.</p>
          </div>
          <NewTenantDialog onCreated={refetch} />
        </div>
        {error && (
          <div className="space-y-3">
            <ErrorNote
              error={`Workspaces could not be loaded: ${error.message}`}
            />
            <Button variant="outline" onClick={refetch}>
              Try again
            </Button>
          </div>
        )}
        {loading && !data && (
          <div className="space-y-2">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        )}
        {data?.length === 0 && (
          <EmptyState
            title="Your first workspace starts here"
            hint="Create a workspace, then bring in a meeting or an email thread."
          />
        )}
        <div className="m-workspace-list">
          {data?.map((t) => (
            <Link
              className="m-workspace-row"
              key={t.slug}
              href={`/t/${encodeURIComponent(t.slug)}`}
            >
              <span className="m-workspace-avatar">
                {t.display_name.slice(0, 1)}
              </span>
              <div className="m-workspace-name">
                <h3>{t.display_name}</h3>
                <span>Company workspace</span>
              </div>
              <div>
                <strong>{fmtNum(t.counts.episodes)}</strong>
                <span>source entries</span>
              </div>
              <div>
                <strong>{fmtNum(t.counts.decisions)}</strong>
                <span>decisions</span>
              </div>
              <div>
                <strong>{fmtNum(t.counts.commitments)}</strong>
                <span>commitments</span>
              </div>
              <span className="m-workspace-open">
                Open workspace <ArrowUpRight size={19} />
              </span>
            </Link>
          ))}
        </div>
        <p className="m-workspaces-note">
          <Network size={13} /> Each workspace has its own graph, sources, and
          conversations.
        </p>
      </section>
  </div>;
}
