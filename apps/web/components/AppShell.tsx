"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowUpRight, ChartColumn, Clock, Database, Layers, Menu, MessageSquare, SquareKanban, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { useMockState } from "@/lib/mock-state";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { StateDot } from "@/components/StateBadge";
import { AskMinutesButton, LandingAssistantProvider } from "@/components/landing/LandingAssistant";

const TEAM_PAGES = [
  { slug: "sources", label: "Sources", icon: Layers },
  { slug: "chat", label: "Chat", icon: MessageSquare },
  { slug: "board", label: "Board", icon: SquareKanban },
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
        "flex h-8 items-center gap-2 rounded-md px-2 text-sm transition-colors",
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
  const label = loading && health === undefined ? "checking API" : health?.ok ? `FalkorDB ${health.falkordb.version}` : health ? "API degraded" : "API offline";
  return (
    <Tooltip>
      <TooltipTrigger render={<div className="flex items-start gap-2 rounded-md px-2 py-1.5 text-xs" />}>
        <StateDot state={state} className="mt-1" />
        <div className="min-w-0">
          <div className="truncate font-medium">{label}</div>
          <div className="truncate font-mono text-[10px] text-muted-foreground">
            {health?.ok ? `${health.llm.backend}/${health.llm.model} · ${health.embeddings.dim}d` : api.base.replace(/^https?:\/\//, "")}
          </div>
        </div>
      </TooltipTrigger>
      <TooltipContent side="right">
        <div className="space-y-0.5 text-left font-mono text-[10px]">
          <div>GET {api.base}/health</div>
          {health?.ok && (
            <>
              <div>graphs: {health.falkordb.graphs}</div>
              <div>embeddings: {health.embeddings.model}</div>
            </>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

function NavBody({ team, pathname, onNavigate }: { team: string | null; pathname: string; onNavigate?: () => void }) {
  const { data: tenants } = useResource(() => api.tenants.list(), [], { enabled: !!team });
  const tenant = tenants?.find((t) => t.slug === team);
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 items-center gap-2 px-3">
        <Link href="/" onClick={onNavigate} className="flex items-center gap-2 font-semibold tracking-tight">
          <span className="inline-block size-2.5 rounded-sm bg-primary" aria-hidden />
          Minutes
        </Link>
        <MockBadge className="ml-auto" />
      </div>

      {team && (
        <div className="mx-2 mb-1 rounded-md border bg-card px-2.5 py-2">
          <div className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">Tenant</div>
          <div className="flex items-baseline justify-between gap-2">
            <div className="truncate text-sm font-medium">{tenant?.display_name ?? team}</div>
            <Link href="/" onClick={onNavigate} className="text-[11px] text-muted-foreground hover:text-foreground">
              switch
            </Link>
          </div>
          <div className="truncate font-mono text-[10px] text-muted-foreground">{tenant?.graph ?? `team_${team}`}</div>
        </div>
      )}

      <nav className="flex-1 space-y-4 overflow-auto px-2 py-1">
        {team && (
          <div className="space-y-0.5">
            {TEAM_PAGES.map((p) => {
              const href = `/t/${encodeURIComponent(team)}/${p.slug}`;
              return (
                <NavLink key={p.slug} href={href} active={pathname.startsWith(href)} icon={p.icon} onNavigate={onNavigate}>
                  {p.label}
                </NavLink>
              );
            })}
          </div>
        )}
        <div className="space-y-0.5">
          {team && <div className="px-2 pb-1 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">Global</div>}
          {GLOBAL_PAGES.map((p) => (
            <NavLink key={p.href} href={p.href} active={pathname.startsWith(p.href)} icon={p.icon} onNavigate={onNavigate}>
              {p.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <div className="border-t p-2">
        <ApiStatus />
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const team = useMemo(() => teamFromPath(pathname), [pathname]);
  const [open, setOpen] = useState(false);
  const [landingScrolled, setLandingScrolled] = useState(false);

  useEffect(() => {
    if (pathname !== "/" && pathname !== "/workspaces") return;
    const onScroll = () => setLandingScrolled(window.scrollY > 18);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [pathname]);

  const current = team ? TEAM_PAGES.find((p) => pathname.startsWith(`/t/${encodeURIComponent(team)}/${p.slug}`))?.label : GLOBAL_PAGES.find((p) => pathname.startsWith(p.href))?.label;

  if (pathname === "/" || pathname === "/workspaces") return (
    <LandingAssistantProvider key={pathname}>
    <div className="entrance-shell">
      <a className="m-skip-link" href="#main-content">Skip to content</a>
      <header className="m-landing-nav" data-scrolled={landingScrolled || undefined}>
        <Link className="m-home-brand" href="/" aria-label="Minutes home">
          <span className="m-home-symbol" aria-hidden="true"><i /><i /><i /></span>
          minutes<span>.</span>
        </Link>
        <nav aria-label="Main navigation">
          <Link href="/#company-memory"><span>01</span>How it works</Link>
          <Link href="/#inside-minutes"><span>02</span>Why Minutes</Link>
          <AskMinutesButton />
        </nav>
        <div className="m-nav-end"><span className="m-nav-live"><i /> context online</span><Link className="m-nav-open" href="/workspaces">Open Minutes <ArrowUpRight size={15} /></Link></div>
      </header>
      <main id="main-content">{children}</main>
    </div>
    </LandingAssistantProvider>
  );

  return (
    <div className="minutes-workspace-shell flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 border-r bg-sidebar text-sidebar-foreground md:block">
        <NavBody team={team} pathname={pathname} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b bg-background/95 px-3 backdrop-blur md:hidden">
          <Button size="icon-sm" variant="ghost" onClick={() => setOpen(true)} aria-label="Open navigation">
            <Menu />
          </Button>
          <span className="font-semibold">Minutes</span>
          {team && <span className="text-muted-foreground">/ {team}</span>}
          {current && <span className="text-muted-foreground">/ {current}</span>}
          <MockBadge className="ml-auto" />
        </header>
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetContent side="left" className="w-64 p-0 sm:max-w-64" showCloseButton={false}>
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <NavBody team={team} pathname={pathname} onNavigate={() => setOpen(false)} />
          </SheetContent>
        </Sheet>

        <main className="min-w-0 flex-1 px-4 py-4 md:px-6 md:py-5">{children}</main>
      </div>
    </div>
  );
}
