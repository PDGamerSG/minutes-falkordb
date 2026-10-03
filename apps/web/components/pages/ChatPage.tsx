"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Plus, SendHorizontal } from "lucide-react";
import { api } from "@/lib/api";
import type { ChatResponse } from "@/lib/types";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { CypherBlock } from "@/components/CypherBlock";
import { GraphView } from "@/components/GraphView";
import { ErrorNote, Mono } from "@/components/Page";
import { fromChatEpisode, fromChatSource, SourceRow } from "@/components/SourceLink";

type Msg = {
  id: string;
  role: "user" | "assistant";
  text: string;
  response?: ChatResponse;
  pending?: boolean;
  error?: string;
};

// Demo questions per seeded tenant (docs/demo-script.md, data/meetings/README.md); generic ones elsewhere.
const SUGGESTIONS: Record<string, string[]> = {
  orbit: ["When is the UPI flow due?", "Why did we choose the side drawer?", "Who knows about PayU?", "What did we decide about offline mode?", "What is still open for Priya?"],
  nimbus: ["When is the events pipeline due?", "When is the Lumen dashboard due?", "Who knows about the schema registry?"],
  quill: ["When is the newsletter sent?", "What did we decide last week?", "What is still open?"],
};
const GENERIC_SUGGESTIONS = ["What did we decide last week?", "What is still open?", "Who knows about the launch?"];

const ROUTE_TONE: Record<string, string> = {
  template: "var(--node-fact)",
  graph: "var(--node-entity)",
  vector: "var(--node-decision)",
  freeform_ro: "var(--state-input-required)",
};

function WhySection({ tenant, r }: { tenant: string; r: ChatResponse }) {
  return (
    <div className="mt-3 space-y-4 rounded-lg border bg-muted/30 p-3">
      <section>
        <h4 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Router decision</h4>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-muted-foreground">intent</dt>
          <dd className="font-mono">{r.router.intent}</dd>
          <dt className="text-muted-foreground">entities</dt>
          <dd className="flex flex-wrap gap-1">
            {r.router.entities.length ? r.router.entities.map((e) => <Badge key={e} variant="secondary">{e}</Badge>) : <span className="text-muted-foreground">none</span>}
          </dd>
          <dt className="text-muted-foreground">route</dt>
          <dd>
            <span
              className="inline-flex h-5 items-center rounded-md border px-1.5 font-mono text-[11px]"
              style={{ color: ROUTE_TONE[r.router.route] ?? "inherit", borderColor: "color-mix(in oklch, currentColor, transparent 70%)" }}
            >
              {r.router.route}
            </span>
          </dd>
          {r.router.template && (
            <>
              <dt className="text-muted-foreground">template</dt>
              <dd className="font-mono">cypher/{r.router.template}.cypher</dd>
            </>
          )}
        </dl>
      </section>

      <section className="space-y-2">
        <h4 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Cypher that ran</h4>
        {r.cypher.length === 0 && <p className="text-xs text-muted-foreground">No Cypher reported.</p>}
        {r.cypher.map((c, i) => (
          <CypherBlock key={i} cypher={c} label={r.cypher.length > 1 ? `Query ${i + 1} of ${r.cypher.length}` : "Cypher"} />
        ))}
      </section>

      <section>
        <h4 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Sources</h4>
        {r.sources.length === 0 && <p className="text-xs text-muted-foreground">No sources attached.</p>}
        <div className="divide-y rounded-md border bg-card">
          {r.sources.map((s, i) => (
            <SourceRow key={`${s.fact_id}-${i}`} tenant={tenant} source={fromChatSource(s)} className="px-2.5 py-1.5" />
          ))}
        </div>
      </section>

      {r.episodes && r.episodes.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Evidence episodes ({r.episodes.length})</h4>
          <ol className="divide-y rounded-md border bg-card">
            {r.episodes.map((e, i) => (
              <li key={`${e.episode_id}-${i}`} className="px-2.5 py-1.5">
                <SourceRow tenant={tenant} source={fromChatEpisode(e)} />
                <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-muted-foreground">{e.text}</p>
                <div className="mt-0.5 flex gap-3 font-mono text-[10px] text-muted-foreground">
                  <span>{e.episode_id}</span>
                  {typeof e.score === "number" && <span className="tabular">score {e.score.toFixed(4)}</span>}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section>
        <h4 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Subgraph</h4>
        <GraphView subgraph={r.subgraph} tenant={tenant} height={280} highlightIds={r.sources.map((s) => s.fact_id)} />
      </section>
    </div>
  );
}

function AssistantMessage({ tenant, m }: { tenant: string; m: Msg }) {
  const [open, setOpen] = useState(false);
  const r = m.response;
  return (
    <div className="max-w-3xl">
      <div className="rounded-lg border bg-card p-3 text-sm">
        {m.pending && (
          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="size-1.5 animate-pulse rounded-full bg-primary" /> Thinking…
          </div>
        )}
        {m.error && <ErrorNote error={m.error} />}
        {!m.pending && !m.error && <p className="leading-relaxed whitespace-pre-wrap">{m.text}</p>}
        {r && (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2 text-[11px] text-muted-foreground">
            <span className="font-mono" style={{ color: ROUTE_TONE[r.router.route] }}>
              {r.router.route}
              {r.router.template ? ` · ${r.router.template}` : ""}
            </span>
            <span className="font-mono">{r.model}</span>
            <span className="font-mono tabular">{fmtNum(r.latency_ms)} ms</span>
            <span className="font-mono tabular">
              {r.subgraph.nodes.length}n/{r.subgraph.edges.length}e
            </span>
            <Button size="xs" variant="ghost" className="ml-auto" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
              {open ? <ChevronDown /> : <ChevronRight />} Why
            </Button>
          </div>
        )}
      </div>
      {r && open && <WhySection tenant={tenant} r={r} />}
    </div>
  );
}

export function ChatPage({ team }: { team: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const urlSession = sp.get("session");

  const [sessionId, setSessionId] = useState<string | null>(urlSession);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const loadedFor = useRef<string | null>(null);

  // Restore a session from the URL.
  useEffect(() => {
    // loadedFor is set by send() for a session this page created, so its turns are already shown.
    if (!urlSession || loadedFor.current === urlSession) return;
    let cancelled = false;
    api.chat
      .history(team, urlSession)
      .then((turns) => {
        if (cancelled) return;
        loadedFor.current = urlSession;
        if (!Array.isArray(turns) || turns.length === 0) return;
        setMsgs(
          turns.map((t, i) => ({
            id: `h${i}`,
            role: t.role,
            text: t.text,
            response: t.response,
          })),
        );
      })
      .catch(() => {
        // unknown session: start fresh but keep the id so the server can attach
      });
    return () => {
      cancelled = true;
    };
  }, [team, urlSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [msgs.length, busy]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      setInput("");
      setBusy(true);
      const uid = `u${Date.now()}`;
      const aid = `a${Date.now()}`;
      setMsgs((m) => [...m, { id: uid, role: "user", text: message }, { id: aid, role: "assistant", text: "", pending: true }]);
      try {
        const r = await api.chat.send(team, message, sessionId ?? undefined);
        setMsgs((m) => m.map((x) => (x.id === aid ? { id: aid, role: "assistant", text: r.answer, response: r } : x)));
        if (r.session_id && r.session_id !== sessionId) {
          setSessionId(r.session_id);
          loadedFor.current = r.session_id;
          const next = new URLSearchParams(sp.toString());
          next.set("session", r.session_id);
          router.replace(`${pathname}?${next.toString()}`, { scroll: false });
        }
      } catch (e) {
        const err = e instanceof Error ? e.message : String(e);
        setMsgs((m) => m.map((x) => (x.id === aid ? { id: aid, role: "assistant", text: "", error: err } : x)));
      } finally {
        setBusy(false);
      }
    },
    [busy, team, sessionId, sp, router, pathname],
  );

  const newSession = () => {
    setSessionId(null);
    setMsgs([]);
    loadedFor.current = null;
    router.replace(pathname, { scroll: false });
  };

  return (
    <div className="flex h-[calc(100dvh-5.5rem)] flex-col md:h-[calc(100dvh-2.5rem)]">
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Chat</h1>
          <p className="text-sm text-muted-foreground">Ask the AnswerAgent. Every answer carries its router decision, the Cypher that ran, the sources and the subgraph it touched.</p>
        </div>
        <div className="flex items-center gap-2">
          {sessionId && <Mono title="session_id">session {sessionId}</Mono>}
          <Button size="sm" variant="outline" onClick={newSession}>
            <Plus /> New session
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-lg border bg-muted/20 p-3">
        {msgs.length === 0 && (
          <div className="flex h-full flex-col items-start justify-end gap-2">
            <div className="text-xs text-muted-foreground">Try one of these:</div>
            <div className="flex flex-wrap gap-1.5">
              {(SUGGESTIONS[team] ?? GENERIC_SUGGESTIONS).map((s) => (
                <Button key={s} size="sm" variant="outline" onClick={() => void send(s)}>
                  {s}
                </Button>
              ))}
            </div>
          </div>
        )}
        {msgs.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-2xl rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">{m.text}</div>
            </div>
          ) : (
            <AssistantMessage key={m.id} tenant={team} m={m} />
          ),
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="mt-3 flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(input);
            }
          }}
          placeholder="Ask about a decision, a commitment, or who said what… (Enter to send, Shift+Enter for a newline)"
          className={cn("min-h-10 flex-1 resize-none")}
          rows={1}
          disabled={busy}
        />
        <Button type="submit" disabled={busy || !input.trim()} aria-label="Send">
          <SendHorizontal /> Send
        </Button>
      </form>
    </div>
  );
}
