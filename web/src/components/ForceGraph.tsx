"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { ArrowDownLeft, ArrowUpRight, Maximize2, Minus, Plus, Search, X } from "lucide-react";
import type { GraphEdge, GraphNode } from "../lib/types";

/* A small force simulation, written out by hand so the picture is deterministic: the same data always
   settles to the same layout. It is pre-run synchronously, so the graph is complete on first paint even
   where animation frames never fire; frames are only used to re-settle after a drag. */

const W = 1000, H = 640;

interface N extends GraphNode { x: number; y: number; vx: number; vy: number; r: number; pkg: string; fx: number | null; fy: number | null }
interface E { s: number; t: number; w: number }

const pkgOf = (id: string) => { const p = id.split("."); return p.length > 2 ? p.slice(0, 2).join(".") : p[0]; };
const short = (id: string) => id.split(".").slice(-2).join(".");
const hash = (s: string) => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 2166136261);

export const NODE_COLOR = { capability: "#e8895a", mcp: "#4a5a3f", other: "#c9c6bd" };
const colour = (n: GraphNode) => (n.capability ? NODE_COLOR.capability : n.mcp_able > 0 ? NODE_COLOR.mcp : NODE_COLOR.other);

function init(nodes: GraphNode[]): N[] {
  const pkgs = [...new Set(nodes.map((n) => pkgOf(n.id)))];
  return nodes.map((nd) => {
    const pkg = pkgOf(nd.id);
    const a = (2 * Math.PI * pkgs.indexOf(pkg)) / pkgs.length;
    const h = hash(nd.id);
    const jitterA = ((h % 360) * Math.PI) / 180, jitterR = 20 + (h % 50);
    return {
      ...nd, pkg, fx: null, fy: null, vx: 0, vy: 0,
      x: W / 2 + (pkgs.length > 1 ? 230 : 0) * Math.cos(a) + jitterR * Math.cos(jitterA),
      y: H / 2 + (pkgs.length > 1 ? 170 : 0) * Math.sin(a) + jitterR * Math.sin(jitterA),
      r: 6 + Math.min(18, Math.sqrt(nd.symbols) * 1.15),
    };
  });
}

function tick(P: N[], E: E[], alpha: number) {
  const n = P.length;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const a = P[i], b = P[j];
      let dx = a.x - b.x, dy = a.y - b.y;
      const d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2);
      let f = (2400 * alpha) / d2;
      const min = a.r + b.r + 6;
      if (d < min) f += ((min - d) / d) * 0.5;
      dx = (dx / d) * f; dy = (dy / d) * f;
      a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy;
    }
  }
  for (const { s, t } of E) {
    const a = P[s], b = P[t];
    const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) + 0.01, f = (d - 90) * 0.02 * alpha;
    a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
  }
  const cent = new Map<string, { x: number; y: number; n: number }>();
  for (const p of P) { const c = cent.get(p.pkg) ?? { x: 0, y: 0, n: 0 }; c.x += p.x; c.y += p.y; c.n++; cent.set(p.pkg, c); }
  for (const p of P) {
    const c = cent.get(p.pkg)!;
    p.vx += (c.x / c.n - p.x) * 0.03 * alpha + (W / 2 - p.x) * 0.006 * alpha;
    p.vy += (c.y / c.n - p.y) * 0.03 * alpha + (H / 2 - p.y) * 0.008 * alpha;
    if (p.fx !== null && p.fy !== null) { p.x = p.fx; p.y = p.fy; p.vx = p.vy = 0; continue; }
    p.x += Math.max(-14, Math.min(14, p.vx)); p.y += Math.max(-14, Math.min(14, p.vy));
    p.vx *= 0.58; p.vy *= 0.58;
  }
}

function settle(P: N[], E: E[], iters = 320) {
  for (let i = 0; i < iters; i++) tick(P, E, 1 - (0.97 * i) / iters);
}

/** The mutable simulation. Held in state and changed only through its methods, from event handlers. */
class Sim {
  P: N[];
  E: E[];
  alpha = 0;
  constructor(nodes: GraphNode[], edges: GraphEdge[]) {
    const idx = new Map(nodes.map((nd, i) => [nd.id, i]));
    this.E = edges.flatMap((e) => {
      const s = idx.get(e.source), t = idx.get(e.target);
      return s === undefined || t === undefined || s === t ? [] : [{ s, t, w: e.weight }];
    });
    this.P = init(nodes);
    settle(this.P, this.E);
  }
  pin(i: number, x: number | null, y: number | null) { this.P[i].fx = x; this.P[i].fy = y; }
  heat(a: number) { this.alpha = Math.max(this.alpha, a); }
  step() { tick(this.P, this.E, this.alpha); this.alpha *= 0.96; return this.alpha > 0.02; }
}

function fit(P: N[]) {
  if (!P.length) return { k: 1, x: 0, y: 0 };
  const xs = P.flatMap((p) => [p.x - p.r, p.x + p.r]), ys = P.flatMap((p) => [p.y - p.r, p.y + p.r - 0]);
  const x0 = Math.min(...xs) - 40, x1 = Math.max(...xs) + 40, y0 = Math.min(...ys) - 30, y1 = Math.max(...ys) + 46;
  const k = Math.min(2.2, W / (x1 - x0), H / (y1 - y0));
  return { k, x: (W - (x0 + x1) * k) / 2, y: (H - (y0 + y1) * k) / 2 };
}

export function ForceGraph({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const svg = useRef<SVGSVGElement>(null);
  const [sim] = useState(() => new Sim(nodes, edges));
  const { P, E } = sim;

  const [, setFrame] = useState(0);
  const [view, setView] = useState(() => fit(P));
  const [hover, setHover] = useState<number | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [panning, setPanning] = useState(false);
  const drag = useRef<{ kind: "node"; i: number; moved: boolean } | { kind: "pan"; sx: number; sy: number; vx: number; vy: number } | null>(null);
  const raf = useRef(0);

  const toView = useCallback((e: { clientX: number; clientY: number }) => {
    const el = svg.current;
    const m = el?.getScreenCTM();
    if (!el || !m) return { x: 0, y: 0 };
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    return { x: pt.x, y: pt.y };
  }, []);

  const run = useCallback(() => {
    cancelAnimationFrame(raf.current);
    const loop = () => {
      const hot = sim.step();
      setFrame((f) => f + 1);
      if (hot || drag.current?.kind === "node") raf.current = requestAnimationFrame(loop);
    };
    raf.current = requestAnimationFrame(loop);
  }, [sim]);
  useEffect(() => () => cancelAnimationFrame(raf.current), []);

  // Wheel zoom around the cursor (non-passive, so the page does not scroll underneath).
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const p = toView(e);
      setView((v) => {
        const k = Math.max(0.35, Math.min(5, v.k * Math.exp(-e.deltaY * 0.0015)));
        return { k, x: p.x - ((p.x - v.x) * k) / v.k, y: p.y - ((p.y - v.y) * k) / v.k };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [toView]);

  const zoomBy = (f: number) => setView((v) => {
    const k = Math.max(0.35, Math.min(5, v.k * f));
    return { k, x: W / 2 - ((W / 2 - v.x) * k) / v.k, y: H / 2 - ((H / 2 - v.y) * k) / v.k };
  });
  const focus = (i: number) => {
    setSel(i);
    setView((v) => { const k = Math.max(v.k, 1.4); return { k, x: W / 2 - P[i].x * k, y: H / 2 - P[i].y * k }; });
  };

  function onDown(e: RPointerEvent<SVGSVGElement>) {
    const target = (e.target as Element).closest("[data-node]");
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    if (target) {
      const i = Number(target.getAttribute("data-node"));
      drag.current = { kind: "node", i, moved: false };
    } else {
      const p = toView(e);
      drag.current = { kind: "pan", sx: p.x, sy: p.y, vx: view.x, vy: view.y };
      setPanning(true);
    }
  }
  function onMove(e: RPointerEvent<SVGSVGElement>) {
    const d = drag.current;
    if (!d) return;
    const p = toView(e);
    if (d.kind === "pan") {
      setView((v) => ({ ...v, x: d.vx + p.x - d.sx, y: d.vy + p.y - d.sy }));
    } else {
      sim.pin(d.i, (p.x - view.x) / view.k, (p.y - view.y) / view.k);
      if (!d.moved) { d.moved = true; sim.heat(0.35); run(); }
    }
  }
  function onUp() {
    const d = drag.current;
    drag.current = null;
    setPanning(false);
    if (d?.kind === "node") {
      sim.pin(d.i, null, null);
      if (!d.moved) setSel((s) => (s === d.i ? null : d.i));
      else { sim.heat(0.2); run(); }
    } else if (d?.kind === "pan" && Math.abs(view.x - d.vx) + Math.abs(view.y - d.vy) < 3) {
      setSel(null);
    }
  }

  const focusIdx = hover ?? sel;
  const near = useMemo(() => {
    if (focusIdx === null) return null;
    const s = new Set<number>([focusIdx]);
    for (const { s: a, t: b } of E) { if (a === focusIdx) s.add(b); if (b === focusIdx) s.add(a); }
    return s;
  }, [focusIdx, E]);
  const q = query.trim().toLowerCase();
  const matches = q ? P.map((p, i) => (p.id.toLowerCase().includes(q) ? i : -1)).filter((i) => i >= 0) : [];
  const pkgCentres = new Map<string, { x: number; y: number; top: number; n: number }>();
  for (const p of P) {
    const c = pkgCentres.get(p.pkg) ?? { x: 0, y: 0, top: Infinity, n: 0 };
    c.x += p.x; c.y += p.y; c.n++; c.top = Math.min(c.top, p.y - p.r);
    pkgCentres.set(p.pkg, c);
  }
  const pkgs = [...pkgCentres].filter(([, c]) => c.n >= 3).map(([name, c]) => ({ name, x: c.x / c.n, y: c.top - 14 }));

  if (!nodes.length) return <p className="py-8 text-center text-[13px] text-muted">Nothing to draw.</p>;
  const s = sel !== null ? P[sel] : null;
  const out = sel !== null ? E.filter((e) => e.s === sel).map((e) => e.t) : [];
  const inc = sel !== null ? E.filter((e) => e.t === sel).map((e) => e.s) : [];
  const showAll = view.k > 2.4;
  const bigOnes = new Set(P.map((p, i) => [p.r, i] as const).sort((a, b) => b[0] - a[0]).slice(0, 12).map(([, i]) => i));

  return (
    <div className="relative overflow-hidden rounded-2xl border border-line bg-panel">
      <div className="grid-lines pointer-events-none absolute inset-0 opacity-60" />
      <svg
        ref={svg} viewBox={`0 0 ${W} ${H}`}
        className={`relative block h-auto w-full touch-none select-none ${panning ? "cursor-grabbing" : "cursor-grab"}`}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <marker id="fg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0 0L10 5L0 10z" fill="#141413" />
          </marker>
        </defs>
        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
          {pkgs.length > 1 && pkgs.map((p) => (
            <text key={p.name} x={p.x} y={p.y} textAnchor="middle" className="pointer-events-none fill-muted/70 font-mono text-[11px] font-semibold uppercase tracking-[0.08em]"
              style={{ fontSize: 11 / Math.max(1, view.k * 0.8) }}>{p.name}</text>
          ))}
          {E.map(({ s: a, t: b, w }, i) => {
            const A = P[a], B = P[b];
            const lit = focusIdx !== null && (a === focusIdx || b === focusIdx);
            const dx = B.x - A.x, dy = B.y - A.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
            const ex = B.x - (dx / d) * (B.r + 2), ey = B.y - (dy / d) * (B.r + 2);
            const mx = (A.x + ex) / 2 - (dy / d) * d * 0.12, my = (A.y + ey) / 2 + (dx / d) * d * 0.12;
            return (
              <path key={i} d={`M${A.x},${A.y} Q${mx},${my} ${ex},${ey}`} fill="none"
                stroke={lit ? "#141413" : "#cfccc3"} strokeWidth={(lit ? 1.6 : 1) * Math.min(2.2, 0.8 + w * 0.2) / Math.sqrt(view.k)}
                opacity={focusIdx !== null && !lit ? 0.18 : lit ? 0.9 : 0.75}
                markerEnd={lit ? "url(#fg-arrow)" : undefined} />
            );
          })}
          {P.map((p, i) => {
            const dim = (near && !near.has(i)) || (q && !matches.includes(i));
            const isSel = sel === i, isHover = hover === i, hit = q && matches.includes(i);
            // Unfocused: label only the biggest modules; focused: only the focused module's neighbourhood.
            const label = near ? near.has(i) || hit : showAll || bigOnes.has(i) || hit;
            return (
              <g key={p.id} data-node={i} opacity={dim ? 0.2 : 1} className="cursor-pointer transition-opacity duration-200"
                onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover((h) => (h === i ? null : h))}>
                {(isSel || hit) && <circle cx={p.x} cy={p.y} r={p.r + 6} fill="none" stroke={isSel ? "#141413" : "#e8895a"} strokeWidth={1.5 / view.k} strokeDasharray={isSel ? "0" : "3 3"} />}
                <circle cx={p.x} cy={p.y} r={p.r} fill={colour(p)} fillOpacity={0.92} stroke="#fff" strokeWidth={(isHover || isSel ? 2.5 : 1.5) / Math.sqrt(view.k)} />
                {p.capability && <circle cx={p.x} cy={p.y} r={Math.max(2, p.r * 0.3)} fill="#fff" opacity={0.85} />}
                {label && (
                  <text x={p.x} y={p.y + p.r + 12 / Math.sqrt(view.k)} textAnchor="middle"
                    className="pointer-events-none fill-ink font-mono" style={{ fontSize: 10.5 / Math.sqrt(view.k), paintOrder: "stroke", stroke: "#f9f8f5", strokeWidth: 3 / view.k }}>
                    {short(p.id)}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* search */}
      <div className="absolute left-3 top-3 flex w-[min(260px,calc(100%-24px))] items-center gap-2 rounded-full border border-line bg-white/90 px-3 py-1.5 shadow-sm backdrop-blur">
        <Search className="h-3.5 w-3.5 shrink-0 text-muted" />
        <input
          value={query} onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && matches.length) focus(matches[0]); if (e.key === "Escape") setQuery(""); }}
          placeholder="Find a module" aria-label="Find a module"
          className="w-full bg-transparent text-[12.5px] outline-none placeholder:text-muted"
        />
        {q && <span className="shrink-0 font-mono text-[10.5px] text-muted">{matches.length}</span>}
      </div>

      {/* zoom controls */}
      <div className="absolute bottom-3 left-3 flex overflow-hidden rounded-full border border-line bg-white/90 shadow-sm backdrop-blur">
        {[
          { l: "Zoom in", i: <Plus className="h-3.5 w-3.5" />, f: () => zoomBy(1.3) },
          { l: "Zoom out", i: <Minus className="h-3.5 w-3.5" />, f: () => zoomBy(1 / 1.3) },
          { l: "Fit to view", i: <Maximize2 className="h-3.5 w-3.5" />, f: () => setView(fit(P)) },
        ].map((b) => (
          <button key={b.l} onClick={b.f} aria-label={b.l} title={b.l} className="flex h-8 w-9 items-center justify-center text-body hover:bg-panel-2 hover:text-ink">{b.i}</button>
        ))}
        <span className="flex items-center border-l border-line px-2.5 font-mono text-[10.5px] text-muted">{Math.round(view.k * 100)}%</span>
      </div>
      <p className="pointer-events-none absolute bottom-4 right-4 hidden text-[11px] text-muted sm:block">Scroll to zoom · drag to pan · drag a node · click for details</p>

      {/* hover card */}
      {hover !== null && hover !== sel && (
        <div className="pointer-events-none absolute left-3 top-14 max-w-[260px] animate-fade-in rounded-xl border border-line bg-white/95 px-3 py-2 text-[12px] shadow-sm backdrop-blur">
          <p className="break-all font-mono text-[11.5px] font-semibold">{P[hover].id}</p>
          <p className="mt-0.5 text-body">{P[hover].symbols.toLocaleString()} symbols · {P[hover].mcp_able.toLocaleString()} MCP-able</p>
        </div>
      )}

      {/* details panel */}
      {s && sel !== null && (
        <div className="absolute inset-y-3 right-3 flex w-[min(300px,calc(100%-24px))] animate-fade-in flex-col overflow-hidden rounded-2xl border border-line bg-white/95 shadow-[0_12px_40px_-16px_rgba(20,20,19,0.35)] backdrop-blur">
          <div className="flex items-start gap-2 border-b border-line p-4">
            <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ background: colour(s) }} />
            <div className="min-w-0 flex-1">
              <p className="break-all font-mono text-[12.5px] font-semibold leading-snug">{s.id}</p>
              <p className="mt-0.5 text-[11.5px] text-muted">package {s.pkg}</p>
            </div>
            <button onClick={() => setSel(null)} aria-label="Close details" className="rounded-full p-1 text-muted hover:bg-panel-2 hover:text-ink"><X className="h-4 w-4" /></button>
          </div>
          <div className="grid grid-cols-3 gap-px border-b border-line bg-line">
            {[["lines", s.loc], ["symbols", s.symbols], ["MCP-able", s.mcp_able]].map(([l, v]) => (
              <div key={l as string} className="bg-white px-3 py-2.5">
                <p className="text-[16px] font-medium tabular-nums tracking-tight">{(v as number).toLocaleString()}</p>
                <p className="text-[10.5px] text-muted">{l}</p>
              </div>
            ))}
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 text-[12px]">
            {s.capability && (
              <p className="rounded-xl bg-[#fbeee6] px-3 py-2 text-[#8a4a26]">Entry point of the <span className="font-semibold">{s.capability}</span> capability</p>
            )}
            {[{ t: "Imports", list: out, icon: <ArrowUpRight className="h-3 w-3" /> }, { t: "Imported by", list: inc, icon: <ArrowDownLeft className="h-3 w-3" /> }].map((g) => (
              <div key={g.t}>
                <p className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted">{g.icon}{g.t} · {g.list.length}</p>
                {g.list.length === 0 ? <p className="text-muted">None among the modules shown.</p> : (
                  <div className="flex flex-wrap gap-1">
                    {g.list.map((j) => (
                      <button key={j} onClick={() => focus(j)} className="inline-flex items-center gap-1 rounded-lg border border-line bg-white px-2 py-0.5 font-mono text-[11px] text-body hover:border-ink/40 hover:text-ink">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ background: colour(P[j]) }} />{short(P[j].id)}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
