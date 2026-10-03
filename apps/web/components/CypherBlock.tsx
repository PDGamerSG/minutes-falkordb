"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const TOKEN =
  /('[^']*'|"[^"]*"|\$\w+|\/\*[\s\S]*?\*\/|\/\/[^\n]*|--[^\n]*|\b(?:MATCH|OPTIONAL|WHERE|RETURN|WITH|CREATE|MERGE|SET|DELETE|DETACH|REMOVE|ORDER|BY|LIMIT|SKIP|UNWIND|CALL|YIELD|AS|AND|OR|XOR|NOT|IS|NULL|DISTINCT|ASC|DESC|CASE|WHEN|THEN|ELSE|END|IN|STARTS|ENDS|CONTAINS|EXISTS|UNION|ALL|ON|FOR|INDEX|VECTOR|FULLTEXT|OPTIONS|TRUE|FALSE)\b)/g;

function highlight(src: string) {
  const out: React.ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of src.matchAll(TOKEN)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push(src.slice(last, idx));
    const tok = m[0];
    let cls = "text-primary";
    if (tok.startsWith("'") || tok.startsWith('"')) cls = "text-(--fact-active)";
    else if (tok.startsWith("$")) cls = "text-(--state-input-required)";
    else if (tok.startsWith("/*") || tok.startsWith("//") || tok.startsWith("--")) cls = "text-muted-foreground italic";
    out.push(
      <span key={i++} className={cls}>
        {tok}
      </span>,
    );
    last = idx + tok.length;
  }
  if (last < src.length) out.push(src.slice(last));
  return out;
}

export function CopyButton({ text, className, label = "Copy" }: { text: string; className?: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      size="xs"
      variant="ghost"
      className={cn("text-muted-foreground", className)}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // clipboard unavailable (insecure context); nothing else to do
        }
      }}
      aria-label={copied ? "Copied" : label}
    >
      {copied ? <Check /> : <Copy />}
      {copied ? "Copied" : label}
    </Button>
  );
}

export function CypherBlock({
  cypher,
  label,
  className,
  maxHeight = 280,
}: {
  cypher: string;
  label?: string;
  className?: string;
  maxHeight?: number;
}) {
  return (
    <div className={cn("overflow-hidden rounded-lg border bg-muted/40", className)}>
      <div className="flex h-7 items-center justify-between gap-2 border-b bg-muted/60 pr-1 pl-2.5">
        <span className="truncate text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          {label ?? "Cypher"}
        </span>
        <CopyButton text={cypher} />
      </div>
      <pre
        className="overflow-auto p-2.5 font-mono text-[12px] leading-relaxed whitespace-pre"
        style={{ maxHeight }}
      >
        <code>{highlight(cypher)}</code>
      </pre>
    </div>
  );
}
