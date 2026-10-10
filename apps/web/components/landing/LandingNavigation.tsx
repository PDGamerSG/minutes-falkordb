import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { MemoryMark } from "./MemoryMark";

export function LandingNavigation() {
  return <header className="mn-header">
    <div className="mn-bar">
      <Link className="mn-brand" href="/" aria-label="Minutes home"><MemoryMark /><span>minutes<span>.</span></span></Link>
      <div className="mn-signature" aria-hidden="true"><span>Keep the thread.</span><svg viewBox="0 0 126 28" fill="none"><path className="mn-thread-base" d="M1 14H20C36 14 33 3 47 3S56 25 70 25s13-11 28-11h27" /><path className="mn-thread-motion" d="M1 14H20C36 14 33 3 47 3S56 25 70 25s13-11 28-11h27" /><circle cx="2" cy="14" r="2" /><circle cx="124" cy="14" r="2" /></svg></div>
      <Link href="/workspaces" className="mn-open"><span>Open workspace</span><ArrowUpRight size={16} aria-hidden="true" /></Link>
    </div>
  </header>;
}
