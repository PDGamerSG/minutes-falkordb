"use client";

import { useRouter } from "next/navigation";
import { Mail, Mic, Play } from "lucide-react";
import type { ChatSource, SourceKind, SourceRef } from "@/lib/types";
import { fmtClock, fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useOverlays } from "@/components/overlay-context";

/** Normalised provenance pointer used by chat sources and the Why panel. */
export type Provenance = {
  kind: SourceKind;
  speaker?: string;
  containerId?: string | null;
  containerTitle?: string | null;
  t_start?: number | null;
  sent_at?: number | null;
  message_id?: string | null;
  fact_id?: string;
};

export function fromChatSource(s: ChatSource): Provenance {
  const kind: SourceKind = s.kind ?? (s.sent_at != null || s.message_id ? "email" : "utterance");
  return {
    kind,
    speaker: s.speaker,
    containerId: s.container_id ?? null,
    containerTitle: kind === "email" ? (s.thread ?? s.meeting) : s.meeting,
    t_start: s.t_start,
    sent_at: s.sent_at ?? null,
    message_id: s.message_id ?? null,
    fact_id: s.fact_id,
  };
}

export function fromSourceRef(s: SourceRef, speaker?: string): Provenance {
  return {
    kind: s.kind,
    speaker,
    containerId: s.container.id,
    containerTitle: s.container.title ?? s.container.subject ?? null,
    t_start: s.t_start ?? null,
    sent_at: s.sent_at ?? null,
    message_id: s.message_id ?? null,
  };
}

export function sourceHref(tenant: string, p: Provenance): string {
  const sp = new URLSearchParams();
  if (p.kind === "email") {
    sp.set("tab", "email");
    if (p.containerId) sp.set("thread", p.containerId);
    else if (p.containerTitle) sp.set("title", p.containerTitle);
    if (p.message_id) sp.set("message", p.message_id);
  } else {
    sp.set("tab", "meetings");
    if (p.containerId) sp.set("meeting", p.containerId);
    else if (p.containerTitle) sp.set("title", p.containerTitle);
    if (p.t_start != null) sp.set("t", String(Math.max(0, Math.round(p.t_start))));
  }
  return `/t/${encodeURIComponent(tenant)}/sources?${sp.toString()}`;
}

export function SourceIcon({ kind, className }: { kind: SourceKind; className?: string }) {
  const Icon = kind === "email" ? Mail : Mic;
  return <Icon className={cn("size-3.5 shrink-0 text-muted-foreground", className)} aria-label={kind === "email" ? "email" : "utterance"} />;
}

/** Action button: "Play at 0:21" for utterances, "Open email" for emails. */
export function SourceAction({ tenant, source, size = "xs" }: { tenant: string; source: Provenance; size?: "xs" | "sm" }) {
  const router = useRouter();
  const { openEmail } = useOverlays();
  if (source.kind === "email") {
    return (
      <Button
        size={size}
        variant="outline"
        onClick={() =>
          openEmail({ tenant, threadId: source.containerId ?? null, subject: source.containerTitle ?? null, messageId: source.message_id ?? null })
        }
      >
        <Mail /> Open email
      </Button>
    );
  }
  return (
    <Button size={size} variant="outline" onClick={() => router.push(sourceHref(tenant, source))}>
      <Play /> Play at {fmtClock(source.t_start ?? 0)}
    </Button>
  );
}

/** One provenance row: icon, speaker, container, time, action. */
export function SourceRow({ tenant, source, className }: { tenant: string; source: Provenance; className?: string }) {
  const when = source.kind === "email" ? fmtDateTime(source.sent_at) : fmtClock(source.t_start ?? 0);
  return (
    <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-xs", className)}>
      <SourceIcon kind={source.kind} />
      {source.speaker && <span className="font-medium">{source.speaker}</span>}
      <span className="text-muted-foreground">
        {source.kind === "email" ? "wrote in" : "said in"}
      </span>
      <span className="truncate">{source.containerTitle ?? source.containerId ?? "unknown source"}</span>
      <span className="font-mono text-[11px] text-muted-foreground tabular">{when}</span>
      {source.fact_id && (
        <span className="font-mono text-[11px] text-muted-foreground" title={source.fact_id}>
          {source.fact_id}
        </span>
      )}
      <span className="ml-auto">
        <SourceAction tenant={tenant} source={source} />
      </span>
    </div>
  );
}
