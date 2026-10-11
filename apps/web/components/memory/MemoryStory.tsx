"use client";

import { useRef, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  CircleDot,
  FileText,
  GitBranch,
  History,
  Mail,
  MessageSquare,
  MousePointer2,
  ScanLine,
  User,
} from "lucide-react";
import { MemoryConnections } from "./MemoryConnections";

const steps = [
  {
    title: "Start with what was said.",
    description:
      "A meeting, an email, a passing conversation. Keep the original words, and the person behind them.",
    icon: MessageSquare,
  },
  {
    title: "Remember what changed.",
    description:
      "A new deadline doesn’t erase the old one. Connect the decision to its history and the reason it moved.",
    icon: GitBranch,
  },
  {
    title: "See what happens next.",
    description:
      "Follow the change to the work that depends on it. Find the owner. Prepare a follow-up with the context intact.",
    icon: CircleDot,
  },
];

export function MemoryStory() {
  const [stage, setStage] = useState(1);
  const [past, setPast] = useState(false);
  const [detail, setDetail] = useState<"source" | "decision" | "work">(
    "decision",
  );
  const map = useRef<HTMLDivElement>(null);
  const first = useRef<HTMLButtonElement>(null);
  const second = useRef<HTMLButtonElement>(null);
  const decision = useRef<HTMLButtonElement>(null);
  const work = useRef<HTMLDivElement>(null);
  const select = (index: number) => {
    setStage(index);
    setDetail((["source", "decision", "work"] as const)[index]);
  };
  return (
    <section
      className="memory-story landing-section"
      id="how-it-works"
      aria-labelledby="story-title"
    >
      <div className="section-intro">
        <div>
          <span className="section-kicker">
            <GitBranch size={14} /> Context that stays connected
          </span>
          <h2 id="story-title">
            Every decision has a story.
            <br />
            Keep the whole thread.
          </h2>
        </div>
        <p>
          Your team’s knowledge doesn’t live in one place.
          <br />
          Now, its context does.
        </p>
      </div>
      <div className="story-workbench">
        <div
          className="story-steps"
          role="group"
          aria-label="Explore how Minutes works"
        >
          {steps.map(({ title, description, icon: Icon }, i) => (
            <button
              key={title}
              aria-pressed={stage === i}
              onClick={() => select(i)}
            >
              <span className="story-step-icon">
                <Icon size={18} />
              </span>
              <span>
                <strong>{title}</strong>
                <span>{description}</span>
              </span>
              <ArrowUpRight size={15} />
            </button>
          ))}
          <div className="story-instruction">
            <MousePointer2 size={13} /> Click a step. Follow the connection.
          </div>
        </div>
        <div className="story-browser">
          <div className="story-browser-bar">
            <div className="browser-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </div>
            <span>Orbit / Company memory</span>
            <span className="example-badge">Illustrative example</span>
          </div>
          <div className={`story-map story-stage-${stage}`} ref={map}>
            <div className="map-topline">
              <span>
                <ScanLine size={13} /> UPI release
              </span>
              <span className="map-lens">Connected view</span>
            </div>
            <MemoryConnections
              container={map}
              sources={[first, second]}
              decision={decision}
              work={work}
              stage={stage}
            />
            <button
              ref={first}
              className={`story-node source-node ${detail === "source" ? "is-selected" : ""}`}
              onClick={() => {
                setDetail("source");
                setStage(0);
              }}
              aria-pressed={detail === "source"}
            >
              <span className="node-type">
                <MessageSquare size={13} /> Meeting
              </span>
              <strong>“Let’s target the 24th.”</strong>
              <span>Priya · Product kickoff</span>
              <span className="node-port" />
            </button>
            <button
              ref={second}
              className={`story-node update-node ${detail === "decision" ? "is-selected" : ""}`}
              onClick={() => {
                setDetail("decision");
                setStage(1);
              }}
              aria-pressed={detail === "decision"}
            >
              <span className="node-type">
                <Mail size={13} /> Follow-up
              </span>
              <strong>“Move it to the 26th.”</strong>
              <span>Sandbox access was delayed</span>
              <span className="node-port" />
            </button>
            <button
              ref={decision}
              className={`story-node decision-node ${detail === "work" ? "is-selected" : ""}`}
              onClick={() => {
                setDetail("work");
                setStage(2);
              }}
              aria-pressed={detail === "work"}
            >
              <span className="node-type">
                <GitBranch size={13} /> UPI release date
              </span>
              <div className="story-date-change">
                {!past && (
                  <>
                    <s>Sep 24</s>
                    <ArrowRight size={16} />
                  </>
                )}
                <strong>{past ? "Sep 24" : "Sep 26"}</strong>
              </div>
              <span className={past ? "node-historical" : "node-current"}>
                <span />
                {past ? "Originally agreed" : "Current decision"}
              </span>
            </button>
            <div className="story-work" ref={work}>
              <span className="mini-avatar">R</span>
              <span>Release handoff</span>
              <span className={past ? "work-aligned" : "work-review"}>
                {past ? <Check size={12} /> : <CircleDot size={12} />}
                {past ? "Aligned" : "Needs review"}
              </span>
            </div>
          </div>
          <div className="story-inspector" aria-live="polite">
            <span className="inspector-icon">
              {detail === "source" ? (
                <MessageSquare size={16} />
              ) : detail === "decision" ? (
                <History size={16} />
              ) : (
                <User size={16} />
              )}
            </span>
            <div>
              <strong>
                {detail === "source"
                  ? "The original context stays close."
                  : detail === "decision"
                    ? "A new date. The same thread."
                    : "Rahul owns the release handoff."}
              </strong>
              <p>
                {detail === "source"
                  ? "The speaker, source, and original commitment remain connected."
                  : detail === "decision"
                    ? past
                      ? "At this point, September 24 was the agreed date. Switch to Now to see the change."
                      : "Both dates are preserved, along with why the deadline changed."
                    : past
                      ? "At this point, the handoff matches the agreed date. Switch to Now to see the impact."
                      : "The handoff still references the original date and needs a review."}
              </p>
            </div>
          </div>
          <div className="story-timeline">
            <span>
              <History size={13} /> Travel through the decision
            </span>
            <div role="group" aria-label="Example decision history">
              <button aria-pressed={past} onClick={() => setPast(true)}>
                Originally
              </button>
              <ArrowRight size={12} />
              <button aria-pressed={!past} onClick={() => setPast(false)}>
                Now
              </button>
            </div>
          </div>
        </div>
      </div>
      <a className="story-next" href="#workspaces">
        Follow a real thread in your workspace <ArrowDown size={15} />
      </a>
    </section>
  );
}

export function MemoryPrinciples() {
  return (
    <section
      className="memory-principles landing-section"
      id="inside-minutes"
      aria-labelledby="principles-title"
    >
      <div className="section-intro">
        <div>
          <span className="section-kicker">
            Built for the questions between the lines
          </span>
          <h2 id="principles-title">
            Less searching.
            <br />
            More understanding.
          </h2>
        </div>
        <p>
          For the people doing the work.
          <br />
          And the agents working alongside them.
        </p>
      </div>
      <div className="principle-grid">
        <article className="principle principle-answer">
          <div className="principle-visual">
            <div className="mini-question">
              <span className="mini-avatar">Y</span>Why did the deadline move?
            </div>
            <div className="mini-answer">
              <span className="answer-spark" aria-hidden="true">
                ✳
              </span>
              <p>
                The sandbox credentials arrived late. The team moved the release
                by two days.
                <span>
                  <FileText size={11} /> Original source attached
                </span>
              </p>
            </div>
          </div>
          <h3>Answers with their receipts.</h3>
          <p>
            Ask in your own words. Follow an answer back to the exact
            conversation it came from.
          </p>
        </article>
        <article className="principle principle-time">
          <div className="principle-visual">
            <div className="mini-history">
              <span>What we knew then</span>
              <i />
              <span>What we know now</span>
            </div>
            <div className="history-cells" aria-hidden="true">
              {Array.from({ length: 24 }, (_, i) => (
                <i key={i} style={{ opacity: 0.2 + (i % 6) * 0.14 }} />
              ))}
            </div>
            <span className="history-note">
              <History size={12} /> History stays intact
            </span>
          </div>
          <h3>A memory that moves with you.</h3>
          <p>
            Decisions evolve. Revisit an earlier moment without losing sight of
            what’s true today.
          </p>
        </article>
        <article className="principle principle-agents">
          <div className="principle-visual">
            <div className="agent-line">
              <span className="agent-symbol">
                <ScanLine size={17} />
              </span>
              <span>Find the change</span>
              <Check size={13} />
            </div>
            <div className="agent-connector" />
            <div className="agent-line">
              <span className="agent-symbol">
                <GitBranch size={17} />
              </span>
              <span>Pass the context</span>
              <ArrowRight size={13} />
            </div>
            <div className="agent-connector" />
            <div className="agent-line">
              <span className="agent-symbol">
                <FileText size={17} />
              </span>
              <span>Prepare the next step</span>
            </div>
          </div>
          <h3>Shared context. Clear handoffs.</h3>
          <p>
            Agents carry the evidence forward. People stay in control of the
            next action.
          </p>
        </article>
      </div>
    </section>
  );
}
