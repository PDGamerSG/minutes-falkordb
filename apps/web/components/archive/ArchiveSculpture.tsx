"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useState, useSyncExternalStore } from "react";
import { ArrowUpRight, Pause, Play } from "lucide-react";

const Scene = dynamic(() => import("./ArchiveScene"), { ssr: false, loading: () => <div className="archive-loading" role="status">Loading sculpture…</div> });
const layers = [
  { label: "Sources", route: "sources" },
  { label: "Decisions", route: "timeline" },
  { label: "Work", route: "board" },
];

function subscribeMotion(onChange: () => void) {
  const media = window.matchMedia("(prefers-reduced-motion: reduce)");
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
const reducedMotionSnapshot = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function ArchiveSculpture({ team, compact = false }: { team?: string; compact?: boolean }) {
  const [selected, setSelected] = useState(1);
  const prefersReduced = useSyncExternalStore(subscribeMotion, reducedMotionSnapshot, () => true);
  const [pauseChoice, setPauseChoice] = useState<boolean | null>(null);
  const paused = pauseChoice ?? prefersReduced;
  return <div className={`archive-sculpture ${compact ? "archive-compact" : ""}`}>
    <p className="sr-only">An interactive sculpture illustrating sources, decisions, and work sharing one memory. This is not a map of database records. Drag with a mouse to rotate, or select a layer below.</p>
    <Scene selected={selected} paused={paused} onSelect={setSelected} />
    <div className="sculpture-footer">
      <div className="archive-layer-controls" aria-label="Explore an archive layer">
        {layers.map((layer, i) => <button key={layer.label} aria-pressed={i === selected} onClick={() => setSelected(i)}><span className="layer-dot" />{layer.label}</button>)}
      </div>
      <button className="scene-pause" onClick={() => setPauseChoice(!paused)} aria-label={paused ? "Play sculpture animation" : "Pause sculpture animation"}>{paused ? <Play size={14} /> : <Pause size={14} />}</button>
    </div>
    <Link className="archive-layer-destination" href={team ? `/t/${encodeURIComponent(team)}/${layers[selected].route}` : "#workspaces"}>{team ? `Explore ${layers[selected].label.toLowerCase()}` : "Choose a workspace"}<ArrowUpRight size={14} /></Link>
  </div>;
}
