"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUpRight, ChevronDown, ChevronRight, History, MessageSquare, Plus, SendHorizontal } from "lucide-react";
import { api } from "@/lib/api";
import type { ChatResponse } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { CypherBlock } from "@/components/CypherBlock";
import { GraphView } from "@/components/GraphView";
import { ErrorNote } from "@/components/Page";
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
    <div className="chat-evidence space-y-5">

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

      <details className="query-details"><summary>Query and routing details</summary><div className="space-y-4 pt-4">      <section>
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
</div></details>
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
    <div className="assistant-message">
      <div className="answer-body">
        {m.pending && (
          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="size-1.5 animate-pulse rounded-full bg-primary" /> Thinking…
          </div>
        )}
        {m.error && <ErrorNote error={m.error} />}
        {!m.pending && !m.error && <p className="leading-relaxed whitespace-pre-wrap">{m.text}</p>}
        {r && (
          <div className="answer-footer"><span className="answer-provenance"><span />{r.sources.length} linked source{r.sources.length !== 1 ? "s" : ""}</span><span>{/fake|scripted/i.test(r.model) ? "Scripted demo answer" : "Evidence available"}</span><Button size="xs" variant="ghost" className="ml-auto" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? <ChevronDown /> : <ChevronRight />} Why this answer</Button></div>
        )}
      </div>
      {r && open && <WhySection tenant={tenant} r={r} />}
    </div>
  );
}

export function ChatPage({ team }: { team: string }) {
  const sp = useSearchParams();
  return <ChatSession key={`${team}:${sp.get("session") ?? "new"}`} team={team} />;
}

function ChatSession({ team }: { team: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const urlSession = sp.get("session");

  const [sessionId, setSessionId] = useState<string | null>(urlSession);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState(() => urlSession ? "" : (sp.get("q") ?? "").slice(0, 2000));
  const [busy, setBusy] = useState(!!urlSession);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const loadedFor = useRef<string | null>(null);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

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
      .catch((error: unknown) => {
        if (!cancelled) setHistoryError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => {
      cancelled = true;
    };
  }, [team, urlSession]);

  useEffect(() => {
    if (!msgs.length) return;
    const conversation = bottomRef.current?.parentElement;
    if (conversation) conversation.scrollTop = conversation.scrollHeight;
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
        if (!mounted.current) return;
        setMsgs((m) => m.map((x) => (x.id === aid ? { id: aid, role: "assistant", text: r.answer, response: r } : x)));
        if (r.session_id && r.session_id !== sessionId) {
          setSessionId(r.session_id);
          loadedFor.current = r.session_id;
          const next = new URLSearchParams(sp.toString());
          next.delete("q");
          next.set("session", r.session_id);
          router.replace(`${pathname}?${next.toString()}`, { scroll: false });
        }
      } catch (e) {
        if (!mounted.current) return;
        const err = e instanceof Error ? e.message : String(e);
        setMsgs((m) => m.map((x) => (x.id === aid ? { id: aid, role: "assistant", text: "", error: err } : x)));
      } finally {
        if (mounted.current) setBusy(false);
      }
    },
    [busy, team, sessionId, sp, router, pathname],
  );

  const newSession = () => {
    setInput("");
    setSessionId(null);
    setMsgs([]);
    loadedFor.current = null;
    router.replace(pathname, { scroll: false });
  };

  return (
    <div className="chat-workspace">
      <div className="chat-header"><div><h1>Ask your company.</h1><p>Find the context behind a decision, and follow it to the source.</p></div><Button size="sm" variant="outline" onClick={newSession} disabled={busy}><Plus /> New conversation</Button></div>
      <div className="chat-context"><span><MessageSquare size={13} /> {team} memory</span><span><History size={13} /> Ask what was known at any point in time</span>{sessionId && <span className="conversation-saved">Conversation saved</span>}</div>

      <div className="chat-messages" role="log" aria-label="Conversation" aria-live="polite">
        {historyError && <ErrorNote error={`Could not load this conversation: ${historyError}`} />}
        {busy && msgs.length === 0 && <p role="status" className="text-sm text-muted-foreground">Loading conversation…</p>}
        {msgs.length === 0 && !busy && (
          <div className="chat-empty"><span className="empty-brain-mark" aria-hidden><span /><span /><span /></span><h2>There’s a reason<br />behind every decision.</h2><p>Start with a question. Every answer keeps its evidence close.</p><div className="chat-suggestions">{(SUGGESTIONS[team] ?? GENERIC_SUGGESTIONS).slice(0, 4).map(s => <button key={s} onClick={() => void send(s)}>{s}<ArrowUpRight size={14} /></button>)}</div></div>
        )}
        {msgs.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <div className="user-message">{m.text}</div>
            </div>
          ) : (
            <AssistantMessage key={m.id} tenant={team} m={m} />
          ),
        )}
        <div ref={bottomRef} />
      </div>

      <form
        className="chat-composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send(input);
            }
          }}
          placeholder="Ask a question about your team…"
          aria-label="Message"
          className={cn("chat-input min-h-12 flex-1 resize-none")}
          rows={1}
          disabled={busy}
        />
        <Button type="submit" disabled={busy || !input.trim()} aria-label="Send">
          <SendHorizontal /> Send
        </Button>
      </form><p className="composer-hint">Enter to send · Shift + Enter for a new line. Answers reflect the sources in this workspace.</p>
    </div>
  );
}
