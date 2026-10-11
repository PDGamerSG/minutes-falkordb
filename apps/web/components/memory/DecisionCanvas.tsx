"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  CircleDot,
  FileText,
  GitBranch,
  History,
  Mail,
  MessageSquare,
  Network,
  User,
} from "lucide-react";
import type { ImpactItem } from "@/lib/types";
import { fmtDateTime } from "@/lib/format";
import { useOverlays } from "@/components/overlay-context";
import { fromSourceRef, sourceHref } from "@/components/SourceLink";

export function DecisionCanvas({
  team,
  items,
  onReview,
}: {
  team: string;
  items: ImpactItem[];
  onReview: (id: string) => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [version, setVersion] = useState<"original" | "current">("current");
  const item =
    items.find((i) => i.id === selectedId) ??
    items.find((i) => i.assessment === "needs_review") ??
    items[0];
  const { openWhy } = useOverlays();
  if (!item) return null;
  const fact = version === "current" ? item.current : item.baseline;
  const source = fact?.source;
  const sourceTitle =
    source?.container.title ??
    source?.container.subject ??
    fact?.meeting?.title ??
    "Source evidence";
  const href = source
    ? sourceHref(team, fromSourceRef(source))
    : fact?.meeting
      ? sourceHref(team, { kind: "utterance", containerId: fact.meeting.id })
      : null;
  return (
    <section className="decision-canvas" aria-labelledby="canvas-title">
      <header className="canvas-heading">
        <div>
          <Network size={17} />
          <h2 id="canvas-title">The connected picture</h2>
        </div>
        <label>
          <span className="sr-only">Explore a work dependency</span>
          <select
            value={item.id}
            onChange={(e) => {
              setSelectedId(e.target.value);
              setVersion("current");
            }}
          >
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.title}
              </option>
            ))}
          </select>
        </label>
      </header>
      <div className="canvas-surface">
        <div className="canvas-context">
          <span>{item.baseline.subject}</span>
          <span>Source → decision → work</span>
        </div>
        <div className="canvas-nodes">
          <div className="canvas-node canvas-source">
            <span className="node-type">
              {source?.kind === "email" ? (
                <Mail size={14} />
              ) : (
                <MessageSquare size={14} />
              )}{" "}
              {source?.kind === "email" ? "Email thread" : "Source"}
            </span>
            <strong>{fact ? sourceTitle : "No current source"}</strong>
            <span className="canvas-node-subtitle">
              {fact?.speaker?.name ?? "Evidence unavailable"}
            </span>
            {fact &&
              (href ? (
                <Link href={href}>
                  Open source <ArrowUpRight size={13} />
                </Link>
              ) : (
                <button onClick={() => openWhy(team, fact.id)}>
                  View evidence <ArrowUpRight size={13} />
                </button>
              ))}
          </div>
          <div className="canvas-connector" aria-hidden="true">
            <span>informs</span>
            <i />
            <ArrowRight size={14} />
          </div>
          <div className="canvas-node canvas-decision">
            <span className="node-type">
              <GitBranch size={14} />
              {version === "original"
                ? "Original decision"
                : "Current decision"}
            </span>
            <strong>{fact?.object ?? "Unresolved"}</strong>
            <span className="canvas-node-subtitle">
              {item.baseline.predicate.replaceAll("_", " ")}
            </span>
            <div
              className="canvas-version-switch"
              role="group"
              aria-label="Decision version"
            >
              <button
                aria-pressed={version === "original"}
                onClick={() => setVersion("original")}
              >
                <History size={12} /> Original
              </button>
              <button
                aria-pressed={version === "current"}
                onClick={() => setVersion("current")}
              >
                <CircleDot size={12} /> Current
              </button>
            </div>
          </div>
          <div className="canvas-connector" aria-hidden="true">
            <span>affects</span>
            <i />
            <ArrowRight size={14} />
          </div>
          <div className="canvas-node canvas-work">
            <span className="node-type">
              <FileText size={14} />
              Connected work
            </span>
            <strong>{item.title}</strong>
            <span className={`canvas-assessment assessment-${item.assessment}`}>
              <i />
              {item.assessment.replaceAll("_", " ")}
            </span>
            <a href={`#${item.id}`} onClick={() => onReview(item.id)}>
              Review dependency <ArrowUpRight size={13} />
            </a>
          </div>
        </div>
        <div className="canvas-owner">
          <span className="mini-avatar">
            {item.owner?.name.slice(0, 1) ?? "?"}
          </span>
          <span>{item.owner?.name ?? "No owner assigned"}</span>
          <span>
            <User size={12} /> Work owner
          </span>
        </div>
      </div>
      <div className="canvas-evidence" aria-live="polite">
        <span className="canvas-evidence-icon">
          <History size={16} />
        </span>
        <div>
          <p>
            {fact?.text ||
              (fact
                ? `${fact.subject} ${fact.predicate.replaceAll("_", " ")} ${fact.object}`
                : "The current decision could not be resolved. Review the original evidence before acting.")}
          </p>
          <span>
            {fact
              ? `${version === "original" ? "Originally recorded" : "Valid from"} ${fmtDateTime(fact.valid_from)}`
              : "Current evidence unavailable"}
            {item.document.synthetic ? " · Synthetic demo source" : ""}
          </span>
        </div>
        {fact && (
          <button onClick={() => openWhy(team, fact.id)}>
            Why this decision <ArrowUpRight size={14} />
          </button>
        )}
      </div>
    </section>
  );
}
