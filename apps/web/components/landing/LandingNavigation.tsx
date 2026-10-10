import Link from "next/link";
import type { CSSProperties } from "react";
import { ArrowUpRight } from "lucide-react";
import { MemoryMark } from "./MemoryMark";

export function LandingNavigation() {
  return <header className="mn-header">
    <div className="mn-bar">
      <Link className="mn-brand" href="/" aria-label="Minutes home"><MemoryMark /><span>minutes<span>.</span></span></Link>
      <div className="mn-keepsake" aria-hidden="true">
        <svg className="mn-keepsake-art" viewBox="-9 -10 84 64" fill="none">
          <ellipse className="mn-keepsake-shadow" cx="33" cy="39" rx="24" ry="5" />
          {Array.from({ length: 9 }, (_, index) => {
            const row = Math.floor(index / 3), column = index % 3;
            return <g key={index} transform={`translate(${33 + (column - row) * 10} ${7 + (column + row) * 5})`}>
              <g className="mn-memory-piece" style={{ "--piece-x": `${(column - 1) * 9}px`, "--piece-y": `${(row - 1) * 7 - 3}px`, animationDelay: `${index * -0.13}s` } as CSSProperties}>
                <path className="mn-piece-left" d="M-6-3 0 0V8L-6 5Z" />
                <path className="mn-piece-right" d="M0 0 6-3V5L0 8Z" />
                <path className="mn-piece-top" d="m0-6 6 3-6 3-6-3Z" />
              </g>
            </g>;
          })}
        </svg>
        <span>Conversations,<br /><strong>connected.</strong></span>
      </div>
      <Link href="/workspaces" className="mn-open"><span>Open workspace</span><ArrowUpRight size={16} aria-hidden="true" /></Link>
    </div>
  </header>;
}
