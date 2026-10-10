"use client";

import dynamic from "next/dynamic";
import { useSyncExternalStore } from "react";

const Scene = dynamic(() => import("./MemoryScene"), { ssr: false, loading: () => <div className="memory-loading"><span className="memory-loading-mark" /><span>Connecting the dots…</span></div> });
function subscribe(onChange: () => void) {
  const media = matchMedia("(prefers-reduced-motion: reduce)");
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
const snapshot = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

export function MemorySculpture({ selected = 1 }: { selected?: number } = {}) {
  const reduced = useSyncExternalStore(subscribe, snapshot, () => true);
  return <div className="memory-sculpture">
    <p className="sr-only">An illustration of scattered information becoming a connected company memory as you scroll.</p>
    <Scene selected={selected} paused={reduced} reducedMotion={reduced} />
  </div>;
}
