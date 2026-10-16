"use client";

import { useEffect, useState } from "react";
import { Boxes, FileCode2, FlaskConical, Loader2, Network, Sparkles, Zap } from "lucide-react";
import { ForceGraph, NODE_COLOR } from "../components/ForceGraph";
import { CountUp, Reveal, Star } from "../components/motion";
import { Badge, Button, Card, Hero, Legend, Skeleton } from "../components/ui";
import { api, post } from "../lib/api";
import type { ExploreData, ExploreRepo } from "../lib/types";

function RepoCard({ repo, active, onClick }: { repo: ExploreRepo; active: boolean; onClick: () => void }) {
  const running = repo.job.state === "running";
  const share = repo.analyzed && repo.symbols ? (repo.mcp_able ?? 0) / repo.symbols : 0;
  return (
    <button onClick={onClick}
      className={`group min-w-[180px] flex-1 rounded-2xl border p-3.5 text-left transition-all ${
        active ? "border-ink bg-ink text-white shadow-[0_10px_30px_-18px_rgba(20,20,19,0.8)]" : "border-line bg-white text-ink hover:-translate-y-0.5 hover:border-ink/30"}`}>
      <p className="flex items-center justify-between gap-2 text-[13.5px] font-semibold">
        {repo.repo}
        {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : repo.analyzed ? <span className={`h-1.5 w-1.5 rounded-full ${active ? "bg-clay" : "bg-good"}`} /> : null}
      </p>
      <p className={`mt-0.5 text-[11.5px] ${active ? "text-white/60" : "text-muted"}`}>
        {running ? "analysing…" : repo.analyzed ? `${repo.symbols?.toLocaleString()} symbols` : repo.cloned ? "not analysed yet" : "not cloned"}
      </p>
      <div className={`mt-3 h-1 rounded-full ${active ? "bg-white/15" : "bg-panel-2"}`}>
        <div className={`h-1 rounded-full ${active ? "bg-clay" : "bg-olive"}`} style={{ width: `${share * 100}%` }} />
      </div>
      <p className={`mt-1 text-[10.5px] ${active ? "text-white/50" : "text-muted"}`}>{repo.analyzed ? `${Math.round(share * 100)}% MCP-able` : " "}</p>
    </button>
  );
}

function Tile({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <Card className="p-4">
      <p className="flex items-center gap-1.5 text-[12px] font-medium text-muted">{icon}{label}</p>
      <p className="mt-2.5 text-[26px] font-medium leading-none tracking-[-0.03em]"><CountUp to={value} /></p>
    </Card>
  );
}

function Funnel({ data }: { data: ExploreData }) {
  const top = Math.log10(Math.max(2, data.funnel[0].count) + 1);
  return (
    <div className="space-y-1">
      {data.funnel.map((s, i) => {
        const prev = i > 0 ? data.funnel[i - 1].count : null;
        const kept = prev ? s.count / prev : 1;
        const last = i === data.funnel.length - 1;
        return (
          <div key={s.stage} className="group rounded-xl px-2 py-2 transition-colors hover:bg-panel">
            <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
              <span className={last ? "font-semibold text-ink" : "text-ink"}>{s.stage}</span>
              <span className="flex items-baseline gap-2">
                {prev !== null && <span className="font-mono text-[10.5px] text-muted">{kept >= 0.995 ? "all kept" : `${(kept * 100).toFixed(kept < 0.01 ? 2 : 0)}% kept`}</span>}
                <span className="font-mono tabular-nums">{s.count.toLocaleString()}</span>
              </span>
            </div>
            <div className="mt-1.5 h-2 rounded-full bg-panel-2">
              <div className={`h-2 origin-left animate-[grow_0.9s_cubic-bezier(0.16,1,0.3,1)_both] rounded-full ${last ? "bg-clay" : "bg-ink"}`}
                style={{ width: `${Math.max(1.5, (Math.log10(s.count + 1) / top) * 100)}%`, animationDelay: `${i * 70}ms` }} />
            </div>
            <p className="mt-1 hidden text-[11px] text-muted group-hover:block">{s.note}</p>
          </div>
        );
      })}
      <p className="px-2 pt-1 text-[11px] text-muted">Bar lengths use a log scale. Hover a stage for what it means.</p>
    </div>
  );
}

function Detail({ name, data }: { name: string; data: ExploreData }) {
  const t = data.totals, f = data.funnel;
  const mcp = f.find((s) => s.stage.startsWith("MCP-able"))?.count ?? 0;
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        <Tile icon={<FileCode2 className="h-3.5 w-3.5" />} label="Lines of code" value={t.loc} />
        <Tile icon={<Boxes className="h-3.5 w-3.5" />} label="Modules" value={t.modules} />
        <Tile icon={<FlaskConical className="h-3.5 w-3.5" />} label={`Tests in ${t.test_files.toLocaleString()} files`} value={t.tests} />
        <Tile icon={<Network className="h-3.5 w-3.5" />} label="Symbols" value={f[0].count} />
        <Tile icon={<Sparkles className="h-3.5 w-3.5" />} label="MCP-able (estimate)" value={mcp} />
      </div>

      <Reveal className="mt-4">
        <Card className="p-4 sm:p-5">
          <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h3 className="text-[15px] font-semibold tracking-tight">Module graph</h3>
              <p className="mt-0.5 max-w-2xl text-[12.5px] leading-relaxed text-muted">
                The {data.graph.shown} most connected of {data.graph.total_modules.toLocaleString()} modules, grouped by package. Arrows point from a module to what it imports; circle size is symbol count.
              </p>
            </div>
            <Legend items={[{ color: NODE_COLOR.capability, label: "capability entry point" }, { color: NODE_COLOR.mcp, label: "has MCP-able symbols" }, { color: NODE_COLOR.other, label: "other" }]} />
          </div>
          <ForceGraph key={name} nodes={data.graph.nodes} edges={data.graph.edges} />
        </Card>
      </Reveal>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.1fr_1fr]">
        <Reveal>
          <Card className="h-full p-5">
            <h3 className="text-[15px] font-semibold tracking-tight">From every symbol to a tool</h3>
            <p className="mb-3 mt-0.5 text-[12.5px] text-muted">Each stage filters the one above it. Only the compile gates decide what is actually verified.</p>
            <Funnel data={data} />
          </Card>
        </Reveal>
        <Reveal delay={80}>
          <Card className="h-full p-5">
            <h3 className="text-[15px] font-semibold tracking-tight">Capabilities in the catalog</h3>
            <p className="mb-3 mt-0.5 text-[12.5px] text-muted">What the Scout found worth compiling from this repository.</p>
            {data.capabilities.length === 0 ? <p className="py-6 text-center text-[13px] text-muted">None recorded yet.</p> : (
              <div className="space-y-2">
                {data.capabilities.map((c) => (
                  <div key={c.name} className="flex items-center gap-3 rounded-xl border border-line px-3.5 py-2.5">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#fbeee6] text-clay"><Star className="h-3.5 w-3.5" /></span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium">{c.title}</p>
                      <p className="truncate font-mono text-[11px] text-muted">{c.name}</p>
                    </div>
                    <Badge>{c.entry_points} entry point{c.entry_points === 1 ? "" : "s"}</Badge>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Reveal>
      </div>

      <Reveal className="mt-4">
        <Card className="p-5">
          <h3 className="text-[15px] font-semibold tracking-tight">Best direct candidates</h3>
          <p className="mb-2 mt-0.5 text-[12.5px] text-muted">Public, side-effect free module functions with simple signatures, ranked by tests, docs and size.</p>
          {data.top_candidates.length === 0 ? <p className="py-6 text-center text-[13px] text-muted">No direct candidates found.</p> : (
            <div className="divide-y divide-line">
              {data.top_candidates.map((c) => (
                <div key={c.id} className="grid gap-x-4 gap-y-1 py-3 sm:grid-cols-[1fr_auto]">
                  <p className="break-all font-mono text-[12px] text-ink">
                    {c.id.split(".").slice(0, -1).join(".")}.<span className="font-semibold">{c.id.split(".").at(-1)}</span>
                    <span className="text-muted">({c.params.join(", ")}){c.returns ? ` → ${c.returns}` : ""}</span>
                  </p>
                  <span className="flex flex-wrap gap-1 sm:justify-end">
                    {c.tested && <Badge tone="good">tested</Badge>}
                    {c.capability && <Badge tone="info">{c.capability}</Badge>}
                  </span>
                  {c.doc && <p className="text-[12px] text-body sm:col-span-2">{c.doc}</p>}
                </div>
              ))}
            </div>
          )}
        </Card>
      </Reveal>

      <p className="mt-4 font-mono text-[11px] text-muted">
        {name} @ {(data.commit ?? "").slice(0, 7)} · {data.license} · analysed in {data.analyzed_in_s}s{data.warnings.length ? ` · ${data.warnings.length} warning(s)` : ""}
      </p>
    </>
  );
}

export function Explorer() {
  const [repos, setRepos] = useState<ExploreRepo[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<{ name: string; data: ExploreData } | null>(null);
  const [poll, setPoll] = useState(0);

  useEffect(() => {
    let alive = true;
    api<ExploreRepo[]>("/api/explore").then((list) => {
      if (!alive) return;
      setRepos(list);
      setSel((cur) => cur ?? (list.find((r) => r.analyzed) ?? list[0])?.repo ?? null);
    }).catch(() => {});
    return () => { alive = false; };
  }, [poll]);

  const anyRunning = !!repos?.some((r) => r.job.state === "running");
  useEffect(() => {
    if (!anyRunning) return;
    const t = setInterval(() => setPoll((n) => n + 1), 3000);
    return () => clearInterval(t);
  }, [anyRunning]);

  const current = repos?.find((r) => r.repo === sel);
  const ready = !!current?.analyzed && current.job.state !== "running";
  useEffect(() => {
    if (!sel || !ready) return;
    let alive = true;
    api<ExploreData>(`/api/explore/${encodeURIComponent(sel)}`).then((d) => alive && setLoaded({ name: sel, data: d })).catch(() => {});
    return () => { alive = false; };
  }, [sel, ready]);
  const data = loaded?.name === sel ? loaded.data : null;

  async function analyze(name: string) {
    await post(`/api/explore/${encodeURIComponent(name)}/analyze`);
    setPoll((n) => n + 1);
  }

  return (
    <>
      <Hero
        eyebrow="Repo explorer"
        title={<>What could this repo <span className="text-muted">become?</span></>}
        sub="Static analysis only, nothing executed: how much of a repository looks like it could become MCP tools, how its modules connect, and which parts a catalog capability already covers."
      />

      <div className="-mx-1 mb-5 flex gap-2.5 overflow-x-auto px-1 pb-2 pt-1 [scrollbar-width:none]">
        {repos === null
          ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[92px] min-w-[180px] flex-1" />)
          : repos.map((r) => <RepoCard key={r.repo} repo={r} active={r.repo === sel} onClick={() => setSel(r.repo)} />)}
      </div>

      {!current ? null : current.job.state === "running" ? (
        <Card className="px-7 py-12 text-center">
          <Loader2 className="mx-auto h-5 w-5 animate-spin" />
          <p className="mt-3 font-medium">Analysing {current.repo}…</p>
          <p className="mt-1 text-[12.5px] text-muted">Large repositories take a couple of minutes (sympy: about two).</p>
        </Card>
      ) : data ? (
        <Detail name={current.repo} data={data} />
      ) : current.analyzed ? (
        <div className="space-y-4"><Skeleton className="h-24" /><Skeleton className="h-[420px]" /></div>
      ) : (
        <Card className="px-7 py-12 text-center">
          <p className="text-[16px] font-semibold">{current.repo} has not been analysed yet</p>
          <p className="mx-auto mb-4 mt-1 max-w-lg text-[13px] text-body">{current.note}</p>
          {current.job.state === "error" && <p className="mb-3 text-[12.5px] text-bad">{current.job.error}</p>}
          {current.cloned
            ? <Button onClick={() => analyze(current.repo)}><Zap className="h-3.5 w-3.5" /> Analyse repository</Button>
            : <p className="text-[12.5px] text-muted">Clone it first with catalog sync.</p>}
        </Card>
      )}
    </>
  );
}
