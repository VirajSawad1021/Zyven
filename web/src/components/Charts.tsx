"use client";

import { useState, type ReactNode } from "react";
import type { StatsCard } from "../lib/types";

/* Hand-built SVG charts. Every chart draws in a fixed viewBox and scales to its container, and every
   tooltip is plain HTML positioned in percentages of that viewBox, so nothing depends on measuring. */

export const KIND = {
  learned: { label: "Compiled a new skill", color: "#e8895a" },
  reused: { label: "Reused a skill", color: "#4a5a3f" },
  compile_failed: { label: "Compile did not verify", color: "#b4544b" },
  direct: { label: "No tool needed", color: "#c9c6bd" },
} as const;
export type Kind = keyof typeof KIND;

export function kindOf(c: StatsCard): Kind {
  if (c.learned.length) return "learned";
  if (c.reused.length) return "reused";
  if (c.compiled) return "compile_failed";
  return "direct";
}

export const fmtDur = (s: number) =>
  s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s` : `${(s / 3600).toFixed(1)}h`;

function Tip({ x, y, w, h, children }: { x: number; y: number; w: number; h: number; children: ReactNode }) {
  const left = (x / w) * 100;
  return (
    <div
      className="pointer-events-none absolute z-10 w-max max-w-[260px] -translate-y-full rounded-xl border border-line bg-white/95 px-3 py-2 text-[12px] shadow-[0_8px_24px_-12px_rgba(20,20,19,0.35)] backdrop-blur animate-fade-in"
      style={{ left: `${left}%`, top: `calc(${(y / h) * 100}% - 10px)`, transform: `translate(${left > 70 ? "-100%" : left < 30 ? "0" : "-50%"}, -100%)` }}
    >
      {children}
    </div>
  );
}

const Empty = ({ text, h = 220 }: { text: string; h?: number }) => (
  <div className="grid place-items-center rounded-xl border border-dashed border-line-strong text-[12.5px] text-muted" style={{ height: h }}>{text}</div>
);

/* ── task timeline: one lollipop per task, duration on a log scale ─────────────────────────────── */

const LOG_TICKS = [5, 10, 30, 60, 300, 600, 1800, 3600];
const tickLabel = (s: number) => (s < 60 ? `${s}s` : s < 3600 ? `${s / 60}m` : `${s / 3600}h`);

export function Timeline({ cards }: { cards: StatsCard[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const data = cards.filter((c) => c.duration != null && c.duration > 0);
  if (!data.length) return <Empty text="No finished tasks yet" />;

  const W = 640, H = 260, M = { l: 46, r: 14, t: 14, b: 30 };
  const maxD = Math.max(...data.map((c) => c.duration as number));
  const minD = Math.min(...data.map((c) => c.duration as number));
  const lo = Math.log10(Math.max(1, Math.min(minD, 10) * 0.7));
  const hi = Math.log10(maxD * 1.4);
  const y = (v: number) => M.t + (1 - (Math.log10(v) - lo) / (hi - lo)) * (H - M.t - M.b);
  const step = (W - M.l - M.r) / data.length;
  const x = (i: number) => M.l + step * (i + 0.5);
  const ticks = LOG_TICKS.filter((t) => Math.log10(t) >= lo && Math.log10(t) <= hi);
  const h = hover !== null ? data[hover] : null;

  return (
    <div className="relative" onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full overflow-visible">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} stroke="#ebe9e3" strokeDasharray={t === 60 || t === 600 ? "0" : "3 4"} />
            <text x={M.l - 8} y={y(t) + 3.5} textAnchor="end" className="fill-muted font-mono text-[10px]">{tickLabel(t)}</text>
          </g>
        ))}
        {data.map((c, i) => {
          const k = kindOf(c);
          const col = KIND[k].color;
          const d = c.duration as number;
          const on = hover === i;
          const dim = hover !== null && !on;
          return (
            <g key={c.id} opacity={dim ? 0.35 : 1} className="transition-opacity">
              <rect x={x(i) - step / 2} y={M.t} width={step} height={H - M.t - M.b} fill={on ? "#f4f3ef" : "transparent"} onMouseEnter={() => setHover(i)} />
              <line x1={x(i)} x2={x(i)} y1={H - M.b} y2={y(d)} stroke={col} strokeWidth={on ? 3 : 2} strokeLinecap="round" className="pointer-events-none" />
              <circle cx={x(i)} cy={y(d)} r={on ? 7 : 5.5} fill={c.status === "FAILED" ? "#fff" : col} stroke={col} strokeWidth={2.2} className="pointer-events-none" />
              <text x={x(i)} y={H - M.b + 16} textAnchor="middle" className="pointer-events-none fill-muted font-mono text-[10px]">{i + 1}</text>
            </g>
          );
        })}
      </svg>
      {h && hover !== null && (
        <Tip x={x(hover)} y={y(h.duration as number)} w={W} h={H}>
          <p className="font-semibold text-ink">{fmtDur(h.duration as number)} · {KIND[kindOf(h)].label}</p>
          <p className="mt-0.5 line-clamp-2 text-body">{h.task}</p>
          {(h.learned.length > 0 || h.reused.length > 0) && (
            <p className="mt-1 font-mono text-[11px] text-muted">{[...h.learned, ...h.reused].join(", ")}</p>
          )}
          {h.status === "FAILED" && <p className="mt-1 text-[11px] font-medium text-bad">Task failed</p>}
        </Tip>
      )}
    </div>
  );
}

/* ── skill growth: cumulative verified skills, a step area ─────────────────────────────────────── */

export function Growth({ cards }: { cards: StatsCard[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!cards.length) return <Empty text="No tasks yet" />;
  const pts = cards.reduce<{ c: StatsCard; v: number }[]>((acc, c) => [...acc, { c, v: (acc.at(-1)?.v ?? 0) + c.learned.length }], []);
  const total = pts.at(-1)?.v ?? 0;

  const W = 960, H = 230, M = { l: 34, r: 18, t: 18, b: 30 };
  const top = Math.max(4, total + 1);
  const x = (i: number) => M.l + (pts.length === 1 ? (W - M.l - M.r) / 2 : (i * (W - M.l - M.r)) / (pts.length - 1));
  const y = (v: number) => M.t + (1 - v / top) * (H - M.t - M.b);
  const line = pts.map((p, i) => (i === 0 ? `M${x(0)},${y(p.v)}` : `H${x(i)}V${y(p.v)}`)).join("");
  const area = `${line}V${H - M.b}H${x(0)}Z`;
  const h = hover !== null ? pts[hover] : null;

  return (
    <div className="relative" onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full overflow-visible">
        <defs>
          <linearGradient id="growth-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#e8895a" stopOpacity="0.32" />
            <stop offset="100%" stopColor="#e8895a" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {Array.from({ length: top + 1 }, (_, v) => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke="#ebe9e3" strokeDasharray={v === 0 ? "0" : "3 4"} />
            <text x={M.l - 8} y={y(v) + 3.5} textAnchor="end" className="fill-muted font-mono text-[10px]">{v}</text>
          </g>
        ))}
        <path d={area} fill="url(#growth-fill)" />
        <path d={line} fill="none" stroke="#141413" strokeWidth="2.2" strokeLinejoin="round" />
        {pts.map((p, i) => (
          <g key={p.c.id}>
            <rect x={x(i) - (W - M.l - M.r) / pts.length / 2} y={M.t} width={(W - M.l - M.r) / pts.length} height={H - M.t - M.b} fill="transparent" onMouseEnter={() => setHover(i)} />
            {p.c.learned.length ? (
              <circle cx={x(i)} cy={y(p.v)} r={hover === i ? 8 : 6.5} fill="#e8895a" stroke="#fff" strokeWidth="2.5" className="pointer-events-none" />
            ) : (
              <circle cx={x(i)} cy={y(p.v)} r={hover === i ? 5 : 3} fill={hover === i ? "#141413" : "#fff"} stroke="#141413" strokeWidth="1.6" className="pointer-events-none" />
            )}
            <text x={x(i)} y={H - M.b + 16} textAnchor="middle" className="pointer-events-none fill-muted font-mono text-[10px]">{i + 1}</text>
          </g>
        ))}
      </svg>
      {h && hover !== null && (
        <Tip x={x(hover)} y={y(h.v)} w={W} h={H}>
          <p className="font-semibold text-ink">{h.v} skill{h.v === 1 ? "" : "s"} after task {hover + 1}</p>
          {h.c.learned.length ? (
            <p className="mt-0.5 font-mono text-[11px] text-clay">+ {h.c.learned.join(", ")}</p>
          ) : (
            <p className="mt-0.5 text-body">{h.c.reused.length ? `reused ${h.c.reused.join(", ")}` : "nothing new learned"}</p>
          )}
        </Tip>
      )}
    </div>
  );
}

/* ── donut ─────────────────────────────────────────────────────────────────────────────────────── */

export function Donut({ parts, center, sub }: { parts: { label: string; value: number; color: string }[]; center: ReactNode; sub: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const total = parts.reduce((a, p) => a + p.value, 0);
  const R = 52, C = 2 * Math.PI * R, GAP = total > 0 && parts.filter((p) => p.value).length > 1 ? 3 : 0;
  const offsets = parts.reduce<number[]>((acc, p, i) => [...acc, i === 0 ? 0 : acc[i - 1] + (parts[i - 1].value / (total || 1)) * C], []);
  const h = hover !== null ? parts[hover] : null;

  return (
    <div className="flex flex-wrap items-center gap-6">
      <div className="relative h-[150px] w-[150px] shrink-0">
        <svg viewBox="0 0 140 140" className="h-full w-full -rotate-90">
          <circle cx="70" cy="70" r={R} fill="none" stroke="#f1efea" strokeWidth="16" />
          {total > 0 && parts.map((p, i) => {
            const len = (p.value / total) * C;
            if (!p.value) return null;
            return (
              <circle
                key={p.label} cx="70" cy="70" r={R} fill="none" stroke={p.color}
                strokeWidth={hover === i ? 20 : 16}
                strokeDasharray={`${Math.max(0, len - GAP)} ${C}`}
                strokeDashoffset={-offsets[i]}
                className="cursor-pointer transition-[stroke-width] duration-200"
                onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
              />
            );
          })}
        </svg>
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
          <div>
            <p className="text-[26px] font-medium leading-none tracking-tight tabular-nums">{h ? h.value : center}</p>
            <p className="mt-1 text-[11px] text-muted">{h ? h.label : sub}</p>
          </div>
        </div>
      </div>
      <ul className="min-w-[150px] flex-1 space-y-2">
        {parts.map((p, i) => (
          <li key={p.label} className={`flex items-center gap-2 text-[12.5px] transition-opacity ${hover !== null && hover !== i ? "opacity-50" : ""}`}
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: p.color }} />
            <span className="text-body">{p.label}</span>
            <span className="ml-auto font-mono tabular-nums text-ink">{p.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
