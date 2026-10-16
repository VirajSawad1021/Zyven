import { Box, GitBranch, Shield, Terminal } from "lucide-react";
import { Badge, ArtFrame, Empty, PageHeader, ToolChip } from "../components/ui";
import type { CatalogRepo, Skill } from "../lib/types";

/** A painted tile with a frosted content box anchored at the bottom. */
function Tile({ seed, tag, mono, children }: { seed: string; tag: string; mono?: boolean; children: React.ReactNode }) {
  return (
    <ArtFrame seed={seed} className="flex min-h-[240px] flex-col justify-end gap-2 rounded-3xl p-4 transition-transform duration-200 hover:-translate-y-0.5">
      <span className={`frost absolute left-3.5 top-3.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold tracking-[0.04em] text-ink ${mono ? "font-mono" : "font-mono"}`}>{tag}</span>
      <div className="frost rounded-[18px] px-4 py-3.5 shadow-[0_1px_2px_rgba(20,20,19,0.08)]">{children}</div>
    </ArtFrame>
  );
}

export function Skills({ skills, onGoTasks }: { skills: Skill[]; onGoTasks: () => void }) {
  return (
    <>
      <PageHeader
        eyebrow="Library"
        title="Verified skills"
        sub="Capabilities Zyven compiled from open-source code and kept after passing every verification gate. Each skill is an MCP tool the agent loads on demand."
      />
      {skills.length === 0 ? (
        <Empty seed="skills" title="No skills learned yet"
          body="Run a task that needs a capability the agent doesn't have. Once you approve the compile and it passes every gate, the verified skill lands here, reusable forever."
          action={<button onClick={onGoTasks} className="inline-flex h-8 items-center rounded-full bg-ink px-3.5 text-[12px] font-semibold text-white hover:bg-ink-soft">Go to tasks</button>} />
      ) : (
        <div className="grid gap-3.5 md:grid-cols-2">
          {skills.map((s) => {
            const h = s.health ?? { ok: 0, calls: 0 };
            const pct = h.calls ? Math.round((100 * h.ok) / h.calls) : 100;
            return (
              <Tile key={s.name} seed={s.name} tag={s.name}>
                <p className="text-[15px] font-semibold tracking-tight text-ink">{s.title || s.name}</p>
                {s.summary && <p className="mt-0.5 text-[13px] leading-relaxed text-body">{s.summary}</p>}
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {s.tools.slice(0, 3).map((t) => <ToolChip key={t}><Terminal className="h-3 w-3" />{t}</ToolChip>)}
                </div>
                <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                  <Badge tone="good"><Shield className="h-3 w-3" /> verified</Badge>
                  {s.verified_for.slice(0, 3).map((v) => <Badge key={v}>{v}</Badge>)}
                </div>
                <div className="mt-2.5">
                  <div className="h-1 overflow-hidden rounded-full bg-panel-2">
                    <div className={`h-full rounded-full transition-[width] duration-500 ${pct < 100 ? "bg-warn" : "bg-good"}`} style={{ width: `${pct}%` }} />
                  </div>
                  <div className="mt-1 flex justify-between text-[11px] text-muted"><span>{h.ok}/{h.calls} calls healthy</span><span>{pct}%</span></div>
                </div>
                <p className="mt-2.5 flex items-center gap-1.5 font-mono text-[11px] text-muted"><GitBranch className="h-3 w-3" />{s.source}</p>
              </Tile>
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
      <PageHeader
        eyebrow="Sources"
        title="Curated catalog"
        sub="Pinned repositories Zyven may compile capabilities from: reviewer-curated, commit-pinned, licenses recorded. Nothing outside this list is ever fetched."
      />
      {repos.length === 0 ? (
        <Empty seed="catalog" title="Catalog is empty" body={<>Add pinned repositories to <span className="font-mono">catalog/repos.json</span>.</>} />
      ) : (
        <div className="grid gap-3.5 md:grid-cols-2">
          {repos.map((r) => (
            <Tile key={r.repo} seed={r.repo} tag={r.repo} mono>
              <p className="text-[15px] font-semibold tracking-tight text-ink">{r.repo}</p>
              {r.note && <p className="mt-0.5 text-[13px] leading-relaxed text-body">{r.note}</p>}
              <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[12px] text-muted">
                <Badge><Box className="h-3 w-3" /> {r.license}</Badge>
                <span className="font-mono text-[11px]">@ {r.commit.slice(0, 7)}</span>
                <a href={r.url} target="_blank" rel="noopener noreferrer" className="ml-auto text-[12px] text-info hover:underline">source ↗</a>
              </div>
            </Tile>
          ))}
        </div>
      )}
    </>
  );
}
