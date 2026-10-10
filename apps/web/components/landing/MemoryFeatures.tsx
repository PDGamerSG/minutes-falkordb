"use client";

import { useState } from "react";
import { ArrowRight, ArrowUpRight, Check, ChevronRight, Clock3, FileText, GitBranch, Mail, Mic, Network, Search, Sparkles } from "lucide-react";
import { MemoryMark } from "./MemoryMark";

const views = [
  { title: "Conversations", icon: Mic, heading: "The details worth keeping.", description: "A meeting ends. An email arrives. Keep the important words connected to the people who said them.", benefit: "Original sources, always a click away." },
  { title: "Decisions", icon: GitBranch, heading: "A new plan. The full picture.", description: "Know where the team landed, what changed along the way, and the conversation behind the decision.", benefit: "The latest answer, with its history intact." },
  { title: "Follow-through", icon: FileText, heading: "Know what needs to move.", description: "When a decision changes, see the work that still depends on the old plan. Give its owner the context to act.", benefit: "Connected work. Clear ownership." },
];

export function MemoryFeatures({ workspaceHref }: { workspaceHref: string }) {
  const [view, setView] = useState(1);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [history, setHistory] = useState(1);
  const [draft, setDraft] = useState(false);
  const current = views[view];
  return (
    <section className="mf-section" id="inside-minutes" aria-labelledby="memory-features-title">
      <header className="mf-section-heading">
        <div><span className="mf-eyebrow"><Network size={14} /> Built around the way teams work</span>
        <h2 id="memory-features-title">Know what changed.<br /><span>See what comes next.</span></h2></div>
        <p>Conversations become decisions. Decisions move the work forward. Keep the whole story connected.</p>
      </header>
      <div className="mf-showcase" id="how-it-works">
        <div className="mf-view-tabs" role="group" aria-label="Explore company memory">
          {views.map(({ title, icon: Icon }, index) => <button type="button" key={title} aria-pressed={view === index} onClick={() => { setView(index); setSourceOpen(false); }}><Icon size={17} />{title}</button>)}
        </div>
        <div className="mf-showcase-body">
          <div className="mf-showcase-copy" key={`copy-${view}`}>
            <span className="mf-index">0{view + 1} / COMPANY MEMORY</span>
            <h3>{current.heading}</h3><p>{current.description}</p>
            <a className="mf-text-link" href={workspaceHref}>Explore your workspace <ArrowUpRight size={16} /></a>
            <span className="mf-benefit"><Check size={15} />{current.benefit}</span>
          </div>
          <div className="mf-stage" key={view}>
            <div className="mf-stage-top"><span><MemoryMark /> Your company memory</span><span>Illustrative example</span></div>
            {view === 0 ? <div className="mf-source-example">
              <div className="mf-source-search"><Search size={16} /> Conversations, with context.</div>
              <div className="mf-source-entry"><span className="mf-source-icon"><Mic size={19} /></span><div><strong>Product kickoff</strong><span>Meeting · Priya, Rahul</span></div><span className="mf-source-state"><Check size={12} /> Connected</span></div>
              <blockquote>“Let’s target September 24 for the UPI flow. We need sandbox access before testing.”<cite>Priya · Product team</cite></blockquote>
              <div className="mf-source-entry"><span className="mf-source-icon"><Mail size={19} /></span><div><strong>Payments follow-up</strong><span>Email · Payments team</span></div><ChevronRight size={17} /></div>
              <div className="mf-extraction"><span><GitBranch size={13} /> UPI launch</span><span>Priya · Owner</span><span>Sep 24 → 28</span></div>
            </div> : view === 1 ? <div className="mf-decision-example">
              <div className="mf-decision-top"><span><GitBranch size={16} /> UPI release</span><span className="mf-status"><span /> Current decision</span></div>
              <span className="mf-field-label">Launch date</span><strong className="mf-current-date">September 28<span>.</span></strong>
              <div className="mf-date-change"><s>September 24</s><ArrowRight size={15} /><span>September 28</span><span className="mf-history-label"><Clock3 size={13} /> History preserved</span></div>
              <div className="mf-reason"><span><Mail size={15} /> The reason behind the change</span><p>Sandbox access was delayed.<br />The team needed a new testing window.</p></div>
              <button className="mf-source-link" type="button" aria-expanded={sourceOpen} onClick={() => setSourceOpen(!sourceOpen)}><span><FileText size={14} /> Payments follow-up</span><span>{sourceOpen ? "Close source" : "View source"}<ArrowUpRight size={13} /></span></button>
              {sourceOpen && <blockquote className="mf-source-quote">“Sandbox access is delayed. Move the launch to September 28.”<cite>Illustrative email · Payments team</cite></blockquote>}
            </div> : <div className="mf-work-example">
              <div className="mf-work-title"><FileText size={20} /><h4>Release handoff</h4><span className="mf-review-status">Needs review</span></div>
              <p>The launch moved. This plan still points to September 24.</p>
              <div className="mf-dependency"><span>UPI release date</span><ArrowRight size={15} /><span>Release handoff</span></div>
              <div className="mf-owner"><span className="mf-avatar">R</span><span><strong>Rahul</strong><small>Work owner</small></span><Check size={16} /></div>
              <div className="mf-work-context"><GitBranch size={15} /><span>Current commitment: <strong>September 28</strong><small>Original sources and change history included.</small></span></div>
            </div>}
          </div>
        </div>
      </div>
      <div className="mf-detail-grid">
        <article className="mf-detail mf-history-detail">
          <span className="mf-detail-icon"><Clock3 size={19} /></span><h3>Plans change.<br />The why doesn’t disappear.</h3><p>Revisit the original commitment or the current decision. Every version keeps its source.</p>
          <div className="mf-mini-timeline" role="group" aria-label="Decision history"><button type="button" aria-pressed={history === 0} onClick={() => setHistory(0)}><span>Original</span><strong>Sep 24</strong><span className="mf-timeline-dot" /></button><span className="mf-timeline-line" /><button type="button" aria-pressed={history === 1} onClick={() => setHistory(1)}><span>Current</span><strong>Sep 28</strong><span className="mf-timeline-dot" /></button></div>
          <div className="mf-history-note" aria-live="polite"><FileText size={15} /><span><strong>{history === 0 ? "Product kickoff" : "Payments follow-up"}</strong>{history === 0 ? "The team sets the first launch target." : "Sandbox access is delayed. The launch moves."}</span><span>0{history + 1}</span></div>
        </article>
        <article className="mf-detail mf-action-detail">
          <span className="mf-detail-icon"><Sparkles size={19} /></span><h3>A useful next step.<br />With a person in control.</h3><p>Turn connected context into a follow-up draft. The owner reviews it before anything moves.</p>
          <div className="mf-draft-card"><div><span className="mf-avatar">R</span><span><strong>For Rahul</strong><small>Release handoff</small></span><span className="mf-draft-label">Draft · Not sent</span></div><p>{draft ? "Review the release handoff against the new September 28 commitment. The payments follow-up explains the sandbox delay." : "The handoff still uses the original launch date. Prepare a follow-up with the latest decision and its source."}</p><button type="button" onClick={() => setDraft(!draft)} aria-expanded={draft}>{draft ? <><Check size={14} /> Draft ready for review</> : <><Sparkles size={14} /> Preview a follow-up</>}<ArrowRight size={14} /></button></div>
        </article>
      </div>
    </section>
  );
}
