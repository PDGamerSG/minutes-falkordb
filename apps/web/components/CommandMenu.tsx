"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, CornerDownLeft, Search, Sparkles } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";

const pages = [
  {
    name: "Overview",
    route: "",
    keywords: "home memory impact decisions work",
  },
  {
    name: "Sources",
    route: "sources",
    keywords: "meetings email import transcripts",
  },
  {
    name: "Ask Minutes",
    route: "chat",
    keywords: "chat question conversation search",
  },
  { name: "Agent board", route: "board", keywords: "agents tasks activity" },
  { name: "Timeline", route: "timeline", keywords: "history time decisions" },
  { name: "Skills", route: "skills", keywords: "routines procedures" },
];

export function CommandMenu({ team }: { team: string | null }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const list = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const entries = team
    ? pages
        .filter((p) =>
          `${p.name} ${p.keywords}`.toLowerCase().includes(query.toLowerCase()),
        )
        .map((p) => ({
          name: p.name,
          href: `/t/${encodeURIComponent(team)}${p.route ? `/${p.route}` : ""}`,
        }))
    : [];
  const globalEntries = [
    { name: "Switch workspace", href: "/workspaces" },
    { name: "Benchmarks", href: "/bench" },
  ].filter((p) => p.name.toLowerCase().includes(query.toLowerCase()));
  const go = (href: string) => {
    setOpen(false);
    setQuery("");
    router.push(href);
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  return (
    <>
      <button
        className="command-trigger"
        onClick={() => {
          setQuery("");
          setOpen(true);
        }}
        aria-label="Search and navigate"
      >
        <Search size={15} />
        <span>Find a page</span>
        <kbd>⌘ K</kbd>
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="command-dialog" showCloseButton={false}>
          <DialogTitle className="sr-only">Search and navigate</DialogTitle>
          <DialogDescription className="sr-only">
            Find a page or ask a question in the current workspace. Use Tab or
            arrow keys to move through results and Enter to open.
          </DialogDescription>
          <form
            className="command-input"
            onSubmit={(e) => {
              e.preventDefault();
              if (team && query.trim())
                go(
                  `/t/${encodeURIComponent(team)}/chat?q=${encodeURIComponent(query.trim())}`,
                );
              else if (entries[0] ?? globalEntries[0])
                go((entries[0] ?? globalEntries[0]).href);
            }}
          >
            <Search size={19} />
            <input
              autoFocus
              aria-label="Search pages or ask a question"
              placeholder={
                team ? "Where would you like to go?" : "Find a workspace…"
              }
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  list.current
                    ?.querySelector<HTMLButtonElement>("button")
                    ?.focus();
                }
              }}
            />
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close search"
            >
              <kbd>esc</kbd>
            </button>
          </form>
          <div
            className="command-results"
            ref={list}
            onKeyDown={(e) => {
              if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
              const buttons = [
                ...(list.current?.querySelectorAll<HTMLButtonElement>(
                  "button",
                ) ?? []),
              ];
              const index = buttons.indexOf(
                document.activeElement as HTMLButtonElement,
              );
              e.preventDefault();
              buttons[
                (index + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) %
                  buttons.length
              ]?.focus();
            }}
          >
            {team && query.trim() && (
              <button
                className="command-ask"
                onClick={() =>
                  go(
                    `/t/${encodeURIComponent(team)}/chat?q=${encodeURIComponent(query.trim())}`,
                  )
                }
              >
                <Sparkles size={16} />
                <span>
                  Ask Minutes: <strong>{query.trim()}</strong>
                </span>
                <CornerDownLeft size={14} />
              </button>
            )}
            <span className="command-group-label">Go to</span>
            {[...entries, ...globalEntries].map((e) => (
              <button key={e.href} onClick={() => go(e.href)}>
                <span>{e.name}</span>
                <ArrowUpRight size={15} />
              </button>
            ))}
            {!entries.length && !globalEntries.length && (
              <p className="command-no-results">
                {team
                  ? "No matching pages. Ask Minutes using the option above."
                  : "No matching pages. Open Workspaces to choose your team."}
              </p>
            )}
          </div>
          <div className="command-footer">
            <span>↑ ↓ to navigate</span>
            <span>↵ to open</span>
            <span>Minutes, at your fingertips.</span>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
