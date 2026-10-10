"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useContext, useRef, useState, useTransition, type ReactNode } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { ArrowRight, ArrowUpRight, ChevronDown, MessageSquare, X } from "lucide-react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { MemoryMark } from "./MemoryMark";

const AssistantContext = createContext<((question?: string) => void) | null>(null);
const suggestions = ["Why did the release date move?", "What is still open?"];

export function AskMinutesButton({ children = "Ask Minutes", className, question }: { children?: ReactNode; className?: string; question?: string }) {
  const open = useContext(AssistantContext);
  return <button type="button" className={className} onClick={() => open?.(question)} aria-haspopup="dialog">{children}</button>;
}

export function LandingAssistantProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [selected, setSelected] = useState("");
  const [pending, startTransition] = useTransition();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const router = useRouter();
  const { data, error, loading, refetch } = useResource(() => api.tenants.list(), [], { enabled: open });
  const workspace = data?.find(item => item.slug === selected) ?? data?.[0];

  function continueInChat() {
    if (!workspace || !question.trim() || pending) return;
    const href = `/t/${encodeURIComponent(workspace.slug)}/chat?${new URLSearchParams({ q: question.trim() })}`;
    startTransition(() => router.push(href));
  }

  return <AssistantContext.Provider value={nextQuestion => { if (nextQuestion) setQuestion(nextQuestion); setOpen(true); }}>
    {children}
    <Dialog.Root open={open} onOpenChange={setOpen} modal={false}>
      <Dialog.Trigger ref={triggerRef} className="m-assistant-trigger" aria-label={open ? "Close Minutes assistant" : "Ask Minutes"}>
        {open ? <X size={20} aria-hidden="true" /> : <MemoryMark />}
        <span>{open ? "Close" : "Ask Minutes"}</span>
        {!open && <MessageSquare size={16} aria-hidden="true" />}
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Popup className="m-assistant-panel" initialFocus={false} finalFocus={triggerRef}>
          <header className="m-assistant-header">
            <span className="m-assistant-avatar"><MemoryMark /></span>
            <div><Dialog.Title>Minutes assistant</Dialog.Title><span>A little context goes a long way.</span></div>
            <Dialog.Close className="m-assistant-close" aria-label="Close assistant"><X size={18} aria-hidden="true" /></Dialog.Close>
          </header>
          <div className="m-assistant-body">
            <span className="m-assistant-overline">PICK UP THE THREAD</span>
            <h2>What’s on your mind?</h2>
            <Dialog.Description>Ask about a decision, a conversation, or your team’s next step.</Dialog.Description>
            <form onSubmit={event => { event.preventDefault(); continueInChat(); }}>
              <label className="m-assistant-workspace" htmlFor="assistant-workspace">
                <span>Your workspace</span>
                <span className="m-assistant-select">
                  <select id="assistant-workspace" value={workspace?.slug ?? ""} onChange={event => setSelected(event.target.value)} disabled={!data?.length || pending}>
                    {!data?.length && <option value="">{loading ? "Loading workspaces…" : "Choose a workspace"}</option>}
                    {data?.map(item => <option key={item.slug} value={item.slug}>{item.display_name}</option>)}
                  </select>
                  <ChevronDown size={15} aria-hidden="true" />
                </span>
              </label>
              {error && <p className="m-assistant-notice" role="alert">Workspaces couldn’t load. <button type="button" onClick={refetch}>Try again</button></p>}
              {!loading && !error && data?.length === 0 && <p className="m-assistant-notice">Start with <Link href="/workspaces">a new workspace</Link>, then bring your conversations in.</p>}
              <div className="m-assistant-suggestions" aria-label="Suggested questions">
                {suggestions.map(text => <button type="button" key={text} onClick={() => { setQuestion(text); inputRef.current?.focus(); }}>{text}<ArrowUpRight size={14} aria-hidden="true" /></button>)}
              </div>
              <label className="m-assistant-composer" htmlFor="assistant-question">
                <span>Your question</span>
                <textarea id="assistant-question" ref={inputRef} value={question} onChange={event => setQuestion(event.target.value)} placeholder="Help me catch up on…" rows={3} maxLength={2000} disabled={pending} onKeyDown={event => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); continueInChat(); }
                }} />
              </label>
              <button className="m-assistant-submit" type="submit" disabled={!workspace || !question.trim() || pending}>{pending ? "Opening your chat…" : "Continue in chat"}<ArrowRight size={17} aria-hidden="true" /></button>
              <p className="m-assistant-hint">Your question goes with you. Answers start in your workspace.</p>
            </form>
          </div>
          <footer className="m-assistant-footer"><span>Need somewhere to start?</span><Link href="/workspaces">Open Minutes <ArrowUpRight size={14} aria-hidden="true" /></Link></footer>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  </AssistantContext.Provider>;
}
