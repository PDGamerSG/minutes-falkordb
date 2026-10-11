"use client";
import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Plus,
  Network,
  Mic,
  Mail,
  GitBranch,
  Users,
  Sparkles,
  FileText,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { fmtNum } from "@/lib/format";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote } from "@/components/Page";
import { CompanyMap } from "@/components/landing/CompanyMap";
import { ProductTour } from "@/components/landing/ProductTour";
import {
  ContextGap,
  HistorySection,
  AnswersSection,
  AgentSection,
  MemoryInterlude,
  QuestionsSection,
  LandingFooter,
} from "@/components/landing/LandingSections";
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

export function TenantsPage() {
  const { data, error, loading, refetch } = useResource(
    () => api.tenants.list(),
    [],
  );
  const featured = data?.find((t) => t.slug === "orbit") ?? data?.[0];
  const workspaceHref = featured
    ? `/t/${encodeURIComponent(featured.slug)}`
    : "#workspaces";
  return (
    <div className="minutes-home">
      <section className="m-hero">
        <div className="m-hero-copy">
          <a className="m-announcement" href="#how-it-works">
            <span>
              <Network size={12} />
            </span>{" "}
            Meet your company’s shared memory <ArrowRight size={13} />
          </a>
          <h1>
            The whole story.
            <br />
            Always connected.
          </h1>
          <p>
            Turn scattered conversations into a living memory.
            <br className="m-desktop-break" /> For the people, decisions, and
            agents moving your company forward.
          </p>
          <div className="m-hero-actions">
            <a className="m-button" href="#workspaces">
              Open your workspace <ArrowUpRight size={16} />
            </a>
            <a className="m-button m-button-secondary" href="#how-it-works">
              See how it works <ArrowRight size={16} />
            </a>
          </div>
        </div>
        <div className="m-hero-map m-container">
          <CompanyMap />
        </div>
        <div className="m-source-strip m-container">
          <span>
            Your company’s context,
            <br />
            <strong>in one connected place.</strong>
          </span>
          <div>
            <span>
              <Mic size={19} /> Meetings
            </span>
            <span>
              <Mail size={19} /> Emails
            </span>
            <span>
              <GitBranch size={19} /> Decisions
            </span>
            <span>
              <Users size={19} /> People
            </span>
            <span>
              <FileText size={19} /> Work
            </span>
            <span>
              <Sparkles size={19} /> Agents
            </span>
          </div>
        </div>
      </section>
      <ContextGap />
      <ProductTour workspaceHref={workspaceHref} />
      <HistorySection />
      <AnswersSection workspaceHref={workspaceHref} />
      <AgentSection workspaceHref={workspaceHref} />
      <MemoryInterlude />
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
            <h2 id="workspaces-heading">
              Your next chapter
              <br />
              starts here.
            </h2>
            <p>Step into the context. Pick up where your team left off.</p>
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
      <QuestionsSection />
      <LandingFooter />
    </div>
  );
}
