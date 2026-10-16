import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, Check, LayoutGrid, Loader2, Plus, Send, Shield, Sparkles, Terminal, X, Zap } from "lucide-react";
import { Badge, Button, Card, Empty, Eyebrow, Hero, LiveDot, Skeleton, Stat, ToolChip, ArtFrame } from "../components/ui";
import { DriftingOrb, Reveal, Star, Stars } from "../components/motion";
import { EXAMPLES, LIVE_STATES, STATUS, eventDetail, eventLabel, eventTone, relTime } from "../lib/labels";
import { post } from "../lib/api";
import type { Card as TaskCard, Skill } from "../lib/types";

/* ── live agent banner: painted art with frosted rows ─────────────────────── */
function AgentBanner({ cards, skills }: { cards: TaskCard[]; skills: Skill[] }) {
  const active = cards.find((c) => LIVE_STATES.has(c.status));
  const pending = cards.find((c) => c.status === "NEEDS_APPROVAL");
  const row = "frost flex items-center justify-between gap-3 rounded-[14px] px-3.5 py-2.5 text-[13.5px] text-ink shadow-[0_1px_2px_rgba(20,20,19,0.08)]";

  let pill: React.ReactNode;
  let rows: React.ReactNode;
  if (pending) {
    const ev = [...(pending.events ?? [])].reverse().find((e) => e.kind === "NEEDS_APPROVAL");
    const r = ev?.data.request ?? {};
    pill = <><Shield className="h-3.5 w-3.5" /> Waiting for your approval</>;
    rows = (
      <>
        <div className={row}>
          <span className="min-w-0 truncate">{r.capability_title ?? "a capability"} from <span className="font-mono">{String(r.repo_url ?? "").replace("https://github.com/", "")}</span></span>
          <span className="shrink-0 text-muted">{r.license}</span>
        </div>
        <div className={row}><span>Nothing compiles until you approve it below</span><span className="shrink-0 text-muted">human in the loop</span></div>
      </>
    );
  } else if (active) {
    const last = active.events?.[active.events.length - 1];
    pill = <><LiveDot className="text-clay" /> Agent {(STATUS[active.status]?.label ?? active.status).toLowerCase()}</>;
    rows = (
      <>
        <div className={row}><span className="min-w-0 truncate">{active.task}</span><span className="shrink-0 font-mono text-muted">#{active.id}</span></div>
        <div className={row}>
          <span className="min-w-0 truncate">{(last && (last.data.detail || last.data.reason)) || "working…"}</span>
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted" />
        </div>
      </>
    );
  } else {
    pill = <><Bot className="h-3.5 w-3.5" /> Agent idle · {skills.length} skill{skills.length === 1 ? "" : "s"} in library</>;
    rows = (
      <>
        <div className={row}><span>Ready for the next task, learned skills load instantly</span><span className="inline-flex shrink-0 items-center gap-1 text-muted"><Zap className="h-3.5 w-3.5" /> reuse</span></div>
        {skills.length > 0 && <div className={row}><span className="min-w-0 truncate">{skills.map((s) => s.name).join(" · ")}</span><span className="shrink-0 text-muted">verified</span></div>}
      </>
    );
  }
  const working = Boolean(active || pending);
  return (
    <ArtFrame seed={active ? active.id : `idle${skills.length}`} className="grain mb-5 min-h-[148px] rounded-[28px] p-5 sm:p-6">
      {working && <DriftingOrb className="opacity-60 mix-blend-soft-light" />}
      <Stars seed={active ? active.id : "idle"} count={working ? 12 : 8} from={62} to={96} />
      <div className="relative z-10 flex max-w-[600px] flex-col gap-2.5">
        <span className="frost inline-flex w-fit items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] font-medium text-ink">{pill}</span>
        {rows}
      </div>
    </ArtFrame>
  );
}

/* ── composer ─────────────────────────────────────────────────────────────── */
function Composer({ prefill, onPrefillUsed }: { prefill: string; onPrefillUsed: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!prefill) return;
    setText(prefill);
    onPrefillUsed();
    ref.current?.focus();
  }, [prefill, onPrefillUsed]);

  async function run() {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await post("/api/cards", { task: text.trim() });
      setText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit the task");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-5 p-4">
      <textarea
        ref={ref}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); }}
        placeholder="Describe a task for the agent, e.g. a Bikram Sambat date, an IBAN check, or a phone number lookup…"
        className="min-h-[66px] w-full resize-y rounded-xl border border-line-strong/80 bg-white px-3.5 py-2.5 text-[14px] text-ink placeholder:text-[#aaa79f] transition-colors focus:border-ink focus:outline-none focus:ring-1 focus:ring-ink"
      />
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button key={ex.label} type="button" onClick={() => setText(ex.text)}
              className="rounded-full border border-line bg-panel px-2.5 py-1 text-[11.5px] text-body transition-colors hover:border-line-strong hover:bg-white hover:text-ink">
              {ex.label}
            </button>
          ))}
        </div>
        <Button onClick={run} loading={busy} disabled={!text.trim()}><Send className="h-3.5 w-3.5" /> Run task</Button>
      </div>
      <p className="mt-2 font-mono text-[11px] text-muted">⌘/Ctrl + ↵ to run</p>
      {error && <p className="mt-2 text-[12.5px] text-bad">{error}</p>}
    </Card>
  );
}

/* ── AI marks and gate progress ───────────────────────────────────────────── */
const AI_STEPS = /^(GAP_CHECK|SEARCHING|DONE|compile\.(architect|compiler|tester|repair)\.)/;
const GATES_TOTAL = 6;

/** Gates of the most recent verify attempt: how many ran, how many passed, whether any failed. */
function gateProgress(events: TaskCard["events"]) {
  const evs = events ?? [];
  let start = -1;
  evs.forEach((e, i) => { if (e.kind === "compile.verify.start" || e.kind === "compile.verify.partial") start = i; });
  if (start < 0) return null;
  const after = evs.slice(start + 1);
  const gates = after.filter((e) => e.kind.startsWith("compile.gate."));
  // Once the attempt has finished, its own gate count is the total (older compiles ran fewer gates).
  const finished = after.some((e) => e.kind === "compile.done" || e.kind === "compile.repair.start" || e.kind === "compile.verify.partial");
  return {
    ran: gates.length,
    total: finished && gates.length ? gates.length : GATES_TOTAL,
    passed: gates.filter((g) => g.data.passed === true).length,
    failed: gates.some((g) => g.data.passed === false),
  };
}

function GateBar({ events, live }: { events: TaskCard["events"]; live: boolean }) {
  const g = gateProgress(events);
  if (!g) return null;
  const pct = Math.round((g.passed / g.total) * 100);
  const color = g.failed ? "bg-bad/70" : g.passed === g.total ? "bg-good" : "bg-ink/70";
  return (
    <div className="mt-3.5" aria-label={`Sandbox gates passed: ${g.passed} of ${g.total}`}>
      <div className="mb-1.5 flex items-center justify-between text-[11.5px] text-muted">
        <span className="inline-flex items-center gap-1.5 font-medium text-body"><Shield className="h-3 w-3" /> Sandbox gates</span>
        <span className="tabular-nums">{g.passed}/{g.total}{g.failed ? " · a gate failed" : live && g.ran < g.total ? " · running" : ""}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-panel-2">
        <div className={`h-full origin-left animate-[grow_0.9s_cubic-bezier(0.16,1,0.3,1)_both] rounded-full transition-[width] duration-700 ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/* ── one task card ────────────────────────────────────────────────────────── */
function ApprovalPanel({ card }: { card: TaskCard }) {
  const [busy, setBusy] = useState(false);
  const ev = [...(card.events ?? [])].reverse().find((e) => e.kind === "NEEDS_APPROVAL");
  if (!ev) return null;
  const r = ev.data.request ?? {};
  const need = r.need ?? {};
  async function decide(approved: boolean) {
    setBusy(true);
    try { await post(`/api/cards/${card.id}/decision`, { approved }); } finally { setBusy(false); }
  }
  const dt = "whitespace-nowrap font-medium text-muted";
  return (
    <div className="mt-4 rounded-[14px] border border-warn/30 bg-warn-bg px-4 py-3.5">
      <p className="flex items-center gap-2 text-[13px] font-semibold text-warn"><Shield className="h-4 w-4" /> Approval needed, nothing compiles until you decide</p>
      <dl className="my-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-[13px]">
        <dt className={dt}>Missing</dt><dd className="break-words">{need.description}</dd>
        {need.why_needed && <><dt className={dt}>Why</dt><dd className="break-words">{need.why_needed}</dd></>}
        <dt className={dt}>Capability</dt><dd className="break-words"><strong>{r.capability_title}</strong> · {r.capability_description}</dd>
        <dt className={dt}>Source</dt>
        <dd className="break-words">
          <a className="text-info underline underline-offset-2" href={r.repo_url} target="_blank" rel="noopener noreferrer">{r.repo_url}</a>{" "}
          <span className="font-mono text-[11px]">@ {String(r.commit ?? "").slice(0, 7)}</span>
        </dd>
        <dt className={dt}>License</dt><dd>{r.license}</dd>
        {r.match_reason && <><dt className={dt}>Match</dt><dd className="break-words">{r.match_reason}</dd></>}
        <dt className={dt}>Sandbox</dt><dd>Compiled to an MCP tool and verified offline (no network, non-root, upstream tests) before the agent can use it.</dd>
      </dl>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy} onClick={() => decide(true)}><Check className="h-3.5 w-3.5" /> Approve &amp; compile</Button>
        <Button size="sm" variant="danger" disabled={busy} onClick={() => decide(false)}><X className="h-3.5 w-3.5" /> Reject</Button>
      </div>
    </div>
  );
}

function TaskItem({ card }: { card: TaskCard }) {
  const events = card.events ?? [];
  const st = STATUS[card.status] ?? { label: card.status, tone: "neutral" as const };
  const live = LIVE_STATES.has(card.status);
  const pending = card.status === "NEEDS_APPROVAL";
  const last = events[events.length - 1];
  const gap = events.find((e) => e.kind === "GAP_CHECK");
  const plan: string[] = Array.isArray(gap?.data.plan) ? gap!.data.plan : [];
  const done = events.find((e) => e.kind === "DONE");
  const toolCalls: [string, unknown][] = Array.isArray(done?.data.tool_calls) ? done!.data.tool_calls : [];
  const dur = card.updated && card.created ? Math.max(0, Math.round(card.updated - card.created)) : null;

  return (
    <article className={`rounded-2xl border bg-white p-[18px] ${pending ? "border-warn/40 shadow-[0_0_0_3px_rgba(138,90,18,0.07)]" : "border-line"}`}>
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 flex-1 text-[14.5px] font-medium leading-normal [overflow-wrap:anywhere]">{card.task}</p>
        <Badge tone={st.tone}>{live && <LiveDot />}{st.label}</Badge>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-muted">
        <span className="font-mono">#{card.id}</span><span className="opacity-50">·</span>
        <span>{relTime(card.created)}</span>
        {dur != null && ["DONE", "FAILED"].includes(card.status) && <><span className="opacity-50">·</span><span>{dur}s</span></>}
      </div>

      {live && (
        <div className="mt-3.5 flex items-center gap-3 rounded-2xl border border-line bg-panel px-4 py-3 animate-fade-in">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink text-white"><Loader2 className="h-4 w-4 animate-spin" /></span>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold">{st.label}</p>
            <p className="truncate text-[12px] text-muted">{(last && (last.data.detail || last.data.reason)) || "waiting…"}</p>
          </div>
        </div>
      )}

      {plan.length > 0 && (
        <div className="mt-3.5 rounded-[14px] border border-line bg-panel px-3.5 py-3">
          <Eyebrow>Agent's plan</Eyebrow>
          <ol className="mb-0 mt-1.5 list-decimal pl-5 text-[13px] leading-relaxed text-body">{plan.map((p, i) => <li key={i}>{p}</li>)}</ol>
        </div>
      )}

      {events.length > 0 && (
        <ul className="timeline mt-3.5 list-none pl-1">
          {events.map((e, i) => {
            const sub = e.kind.startsWith("compile.");
            const detail = eventDetail(e);
            return (
              <li key={i} className={`${eventTone(e)}${sub ? " sub" : ""}`}>
                {AI_STEPS.test(e.kind) && <Star className="mr-1 inline h-2.5 w-2.5 -translate-y-px text-clay" />}
                <span className="font-semibold">{eventLabel(e.kind)}</span>
                {detail && <span className="text-muted [overflow-wrap:anywhere]"> — {detail}</span>}
              </li>
            );
          })}
        </ul>
      )}

      <GateBar events={events} live={live} />

      {pending && <ApprovalPanel card={card} />}

      {card.status === "DONE" && card.answer && (
        <div className="mt-4 rounded-[14px] border border-good/30 bg-good-bg px-4 py-3.5">
          <p className="flex items-center gap-2 text-[13px] font-semibold text-good"><Check className="h-4 w-4" /> Answer</p>
          <div className="mt-2 whitespace-pre-wrap text-[13.5px] [overflow-wrap:anywhere]">{card.answer}</div>
          {toolCalls.length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {toolCalls.map((t, i) => <ToolChip key={i}><Terminal className="h-3 w-3" />{String(t[0])}</ToolChip>)}
            </div>
          )}
        </div>
      )}

      {(card.learned?.length > 0 || card.reused?.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {card.learned.map((s) => <Badge key={`l${s}`} tone="good"><Plus className="h-3 w-3" /> learned: {s}</Badge>)}
          {card.reused.map((s) => <Badge key={`r${s}`} tone="info"><Zap className="h-3 w-3" /> reused: {s}</Badge>)}
        </div>
      )}
    </article>
  );
}

/* ── view ─────────────────────────────────────────────────────────────────── */
export function Tasks({ cards, skills, loaded }: { cards: TaskCard[]; skills: Skill[]; loaded: boolean }) {
  const [prefill, setPrefill] = useState("");
  const clearPrefill = useCallback(() => setPrefill(""), []);
  const reuses = cards.reduce((n, c) => n + (c.reused?.length ?? 0), 0);
  const approvals = cards.reduce((n, c) => n + (c.events ?? []).filter((e) => e.kind === "approval.decision" && String(e.data.detail ?? "").startsWith("approved")).length, 0);

  return (
    <>
      <Hero
        eyebrow="Task board"
        title={<>Give the agent work.<br />It grows the tools it needs.</>}
        sub="When the agent lacks a capability, Zyven finds it in pinned open-source code. You approve, a verified MCP tool is compiled in a sandbox, and it's hot-loaded mid-task. Learned skills are reused forever."
      />
      <Reveal delay={200}><AgentBanner cards={cards} skills={skills} /></Reveal>
      <Reveal delay={280}><Composer prefill={prefill} onPrefillUsed={clearPrefill} /></Reveal>

      <Reveal delay={340}>
        <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat value={cards.length} label="Tasks run" icon={<LayoutGrid className="h-3.5 w-3.5" />} />
          <Stat value={skills.length} label="Skills in library" icon={<Sparkles className="h-3.5 w-3.5" />} />
          <Stat value={reuses} label="Skill reuses" icon={<Zap className="h-3.5 w-3.5" />} />
          <Stat value={approvals} label="Approvals given" icon={<Shield className="h-3.5 w-3.5" />} />
        </div>
      </Reveal>

      {!loaded ? (
        <div className="space-y-3.5"><Skeleton className="h-[120px]" /><Skeleton className="h-[120px]" /></div>
      ) : cards.length === 0 ? (
        <Empty seed="tasks" title="No tasks yet"
          body="Give the agent something that needs a capability it doesn't have, like a Bikram Sambat date or an IBAN check. Watch it notice the gap, ask you to approve a compile, and finish with tools it just built."
          action={<Button size="sm" onClick={() => setPrefill(EXAMPLES[0].text)}>Use the first example</Button>} />
      ) : (
        <div className="flex flex-col gap-3.5">
          {cards.map((c, i) => <Reveal key={c.id} delay={Math.min(i, 5) * 70}><TaskItem card={c} /></Reveal>)}
        </div>
      )}
    </>
  );
}
