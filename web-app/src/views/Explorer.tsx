import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Zap } from "lucide-react";
import { ForceGraph } from "../components/ForceGraph";
import { Badge, Button, Card, Legend, PageHeader, Section, Stat } from "../components/ui";
import { api, post } from "../lib/api";
import type { ExploreData, ExploreRepo } from "../lib/types";

function Pill({ repo, active, onClick }: { repo: ExploreRepo; active: boolean; onClick: () => void }) {
  const sub = repo.job.state === "running" ? "analyzing…" : repo.analyzed ? `${repo.mcp_able?.toLocaleString()} of ${repo.symbols?.toLocaleString()} MCP-able` : repo.cloned ? "not analyzed" : "not cloned";
  return (
    <button onClick={onClick}
      className={`rounded-xl border px-3.5 py-2 text-left text-[13px] transition-colors ${active ? "border-ink bg-ink text-white" : "border-line-strong bg-white text-ink hover:border-ink/40"}`}>
      {repo.repo}
      <small className={`mt-0.5 block text-[11px] ${active ? "text-white/70" : "text-muted"}`}>{sub}</small>
    </button>
  );
}

function Funnel({ data }: { data: ExploreData }) {
  const max = Math.max(1, data.funnel[0].count);
  return (
    <div className="mt-2.5 flex flex-col gap-2 pb-2">
      {data.funnel.map((s, i) => (
        <div key={s.stage} className="grid grid-cols-[150px_1fr_64px] items-center gap-3 text-[12.5px] sm:grid-cols-[180px_1fr_64px]">
          <div className="font-medium">{s.stage}<small className="block text-[11px] font-normal text-muted">{s.note}</small></div>
          <div className="h-[22px] overflow-hidden rounded-lg bg-panel-2">
            <div className={`h-full rounded-lg transition-[width] duration-500 ${i === 4 ? "bg-clay" : "bg-olive"}`} style={{ width: `${(100 * s.count) / max}%` }} />
          </div>
          <div className="text-right font-mono tabular-nums">{s.count.toLocaleString()}</div>
        </div>
      ))}
    </div>
  );
}

function Detail({ data }: { data: ExploreData }) {
  const t = data.totals, f = data.funnel;
  return (
    <>
      <div className="mb-3.5 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        <Stat value={t.modules.toLocaleString()} label="modules" />
        <Stat value={f[0].count.toLocaleString()} label="symbols" />
        <Stat value={f[4].count.toLocaleString()} label="MCP-able (estimate)" />
        <Stat value={t.tests.toLocaleString()} label={`tests in ${t.test_files} files`} />
        <Stat value={data.capabilities.length} label="catalog capabilities" />
      </div>

      <Section title="MCP funnel"
        sub={<>From every symbol to the ones that could plausibly become tools.{data.capabilities.length > 0 && <> Capabilities: {data.capabilities.map((c) => <Badge key={c.name} className="mr-1">{c.title} · {c.entry_points} entry points</Badge>)}</>}</>}>
        <Funnel data={data} />
      </Section>

      <Section className="mt-3.5" title="Module graph"
        sub={`Top ${data.graph.shown} of ${data.graph.total_modules.toLocaleString()} modules by size and connectivity. Edges are imports; circle size is symbol count. Hover a node to see its neighbours.`}>
        <Legend items={[{ color: "#e8895a", label: "in a catalog capability" }, { color: "#4a5a3f", label: "has MCP-able symbols" }, { color: "#c9c6bd", label: "other" }]} />
        <div className="pb-2"><ForceGraph nodes={data.graph.nodes} edges={data.graph.edges} /></div>
      </Section>

      <Section className="mt-3.5" title="Best direct candidates"
        sub="Module-level functions that are public, side-effect free, simply typed, and ranked by tests, docs and small signatures.">
        {data.top_candidates.length === 0 ? <p className="pb-2 text-[13px] text-muted">No direct candidates found.</p> : (
          <div className="pb-1">
            {data.top_candidates.map((c) => (
              <div key={c.id} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 border-t border-line py-2.5 text-[12.5px] first:border-t-0">
                <span className="break-all font-mono text-[12px]">{c.id}({c.params.join(", ")}){c.returns ? ` -> ${c.returns}` : ""}</span>
                <span className="flex gap-1">{c.tested && <Badge tone="good">tested</Badge>}{c.capability && <Badge tone="info">{c.capability}</Badge>}</span>
                {c.doc && <span className="col-span-2 text-[12px] text-muted">{c.doc}</span>}
              </div>
            ))}
          </div>
        )}
      </Section>

      <p className="mx-0.5 mt-3 font-mono text-[11px] text-muted">
        {data.repo} @ {(data.commit ?? "").slice(0, 7)} · {data.license} · analyzed in {data.analyzed_in_s}s{data.warnings.length ? ` · ${data.warnings.length} warning(s)` : ""}
      </p>
    </>
  );
}

export function Explorer() {
  const [repos, setRepos] = useState<ExploreRepo[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [data, setData] = useState<ExploreData | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const load = useCallback(async () => {
    const list = await api<ExploreRepo[]>("/api/explore").catch(() => null);
    if (!list) return;
    setRepos(list);
    setSel((cur) => cur ?? (list.find((r) => r.analyzed) ?? list[0])?.repo ?? null);
    window.clearTimeout(timer.current);
    if (list.some((r) => r.job.state === "running")) timer.current = window.setTimeout(load, 3000);
  }, []);

  useEffect(() => { load(); return () => window.clearTimeout(timer.current); }, [load]);

  const current = repos.find((r) => r.repo === sel);
  const analyzed = current?.analyzed;
  const running = current?.job.state === "running";
  useEffect(() => {
    setData(null);
    if (sel && analyzed) api<ExploreData>(`/api/explore/${encodeURIComponent(sel)}`).then(setData).catch(() => {});
  }, [sel, analyzed, running]);

  async function analyze(name: string) {
    await post(`/api/explore/${encodeURIComponent(name)}/analyze`);
    load();
  }

  return (
    <>
      <PageHeader
        eyebrow="Repo explorer"
        title="What could this repo become?"
        sub="Pure static analysis, nothing executed: how much of a repository looks like it could be turned into MCP tools, how its modules connect, and which parts a catalog capability already covers. The MCP-able count is an estimate. Only the compile gates decide what is actually verified."
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {repos.map((r) => <Pill key={r.repo} repo={r} active={r.repo === sel} onClick={() => setSel(r.repo)} />)}
      </div>

      {!current ? null : running ? (
        <Card className="px-7 py-8 text-center">
          <Loader2 className="mx-auto h-5 w-5 animate-spin" />
          <p className="mt-2.5 font-medium">Analyzing {current.repo}…</p>
          <p className="mt-1 font-mono text-[12px] text-muted">Large repos take a couple of minutes (sympy: about 2).</p>
        </Card>
      ) : data ? (
        <Detail data={data} />
      ) : (
        <Card className="px-7 py-8 text-center">
          <p className="font-semibold">{current.repo} has not been analyzed yet</p>
          <p className="mb-3.5 mt-1 text-[13px] text-body">{current.note}</p>
          {current.job.state === "error" && <p className="mb-3 text-[12.5px] text-bad">{current.job.error}</p>}
          {current.cloned
            ? <Button onClick={() => analyze(current.repo)}><Zap className="h-3.5 w-3.5" /> Analyze repo</Button>
            : <p className="text-[12.5px] text-muted">Clone it first with catalog sync.</p>}
        </Card>
      )}
    </>
  );
}
