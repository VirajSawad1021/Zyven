import type { StatsCard } from "../lib/types";

const W = 480, H = 240, M = { l: 42, r: 16, t: 12, b: 28 };

function niceTicks(max: number) {
  const raw = max / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-9))));
  const step = [1, 2, 5, 10].map((f) => f * mag).find((s) => s >= raw) ?? mag;
  const top = Math.ceil(max / step) * step;
  return { step, top, ticks: Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step) };
}

const fmt = (n: number) => (n >= 1000 ? `${n / 1000}k` : String(n));

function Frame({ top, ticks, count, children }: { top: number; ticks: number[]; count: number; children: (x: (i: number) => number, y: (v: number) => number) => React.ReactNode }) {
  const x = (i: number) => M.l + (count === 1 ? (W - M.l - M.r) / 2 : (i * (W - M.l - M.r)) / (count - 1));
  const y = (v: number) => H - M.b - (v * (H - M.t - M.b)) / top;
  const every = Math.ceil(count / 8);
  return (
    <svg viewBox={`0 0 ${W} ${H + 10}`} className="block h-auto w-full overflow-visible">
      <g stroke="#ebe9e3" strokeWidth="1">{ticks.map((t) => <line key={t} x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} />)}</g>
      <g className="fill-muted font-mono text-[10.5px]">
        {ticks.map((t) => <text key={t} x={M.l - 6} y={y(t) + 3} textAnchor="end">{fmt(t)}</text>)}
        {Array.from({ length: count }, (_, i) => (i === 0 || (i + 1) % every === 0) ? <text key={i} x={x(i)} y={H - 10} textAnchor="middle">{i + 1}</text> : null)}
        <text x={(M.l + W - M.r) / 2} y={H + 6} textAnchor="middle">task #</text>
      </g>
      {children(x, y)}
    </svg>
  );
}

const NoData = ({ text }: { text: string }) => (
  <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full"><text x={W / 2} y={H / 2} textAnchor="middle" className="fill-muted text-[12px]">{text}</text></svg>
);

export function DurationChart({ cards }: { cards: StatsCard[] }) {
  const data = cards.filter((c) => c.duration != null);
  if (!data.length) return <NoData text="No finished tasks yet" />;
  const { top, ticks } = niceTicks(Math.max(...data.map((c) => c.duration as number), 10));
  const bw = Math.min(26, ((W - M.l - M.r) / Math.max(data.length, 1)) * 0.6);
  return (
    <Frame top={top} ticks={ticks} count={data.length}>
      {(x, y) => data.map((c, i) => {
        const d = c.duration as number;
        return (
          <rect key={c.id} x={x(i) - bw / 2} y={y(d)} width={bw} height={H - M.b - y(d)} rx="3" fill={c.compiled ? "#e8895a" : "#4a5a3f"}>
            <title>{`${c.task} — ${Math.round(d)}s${c.compiled ? " (compiled)" : " (reused)"}`}</title>
          </rect>
        );
      })}
    </Frame>
  );
}

export function GrowthChart({ cards }: { cards: StatsCard[] }) {
  const data = cards.filter((c) => c.duration != null || c.learned.length);
  if (!data.length) return <NoData text="No tasks yet" />;
  let cum = 0;
  const pts = data.map((c) => ({ c, v: (cum += c.learned.length) }));
  const { top, ticks } = niceTicks(Math.max(cum, 4));
  return (
    <Frame top={top} ticks={ticks} count={pts.length}>
      {(x, y) => (
        <>
          <polyline points={pts.map((p, i) => `${x(i)},${y(p.v)}`).join(" ")} fill="none" stroke="#141413" strokeWidth="2" strokeLinejoin="round" />
          {pts.map((p, i) => p.c.learned.length
            ? <circle key={p.c.id} cx={x(i)} cy={y(p.v)} r="4.5" fill="#e8895a" stroke="#fff" strokeWidth="2"><title>{`learned: ${p.c.learned.join(", ")}`}</title></circle>
            : <circle key={p.c.id} cx={x(i)} cy={y(p.v)} r="3" fill="#141413" stroke="#fff" strokeWidth="1.5" />)}
          <text x={x(pts.length - 1) - 4} y={y(cum) - 10} textAnchor="end" className="fill-ink text-[11px] font-semibold">{cum} skill{cum === 1 ? "" : "s"}</text>
        </>
      )}
    </Frame>
  );
}
