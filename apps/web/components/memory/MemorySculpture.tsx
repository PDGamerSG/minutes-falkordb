"use client";

import dynamic from "next/dynamic";
import { useState, useSyncExternalStore } from "react";
import { Boxes, GitBranch, Grip, MousePointer2 } from "lucide-react";

const Scene = dynamic(() => import("./MemoryScene"), { ssr: false, loading: () => <div className="memory-loading"><span className="memory-loading-mark" /><span>Connecting the dots…</span></div> });
const modes = [{ name: "Gather", icon: Grip }, { name: "Connect", icon: GitBranch }, { name: "Remember", icon: Boxes }];
function subscribe(onChange: () => void) {
  const media = matchMedia("(prefers-reduced-motion: reduce)");
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
const snapshot = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

export function MemorySculpture({ selected: controlledSelection, onSelectedChange }: { selected?: number; onSelectedChange?: (index: number) => void } = {}) {
  const [localSelection, setLocalSelection] = useState(1);
  const selected = controlledSelection ?? localSelection;
  const setSelected = onSelectedChange ?? setLocalSelection;
  const reduced = useSyncExternalStore(subscribe, snapshot, () => true);
  return <div className="memory-sculpture">
    <p className="sr-only">An interactive illustration of scattered information becoming a connected company memory. Use the Gather, Connect, and Remember buttons to change its shape. Mouse users can also drag to rotate.</p>
    <div className="sculpture-orbit orbit-one" aria-hidden="true" /><div className="sculpture-orbit orbit-two" aria-hidden="true" />
    <Scene selected={selected} paused={reduced} reducedMotion={reduced} />
    <span className="sculpture-tag tag-source"><span className="tag-light" /> Every conversation</span>
    <span className="sculpture-tag tag-context"><GitBranch size={13} /> Connected context</span>
    <div className="memory-scene-controls"><div role="group" aria-label="Memory illustration mode">{modes.map(({ name, icon: Icon }, i) => <button key={name} aria-pressed={selected === i} onClick={() => setSelected(i)}><Icon size={14} />{name}</button>)}</div></div>
    <div className="memory-scene-caption"><MousePointer2 size={12} /><span>Made to explore. Drag to rotate.</span><span>Interactive illustration</span></div>
  </div>;
}
