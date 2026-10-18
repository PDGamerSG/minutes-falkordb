"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import { ArrowUpRight, ChartColumn, Clock, Database, Layers, Menu, MessageSquare, Orbit, SquareKanban, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { useMockState } from "@/lib/mock-state";
import type { Tenant } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button, buttonVariants } from "@/components/ui/button";
import { PageHeader } from "@/components/Page";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { StateDot } from "@/components/StateBadge";
import { CommandMenu } from "@/components/CommandMenu";
import "@/app/workspace.css";
import { LandingAssistantProvider } from "@/components/landing/LandingAssistant";
import { LandingNavigation } from "@/components/landing/LandingNavigation";

const TEAM_PAGES = [
  { slug: "", label: "Overview", icon: Orbit },
  { slug: "sources", label: "Sources", icon: Layers },
  { slug: "chat", label: "Ask Minutes", icon: MessageSquare },
  { slug: "board", label: "Agent board", icon: SquareKanban },
  { slug: "timeline", label: "Timeline", icon: Clock },
  { slug: "skills", label: "Skills", icon: Workflow },
] as const;

const GLOBAL_PAGES = [
  { href: "/workspaces", label: "Workspaces", icon: Database },
  { href: "/bench", label: "Bench", icon: ChartColumn },
] as const;

export function teamFromPath(pathname: string): string | null {
  const m = pathname.match(/^\/t\/([^/]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

function NavLink({ href, active, icon: Icon, children, onNavigate }: { href: string; active: boolean; icon: React.ComponentType<{ className?: string }>; children: ReactNode; onNavigate?: () => void }) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "nav-link flex h-10 items-center gap-3 rounded-md px-3 text-sm transition-colors",
        active ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground" : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
      )}
    >
      <Icon className="size-4" />
      {children}
    </Link>
  );
}

export function MockBadge({ className }: { className?: string }) {
  const s = useMockState();
  const routes = Object.values(s.fallbacks).sort((a, b) => b.at - a.at);
  const show = s.forced || routes.length > 0;
  if (!show) return null;
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            className={cn(
              "inline-flex h-5 cursor-default items-center gap-1.5 rounded-md border border-(--fact-superseded)/40 bg-(--fact-superseded)/10 px-1.5 text-[11px] font-medium text-(--fact-superseded)",
              className,
            )}
          />
        }
      >
        <StateDot state="mock" />
        mock data
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-xs">
        <div className="space-y-1 text-left">
          <div>{s.forced ? "NEXT_PUBLIC_MOCK=1 forces mock data." : "These routes fell back to mock data:"}</div>
          {!s.forced && (
            <ul className="space-y-0.5 font-mono text-[10px]">
              {routes.slice(0, 7).map((r) => (
                <li key={r.route}>
                  {r.route} <span className="opacity-70">({r.reason})</span>
                </li>
              ))}
              {routes.length > 7 && <li>…and {routes.length - 7} more</li>}
            </ul>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

function ApiStatus() {
  const { data: health, loading } = useResource(() => api.health(), [], { refreshMs: 30_000 });
  const state = loading && health === undefined ? "connecting" : health?.ok ? "live" : health ? "failed" : "offline";
  const label = loading && health === undefined ? "checking API" : health?.ok ? (health.falkordb.kind === "fake" ? "In-memory preview" : `FalkorDB ${health.falkordb.version}`) : health ? "API degraded" : "API offline";
  return (
    <Tooltip>
      <TooltipTrigger render={<div className="flex items-start gap-2 rounded-md px-2 py-1.5 text-xs" />}>
        <StateDot state={state} className="mt-1" />
        <div className="min-w-0">
          <div className="truncate font-medium">{label}</div>
          <div className="truncate font-mono text-[10px] text-muted-foreground">
            {health?.ok ? `${health.falkordb.graphs.length} team graphs` : api.base.replace(/^https?:\/\//, "")}
          </div>
        </div>
      </TooltipTrigger>
      <TooltipContent side="right">
        <div className="space-y-0.5 text-left font-mono text-[10px]">
          <div>GET {api.base}/health</div>
          {health?.ok && <div>graphs: {health.falkordb.graphs.join(", ")}</div>}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

export function Brand({ onNavigate }: { onNavigate?: () => void }) {
  return <Link href="/" className="brand" onClick={onNavigate} aria-label="Minutes home"><span className="brand-mark" aria-hidden><i /><i /><i /></span><span>minutes<span className="brand-period">.</span></span></Link>;
}

function NavBody({ team, tenants, pathname, onNavigate }: { team: string | null; tenants?: Tenant[]; pathname: string; onNavigate?: () => void }) {
  const tenant = tenants?.find((t) => t.slug === team);
  return <div className="workspace-navigation flex h-full flex-col">
    <div className="sidebar-brand"><Link href="/" onClick={onNavigate} aria-label="Minutes home" className="workspace-brand"><span className="workspace-mark" aria-hidden="true">{Array.from({ length: 9 }, (_, i) => <i key={i} />)}</span><span>minutes<span>.</span></span></Link></div>
    {team && <div className="workspace-switch"><span className="workspace-avatar">{(tenant?.display_name ?? team).slice(0, 1)}</span><div><strong>{tenant?.display_name ?? team}</strong><span>Company workspace</span></div><Link href="/workspaces" onClick={onNavigate} aria-label="Switch workspace"><ArrowUpRight size={16} /></Link></div>}
    <nav className="flex-1 space-y-7 overflow-auto px-3 py-4" aria-label="Main navigation">
      {team && <div className="space-y-1">{TEAM_PAGES.map((p) => {
        const href = `/t/${encodeURIComponent(team)}${p.slug ? `/${p.slug}` : ""}`;
        return <NavLink key={p.slug} href={href} active={p.slug ? pathname.startsWith(href) : pathname === href} icon={p.icon} onNavigate={onNavigate}>{p.label}</NavLink>;
      })}</div>}
      <div className="space-y-1 border-t pt-5"><span className="sidebar-label">Workspace tools</span>{GLOBAL_PAGES.map(p => <NavLink key={p.href} href={p.href} active={pathname === p.href} icon={p.icon} onNavigate={onNavigate}>{p.label}</NavLink>)}</div>
    </nav>
    <div className="sidebar-foot"><div className="sidebar-foot-label">Connected knowledge<Orbit size={15} /></div><ApiStatus /><MockBadge /></div>
  </div>;
}

function WorkspaceNotFound({ team }: { team: string }) {
  return (
    <div className="space-y-4">
      <PageHeader title="Workspace not found." description={`There is no workspace called "${team}". Pick one of your team workspaces to continue.`} />
      <Link href="/workspaces" className={buttonVariants()}>
        <Database /> Open workspaces
      </Link>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const team = useMemo(() => teamFromPath(pathname), [pathname]);
  const [open, setOpen] = useState(false);
  const { data: tenants } = useResource(() => api.tenants.list(), [], { enabled: !!team });
  // Only a loaded list can prove a slug wrong; while it loads (or if it fails) the page renders as usual.
  const unknownTeam = !!team && !!tenants && !tenants.some((t) => t.slug === team);
  const current = team ? TEAM_PAGES.find((p) => p.slug ? pathname.startsWith(`/t/${encodeURIComponent(team)}/${p.slug}`) : pathname === `/t/${encodeURIComponent(team)}`)?.label : GLOBAL_PAGES.find(p => p.href === pathname)?.label ?? "Workspace";
  if (pathname === "/") return (
    <LandingAssistantProvider key={pathname}>
      <div className="entrance-shell">
        <a className="m-skip-link" href="#main-content">Skip to content</a>
        <LandingNavigation />
        <main id="main-content">{children}</main>
      </div>
    </LandingAssistantProvider>
  );
  return <div className="minutes-workspace-shell flex min-h-dvh">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className="workspace-sidebar sticky top-0 hidden h-dvh shrink-0 border-r bg-sidebar text-sidebar-foreground lg:block"><NavBody team={unknownTeam ? null : team} tenants={tenants} pathname={pathname} /></aside>
    <div className="flex min-w-0 flex-1 flex-col">
      <header className="workspace-header"><div className="flex items-center gap-3"><Button size="icon-sm" variant="ghost" className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open navigation"><Menu /></Button><Link className="workspace-breadcrumb" href={team ? `/t/${encodeURIComponent(team)}` : "/workspaces"}>{team ?? "Minutes"}</Link><span className="breadcrumb-divider">/</span><span>{current}</span></div><CommandMenu team={team} /><MockBadge /></header>
      <Sheet open={open} onOpenChange={setOpen}><SheetContent side="left" className="workspace-mobile-nav w-64 p-0 sm:max-w-64" showCloseButton={true}><SheetTitle className="sr-only">Navigation</SheetTitle><NavBody team={unknownTeam ? null : team} tenants={tenants} pathname={pathname} onNavigate={() => setOpen(false)} /></SheetContent></Sheet>
      <main id="main-content" key={team ?? "global"} className="workspace-main min-w-0 flex-1" tabIndex={-1}>{unknownTeam && team ? <WorkspaceNotFound team={team} /> : children}</main>
    </div>
  </div>;
}
