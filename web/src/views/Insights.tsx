"use client";

import { Check, Clock, LayoutGrid, Sparkles, X } from "lucide-react";
import { Donut, Growth, KIND, Timeline, fmtDur, kindOf, type Kind } from "../components/Charts";
import { CountUp, Reveal, Stars } from "../components/motion";
import { Card, Hero, Legend, Skeleton } from "../components/ui";
import type { Stats, StatsCard } from "../lib/types";

const GATE_ORDER = ["policy", "import", "upstream_tests", "input_robustness", "mcp_smoke", "differential"];
const GATE_SHORT: Record<string, string> = {
  policy: "Policy", import: "Import", upstream_tests: "Upstream", input_robustness: "Robustness", mcp_smoke: "MCP", differential: "Differential",
};

/** Splits a card's flat gate list into compile attempts: each attempt starts at the policy gate. */
function attempts(c: StatsCard) {
  const out: Record<string, boolean>[] = [];
  for (const g of c.gates ?? []) {
    if (g.name === "policy" || !out.length) out.push({});
    out[out.length - 1][g.name] = g.passed;
  }
  return out;
}

function Tile({ label, value, sub, icon }: { label: string; value: React.ReactNode; sub?: React.ReactNode; icon: React.ReactNode }) {
  return (
    <Card className="flex flex-col p-4">
      <p className="flex items-center gap-1.5 text-[12px] font-medium text-muted">{icon}{label}</p>
      <p className="mt-3 text-[30px] font-medium leading-none tracking-[-0.03em] tabular-nums">{value}</p>
      {sub && <p className="mt-2 text-[12px] text-body">{sub}</p>}
    </Card>
  );
}

function Panel({ title, sub, right, children, className = "" }: { title: string; sub?: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <Card className={`p-5 ${className}`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-[15px] font-semibold tracking-tight">{title}</h3>
          {sub && <p className="mt-0.5 max-w-xl text-[12.5px] leading-relaxed text-muted">{sub}</p>}
        </div>
        {right}
      </div>
      {children}
    </Card>
  );
}

function SpeedUp({ compile, reuse }: { compile: number | null; reuse: number | null }) {
  const ratio = compile && reuse ? compile / reuse : null;
  return (
    <div className="art art-warm grain relative h-full overflow-hidden rounded-[24px] p-3">
      <Stars seed="speedup" count={7} from={60} to={96} />
      <div className="frost relative z-10 flex h-full flex-col rounded-[18px] p-5">
        <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">The learning curve</p>
        <p className="mt-3 text-[56px] font-medium leading-none tracking-[-0.04em]">
          {ratio ? <><CountUp to={Math.round(ratio)} /><span className="text-[30px] text-muted">×</span></> : "—"}
        </p>
        <p className="mt-2 text-[14px] leading-relaxed text-body">
          {ratio ? "faster when the agent reuses a verified skill instead of compiling one." : "Run a task twice to see reuse against compile."}
        </p>
        <div className="mt-auto space-y-3 pt-6">
          {[
            { l: "Average task that compiled", v: compile, c: "bg-clay" },
            { l: "Average task that reused", v: reuse, c: "bg-olive" },
          ].map((r) => (
            <div key={r.l}>
              <div className="flex justify-between text-[12px]">
                <span className="text-body">{r.l}</span>
                <span className="font-mono tabular-nums">{r.v != null ? fmtDur(r.v) : "—"}</span>
              </div>
              <div className="mt-1.5 h-2 rounded-full bg-panel-2">
                <div className={`h-2 origin-left animate-[grow_1.1s_cubic-bezier(0.16,1,0.3,1)_both] rounded-full ${r.c}`}
                  style={{ width: r.v != null && compile ? `${Math.max(2, (r.v / Math.max(compile, reuse ?? 0)) * 100)}%` : "0%" }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function GateMatrix({ cards }: { cards: StatsCard[] }) {
  const rows = cards.flatMap((c, i) => attempts(c).map((a, j, all) => ({ c, n: i + 1, a, j, of: all.length })));
  if (!rows.length) return <p className="py-6 text-center text-[13px] text-muted">No compiles have run yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] border-separate border-spacing-y-1.5 text-[12.5px]">
        <thead>
          <tr className="text-left text-[11px] font-medium text-muted">
            <th className="pb-1 pr-3 font-medium">Compile attempt</th>
            {GATE_ORDER.map((g) => <th key={g} className="px-1 pb-1 text-center font-medium">{GATE_SHORT[g]}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const ok = GATE_ORDER.every((g) => r.a[g] !== false) && Object.keys(r.a).length > 0;
            return (
              <tr key={`${r.c.id}-${r.j}`}>
                <td className="max-w-[260px] pr-3">
                  <p className="truncate text-ink" title={r.c.task}>
                    <span className="mr-1.5 font-mono text-[11px] text-muted">#{r.n}{r.of > 1 ? `.${r.j + 1}` : ""}</span>{r.c.task}
                  </p>
                </td>
                {GATE_ORDER.map((g) => {
                  const v = r.a[g];
                  return (
                    <td key={g} className="px-1">
                      <div title={`${GATE_SHORT[g]}: ${v === undefined ? "not run" : v ? "passed" : "failed"}`}
                        className={`mx-auto flex h-7 w-full min-w-9 items-center justify-center rounded-lg ${
                          v === undefined ? "border border-dashed border-line-strong" : v ? (ok ? "bg-good text-white" : "bg-good-bg text-good") : "bg-bad text-white"}`}>
                        {v === undefined ? null : v ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
                      </div>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function GateRates({ gates }: { gates: Stats["gates"] }) {
  const list = GATE_ORDER.filter((g) => gates[g]).map((g) => ({ g, ...gates[g], total: gates[g].pass + gates[g].fail }));
  return (
    <div className="space-y-3.5">
      {list.map((r) => (
        <div key={r.g}>
          <div className="flex items-baseline justify-between text-[12.5px]">
            <span className="text-ink">{GATE_SHORT[r.g]}</span>
            <span className="font-mono tabular-nums text-muted">
              <span className="text-ink">{Math.round((100 * r.pass) / r.total)}%</span> · {r.pass}/{r.total}
            </span>
          </div>
          <div className="mt-1.5 flex h-2 gap-0.5 overflow-hidden rounded-full">
            <div className="origin-left animate-[grow_1s_cubic-bezier(0.16,1,0.3,1)_both] rounded-full bg-good" style={{ width: `${(100 * r.pass) / r.total}%` }} />
            {r.fail > 0 && <div className="rounded-full bg-bad/80" style={{ width: `${(100 * r.fail) / r.total}%` }} />}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Insights({ stats }: { stats: Stats | null }) {
  const header = (
    <Hero
      eyebrow="Insights"
      title={<>Learning, <span className="text-muted">measured.</span></>}
      sub="The first task that needs a capability pays the compile cost. Every similar task after that reuses the verified skill. Everything here is live from the board."
    />
  );
  if (!stats) {
    return (
      <>
        {header}
        <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]"><Skeleton className="h-72" /><Skeleton className="h-72" /></div>
      </>
    );
  }

  const { totals: t, averages: av, cards } = stats;
  const failed = t.failed ?? cards.filter((c) => c.status === "FAILED").length;
  const kinds = cards.reduce<Record<Kind, number>>((acc, c) => ({ ...acc, [kindOf(c)]: acc[kindOf(c)] + 1 }), { learned: 0, reused: 0, compile_failed: 0, direct: 0 });
  const compileTime = cards.filter((c) => c.compiled).reduce((a, c) => a + (c.duration ?? 0), 0);
  const otherTime = cards.filter((c) => !c.compiled).reduce((a, c) => a + (c.duration ?? 0), 0);
  const running = Math.max(0, t.tasks - t.done - failed);

  return (
    <>
      {header}

      <div className="grid gap-4 lg:grid-cols-[1fr_1.45fr]">
        <Reveal className="h-full"><SpeedUp compile={av.compile_s} reuse={av.reuse_s} /></Reveal>
        <Reveal delay={80} className="grid grid-cols-2 gap-4">
          <Tile label="Tasks" icon={<LayoutGrid className="h-3.5 w-3.5" />} value={<CountUp to={t.tasks} />}
            sub={<><span className="text-good">{t.done} done</span> · <span className="text-bad">{failed} failed</span>{running ? ` · ${running} open` : ""}</>} />
          <Tile label="Success rate" icon={<Check className="h-3.5 w-3.5" />} value={<>{t.tasks ? <CountUp to={Math.round((100 * t.done) / t.tasks)} /> : "—"}<span className="text-[18px] text-muted">%</span></>}
            sub="of tasks answered end to end" />
          <Tile label="Verified skills" icon={<Sparkles className="h-3.5 w-3.5" />} value={<CountUp to={t.skills} />}
            sub={`${t.reuses} reuse${t.reuses === 1 ? "" : "s"} so far`} />
          <Tile label="Time compiling" icon={<Clock className="h-3.5 w-3.5" />} value={fmtDur(compileTime)}
            sub={`vs ${fmtDur(otherTime)} on everything else`} />
        </Reveal>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.45fr_1fr]">
        <Reveal>
          <Panel title="Every task, by time taken" sub="One stem per task, in order. Log scale: a compile takes minutes, a reuse takes seconds. Hollow dots are tasks that failed.">
            <Legend items={(Object.keys(KIND) as Kind[]).map((k) => ({ color: KIND[k].color, label: KIND[k].label }))} />
            <Timeline cards={cards} />
          </Panel>
        </Reveal>
        <Reveal delay={80}>
          <Panel title="What each task did" sub="Hover a slice for the count.">
            <Donut
              center={t.tasks}
              sub="tasks"
              parts={(Object.keys(KIND) as Kind[]).map((k) => ({ label: KIND[k].label, value: kinds[k], color: KIND[k].color }))}
            />
            <div className="mt-6 border-t border-line pt-5">
              <p className="mb-3 text-[12px] font-medium text-muted">Gate pass rate, all attempts</p>
              <GateRates gates={stats.gates} />
            </div>
          </Panel>
        </Reveal>
      </div>

      <Reveal className="mt-4 block">
        <Panel title="Skill library growth" sub="Each orange step is a new skill that passed its gates. Flat stretches are the agent reusing what it already knows."
          right={<span className="rounded-full bg-panel-2 px-3 py-1 text-[12px] font-medium text-body">{t.skills} skill{t.skills === 1 ? "" : "s"}</span>}>
          <Growth cards={cards} />
        </Panel>
      </Reveal>

      <Reveal className="mt-4 block">
        <Panel title="Gate results per compile attempt"
          sub="Each row is one sandbox run. A repair produces a second row for the same task. A solid green row is a skill that shipped; a red cell is the gate that stopped it.">
          <GateMatrix cards={cards} />
        </Panel>
      </Reveal>
    </>
  );
}
