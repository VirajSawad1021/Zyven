import { Check, Clock, LayoutGrid, Sparkles, Zap } from "lucide-react";
import { DurationChart, GrowthChart } from "../components/Charts";
import { Legend, PageHeader, Section, Skeleton, Stat } from "../components/ui";
import type { Stats } from "../lib/types";

const GATE_ORDER = ["policy", "import", "upstream_tests", "input_robustness", "mcp_smoke", "differential"];

export function Insights({ stats }: { stats: Stats | null }) {
  const header = (
    <PageHeader
      eyebrow="Insights"
      title="Learning, measured"
      sub="The first task that needs a capability pays the compile cost. Every similar task after that reuses the verified skill. This is the learning curve, live from the board."
    />
  );
  if (!stats) return <>{header}<Skeleton className="h-64" /></>;

  const { totals: t, averages: av } = stats;
  const gates = Object.entries(stats.gates).sort(([a], [b]) => GATE_ORDER.indexOf(a) - GATE_ORDER.indexOf(b));
  const sec = (v: number | null) => (v != null ? `${Math.round(v)}s` : "—");

  return (
    <>
      {header}
      <div className="mb-3.5 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat value={t.tasks} label="Tasks" icon={<LayoutGrid className="h-3.5 w-3.5" />} />
        <Stat value={`${t.done}/${t.tasks}`} label="Done" icon={<Check className="h-3.5 w-3.5" />} />
        <Stat value={t.skills} label="Skills learned" icon={<Sparkles className="h-3.5 w-3.5" />} />
        <Stat value={t.reuses} label="Skill reuses" icon={<Zap className="h-3.5 w-3.5" />} />
        <Stat value={sec(av.compile_s)} label="Avg with compile" icon={<Clock className="h-3.5 w-3.5" />} />
        <Stat value={sec(av.reuse_s)} label="Avg reuse" icon={<Zap className="h-3.5 w-3.5" />} />
      </div>

      <div className="grid gap-3.5 lg:grid-cols-2">
        <Section title="Task duration" sub="Seconds per task. Compiling tasks pay the one-time cost; reuses are nearly instant.">
          <Legend items={[{ color: "#e8895a", label: "compiled a skill" }, { color: "#4a5a3f", label: "reused / no compile" }]} />
          <DurationChart cards={stats.cards} />
        </Section>
        <Section title="Cumulative skills learned" sub="Each step is a new verified skill added to the library. The flat parts are reuse.">
          <GrowthChart cards={stats.cards} />
        </Section>
      </div>

      <Section title="Verification gates" sub="How often each sandbox gate passed across all compile attempts." className="mt-3.5">
        {gates.length === 0 ? (
          <p className="pb-2 text-[13px] text-muted">No compiles have run yet.</p>
        ) : (
          <div className="space-y-2 pb-2 pt-1">
            {gates.map(([name, g]) => {
              const total = g.pass + g.fail;
              return (
                <div key={name} className="grid grid-cols-[150px_1fr_52px] items-center gap-3 text-[12.5px]">
                  <span className="capitalize">{name.replace(/_/g, " ")}</span>
                  <div className="flex h-2.5 overflow-hidden rounded-full bg-panel-2">
                    <div className="bg-good" style={{ width: `${(100 * g.pass) / total}%` }} />
                    <div className="bg-bad" style={{ width: `${(100 * g.fail) / total}%` }} />
                  </div>
                  <span className="text-right font-mono tabular-nums">{g.pass}/{total}</span>
                </div>
              );
            })}
          </div>
        )}
      </Section>
    </>
  );
}
