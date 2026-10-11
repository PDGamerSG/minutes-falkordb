"use client";

import { useState, type CSSProperties } from "react";
import {
  ArrowUpRight,
  Check,
  FileText,
  GitBranch,
  Mail,
  Mic,
  MousePointer2,
  Network,
  Sparkles,
  User,
} from "lucide-react";

const items = [
  {
    id: "meeting",
    title: "Product kickoff",
    kind: "Meeting",
    icon: Mic,
    x: 16,
    y: 29,
    text: "“Let’s target September 24 for the UPI flow.”",
    foot: "Priya · Original conversation",
    detail: "The original commitment",
    body: "The kickoff records who proposed the date and why. The source stays attached as plans evolve.",
  },
  {
    id: "email",
    title: "A change of plan",
    kind: "Email",
    icon: Mail,
    x: 20,
    y: 76,
    text: "“Sandbox access is delayed. Move the date.”",
    foot: "Payments follow-up",
    detail: "The reason behind the change",
    body: "A later email revises the plan. Minutes connects it to the earlier commitment instead of losing that history.",
  },
  {
    id: "decision",
    title: "UPI release",
    kind: "Decision",
    icon: GitBranch,
    x: 72,
    y: 25,
    text: "September 28",
    foot: "Current date · history preserved",
    detail: "A decision with a memory",
    body: "Follow the date from September 24 to 25 to 28. Each change has its own source and point in time.",
  },
  {
    id: "work",
    title: "Release handoff",
    kind: "Connected work",
    icon: FileText,
    x: 81,
    y: 70,
    text: "The old date is still in the plan.",
    foot: "Rahul · Needs review",
    detail: "Know what needs attention",
    body: "A tracked dependency still points to the earlier decision. Its owner can review the change with the evidence close by.",
  },
];

export function MemoryMark({ className = "" }: { className?: string }) {
  return (
    <span className={`m-memory-mark ${className}`} aria-hidden="true">
      {Array.from({ length: 9 }, (_, i) => (
        <i key={i} />
      ))}
    </span>
  );
}

export function CompanyMap() {
  const [selected, setSelected] = useState("decision");
  const [connected, setConnected] = useState(true);
  const item = items.find((x) => x.id === selected)!;
  return (
    <div className="m-map-wrap">
      <div className="m-map-toolbar">
        <span>
          <Network size={14} /> A company, connected
        </span>
        <button
          onClick={() => setConnected(!connected)}
          aria-pressed={connected}
        >
          {connected ? <Check size={13} /> : <Network size={13} />}
          {connected ? "Connections on" : "Connect the dots"}
        </button>
      </div>
      <div
        className={`m-company-map ${connected ? "is-connected" : "is-scattered"}`}
      >
        <svg
          className="m-map-lines"
          viewBox="0 0 1100 410"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <defs>
            <linearGradient id="memory-line">
              <stop stopColor="#c5d3f6" />
              <stop offset=".5" stopColor="#3863ee" />
              <stop offset="1" stopColor="#c5d3f6" />
            </linearGradient>
          </defs>
          <g fill="none" stroke="url(#memory-line)" strokeWidth="1.4">
            <path d="M176 119 C330 119 360 201 550 201" />
            <path d="M220 312 C345 312 368 201 550 201" />
            <path d="M550 201 C686 201 648 103 792 103" />
            <path d="M550 201 C700 201 714 287 891 287" />
            <path d="M550 201 C530 120 473 90 462 54" />
            <path d="M550 201 C530 279 525 317 550 362" />
          </g>
          <g fill="#4067eb">
            <circle cx="372" cy="167" r="3" />
            <circle cx="371" cy="253" r="3" />
            <circle cx="684" cy="153" r="3" />
            <circle cx="728" cy="251" r="3" />
          </g>
          <g fill="none" stroke="#dce3f1" strokeDasharray="3 5">
            <ellipse cx="550" cy="201" rx="180" ry="158" />
            <ellipse cx="550" cy="201" rx="244" ry="192" />
          </g>
        </svg>
        <div className="m-core">
          <div className="m-core-block">
            <MemoryMark />
          </div>
          <span>minutes</span>
          <small>Company memory</small>
        </div>
        {items.map(({ icon: Icon, ...node }) => (
          <button
            key={node.id}
            onClick={() => setSelected(node.id)}
            aria-pressed={selected === node.id}
            className={`m-map-node m-map-${node.id}`}
            style={
              { "--x": `${node.x}%`, "--y": `${node.y}%` } as CSSProperties
            }
          >
            <span className="m-node-kind">
              <Icon size={13} />
              {node.kind}
              <ArrowUpRight size={12} />
            </span>
            <strong>{node.title}</strong>
            <p>{node.text}</p>
            <small>{node.foot}</small>
          </button>
        ))}
        <span className="m-map-person">
          <span>
            <User size={14} />
          </span>{" "}
          Priya <small>Owner</small>
        </span>
        <span className="m-map-agent">
          <Sparkles size={14} /> Follow-up agent
        </span>
        <div className="m-orbit-dot m-dot-a" />
        <div className="m-orbit-dot m-dot-b" />
        <div className="m-orbit-dot m-dot-c" />
      </div>
      <div className="m-map-caption">
        <div key={item.id} aria-live="polite">
          <strong>{item.detail}</strong>
          <span>{item.body}</span>
        </div>
        <span>
          <MousePointer2 size={13} /> Explore any card{" "}
          <small>Illustrative example</small>
        </span>
      </div>
    </div>
  );
}
