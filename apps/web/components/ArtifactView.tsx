import { ExternalLink } from "lucide-react";
import type { Artifact } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

/** GitHub mark (lucide has no brand icons). */
export function GitHubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden className={cn("size-3.5 shrink-0 fill-current", className)}>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

export function ArtifactView({ artifact, className }: { artifact: Artifact; className?: string }) {
  if (artifact.kind === "github_issue") {
    const label = artifact.title ?? artifact.text ?? artifact.uri ?? "GitHub issue";
    const inner = (
      <>
        <GitHubMark />
        <span className="truncate">{label}</span>
        {artifact.uri && <ExternalLink className="size-3 shrink-0 text-muted-foreground" />}
      </>
    );
    return (
      <div className={cn("flex flex-wrap items-center gap-2 text-xs", className)}>
        {artifact.uri ? (
          <a
            href={artifact.uri}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex min-w-0 items-center gap-1.5 rounded-md border bg-card px-2 py-1 font-medium hover:bg-muted"
          >
            {inner}
          </a>
        ) : (
          <span className="inline-flex min-w-0 items-center gap-1.5 rounded-md border bg-card px-2 py-1 font-medium">{inner}</span>
        )}
        {artifact.simulated && (
          <Badge variant="outline" className="h-4 px-1.5 text-[10px] text-(--fact-superseded)">
            simulated
          </Badge>
        )}
        {artifact.uri && <span className="font-mono text-[10px] text-muted-foreground">{artifact.uri.replace(/^https?:\/\//, "")}</span>}
      </div>
    );
  }
  return (
    <div className={cn("rounded-md border bg-card p-2 text-xs", className)}>
      <div className="mb-0.5 flex items-center gap-2 font-mono text-[10px] text-muted-foreground uppercase">
        {artifact.kind}
        {artifact.simulated && (
          <Badge variant="outline" className="h-4 px-1.5 text-[10px] text-(--fact-superseded)">
            simulated
          </Badge>
        )}
      </div>
      {artifact.title && <div className="font-medium">{artifact.title}</div>}
      {artifact.text && <p className="whitespace-pre-wrap text-muted-foreground">{artifact.text}</p>}
      {artifact.uri && (
        <a href={artifact.uri} target="_blank" rel="noreferrer noopener" className="font-mono text-[11px] text-primary underline-offset-2 hover:underline">
          {artifact.uri}
        </a>
      )}
    </div>
  );
}
