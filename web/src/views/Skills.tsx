"use client";

import { useState } from "react";
import { BookOpen, Box, Check, GitBranch, Globe, RefreshCw, Sparkles, Terminal, WifiOff } from "lucide-react";
import { Badge, Empty, Hero, ToolChip } from "../components/ui";
import { Reveal } from "../components/motion";
import type { CatalogRepo, Skill } from "../lib/types";
import { api } from "../lib/api";

const GATES: [string, string][] = [
  ["policy", "Policy"], ["import", "Import"], ["upstream_tests", "Upstream"],
  ["input_robustness", "Robustness"], ["mcp_smoke", "MCP"], ["differential", "Differential"],
];

/** A skill card: its id and a verified mark on top, the details below; it lifts slightly on hover. */
function Tile({ tag, children, mark = "verified" }: { seed: string; tag: string; mono?: boolean; mark?: "verified" | "pinned"; children: React.ReactNode }) {
  return (
    <div className="group flex h-full flex-col rounded-[10px] border border-line bg-canvas p-4 transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-px hover:border-line-strong hover:shadow-[0_12px_28px_-18px_rgba(27,25,21,0.28)]">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="min-w-0 truncate font-mono text-[11.5px] text-muted">{tag}</span>
        {mark === "verified" ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-[5px] bg-good-bg px-1.5 py-0.5 text-[10.5px] font-medium text-good">
            <Check className="h-3 w-3" strokeWidth={2.5} />Verified
          </span>
        ) : (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-[5px] bg-panel-2 px-1.5 py-0.5 text-[10.5px] font-medium text-body">
            <GitBranch className="h-3 w-3" />Pinned
          </span>
        )}
      </div>
      <div className="flex-1">{children}</div>
    </div>
  );
}

/** Network: none (the default sandbox), or the reviewer-set allowlist. Then an on-demand upstream check. */
function Freshness({ s }: { s: Skill }) {
  const [up, setUp] = useState<{ state: string; upstream: string; detail: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const hosts = s.network_hosts ?? [];
  const check = async () => {
    setBusy(true);
    try { setUp(await api<{ state: string; upstream: string; detail: string }>(`/api/skills/${encodeURIComponent(s.name)}/upstream`)); }
    catch { setUp({ state: "unknown", upstream: "", detail: "check failed" }); }
    finally { setBusy(false); }
  };
  return (
    <div className="mt-2.5 space-y-1 text-[11px]">
      <p className="flex items-center gap-1.5 text-muted" title={hosts.length ? "Reaches only these hosts, through the egress proxy" : "No network in the sandbox"}>
        {hosts.length ? <Globe className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
        {hosts.length ? <span>network: <span className="font-mono">{hosts.join(", ")}</span></span> : "no network"}
      </p>
      <p className="flex items-center gap-1.5 text-muted">
        <GitBranch className="h-3 w-3" />upstream:
        {up ? (
          <span className={up.state === "behind" ? "text-warn" : up.state === "up to date" ? "text-good" : ""} title={up.detail}>
            {up.state === "behind" ? `behind upstream (${up.upstream})` : up.state}
          </span>
        ) : (
          <button onClick={check} disabled={busy} className="inline-flex items-center gap-1 underline decoration-dotted hover:text-ink">
            <RefreshCw className={`h-2.5 w-2.5 ${busy ? "animate-spin" : ""}`} />check upstream
          </button>
        )}
      </p>
    </div>
  );
}

export function Skills({ skills, onGoTasks }: { skills: Skill[]; onGoTasks: () => void }) {
  return (
    <>
      <Hero
        icon={<Sparkles />}
        title="Skills"
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
                <p className="mt-2.5 flex items-center gap-1.5 font-mono text-[11px] text-muted"><Box className="h-3 w-3" />{s.source}</p>
                <Freshness s={s} />
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
        icon={<BookOpen />}
        title="Catalog"
        sub="Pinned repositories Zyven may compile capabilities from: reviewer-curated, commit-pinned, licenses recorded. Nothing outside this list is ever fetched."
      />
      {repos.length === 0 ? (
        <Empty seed="catalog" title="Catalog is empty" body={<>Add pinned repositories to <span className="font-mono">catalog/repos.json</span>.</>} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {repos.map((r, i) => (
            <Reveal key={r.repo} delay={Math.min(i, 5) * 80}><Tile seed={r.repo} tag={r.repo} mono mark="pinned">
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
