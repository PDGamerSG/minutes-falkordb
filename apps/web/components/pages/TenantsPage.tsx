"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Plus, ShieldOff } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import type { AclProbe, Tenant } from "@/lib/types";
import { fmtMb, fmtNum } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorNote, PageHeader } from "@/components/Page";

const COUNT_KEYS = ["episodes", "facts", "decisions", "commitments", "tasks", "skills"] as const;

function TenantCard({ tenant, others }: { tenant: Tenant; others: Tenant[] }) {
  const [target, setTarget] = useState(others[0]?.slug ?? "");
  const [probe, setProbe] = useState<AclProbe | null>(null);
  const [probing, setProbing] = useState(false);

  const runProbe = async () => {
    if (!target) return;
    setProbing(true);
    setProbe(null);
    try {
      const r = await api.tenants.aclProbe(tenant.slug, target);
      setProbe(r);
    } catch (e) {
      setProbe({ allowed: false, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setProbing(false);
    }
  };

  return (
    <Card className="flex flex-col">
      <CardHeader>
        <CardTitle className="flex items-baseline gap-2">
          {tenant.display_name}
          <span className="font-mono text-xs font-normal text-muted-foreground">{tenant.slug}</span>
        </CardTitle>
        <CardDescription className="font-mono text-xs">
          {tenant.graph} · {fmtNum(tenant.nodes ?? 0)} nodes · {fmtNum(tenant.edges ?? 0)} edges
          {tenant.usage_mb > 0 ? ` · ${fmtMb(tenant.usage_mb)}` : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex-1 space-y-4">
        <dl className="grid grid-cols-3 gap-x-3 gap-y-2">
          {COUNT_KEYS.map((k) => (
            <div key={k}>
              <dt className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">{k}</dt>
              <dd className="text-base font-semibold tabular">{fmtNum(tenant.counts[k])}</dd>
            </div>
          ))}
        </dl>

        <div>
          <div className="mb-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">ACL</div>
          <div className="grid grid-cols-[auto_1fr] gap-x-2 font-mono text-[11px]">
            <span className="text-muted-foreground">rw</span>
            <span className="truncate">{tenant.acl.rw_user}</span>
            <span className="text-muted-foreground">ro</span>
            <span className="truncate">{tenant.acl.ro_user}</span>
          </div>
          {tenant.acl.rules.length > 0 && (
            <pre className="mt-1.5 overflow-x-auto rounded-md border bg-muted/40 p-2 font-mono text-[10px] leading-relaxed text-muted-foreground">
              {tenant.acl.rules.join("\n")}
            </pre>
          )}
        </div>

        <div>
          <div className="mb-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">ACL probe</div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">
              read <span className="font-mono">team_{target || "…"}</span> as <span className="font-mono">{tenant.acl.ro_user}</span>
            </span>
            <select
              aria-label="Target tenant"
              className="h-7 rounded-md border bg-background px-1.5 font-mono text-xs"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              {others.map((o) => (
                <option key={o.slug} value={o.slug}>
                  {o.slug}
                </option>
              ))}
            </select>
            <Button size="sm" variant="outline" onClick={runProbe} disabled={probing || !target}>
              <ShieldOff /> {probing ? "Probing…" : "Probe"}
            </Button>
          </div>
          {probe && (
            <div className="mt-2 rounded-md border border-(--state-failed)/40 bg-(--state-failed)/5 p-2 text-xs">
              <div className="mb-0.5 font-medium text-(--state-failed)">allowed: {String(probe.allowed)}</div>
              <code className="block font-mono text-[11px] break-words [overflow-wrap:anywhere] text-foreground/80">{probe.error}</code>
            </div>
          )}
        </div>
      </CardContent>
      <CardFooter>
        <Button render={<Link href={`/t/${encodeURIComponent(tenant.slug)}/sources`} />} nativeButton={false} className="w-full">
          Open {tenant.display_name} <ArrowRight />
        </Button>
      </CardFooter>
    </Card>
  );
}

function NewTenantDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^[a-z][a-z0-9-]{1,30}$/.test(slug) && name.trim().length > 0;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <Plus /> New tenant
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create tenant</DialogTitle>
          <DialogDescription>
            Creates graph <span className="font-mono">team_{slug || "<slug>"}</span> with its own rw/ro ACL users.
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
              toast.success(`Tenant ${slug} created`);
              setOpen(false);
              setSlug("");
              setName("");
              onCreated();
            } catch (err) {
              toast.error(err instanceof Error ? err.message : "Failed to create tenant");
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="block space-y-1 text-xs">
            <span className="text-muted-foreground">Slug</span>
            <Input value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} placeholder="orbit" className="font-mono" />
          </label>
          <label className="block space-y-1 text-xs">
            <span className="text-muted-foreground">Display name</span>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Orbit" />
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
  const { data, error, loading, refetch } = useResource(() => api.tenants.list(), []);
  return (
    <div className="space-y-5">
      <PageHeader
        title="Tenants"
        description="One FalkorDB graph per team, one ACL user pair per graph. Pick a tenant to open its memory; probe the ACL to watch a cross-tenant read fail."
        actions={<NewTenantDialog onCreated={refetch} />}
      />
      {error && !data && <ErrorNote error={error} />}
      {loading && !data && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-80" />
          ))}
        </div>
      )}
      {data && data.length === 0 && <EmptyState title="No tenants yet" hint="Create one, or run data/seed.py against the API." />}
      {data && data.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((t) => (
            <TenantCard key={t.slug} tenant={t} others={data.filter((o) => o.slug !== t.slug)} />
          ))}
        </div>
      )}
    </div>
  );
}
