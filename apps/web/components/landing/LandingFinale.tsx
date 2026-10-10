"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Mail, Mic } from "lucide-react";
import { MemorySculpture } from "@/components/memory/MemorySculpture";
import { AskMinutesButton } from "./LandingAssistant";
import { MemoryMark } from "./MemoryMark";

const stages = [
  { name: "Gather", title: "Bring the pieces in.", description: "A meeting. A follow-up email. A decision. Each holds a part of the story." },
  { name: "Connect", title: "See how it fits together.", description: "Link the conversation to the decision, the people involved, and the work it changes." },
  { name: "Remember", title: "Keep the whole picture.", description: "One shared memory, with every source and earlier decision ready when you need them." },
];

export function LandingFinale() {
  const journeyRef = useRef<HTMLDivElement>(null);
  const storyRef = useRef<HTMLElement>(null);
  const [mode, setMode] = useState(0);

  useEffect(() => {
    const journey = journeyRef.current;
    const story = storyRef.current;
    if (!journey || !story) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => {
      if (motion.matches) { setMode(2); return; }
      const rect = journey.getBoundingClientRect();
      const distance = journey.offsetHeight - story.offsetHeight;
      const progress = distance > 0 ? -rect.top / distance : (innerHeight * .8 - rect.top) / rect.height;
      setMode(Math.min(2, Math.max(0, Math.floor(progress * 3))));
    };
    const observer = new ResizeObserver(update);
    observer.observe(journey);
    observer.observe(story);
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    motion.addEventListener("change", update);
    update();
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      motion.removeEventListener("change", update);
    };
  }, []);

  return <div className="m-finale" id="shared-memory">
    <div className="m-finale-journey" ref={journeyRef} data-memory-mode={["gather", "connect", "remember"][mode]}>
    <section className="m-finale-story" ref={storyRef} aria-labelledby="finale-title">
      <div className="m-finale-copy">
        <div className="m-finale-origin" aria-hidden="true"><Mic size={16} /><span /><Mail size={16} /><svg viewBox="0 0 65 24" fill="none"><path d="M0 12H20C31 12 31 4 40 4S47 12 58 12h7" /></svg><MemoryMark /></div>
        <h2 id="finale-title">More than meetings.<br /><span>A shared memory.</span></h2>
        <div className="m-finale-stage-copy" key={mode}>
          <h3>{stages[mode].title}</h3>
          <p>{stages[mode].description}</p>
        </div>
      </div>
      <MemorySculpture selected={mode} />
    </section>
    </div>
    <footer className="m-finale-footer">
      <div className="m-finale-links">
        <div className="m-finale-signoff"><MemoryMark /><p>A little less catching up.<br /><span>A lot more moving forward.</span></p></div>
        <nav aria-label="Footer">
          <div><span>Explore</span><a href="#company-memory">How it works</a><a href="#inside-minutes">Why Minutes</a></div>
          <div><span>Your next step</span><AskMinutesButton /><Link href="/workspaces">Workspaces <ArrowUpRight size={13} aria-hidden="true" /></Link></div>
        </nav>
      </div>
      <div className="m-finale-wordmark" aria-label="Minutes">minutes<span>.</span></div>
      <div className="m-finale-colophon"><span>Made with context. Built by Team Vulcan.</span></div>
    </footer>
  </div>;
}
