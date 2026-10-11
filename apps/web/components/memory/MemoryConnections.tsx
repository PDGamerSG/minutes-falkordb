"use client";

import { useEffect, useState, type RefObject } from "react";

type ElementRef = RefObject<HTMLElement | null>;

/** Measured SVG connections, inspired by 21st's Animated Beam pattern.
 * https://21st.dev/@dillionverma/components/animated-beam
 * Uses native SVG/CSS, with no additional animation dependency.
 */
export function MemoryConnections({
  container,
  sources,
  decision,
  work,
  stage,
}: {
  container: ElementRef;
  sources: [ElementRef, ElementRef];
  decision: ElementRef;
  work: ElementRef;
  stage: number;
}) {
  const [layout, setLayout] = useState({
    width: 1,
    height: 1,
    paths: ["", "", ""],
  });
  const [first, second] = sources;
  useEffect(() => {
    const root = container.current;
    const elements = [
      first.current,
      second.current,
      decision.current,
      work.current,
    ];
    if (!root || elements.some((el) => !el)) return;
    const measure = () => {
      const rect = root.getBoundingClientRect();
      const boxes = elements.map((el) => el!.getBoundingClientRect());
      const connect = (a: DOMRect, b: DOMRect) => {
        const x1 = a.x + a.width / 2 - rect.x,
          y1 = a.bottom - rect.y;
        const x2 = b.x + b.width / 2 - rect.x,
          y2 = b.top - rect.y;
        const curve = Math.max(12, (y2 - y1) * 0.65);
        return `M ${x1} ${y1} C ${x1} ${y1 + curve}, ${x2} ${y2 - curve}, ${x2} ${y2}`;
      };
      setLayout({
        width: rect.width,
        height: rect.height,
        paths: [
          connect(boxes[0], boxes[2]),
          connect(boxes[1], boxes[2]),
          connect(boxes[2], boxes[3]),
        ],
      });
    };
    const observer = new ResizeObserver(measure);
    [root, ...elements].forEach((el) => observer.observe(el!));
    measure();
    return () => observer.disconnect();
  }, [container, first, second, decision, work]);
  return (
    <svg
      className="story-connections"
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      aria-hidden="true"
    >
      <path d={layout.paths.join(" ")} />
      <path key={stage} className="connection-signal" d={layout.paths[stage]} />
    </svg>
  );
}
