"use client";

import { useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCheck,
  ChevronRight,
  CircleDot,
  Clock3,
  FileText,
  GitBranch,
  Layers,
  Mail,
  MessageSquare,
  Mic,
  Network,
  Search,
  ShieldCheck,
  Sparkles,
  SquareKanban,
} from "lucide-react";
import { MemoryMark } from "./CompanyMap";

const steps = [
  {
    title: "Capture the conversation",
    text: "Keep the words, the people, and the moment.",
    icon: Mic,
  },
  {
    title: "Connect the decision",
    text: "Know what changed. Understand the reason.",
    icon: GitBranch,
  },
  {
    title: "Move work forward",
    text: "Find the owner and prepare the next step.",
    icon: CircleDot,
  },
];

export function ProductTour({ workspaceHref }: { workspaceHref: string }) {
  const [stage, setStage] = useState(1);
  const [evidence, setEvidence] = useState(false);
  return (
    <section className="m-product-section" id="how-it-works">
      <div className="m-container">
        <div className="m-section-heading">
          <div>
            <span className="m-eyebrow">
              <span /> The context behind the work
            </span>
            <h2>
              It starts with a conversation.
              <br />
              It doesn’t end there.
            </h2>
          </div>
          <p>
            A meeting note is just the beginning. Minutes follows the thread
            from what was said to what needs to happen next.
          </p>
        </div>
        <div
          className="m-tour-tabs"
          role="group"
          aria-label="Product walkthrough"
        >
          {steps.map(({ title, text, icon: Icon }, i) => (
            <button
              key={title}
              onClick={() => {
                setStage(i);
                setEvidence(false);
              }}
              aria-pressed={stage === i}
            >
              <span className="m-step-number">0{i + 1}</span>
              <div>
                <strong>{title}</strong>
                <span>{text}</span>
              </div>
              <Icon size={19} />
            </button>
          ))}
        </div>
        <div className="m-product-window">
          <div className="m-window-bar">
            <span className="m-window-dots">
              <i />
              <i />
              <i />
            </span>
            <span>Orbit workspace</span>
            <span>Interactive walkthrough</span>
          </div>
          <div className="m-product-body">
            <aside className="m-demo-sidebar">
              <div className="m-demo-brand">
                <MemoryMark /> minutes
              </div>
              <span className="m-demo-workspace">
                O <strong>Orbit</strong>
                <ChevronRight size={12} />
              </span>
              <span>
                <Search size={14} /> Search company memory
              </span>
              <div className={stage === 1 ? "active" : ""}>
                <Network size={15} /> Overview
              </div>
              <div className={stage === 0 ? "active" : ""}>
                <Layers size={15} /> Sources
              </div>
              <div>
                <MessageSquare size={15} /> Ask Minutes
              </div>
              <div className={stage === 2 ? "active" : ""}>
                <SquareKanban size={15} /> Agent board
              </div>
              <div>
                <Clock3 size={15} /> Timeline
              </div>
              <p>
                <span /> Connected knowledge
              </p>
            </aside>
            <div className="m-demo-content" key={stage} aria-live="polite">
              <div className="m-demo-breadcrumb">
                Orbit <ChevronRight size={11} />{" "}
                {stage === 0
                  ? "Sources"
                  : stage === 1
                    ? "Decision history"
                    : "Connected work"}
                <span>Illustrative example</span>
              </div>
              {stage === 0 ? (
                <>
                  <div className="m-demo-title">
                    <span className="m-demo-icon">
                      <Mic size={21} />
                    </span>
                    <div>
                      <small>Meeting transcript</small>
                      <h3>The plan, in their own words.</h3>
                    </div>
                  </div>
                  <div className="m-transcript">
                    <div>
                      <span className="m-avatar peach">P</span>
                      <p>
                        <strong>
                          Priya <time>10:24 AM</time>
                        </strong>
                        Let’s target the 24th for the UPI flow. We need sandbox
                        access before we can finish testing.
                      </p>
                    </div>
                    <div>
                      <span className="m-avatar blue">R</span>
                      <p>
                        <strong>
                          Rahul <time>10:25 AM</time>
                        </strong>
                        I’ll update the release handoff once the date is
                        confirmed.
                      </p>
                    </div>
                    <div className="m-transcript-highlight">
                      <span className="m-avatar green">S</span>
                      <p>
                        <strong>
                          Sana <time>10:26 AM</time>
                        </strong>
                        Keep the accessibility review linked to the navigation
                        decision too.
                      </p>
                    </div>
                  </div>
                  <div className="m-extracted">
                    <Sparkles size={16} />
                    <span>Context connected</span>
                    <span>People</span>
                    <span>Commitments</span>
                    <span>Decisions</span>
                  </div>
                </>
              ) : stage === 1 ? (
                <>
                  <div className="m-demo-title">
                    <span className="m-demo-icon">
                      <GitBranch size={21} />
                    </span>
                    <div>
                      <small>Release planning</small>
                      <h3>New date. Full history.</h3>
                    </div>
                    <span className="m-status green">
                      <span /> Current
                    </span>
                  </div>
                  <div className="m-date-flow">
                    <div>
                      <small>Originally agreed</small>
                      <strong>Sep 24</strong>
                      <span>Product kickoff</span>
                    </div>
                    <ArrowRight size={22} />
                    <div>
                      <small>Revised</small>
                      <strong>Sep 25</strong>
                      <span>Payments follow-up</span>
                    </div>
                    <ArrowRight size={22} />
                    <div className="current">
                      <small>Current commitment</small>
                      <strong>Sep 28</strong>
                      <span>Latest update</span>
                    </div>
                  </div>
                  <div className="m-demo-reason">
                    <span>
                      <Mail size={16} /> Why it changed
                    </span>
                    <p>
                      Sandbox access was delayed. The deadline moved, and the
                      previous dates remain part of the record.
                    </p>
                    <button
                      onClick={() => setEvidence(!evidence)}
                      aria-expanded={evidence}
                    >
                      {evidence
                        ? "Hide source context"
                        : "Read the source context"}
                      <ArrowUpRight size={13} />
                    </button>
                    {evidence && (
                      <blockquote>
                        “Move the UPI flow to the 28th. Keep the release handoff
                        in sync.”<cite>Illustrative follow-up · Priya</cite>
                      </blockquote>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div className="m-demo-title">
                    <span className="m-demo-icon">
                      <CircleDot size={21} />
                    </span>
                    <div>
                      <small>Dependency review</small>
                      <h3>The next move is clear.</h3>
                    </div>
                  </div>
                  <div className="m-work-preview">
                    <div>
                      <FileText size={17} />
                      <strong>Release handoff</strong>
                      <span className="m-status amber">Needs review</span>
                    </div>
                    <p>
                      The release plan still depends on the September 24
                      decision.
                    </p>
                    <span>
                      <span className="m-avatar blue">R</span> Rahul{" "}
                      <small>Work owner</small>
                    </span>
                  </div>
                  <div className="m-draft-preview">
                    <span>
                      <Sparkles size={15} /> Suggested follow-up
                    </span>
                    <p>
                      Review the release handoff against the new September 28
                      commitment. Include the original source when updating the
                      plan.
                    </p>
                    <div>
                      <ShieldCheck size={13} /> A draft for a person to review.
                      Nothing sent.
                    </div>
                  </div>
                </>
              )}
            </div>
            <aside className="m-demo-inspector">
              <span>Connected context</span>
              <div>
                <span className="m-inspector-symbol">
                  <GitBranch size={16} />
                </span>
                <small>Decision</small>
                <strong>UPI release date</strong>
                <p>September 28</p>
              </div>
              <div>
                <span className="m-inspector-symbol">
                  <FileText size={16} />
                </span>
                <small>Related work</small>
                <strong>Release handoff</strong>
                <span className="m-inspector-review">
                  <CircleDot size={11} /> Review required
                </span>
              </div>
              <div>
                <small>People in the loop</small>
                <span className="m-person-row">
                  <span className="m-avatar peach">P</span> Priya{" "}
                  <small>Decision owner</small>
                </span>
                <span className="m-person-row">
                  <span className="m-avatar blue">R</span> Rahul{" "}
                  <small>Work owner</small>
                </span>
              </div>
              <div className="m-provenance">
                <CheckCheck size={15} /> Every fact has a source
              </div>
            </aside>
          </div>
          <div className="m-window-footer">
            <span>
              <ShieldCheck size={13} /> Original context, preserved
            </span>
            <a href={workspaceHref}>
              Explore your workspace <ArrowUpRight size={13} />
            </a>
          </div>
        </div>
        <div className="m-product-notes">
          <p>
            <Check size={14} /> Source-linked decisions
          </p>
          <p>
            <Check size={14} /> A history that stays intact
          </p>
          <p>
            <Check size={14} /> Work with an accountable owner
          </p>
        </div>
      </div>
    </section>
  );
}
