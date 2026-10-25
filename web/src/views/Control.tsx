"use client";

import { useCallback, useEffect, useState } from "react";
import { Bot, Calendar, Check, Container, Plus, Square, X } from "lucide-react";
import { Badge, Button, Card, Empty, Eyebrow, Hero, LiveDot, Stat } from "../components/ui";
import { api, post } from "../lib/api";
import { relTime, type Tone } from "../lib/labels";

interface RuntimeStatus { installed: boolean; signed_in: boolean | null; detail: string }
interface RuntimeInfo { label: string; open_weight: boolean; available: boolean; note: string; exposes: Record<string, boolean>; status?: RuntimeStatus;
  settings?: { enabled: boolean; model: string }; env_enabled?: boolean;
  full_access?: { supported: boolean; allowed: boolean } }
interface Runtimes { runtimes: Record<string, RuntimeInfo>; planned: Record<string, string>; default_image: string }
interface Run {
  id: string; title: string; runtime: string; full_access?: boolean; prompt: string; image: string; network: boolean; memory: string; cpus: string;
  repo_url: string; run_at: number | null; status: string; created: number; updated: number; exit_code: number | null;
  files: { added: string[]; modified: string[] } | null; answer?: string; log?: { ts: number; kind: string; text: string }[];
}

const TONE: Record<string, Tone> = { QUEUED: "neutral", SCHEDULED: "info", RUNNING: "info", NEEDS_APPROVAL: "warn", COMPLETED: "good", FAILED: "bad", CANCELLED: "neutral" };
const LABEL: Record<string, string> = { QUEUED: "Queued", SCHEDULED: "Scheduled", RUNNING: "Running", NEEDS_APPROVAL: "Needs approval", COMPLETED: "Completed", FAILED: "Failed", CANCELLED: "Cancelled" };
const EXPOSES: Record<string, string> = { live_output: "live output", tool_calls: "tool calls", approvals: "approvals", file_changes: "file changes", tokens: "token usage" };
const input = "w-full rounded-xl border border-line-strong/80 bg-white px-3 py-2 text-[13px] text-ink placeholder:text-[#aaa79f] focus:border-ink focus:outline-none focus:ring-1 focus:ring-ink";

function RuntimeSwitch({ id, info, onChanged }: { id: string; info: RuntimeInfo; onChanged: () => void }) {
  const [model, setModel] = useState(info.settings?.model ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!info.settings) return null;
  const save = async (body: { enabled?: boolean; model?: string }) => {
    setBusy(true); setErr(null);
    try { await post(`/api/runtime-settings/${id}`, body); onChanged(); } catch (e) { setErr(e instanceof Error ? e.message : "failed"); } finally { setBusy(false); }
  };
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2.5 rounded-xl border border-line bg-panel px-3 py-2.5">
      {info.env_enabled
        ? <Badge tone="good">On (set by environment variable)</Badge>
        : <Button size="sm" variant={info.settings.enabled ? "secondary" : "primary"} loading={busy} onClick={() => save({ enabled: !info.settings!.enabled })}>{info.settings.enabled ? "Turn off" : "Turn on"}</Button>}
      {id !== "github" && (
        <>
          <input className={`${input} max-w-[260px]`} placeholder="model (empty = the program's own default)" value={model} onChange={(e) => setModel(e.target.value)} />
          <Button size="sm" variant="secondary" loading={busy} disabled={model === (info.settings.model ?? "")} onClick={() => save({ model })}>Save model</Button>
        </>
      )}
      {err && <span className="text-[12.5px] text-bad">{err}</span>}
    </div>
  );
}

function NewTask({ rt, onCreated, onSettingsChanged }: { rt: Runtimes; onCreated: (id: string) => void; onSettingsChanged: () => void }) {
  const [runtime, setRuntime] = useState("docker");
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [image, setImage] = useState(rt.default_image);
  const [network, setNetwork] = useState(false);
  const [memory, setMemory] = useState("1g");
  const [cpus, setCpus] = useState("1");
  const [repo, setRepo] = useState("");
  const [when, setWhen] = useState("");
  const [every, setEvery] = useState("0");
  const [fullAccess, setFullAccess] = useState(false);
  const [fullSure, setFullSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const info = rt.runtimes[runtime];
  const docker = runtime === "docker";

  async function submit() {
    setBusy(true); setErr(null);
    try {
      const run = await post<Run>("/api/runs", {
        runtime, title, prompt, image, network, memory, cpus, repo_url: repo,
        run_at: when ? new Date(when).getTime() / 1000 : null,
        repeat_secs: Number(every) || null,
        full_access: fullAccess && fullSure,
      });
      setPrompt(""); setTitle(""); setFullAccess(false); setFullSure(false); onCreated(run.id);
    } catch (e) { setErr(e instanceof Error ? e.message : "failed"); } finally { setBusy(false); }
  }

  return (
    <Card className="mb-5 p-4">
      <div className="mb-3 flex flex-wrap gap-2">
        {Object.entries(rt.runtimes).map(([id, r]) => (
          <button key={id} onClick={() => setRuntime(id)} title={r.note}
            className={`flex disabled:cursor-not-allowed disabled:opacity-50 items-center gap-2 rounded-xl border px-3 py-2 text-left text-[13px] ${runtime === id ? "border-ink bg-ink text-white" : "border-line-strong bg-white hover:border-ink/40"} ${r.available ? "" : "opacity-60"}`}>
            {id === "docker" ? <Container className="h-4 w-4" /> : <Bot className="h-4 w-4" />}{r.label}{!r.available && <span className="text-[10px]">off</span>}
            {r.open_weight && <span className={`rounded-full px-1.5 text-[10px] font-semibold ${runtime === id ? "bg-white/20" : "bg-good-bg text-good"}`}>open</span>}
          </button>
        ))}
        {Object.entries(rt.planned).map(([id, why]) => (
          <span key={id} title={why} className="flex cursor-help items-center gap-2 rounded-xl border border-dashed border-line-strong px-3 py-2 text-[13px] text-muted">
            {id} <span className="text-[10px]">adapter not built</span>
          </span>
        ))}
      </div>
      {info.status && (
        <p className="mb-1.5 flex items-center gap-1.5 text-[12px]">
          <span className={`h-2 w-2 rounded-full ${!info.status.installed ? "bg-bad" : info.status.signed_in === false ? "bg-warn" : info.status.signed_in ? "bg-good" : "bg-muted"}`} />
          <span className="font-medium">{!info.status.installed ? "Not installed" : info.status.signed_in === false ? "Not signed in" : info.status.signed_in ? "Installed and signed in" : "Installed"}</span>
          {info.status.detail && <span className="text-muted">{info.status.detail}</span>}
        </p>
      )}
      <RuntimeSwitch key={`${runtime}:${info.settings?.model ?? ""}`} id={runtime} info={info} onChanged={onSettingsChanged} />
      <p className="mb-3 text-[12px] text-body">{info.note} <span className="text-muted">
        Exposes: {Object.entries(info.exposes).map(([k, v]) => `${EXPOSES[k]} ${v ? "✓" : "✗"}`).join(" · ")}. Anything marked ✗ is shown as &ldquo;not exposed&rdquo;, never estimated.</span></p>

      <input className={`${input} mb-2`} placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea className={`${input} min-h-[70px] font-mono`} value={prompt} onChange={(e) => setPrompt(e.target.value)}
        placeholder={docker ? "Shell command to run in the container, e.g. python -c 'print(6*7)' > answer.txt" : runtime === "github" ? '{"action": "create_repo", "name": "my-repo", "description": "...", "private": true}' : `Describe the task for ${info.label}`} />

      {docker && (
        <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-[11px] font-semibold text-ink">Image<input className={`${input} mt-1 font-mono`} value={image} onChange={(e) => setImage(e.target.value)} /></label>
          <label className="text-[11px] font-semibold text-ink">Memory<input className={`${input} mt-1`} value={memory} onChange={(e) => setMemory(e.target.value)} /></label>
          <label className="text-[11px] font-semibold text-ink">CPUs<input className={`${input} mt-1`} value={cpus} onChange={(e) => setCpus(e.target.value)} /></label>
          <label className="text-[11px] font-semibold text-ink sm:col-span-2 lg:col-span-3">Repo to check out (https, optional; needs network on)
            <input className={`${input} mt-1 font-mono`} placeholder="https://github.com/owner/repo" value={repo} onChange={(e) => setRepo(e.target.value)} /></label>
          <label className="flex items-center gap-2 self-end pb-2 text-[12px]"><input type="checkbox" checked={network} onChange={(e) => setNetwork(e.target.checked)} /> Allow network</label>
        </div>
      )}
      <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-[11px] font-semibold text-ink">Start at (optional)<input type="datetime-local" className={`${input} mt-1`} value={when} onChange={(e) => setWhen(e.target.value)} /></label>
        <label className="text-[11px] font-semibold text-ink">Repeat<select className={`${input} mt-1`} value={every} onChange={(e) => setEvery(e.target.value)}>
          <option value="0">Once</option><option value="3600">Every hour</option><option value="86400">Every day</option><option value="604800">Every week</option></select></label>
      </div>
      {info.full_access?.supported && (
        <div className={`mt-3 rounded-xl border px-3 py-2.5 text-[12.5px] ${fullAccess ? "border-bad/40 bg-bad-bg" : "border-line bg-panel"}`}>
          <label className="flex items-center gap-2 font-medium">
            <input type="checkbox" disabled={!info.full_access.allowed} checked={fullAccess}
              onChange={(e) => { setFullAccess(e.target.checked); setFullSure(false); }} />
            Full PC access (no sandbox)
          </label>
          {!info.full_access.allowed && (
            <p className="mt-1 text-muted">Off. To allow it, set <code className="font-mono">ZYVEN_ALLOW_FULL_ACCESS=1</code> and restart Zyven. This is a deliberate step on the machine itself.</p>
          )}
          {fullAccess && (
            <>
              <p className="mt-1.5 text-bad">This task will not be sandboxed. It can read, change and delete any file your account can and run any program. A wrong or manipulated model can do real damage. It cannot repeat on a schedule.</p>
              <label className="mt-1.5 flex items-center gap-2"><input type="checkbox" checked={fullSure} onChange={(e) => setFullSure(e.target.checked)} /> I understand and want this task to run with full access.</label>
            </>
          )}
        </div>
      )}
      <div className="mt-3 flex items-center gap-3">
        <Button onClick={submit} loading={busy} disabled={!prompt.trim() || !info.available || (fullAccess && (!fullSure || Number(every) > 0))}>{when || Number(every) ? <Calendar className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}{when || Number(every) ? "Schedule task" : "Create task"}</Button>
        {!info.available && <span className="text-[12.5px] text-warn">This runtime is off. See the note above for how to turn it on.</span>}
        {err && <span className="text-[12.5px] text-bad">{err}</span>}
      </div>
    </Card>
  );
}

function ExportBar({ id }: { id: string }) {
  const [info, setInfo] = useState<{ export_dir: string | null; suggested: string } | null>(null);
  const [path, setPath] = useState("");
  const [editing, setEditing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<{ export_dir: string | null; suggested: string }>("/api/export-settings").then(setInfo).catch(() => {}); }, []);
  if (!info) return null;
  const save = async () => {
    setErr(null);
    try { const r = await post<{ export_dir: string }>("/api/export-settings", { export_dir: path }); setInfo({ ...info, export_dir: r.export_dir }); setEditing(false); }
    catch (e) { setErr(e instanceof Error ? e.message : "failed"); }
  };
  const copy = async () => {
    setErr(null); setMsg(null);
    try { const r = await post<{ copied: number; to: string }>(`/api/runs/${id}/export`); setMsg(`Copied ${r.copied} file${r.copied === 1 ? "" : "s"} to ${r.to}`); }
    catch (e) { setErr(e instanceof Error ? e.message : "failed"); }
  };
  return (
    <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[12px]">
      {info.export_dir && !editing ? (
        <>
          <button onClick={copy} className="rounded-lg bg-ink px-2.5 py-1 text-white">Save a copy to {info.export_dir.split(/[/\\]/).pop() || info.export_dir}</button>
          <button onClick={() => { setPath(info.export_dir ?? ""); setEditing(true); }} className="text-muted underline-offset-2 hover:underline">change folder</button>
        </>
      ) : (
        <>
          <input className={`${input} max-w-[360px] font-mono`} placeholder={`Existing folder, e.g. ${info.suggested}`} value={path} onChange={(e) => setPath(e.target.value)} />
          <button onClick={() => { setPath(info.suggested); }} className="text-muted underline-offset-2 hover:underline">use Desktop</button>
          <button onClick={save} disabled={!path.trim()} className="rounded-lg border border-line-strong px-2.5 py-1 hover:bg-panel-2 disabled:opacity-50">Set export folder</button>
        </>
      )}
      {msg && <span className="text-good">{msg}</span>}
      {err && <span className="text-bad">{err}</span>}
    </div>
  );
}

function Detail({ id, onClose, runtimes }: { id: string; onClose: () => void; runtimes: Record<string, RuntimeInfo> }) {
  const [run, setRun] = useState<Run | null>(null);
  useEffect(() => {
    let live = true;
    const tick = () => api<Run>(`/api/runs/${id}`).then((r) => live && setRun(r)).catch(() => {});
    tick();
    const t = setInterval(tick, 1500);
    return () => { live = false; clearInterval(t); };
  }, [id]);
  if (!run) return null;
  const active = ["RUNNING", "QUEUED", "SCHEDULED"].includes(run.status);
  const doneLine = [...(run.log ?? [])].reverse().find((l) => l.text.startsWith("done:"));
  const tokens = doneLine ? doneLine.text.replace(/^done:\s*/, "") : "";
  const toolCalls = (run.log ?? []).filter((l) => l.kind === "tool").length;
  return (
    <Card className="mb-5 overflow-hidden">
      <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <p className="truncate text-[14px] font-semibold">{run.title}</p>
          <p className="mt-0.5 font-mono text-[11px] text-muted">#{run.id} · {run.runtime}{run.runtime === "docker" ? ` · ${run.image} · network ${run.network ? "on" : "off"} · ${run.memory}/${run.cpus} cpu` : ""}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {run.full_access && <Badge tone="bad">full PC access</Badge>}<Badge tone={TONE[run.status]}>{run.status === "RUNNING" && <LiveDot />}{LABEL[run.status]}</Badge>
          {run.runtime !== "zyven" && active && <Button size="sm" variant="danger" onClick={() => post(`/api/runs/${id}/cancel`)}><Square className="h-3 w-3" /> Cancel</Button>}
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted hover:bg-panel-2" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
      </div>
      {run.runtime === "zyven" ? (
        <div className="px-4 py-3 text-[13px]">
          <p className="text-body">Runs on the Zyven agent. Full timeline, approvals and compile gates are on the <a className="text-info underline" href="/app/">Tasks</a> board.</p>
          {run.answer && <div className="mt-2 whitespace-pre-wrap rounded-xl border border-good/30 bg-good-bg px-3 py-2">{run.answer}</div>}
        </div>
      ) : (
        <>
          <pre className="m-0 max-h-[320px] overflow-auto bg-ink px-4 py-3 font-mono text-[12px] leading-relaxed text-[#e9e7e1]">
            {(run.log ?? []).map((l, i) => <div key={i} className={l.kind === "error" ? "text-[#f0a0a0]" : l.kind === "info" ? "text-[#8d8b84]" : l.kind === "tool" ? "text-[#9db8e8]" : ""}>{l.kind === "info" ? "# " : l.kind === "tool" ? "» " : ""}{l.text}</div>)}
            {!run.log?.length && <span className="text-[#8d8b84]"># waiting for output…</span>}
          </pre>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2.5 text-[12px] text-body">
            <span>Exit code: <b className="font-mono">{run.exit_code ?? "—"}</b></span>
            <span>Token usage: {tokens ? <b className="font-mono">{tokens}</b> : <i className="text-muted">not exposed</i>}</span>
            <span>Tool calls: {runtimes[run.runtime]?.exposes?.tool_calls ? <b className="font-mono">{toolCalls}</b> : <i className="text-muted">not exposed</i>}</span>
          </div>
          {run.files && (
            <div className="border-t border-line px-4 py-3 text-[12.5px]">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Eyebrow>Changed files</Eyebrow>
                {run.files.added.length + run.files.modified.length > 0 && (
                  <span className="flex gap-2">
                    <a href={`/api/runs/${id}/archive`} className="rounded-lg border border-line-strong px-2.5 py-1 text-[12px] hover:bg-panel-2">Download all (.zip)</a>
                    <button onClick={() => post(`/api/runs/${id}/reveal`).catch(() => {})} className="rounded-lg border border-line-strong px-2.5 py-1 text-[12px] hover:bg-panel-2">Open folder</button>
                  </span>
                )}
              </div>
              {run.files.added.length + run.files.modified.length === 0 ? <p className="mt-1 text-muted">No files changed.</p> : (
                <ul className="mt-1.5 space-y-0.5 font-mono text-[12px]">
                  {run.files.added.map((f) => <li key={f} className="text-good">+ <a className="underline-offset-2 hover:underline" href={`/api/runs/${id}/files/${f}`}>{f}</a></li>)}
                  {run.files.modified.map((f) => <li key={f} className="text-warn">~ <a className="underline-offset-2 hover:underline" href={`/api/runs/${id}/files/${f}`}>{f}</a></li>)}
                </ul>
              )}
              {run.files.added.length + run.files.modified.length > 0 && <ExportBar id={id} />}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

interface Approval { id: string; run: string; kind: string; summary: string; detail: string; created: number }

function Approvals({ items, onDecided }: { items: Approval[]; onDecided: () => void }) {
  if (!items.length) return null;
  const decide = (id: string, approved: boolean) => post(`/api/approvals/${id}`, { approved }).then(onDecided).catch(onDecided);
  return (
    <Card className="mb-5 border-warn/40 p-4">
      <Eyebrow>Waiting for your approval</Eyebrow>
      <p className="mt-1 text-[12px] text-muted">An agent wants to do something outside its sandbox. Nothing happens unless you approve; unanswered requests are denied after an hour.</p>
      <div className="mt-3 space-y-2.5">
        {items.map((a) => (
          <div key={a.id} className="rounded-xl border border-line bg-white p-3">
            <p className="text-[13px] font-medium">{a.summary} <span className="ml-1 rounded-full bg-panel-2 px-1.5 font-mono text-[10px] text-muted">{a.kind}</span></p>
            {a.detail && <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-panel px-2.5 py-2 font-mono text-[11.5px]">{a.detail}</pre>}
            <div className="mt-2.5 flex items-center gap-2">
              <Button size="sm" onClick={() => decide(a.id, true)}><Check className="h-3 w-3" /> Approve</Button>
              <Button size="sm" variant="danger" onClick={() => decide(a.id, false)}><X className="h-3 w-3" /> Deny</Button>
              <span className="font-mono text-[11px] text-muted">run #{a.run} · {relTime(a.created)}</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

const COLUMNS: { title: string; statuses: string[] }[] = [
  { title: "Running", statuses: ["RUNNING", "QUEUED"] },
  { title: "Needs approval", statuses: ["NEEDS_APPROVAL"] },
  { title: "Scheduled", statuses: ["SCHEDULED"] },
  { title: "Finished", statuses: ["COMPLETED", "FAILED", "CANCELLED"] },
];

export function Control() {
  const [rt, setRt] = useState<Runtimes | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [pending, setPending] = useState<Approval[]>([]);
  const load = useCallback(() => {
    api<Run[]>("/api/runs").then(setRuns).catch(() => {});
    api<Approval[]>("/api/approvals").then(setPending).catch(() => {});
  }, []);
  useEffect(() => {
    const loadRuntimes = () => api<Runtimes>("/api/runtimes").then(setRt).catch(() => {});
    loadRuntimes();
    load();
    const t = setInterval(load, 2000);
    const t2 = setInterval(loadRuntimes, 8000);  // sign-in checks finish in the background; pick up the answer
    return () => { clearInterval(t); clearInterval(t2); };
  }, [load]);
  if (!rt) return <Hero eyebrow="Control center" title="Loading…" />;
  const count = (s: string[]) => runs.filter((r) => s.includes(r.status)).length;

  return (
    <>
      <Hero eyebrow="Control center" title={<>Assign work. <span className="text-muted">Watch it run.</span></>}
        sub="Create a task, pick a runtime and an isolated environment, then follow the run live. Each runtime reports only what it truly exposes. Open-weight by default." />
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat value={count(["RUNNING", "QUEUED"])} label="Running" icon={<LiveDot />} />
        <Stat value={count(["NEEDS_APPROVAL"])} label="Needs approval" />
        <Stat value={count(["SCHEDULED"])} label="Scheduled" icon={<Calendar className="h-3.5 w-3.5" />} />
        <Stat value={count(["COMPLETED"])} label="Completed" icon={<Check className="h-3.5 w-3.5" />} />
      </div>
      <Approvals items={pending} onDecided={load} />
      <NewTask rt={rt} onCreated={(id) => { setSel(id); load(); }} onSettingsChanged={() => api<Runtimes>("/api/runtimes").then(setRt).catch(() => {})} />
      {sel && <Detail id={sel} onClose={() => setSel(null)} runtimes={rt.runtimes} />}
      {runs.length === 0 ? (
        <Empty seed="control" title="No tasks yet" body="Create a Docker task above, for example a command that writes a file, and watch the output stream in live." />
      ) : (
        <div className="grid gap-3.5 lg:grid-cols-4">
          {COLUMNS.map((col) => (
            <div key={col.title} className="rounded-2xl border border-line bg-panel p-3">
              <p className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">{col.title}<span>{count(col.statuses)}</span></p>
              <div className="space-y-2">
                {runs.filter((r) => col.statuses.includes(r.status)).map((r) => (
                  <button key={r.id} onClick={() => setSel(r.id)} className={`w-full rounded-xl border bg-white p-3 text-left transition-colors hover:border-ink/40 ${sel === r.id ? "border-ink" : "border-line"}`}>
                    <p className="line-clamp-2 text-[13px] font-medium">{r.title}</p>
                    <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                      <Badge tone={TONE[r.status]}>{LABEL[r.status]}</Badge>{r.full_access && <Badge tone="bad">full PC access</Badge>}{r.runtime === "docker" ? "Docker" : r.runtime === "zyven" ? "Zyven agent" : r.runtime} · {r.status === "SCHEDULED" && r.run_at ? new Date(r.run_at * 1000).toLocaleTimeString() : relTime(r.created)}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
