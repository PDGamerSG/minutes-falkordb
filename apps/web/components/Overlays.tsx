"use client";

// Renders the app-wide Why sheet and Email drawer and provides the context
// used to open them from anywhere.

import { useCallback, useMemo, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import type { EmailMessage } from "@/lib/types";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { OverlayContext, type OpenEmailArgs } from "@/components/overlay-context";
import { WhyPanel } from "@/components/WhyPanel";
import { EmailThreadView } from "@/components/EmailThreadView";
import { ErrorNote } from "@/components/Page";

type WhyTarget = { tenant: string; nodeId: string } | null;

function WhySheet({ target, onClose }: { target: WhyTarget; onClose: () => void }) {
  const { data, error, loading } = useResource(
    () => (target ? api.why(target.tenant, target.nodeId) : Promise.reject(new Error("no target"))),
    [target?.tenant, target?.nodeId],
    { enabled: !!target },
  );
  return (
    <Sheet open={!!target} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-hidden sm:max-w-xl">
        <SheetHeader className="border-b">
          <SheetTitle>Why</SheetTitle>
          <SheetDescription className="font-mono text-xs">{target?.nodeId}</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {target && loading && !data && (
            <div className="space-y-3">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          )}
          {error && !data && <ErrorNote error={error} />}
          {target && data && <WhyPanel tenant={target.tenant} why={data} />}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function EmailDrawer({ target, onClose }: { target: OpenEmailArgs | null; onClose: () => void }) {
  const { data, error, loading } = useResource<{ subject: string; messages: EmailMessage[] }>(
    async () => {
      if (!target) throw new Error("no target");
      let threadId = target.threadId ?? null;
      let subject = target.subject ?? null;
      if (!threadId) {
        const threads = await api.threads.list(target.tenant);
        const hit = threads.find((t) => t.subject === subject) ?? threads.find((t) => subject && t.subject.toLowerCase().includes(subject.toLowerCase()));
        if (!hit) throw new Error(`Thread not found: ${subject ?? "?"}`);
        threadId = hit.id;
        subject = hit.subject;
      }
      const messages = await api.threads.messages(target.tenant, threadId);
      return { subject: subject ?? threadId, messages };
    },
    [target?.tenant, target?.threadId, target?.subject],
    { enabled: !!target },
  );
  return (
    <Sheet open={!!target} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-hidden sm:max-w-xl">
        <SheetHeader className="border-b">
          <SheetTitle>{data?.subject ?? target?.subject ?? "Email thread"}</SheetTitle>
          <SheetDescription className="font-mono text-xs">
            {target?.threadId ?? ""}
            {target?.messageId ? ` · ${target.messageId}` : ""}
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {target && loading && !data && (
            <div className="space-y-2">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}
          {error && !data && <ErrorNote error={error} />}
          {data && <EmailThreadView messages={data.messages} highlightId={target?.messageId ?? null} />}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function OverlayProvider({ children }: { children: ReactNode }) {
  const [why, setWhy] = useState<WhyTarget>(null);
  const [email, setEmail] = useState<OpenEmailArgs | null>(null);

  const openWhy = useCallback((tenant: string, nodeId: string) => setWhy({ tenant, nodeId }), []);
  const openEmail = useCallback((args: OpenEmailArgs) => setEmail(args), []);
  const value = useMemo(() => ({ openWhy, openEmail }), [openWhy, openEmail]);

  return (
    <OverlayContext.Provider value={value}>
      {children}
      <WhySheet target={why} onClose={() => setWhy(null)} />
      <EmailDrawer target={email} onClose={() => setEmail(null)} />
    </OverlayContext.Provider>
  );
}
