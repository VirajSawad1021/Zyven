"use client";

import { Box, Check, GitBranch, Terminal } from "lucide-react";
import { Badge, ArtFrame, Empty, Hero, ToolChip } from "../components/ui";
import { Reveal, Stars } from "../components/motion";
import type { CatalogRepo, Skill } from "../lib/types";

const GATES: [string, string][] = [
  ["policy", "Policy"], ["import", "Import"], ["upstream_tests", "Upstream"],
  ["input_robustness", "Robustness"], ["mcp_smoke", "MCP"], ["differential", "Differential"],
];

/** A painted tile with a frosted content box anchored at the bottom. */
function Tile({ seed, tag, mono, children }: { seed: string; tag: string; mono?: boolean; children: React.ReactNode }) {
  return (
    <ArtFrame seed={seed} className="grain flex h-full min-h-[240px] flex-col justify-end gap-2 rounded-[28px] p-4 pt-14 transition-transform duration-300 hover:-translate-y-1">
      <Stars seed={seed} count={6} from={55} to={95} />
      <span className={`frost absolute left-3.5 top-3.5 z-10 rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-[0.04em] text-ink ${mono ? "font-mono" : "font-mono"}`}>{tag}</span>
      <div className="frost relative z-10 rounded-[18px] px-4 py-3.5 shadow-[0_1px_2px_rgba(20,20,19,0.08)]">{children}</div>
    </ArtFrame>
  );
}

export function Skills({ skills, onGoTasks }: { skills: Skill[]; onGoTasks: () => void }) {
  return (
    <>
      <Hero
        eyebrow="Library"
        title={<>Verified <span className="text-muted">skills.</span></>}
        sub="Capabilities Zyven compiled from open-source code and kept because they passed the sandbox. Each one lists exactly which gates it passed, and the agent loads it as an MCP tool on demand."
      />
      {skills.length === 0 ? (
        <Empty seed="skills" title="No skills learned yet"
          body="Run a task that needs a capability the agent doesn&apos;t have. Once you approve the compile and it passes every gate, the verified skill lands here, reusable forever."
          action={<button onClick={onGoTasks} className="inline-flex h-8 items-center rounded-full bg-ink px-3.5 text-[12px] font-semibold text-white hover:bg-ink-soft">Go to tasks</button>} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {skills.map((s, i) => {
            const h = s.health ?? { ok: 0, calls: 0 };
            const pct = h.calls ? Math.round((100 * h.ok) / h.calls) : 100;
            return (
              <Reveal key={s.name} delay={Math.min(i, 5) * 80}><Tile seed={s.name} tag={s.name}>
                <p className="text-[15px] font-semibold tracking-tight text-ink">{s.title || s.name}</p>
                {s.summary && <p className="mt-0.5 text-[13px] leading-relaxed text-body">{s.summary}</p>}
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {s.tools.slice(0, 3).map((t) => <ToolChip key={t}><Terminal className="h-3 w-3" />{t}</ToolChip>)}
                </div>
                <div className="mt-3 grid grid-cols-3 gap-1">
                  {GATES.map(([g, label]) => {
                    const ok = s.verified_for.includes(g);
                    return (
                      <span key={g} title={ok ? `${label}: passed` : `${label}: not run for this skill`}
                        className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] ${ok ? "bg-good-bg text-good" : "border border-dashed border-line-strong text-muted"}`}>
                        {ok && <Check className="h-2.5 w-2.5" />}{label}
                      </span>
                    );
                  })}
                </div>
                <div className="mt-2.5">
                  <div className="h-1 overflow-hidden rounded-full bg-panel-2">
                    <div className={`h-full rounded-full transition-[width] duration-500 ${pct < 100 ? "bg-warn" : "bg-good"}`} style={{ width: `${pct}%` }} />
                  </div>
                  <div className="mt-1 flex justify-between text-[11px] text-muted"><span>{h.ok}/{h.calls} calls healthy</span><span>{pct}%</span></div>
                </div>
                <p className="mt-2.5 flex items-center gap-1.5 font-mono text-[11px] text-muted"><GitBranch className="h-3 w-3" />{s.source}</p>
              </Tile></Reveal>
            );
          })}
        </div>
      )}
    </>
  );
}

export function Catalog({ repos }: { repos: CatalogRepo[] }) {
  return (
    <>
      <Hero
        eyebrow="Sources"
        title={<>Curated <span className="text-muted">catalog.</span></>}
        sub="Pinned repositories Zyven may compile capabilities from: reviewer-curated, commit-pinned, licenses recorded. Nothing outside this list is ever fetched."
      />
      {repos.length === 0 ? (
        <Empty seed="catalog" title="Catalog is empty" body={<>Add pinned repositories to <span className="font-mono">catalog/repos.json</span>.</>} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {repos.map((r, i) => (
            <Reveal key={r.repo} delay={Math.min(i, 5) * 80}><Tile seed={r.repo} tag={r.repo} mono>
              <p className="text-[15px] font-semibold tracking-tight text-ink">{r.repo}</p>
              {r.note && <p className="mt-0.5 text-[13px] leading-relaxed text-body">{r.note}</p>}
              <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[12px] text-muted">
                <Badge><Box className="h-3 w-3" /> {r.license}</Badge>
                <span className="font-mono text-[11px]">@ {r.commit.slice(0, 7)}</span>
                <a href={r.url} target="_blank" rel="noopener noreferrer" className="ml-auto text-[12px] text-info hover:underline">source ↗</a>
              </div>
            </Tile></Reveal>
          ))}
        </div>
      )}
    </>
  );
}
