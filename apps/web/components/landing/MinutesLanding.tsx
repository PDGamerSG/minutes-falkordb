"use client";
import { ArrowRight, ArrowUpRight, Network, Mic, Mail, GitBranch, Users, Sparkles, FileText } from "lucide-react";
import { CompanyWalkthrough } from "./CompanyWalkthrough";
import { MemoryFeatures } from "./MemoryFeatures";
import { LandingFinale } from "./LandingFinale";

export function MinutesLanding() {
  return (
    <div className="minutes-home">
      <section className="m-hero">
        <div className="m-hero-copy">
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
              Open your workspace <ArrowUpRight size={16} />
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
      <MemoryFeatures workspaceHref="/workspaces" />
      <LandingFinale />
    </div>
  );
}
