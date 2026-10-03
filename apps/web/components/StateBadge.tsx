import { cn } from "@/lib/utils";
import type { CSSProperties } from "react";

/**
 * Semantic badge for task states (submitted, working, input_required,
 * completed, failed), fact status (active, superseded, retracted), job
 * status, agent state and stream status. Colour comes from CSS tokens.
 */
const TONES: Record<string, string> = {
  submitted: "var(--state-submitted)",
  queued: "var(--state-submitted)",
  draft: "var(--state-submitted)",
  working: "var(--state-working)",
  running: "var(--state-working)",
  connecting: "var(--state-working)",
  reconnecting: "var(--state-working)",
  input_required: "var(--state-input-required)",
  completed: "var(--state-completed)",
  done: "var(--state-completed)",
  open: "var(--state-completed)",
  ok: "var(--state-completed)",
  live: "var(--state-completed)",
  failed: "var(--state-failed)",
  error: "var(--state-failed)",
  offline: "var(--state-failed)",
  active: "var(--fact-active)",
  superseded: "var(--fact-superseded)",
  retracted: "var(--fact-retracted)",
  deprecated: "var(--fact-retracted)",
  idle: "var(--muted-foreground)",
  ingested: "var(--fact-active)",
  mock: "var(--fact-superseded)",
};

export function toneFor(state: string): string {
  return TONES[state] ?? "var(--muted-foreground)";
}

export function StateBadge({
  state,
  label,
  className,
  size = "sm",
  pulse = false,
}: {
  state: string;
  label?: string;
  className?: string;
  size?: "xs" | "sm";
  pulse?: boolean;
}) {
  const tone = toneFor(state);
  return (
    <span
      data-state={state}
      style={{ "--tone": tone } as CSSProperties}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-md border font-medium whitespace-nowrap",
        "border-(--tone)/30 bg-(--tone)/10 text-(--tone)",
        size === "xs" ? "h-4 px-1 text-[10px]" : "h-5 px-1.5 text-xs",
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full bg-(--tone)", pulse && "animate-pulse")} />
      {label ?? state.replace(/_/g, " ")}
    </span>
  );
}

export function StateDot({ state, className }: { state: string; className?: string }) {
  return (
    <span
      aria-hidden
      style={{ "--tone": toneFor(state) } as CSSProperties}
      className={cn("inline-block size-2 shrink-0 rounded-full bg-(--tone)", className)}
    />
  );
}
