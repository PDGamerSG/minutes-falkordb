"use client";
import { useEffect, useRef } from "react";
import { ArrowRight, ArrowUpRight, Network, Mic, Mail, GitBranch, Users, Sparkles, FileText } from "lucide-react";
import { CompanyWalkthrough } from "./CompanyWalkthrough";
import { MemoryFeatures } from "./MemoryFeatures";
import { LandingFinale } from "./LandingFinale";
import { HeroFlow } from "./HeroFlow";
import { ContextQuestions } from "./ContextQuestions";

export function MinutesLanding() {
  const page = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = page.current;
    if (!root || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        entry.target.setAttribute("data-revealed", "true");
        observer.unobserve(entry.target);
      }
    }, { threshold: .15 });
    root.querySelectorAll(".m-walkthrough-heading,.m-source-strip,.ms-heading,.mq-intro,.mq-question,.m-finale-links,.m-finale-wordmark").forEach(element => {
      element.setAttribute("data-revealed", "false");
      observer.observe(element);
    });
    return () => observer.disconnect();
  }, []);
  return (
    <div className="minutes-home" ref={page}>
      <section className="m-hero">
        <div className="m-hero-copy">
          <HeroFlow />
          <a className="m-announcement" href="#company-memory">
            <span>
              <Network size={12} />
            </span>{" "}
            A shared memory for your company <ArrowRight size={13} />
          </a>
          <h1>
            Your company,
            <br />
            <span>with a memory.</span>
          </h1>
          <p>
            Minutes connects your meetings, emails, and decisions.
            <br className="m-desktop-break" /> Know what changed, why it changed, and what comes next.
          </p>
          <div className="m-hero-actions">
            <a className="m-button" href="/workspaces">
              Open Minutes <ArrowUpRight size={16} />
            </a>
            <a className="m-button m-button-secondary" href="#company-memory">
              See the story <ArrowRight size={16} />
            </a>
          </div>
        </div>
        <div className="m-hero-map m-container">
          <CompanyWalkthrough />
        </div>
        <div className="m-source-strip m-container">
          <span>
            Your company’s context,
            <br />
            <strong>in one connected place.</strong>
          </span>
          <div>
            <span>
              <Mic size={19} /> Meetings
            </span>
            <span>
              <Mail size={19} /> Emails
            </span>
            <span>
              <GitBranch size={19} /> Decisions
            </span>
            <span>
              <Users size={19} /> People
            </span>
            <span>
              <FileText size={19} /> Work
            </span>
            <span>
              <Sparkles size={19} /> Agents
            </span>
          </div>
        </div>
      </section>
      <MemoryFeatures />
      <ContextQuestions />
      <LandingFinale />
    </div>
  );
}
