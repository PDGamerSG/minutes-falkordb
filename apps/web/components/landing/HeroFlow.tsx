"use client";

import { useEffect, useRef } from "react";

const paths = [
  "M-100 52C96 25 229 88 192 180S12 272 32 366s179 77 230 153",
  "M-98 65C88 39 211 94 181 178S-2 279 18 373s182 84 238 157",
  "M-98 78C80 54 195 101 170 176S-17 286 4 380s185 91 246 161",
  "M-97 91C72 69 179 108 159 174S-32 293-10 387s188 98 254 165",
];

export function HeroFlow() {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let visible = false;
    const sync = () => { element.dataset.running = String(visible && !document.hidden); };
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; sync(); });
    observer.observe(element);
    document.addEventListener("visibilitychange", sync);
    return () => { observer.disconnect(); document.removeEventListener("visibilitychange", sync); };
  }, []);

  return <div className="m-hero-flow" ref={host} aria-hidden="true">
    {["left", "right"].map(side => <svg key={side} className={`m-thread-art m-thread-art-${side}`} viewBox="0 0 300 560" fill="none">
      {paths.map((d, index) => <path className="m-thread-outline" d={d} key={index} />)}
      <path className="m-thread-signal" d={paths[0]} />
      <path className="m-thread-signal m-thread-signal-soft" d={paths[3]} />
      <g className="m-thread-junction" transform="translate(178 146)"><circle r="19" /><circle r="4" /><path d="M-8 0H8M0-8V8" /></g>
      <g className="m-thread-blocks" transform="translate(30 381) rotate(-12)"><rect x="-14" y="-14" width="11" height="11" rx="2" /><rect x="3" y="-14" width="11" height="11" rx="2" /><rect x="-14" y="3" width="11" height="11" rx="2" /><rect x="3" y="3" width="11" height="11" rx="2" /></g>
    </svg>)}
  </div>;
}
