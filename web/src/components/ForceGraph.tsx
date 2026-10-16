"use client";

import { useMemo, useState } from "react";
import type { GraphEdge, GraphNode } from "../lib/types";

const W = 760, H = 520;

interface P { x: number; y: number; vx: number; vy: number; r: number }

/** Deterministic force layout: seeded on a circle, so the same data always gives the same picture. */
function layout(nodes: GraphNode[], edges: [number, number][]): P[] {
  const n = nodes.length;
  const P: P[] = nodes.map((nd, i) => {
    const a = (2 * Math.PI * i) / n;
    return { x: W / 2 + 200 * Math.cos(a), y: H / 2 + 150 * Math.sin(a), vx: 0, vy: 0, r: 5 + Math.min(16, Math.sqrt(nd.symbols)) * 0.9 };
  });
  const ITER = 320;
  for (let it = 0; it < ITER; it++) {
    const cool = 1 - it / ITER;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = P[i].x - P[j].x, dy = P[i].y - P[j].y;
        const d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2), f = 2600 / d2;
        dx = (dx / d) * f; dy = (dy / d) * f;
        P[i].vx += dx; P[i].vy += dy; P[j].vx -= dx; P[j].vy -= dy;
      }
    }
    for (const [a, b] of edges) {
      const dx = P[b].x - P[a].x, dy = P[b].y - P[a].y, d = Math.sqrt(dx * dx + dy * dy) + 0.01, f = (d - 70) * 0.012;
      P[a].vx += (dx / d) * f; P[a].vy += (dy / d) * f; P[b].vx -= (dx / d) * f; P[b].vy -= (dy / d) * f;
    }
    for (const p of P) {
      p.vx += (W / 2 - p.x) * 0.004; p.vy += (H / 2 - p.y) * 0.004;
      p.x += Math.max(-12, Math.min(12, p.vx)) * cool; p.y += Math.max(-12, Math.min(12, p.vy)) * cool;
      p.vx *= 0.6; p.vy *= 0.6;
      p.x = Math.max(p.r + 6, Math.min(W - p.r - 6, p.x));
      p.y = Math.max(p.r + 6, Math.min(H - p.r - 6, p.y));
    }
  }
  return P;
}

const colour = (n: GraphNode) => (n.capability ? "#e8895a" : n.mcp_able > 0 ? "#4a5a3f" : "#c9c6bd");
const short = (id: string) => id.split(".").slice(-2).join(".");

export function ForceGraph({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const { P, E } = useMemo(() => {
    const idx = new Map(nodes.map((nd, i) => [nd.id, i]));
    const E = edges
      .map((e) => [idx.get(e.source), idx.get(e.target)] as const)
      .filter((e): e is readonly [number, number] => e[0] !== undefined && e[1] !== undefined)
      .map((e) => [e[0], e[1]] as [number, number]);
    return { P: layout(nodes, E), E };
  }, [nodes, edges]);

  const near = useMemo(() => {
    if (hover === null) return null;
    const s = new Set<number>([hover]);
    for (const [a, b] of E) { if (a === hover) s.add(b); if (b === hover) s.add(a); }
    return s;
  }, [hover, E]);

  if (!nodes.length) return <p className="py-8 text-center text-[13px] text-muted">Nothing to draw.</p>;
  const h = hover !== null ? nodes[hover] : null;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full rounded-xl bg-panel" onMouseLeave={() => setHover(null)}>
        {E.map(([a, b], i) => {
          const lit = near && near.has(a) && near.has(b) && (a === hover || b === hover);
          return <line key={i} x1={P[a].x} y1={P[a].y} x2={P[b].x} y2={P[b].y} stroke={lit ? "#141413" : "#d8d5cc"} strokeWidth={lit ? 1.6 : 1} opacity={near && !lit ? 0.25 : 1} />;
        })}
        {nodes.map((nd, i) => {
          const dim = near && !near.has(i);
          return (
            <g key={nd.id} opacity={dim ? 0.25 : 1} onMouseEnter={() => setHover(i)} className="cursor-pointer">
              <circle cx={P[i].x} cy={P[i].y} r={P[i].r} fill={colour(nd)} fillOpacity={0.88} stroke={hover === i ? "#141413" : "#fff"} strokeWidth={hover === i ? 2 : 1.5} />
              {(nd.capability || P[i].r > 11 || near?.has(i)) && (
                <text x={P[i].x} y={P[i].y + P[i].r + 11} textAnchor="middle" className="pointer-events-none fill-body font-mono text-[9.5px]">{short(nd.id)}</text>
              )}
            </g>
          );
        })}
      </svg>
      {h && (
        <div className="pointer-events-none absolute left-3 top-3 max-w-[300px] rounded-xl border border-line bg-white/95 px-3 py-2 text-[12px] shadow-sm backdrop-blur">
          <p className="break-all font-mono text-[11.5px] font-semibold">{h.id}</p>
          <p className="mt-0.5 text-body">{h.symbols.toLocaleString()} symbols · {h.mcp_able.toLocaleString()} MCP-able · {h.loc.toLocaleString()} lines</p>
          {h.capability && <p className="mt-0.5 font-semibold text-clay">capability: {h.capability}</p>}
        </div>
      )}
    </div>
  );
}
