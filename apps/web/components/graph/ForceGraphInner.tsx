"use client";

// Client-only wrapper around react-force-graph-2d. Loaded through next/dynamic
// with ssr: false from GraphView. Owns the ref so it can zoom-to-fit.

import { useCallback, useEffect, useMemo, useRef } from "react";
import ForceGraph2D, { type ForceGraphMethods, type NodeObject, type LinkObject } from "react-force-graph-2d";

export type GNode = { id: string; label: string; name: string; props: Record<string, unknown> };
export type GLink = { source: string; target: string; type: string };

export type Palette = Record<string, string> & { link: string; text: string; default: string };

type Props = {
  nodes: GNode[];
  links: GLink[];
  width: number;
  height: number;
  palette: Palette;
  selectedId: string | null;
  highlightIds?: Set<string>;
  onSelect: (node: GNode | null) => void;
};

type N = NodeObject<GNode>;
type L = LinkObject<GNode, GLink>;

export default function ForceGraphInner({ nodes, links, width, height, palette, selectedId, highlightIds, onSelect }: Props) {
  const fg = useRef<ForceGraphMethods<N, L> | undefined>(undefined);

  // force-graph mutates node objects (x, y, vx...). Clone once per distinct input;
  // GraphView memoises `nodes`/`links` on the subgraph, so this is stable per graph.
  const data = useMemo<{ nodes: N[]; links: L[] }>(
    () => ({ nodes: nodes.map((n) => ({ ...n })), links: links.map((l) => ({ ...l })) }),
    [nodes, links],
  );

  useEffect(() => {
    const t = setTimeout(() => fg.current?.zoomToFit(400, 24), 600);
    return () => clearTimeout(t);
  }, [data, width, height]);

  const colorFor = useCallback((label: string) => palette[label] ?? palette.default, [palette]);

  const paintNode = useCallback(
    (node: N, ctx: CanvasRenderingContext2D, scale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const selected = node.id === selectedId;
      const dim = highlightIds && highlightIds.size > 0 && !highlightIds.has(String(node.id));
      const r = selected ? 6.5 : 4.5;
      ctx.globalAlpha = dim ? 0.35 : 1;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle = colorFor(node.label);
      ctx.fill();
      if (selected) {
        ctx.lineWidth = 1.5 / scale;
        ctx.strokeStyle = palette.text;
        ctx.stroke();
      }
      const fontSize = Math.max(10 / scale, 2.2);
      ctx.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = palette.text;
      const name = node.name.length > 26 ? `${node.name.slice(0, 25)}…` : node.name;
      ctx.fillText(name, x, y + r + 1.5);
      ctx.globalAlpha = 1;
    },
    [selectedId, highlightIds, colorFor, palette.text],
  );

  const paintArea = useCallback((node: N, color: string, ctx: CanvasRenderingContext2D) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x ?? 0, node.y ?? 0, 9, 0, 2 * Math.PI);
    ctx.fill();
  }, []);

  return (
    <ForceGraph2D
      ref={fg}
      width={width}
      height={height}
      graphData={data}
      backgroundColor="rgba(0,0,0,0)"
      nodeId="id"
      nodeLabel={(n: N) => `${n.label} · ${n.name}`}
      nodeCanvasObject={paintNode}
      nodeCanvasObjectMode={() => "replace"}
      nodePointerAreaPaint={paintArea}
      linkColor={() => palette.link}
      linkWidth={1}
      linkDirectionalArrowLength={3.5}
      linkDirectionalArrowRelPos={1}
      linkLabel={(l: L) => l.type}
      linkCurvature={0.08}
      cooldownTicks={90}
      d3VelocityDecay={0.35}
      enableNodeDrag
      onNodeClick={(n: N) => onSelect(n as GNode)}
      onBackgroundClick={() => onSelect(null)}
    />
  );
}
