"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Plug, Trash2 } from "lucide-react";
import { Badge, Button, Card, Empty, Eyebrow, Hero } from "../components/ui";
import { api, post } from "../lib/api";

interface Tool { name: string; description: string; needs_approval: boolean }
interface Conn {
  id: string; name: string; kind: "http" | "stdio"; url?: string; command?: string; args?: string[];
  enabled: boolean; tools: Tool[] | null; error: string | null; secret_names: string[]; oauth?: boolean; signed_in?: boolean; signing_in?: boolean;
}
interface Template { id: string; label: string; kind: "http" | "stdio"; oauth?: boolean; hint: string; url: string; command: string; args: string[]; secrets: string[] }
interface Data { connections: Conn[]; templates: Template[]; stdio_allowed: boolean }

const input = "w-full rounded-xl border border-line-strong/80 bg-white px-3 py-2 text-[13px] text-ink placeholder:text-[#aaa79f] focus:border-ink focus:outline-none focus:ring-1 focus:ring-ink";

function AddConnection({ data, onAdded }: { data: Data; onAdded: () => void }) {
  const [tpl, setTpl] = useState<Template | null>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function pick(t: Template) {
    setTpl(t); setName(t.label); setUrl(t.url); setCommand(t.command); setArgs(t.args.join(" ")); setSecrets({});
    setClientId(""); setClientSecret(""); setErr(null);
  }
  async function submit() {
    if (!tpl) return;
    setBusy(true); setErr(null);
    try {
      await post("/api/connections", {
        name, kind: tpl.kind, url, command, args: args.split(/\s+/).filter(Boolean), secrets,
        oauth: !!tpl.oauth, oauth_client_id: clientId, oauth_client_secret: clientSecret,
      });
      setTpl(null); onAdded();
    } catch (e) { setErr(e instanceof Error ? e.message : "failed"); } finally { setBusy(false); }
  }

  return (
    <Card className="mb-5 p-4">
      <Eyebrow>Add a connection</Eyebrow>
      <div className="mt-2.5 flex flex-wrap gap-2">
        {data.templates.map((t) => {
          const off = !t.oauth && t.kind === "stdio" && !data.stdio_allowed;
          return (
            <button key={t.id} onClick={() => pick(t)} title={off ? "Local commands are off. Set ZYVEN_ALLOW_STDIO_CONNECTORS=1 to allow them." : t.hint}
              className={`rounded-xl border px-3 py-2 text-left text-[13px] ${tpl?.id === t.id ? "border-ink bg-ink text-white" : "border-line-strong bg-white hover:border-ink/40"} ${off ? "opacity-50" : ""}`}>
              {t.label}{t.oauth && <span className="ml-1.5 text-[10px]">sign in</span>}{off && <span className="ml-1.5 text-[10px]">off</span>}
            </button>
          );
        })}
      </div>
      {tpl && (
        <div className="mt-3">
          <p className="mb-2.5 text-[12px] text-body">{tpl.hint}</p>
          <div className="grid gap-2.5 sm:grid-cols-2">
            <label className="text-[11px] font-semibold text-ink">Name<input className={`${input} mt-1`} value={name} onChange={(e) => setName(e.target.value)} /></label>
            {tpl.kind === "http" ? (
              <label className="text-[11px] font-semibold text-ink">Server URL<input className={`${input} mt-1 font-mono`} placeholder="https://…/mcp" value={url} onChange={(e) => setUrl(e.target.value)} /></label>
            ) : (
              <>
                <label className="text-[11px] font-semibold text-ink">Command<input className={`${input} mt-1 font-mono`} value={command} onChange={(e) => setCommand(e.target.value)} /></label>
                <label className="text-[11px] font-semibold text-ink sm:col-span-2">Arguments<input className={`${input} mt-1 font-mono`} value={args} onChange={(e) => setArgs(e.target.value)} /></label>
              </>
            )}
            {tpl.oauth && (
              <>
                <label className="text-[11px] font-semibold text-ink">OAuth client ID <span className="font-normal text-muted">(only if the service needs you to register an app)</span>
                  <input className={`${input} mt-1 font-mono`} value={clientId} onChange={(e) => setClientId(e.target.value)} /></label>
                <label className="text-[11px] font-semibold text-ink">OAuth client secret <span className="font-normal text-muted">(kept on this machine)</span>
                  <input type="password" autoComplete="off" className={`${input} mt-1 font-mono`} value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} /></label>
              </>
            )}
            {tpl.secrets.map((k) => (
              <label key={k} className="text-[11px] font-semibold text-ink">{k} <span className="font-normal text-muted">(kept on this machine, never shown again)</span>
                <input type="password" autoComplete="off" className={`${input} mt-1 font-mono`} value={secrets[k] ?? ""} onChange={(e) => setSecrets({ ...secrets, [k]: e.target.value })} /></label>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-3">
            <Button onClick={submit} loading={busy} disabled={!name.trim() || (tpl.kind === "http" ? !url.trim() : !command.trim())}><Plug className="h-3.5 w-3.5" /> Add connection</Button>
            {err && <span className="text-[12.5px] text-bad">{err}</span>}
          </div>
        </div>
      )}
    </Card>
  );
}

function ConnCard({ c, onChange }: { c: Conn; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await fn(); } catch (e) { setErr(e instanceof Error ? e.message : "failed"); } finally { setBusy(false); onChange(); }
  };
  const asks = c.tools?.filter((t) => t.needs_approval).length ?? 0;
  const signIn = () => run(async () => {
    const r = await post<{ url: string | null }>(`/api/connections/${c.id}/signin`);
    if (r.url) window.open(r.url, "_blank", "noopener");
  });
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[14px] font-semibold">{c.name}</p>
          <p className="mt-0.5 truncate font-mono text-[11px] text-muted">{c.kind === "http" ? c.url : `${c.command} ${(c.args ?? []).join(" ")}`}</p>
          {c.secret_names.length > 0 && <p className="mt-0.5 text-[11px] text-muted">Stored here: {c.secret_names.join(", ")}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge tone={c.enabled ? "good" : c.error ? "bad" : "neutral"}>{c.enabled ? "On" : c.signing_in ? "Signing in" : c.error ? "Failed" : c.oauth && !c.signed_in ? "Not signed in" : c.tools ? "Tested, off" : "Not tested"}</Badge>
          {c.oauth && !c.signed_in && <Button size="sm" loading={busy || !!c.signing_in} onClick={signIn}>{c.signing_in ? "Waiting for you…" : "Sign in"}</Button>}
          {c.oauth && c.signed_in && <Button size="sm" variant="secondary" onClick={() => run(() => post(`/api/connections/${c.id}/signout`))}>Sign out</Button>}
          {(!c.oauth || c.signed_in) && <Button size="sm" variant="secondary" loading={busy} onClick={() => run(() => post(`/api/connections/${c.id}/test`))}>Test</Button>}
          {c.tools && <Button size="sm" onClick={() => run(() => post(`/api/connections/${c.id}/enabled`, { enabled: !c.enabled }))}>{c.enabled ? "Turn off" : "Turn on"}</Button>}
          <button aria-label="Remove" onClick={() => run(() => api(`/api/connections/${c.id}`, { method: "DELETE" }))} className="rounded-lg p-1.5 text-muted hover:bg-panel-2"><Trash2 className="h-4 w-4" /></button>
        </div>
      </div>
      {c.signing_in && <p className="mt-2 text-[12px] text-body">Finish signing in on the page that opened. If you pressed Sign in more than once, use the newest tab and close the others.</p>}
      {(err || c.error) && <p className="mt-2 break-words rounded-lg bg-bad-bg px-3 py-2 font-mono text-[11.5px] text-bad">{err ?? c.error}</p>}
      {c.tools && (
        <div className="mt-3 border-t border-line pt-3">
          <p className="text-[12px] text-body">{c.tools.length} tools. <b>{asks}</b> will ask for your approval before they run; the rest only read.</p>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
            {c.tools.map((t) => (
              <li key={t.name} title={t.description} className="flex items-center gap-1.5 font-mono text-[11.5px]">
                {t.needs_approval ? <span className="rounded-full bg-warn-bg px-1.5 text-[10px] font-semibold text-warn">asks</span> : <Check className="h-3 w-3 text-good" />}{t.name}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

export function Connections() {
  const [data, setData] = useState<Data | null>(null);
  const load = useCallback(() => api<Data>("/api/connections").then(setData).catch(() => {}), []);
  useEffect(() => {
    load();
    const t = setInterval(load, 2500); // a sign-in finishes in another tab; pick it up without a reload
    return () => clearInterval(t);
  }, [load]);
  if (!data) return <Hero eyebrow="Connections" title="Loading…" />;
  return (
    <>
      <Hero eyebrow="Connections" title={<>Connect your tools. <span className="text-muted">Approve what they do.</span></>}
        sub="Connect any MCP server, then test it to see exactly which tools it offers. Tools that only read run freely; anything that writes, sends or deletes asks you first. Keys stay on this machine." />
      <AddConnection data={data} onAdded={load} />
      {data.connections.length === 0 ? (
        <Empty seed="connections" title="Nothing connected yet" body="Pick a template above, add your key, then press Test to see what the connection can do." />
      ) : (
        <div className="space-y-3">{data.connections.map((c) => <ConnCard key={c.id} c={c} onChange={load} />)}</div>
      )}
    </>
  );
}
