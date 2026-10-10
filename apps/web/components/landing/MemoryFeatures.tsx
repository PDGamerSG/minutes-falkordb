"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, Mail } from "lucide-react";

export function MemoryFeatures() {
  const story = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState(0);
  const [draftOpen, setDraftOpen] = useState(false);
  const inspecting = useRef(false);
  useEffect(() => { inspecting.current = draftOpen; }, [draftOpen]);

  useEffect(() => {
    const element = story.current;
    if (!element) return;
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    let visible = false;
    let elapsed = 0;
    let last = 0;
    let frame = 0;
    let currentPhase = 0;
    const active = () => visible && !document.hidden && !motion.matches;
    const showPhase = (next: number) => {
      if (next !== currentPhase) { currentPhase = next; setPhase(next); }
    };
    const tick = () => {
      frame = 0;
      if (!active()) return;
      const now = performance.now();
      // Keep the complete scene in place while someone inspects its sources.
      if (!inspecting.current && !element.contains(document.activeElement)) {
        elapsed += last ? now - last : 0;
        if (elapsed >= 22000) elapsed = 0;
        showPhase(elapsed >= 10500 ? 3 : elapsed >= 6500 ? 2 : elapsed >= 3000 ? 1 : 0);
      }
      last = now;
      frame = window.setTimeout(tick, 100);
    };
    const wake = () => {
      element.dataset.running = String(active());
      if (motion.matches) showPhase(3);
      if (!active()) { clearTimeout(frame); frame = 0; last = 0; return; }
      if (!frame) { last = 0; frame = window.setTimeout(tick, 0); }
    };
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting && entry.intersectionRatio >= .2;
      wake();
    }, { threshold: [0, .2] });
    observer.observe(element);
    document.addEventListener("visibilitychange", wake);
    motion.addEventListener("change", wake);
    wake();
    return () => {
      clearTimeout(frame);
      observer.disconnect();
      document.removeEventListener("visibilitychange", wake);
      motion.removeEventListener("change", wake);
    };
  }, []);

  const changed = phase >= 2;
  const ready = phase >= 3;

  return <section className="ms-section" id="inside-minutes" aria-labelledby="memory-features-title">
    <header className="ms-heading">
      <h2 id="memory-features-title">Know what changed.</h2>
      <p>A new plan. The reason. Your next step.</p>
    </header>

    <div className="ms-story" id="how-it-works" ref={story} data-phase={phase}>
      <article className="ms-message">
        <div className="ms-message-meta"><Mail size={16} aria-hidden="true" /><span>Payments follow-up</span></div>
        <blockquote>“Sandbox access is delayed. Move the launch to <mark>September 28.</mark>”</blockquote>
        <span className="ms-message-author">From the payments team</span>
      </article>
      <div className="ms-bridge" aria-hidden="true"><svg viewBox="0 0 90 24" fill="none"><path d="M0 12H88m-7-6 7 6-7 6" /><path className="ms-bridge-signal" d="M0 12H88" /></svg></div>
      <div className="ms-decision">
        <h3>UPI launch <span>· September</span></h3>
        <div className="ms-date" aria-label={changed ? "Launch moved from September 24 to September 28" : "Launch planned for September 24"}>
          <span className="ms-old-date" aria-hidden="true">24</span><span className="ms-date-arrow" aria-hidden="true">→</span><span className="ms-new-date" aria-hidden="true">28</span>
        </div>
        <p className="ms-date-caption">{changed ? "Four more days for testing. Context kept." : "The original plan, from the product kickoff."}</p>
      </div>
      <div className="ms-handoff" aria-hidden={!ready} inert={!ready}>
        <span className="ms-handoff-person">R</span><p>Rahul’s handoff needs the new date.</p>
        <button type="button" onClick={()=>setDraftOpen(value=>!value)} aria-expanded={draftOpen} aria-controls="memory-draft">{draftOpen ? "Close draft" : "See the draft"}<ArrowUpRight size={15} aria-hidden="true" /></button>
      </div>
      {draftOpen && <div id="memory-draft" className="ms-draft"><ArrowRight size={15} aria-hidden="true" /><div><p>Rahul, the UPI launch moved to September 28 because sandbox access is delayed. Review the release handoff against the new date.</p><span>Draft preview. Nothing is sent.</span></div></div>}
    </div>
    <p className="ms-example-note">Illustrative example</p>
  </section>;
}
