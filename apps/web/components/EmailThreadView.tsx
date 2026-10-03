"use client";

import { useEffect, useRef } from "react";
import { Mail } from "lucide-react";
import type { EmailMessage, PersonRef } from "@/lib/types";
import { fmtFull } from "@/lib/format";
import { cn } from "@/lib/utils";

function people(list: PersonRef[]) {
  return list.map((p) => p.name || p.email || p.id).join(", ");
}

export function EmailMessageCard({ m, highlighted, depth = 0 }: { m: EmailMessage; highlighted?: boolean; depth?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (highlighted) ref.current?.scrollIntoView({ block: "center" });
  }, [highlighted]);
  return (
    <article
      ref={ref}
      id={`msg-${m.id}`}
      className={cn("rounded-lg border bg-card p-3 text-sm", highlighted && "border-primary/50 ring-2 ring-primary/20")}
      style={{ marginLeft: Math.min(depth, 4) * 12 }}
    >
      <header className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
        <Mail className="size-3.5 translate-y-0.5 text-muted-foreground" />
        <span className="font-medium">{m.sender.name}</span>
        {m.sender.email && <span className="font-mono text-[11px] text-muted-foreground">&lt;{m.sender.email}&gt;</span>}
        <span className="ml-auto font-mono text-[11px] text-muted-foreground tabular">{fmtFull(m.sent_at)}</span>
      </header>
      <div className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 text-xs text-muted-foreground">
        <span>to</span>
        <span>{people(m.to) || "—"}</span>
        {m.cc.length > 0 && (
          <>
            <span>cc</span>
            <span>{people(m.cc)}</span>
          </>
        )}
      </div>
      <p className="mt-2 whitespace-pre-wrap leading-relaxed">{m.text}</p>
      <footer className="mt-2 flex gap-3 font-mono text-[10px] text-muted-foreground">
        <span>{m.id}</span>
        {m.in_reply_to && <span>↳ {m.in_reply_to}</span>}
      </footer>
    </article>
  );
}

/** Renders messages in order with light indentation for replies. */
export function EmailThreadView({ messages, highlightId, className }: { messages: EmailMessage[]; highlightId?: string | null; className?: string }) {
  const depth = new Map<string, number>();
  for (const m of messages) depth.set(m.id, m.in_reply_to ? (depth.get(m.in_reply_to) ?? 0) + 1 : 0);
  return (
    <div className={cn("space-y-2", className)}>
      {messages.map((m) => (
        <EmailMessageCard key={m.id} m={m} depth={depth.get(m.id) ?? 0} highlighted={highlightId === m.id} />
      ))}
      {messages.length === 0 && <p className="text-sm text-muted-foreground">No messages.</p>}
    </div>
  );
}
