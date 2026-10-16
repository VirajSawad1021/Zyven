"use client";

import { useRef, useState } from "react";
import { Bot, Check, ChevronDown, Clock, LayoutGrid, Loader2, Plus, Send, Shield, Sparkles, Terminal, X, Zap } from "lucide-react";
import { Badge, Button, Card, Empty, Hero, LiveDot, Skeleton, ToolChip, ArtFrame } from "../components/ui";
import { CountUp, DriftingOrb, Reveal, Star, Stars } from "../components/motion";
import { Markdown } from "../components/Markdown";
import { EXAMPLES, LIVE_STATES, STATUS, eventDetail, eventLabel, eventTone, relTime } from "../lib/labels";
import { post } from "../lib/api";
import type { CatalogRepo, Card as TaskCard, Skill } from "../lib/types";

const fmtDur = (s: number) => (s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`);

/* ── live agent panel: painted art with frosted rows ──────────────────────── */
function AgentPanel({ cards, skills }: { cards: TaskCard[]; skills: Skill[] }) {
  const active = cards.find((c) => LIVE_STATES.has(c.status));
  const pending = cards.find((c) => c.status === "NEEDS_APPROVAL");
  const row = "frost flex items-center justify-between gap-3 rounded-[14px] px-3.5 py-2.5 text-[13px] text-ink shadow-[0_1px_2px_rgba(20,20,19,0.08)]";

  let pill: React.ReactNode;
  let rows: React.ReactNode;
  if (pending) {
    const ev = [...(pending.events ?? [])].reverse().find((e) => e.kind === "NEEDS_APPROVAL");
    const r = ev?.data.request ?? {};
    pill = <><Shield className="h-3.5 w-3.5" /> Waiting for your approval</>;
    rows = (
      <>
        <div className={row}><span className="min-w-0 truncate">{r.capability_title ?? "a capability"}</span><span className="shrink-0 text-muted">{r.license}</span></div>
        <div className={row}><span className="min-w-0 truncate font-mono text-[12px]">{String(r.repo_url ?? "").replace("https://github.com/", "")}</span></div>
      </>
    );
  } else if (active) {
    const last = active.events?.[active.events.length - 1];
    pill = <><LiveDot className="text-clay" /> {(STATUS[active.status]?.label ?? active.status)}</>;
    rows = (
      <>
        <div className={row}><span className="min-w-0 truncate">{active.task}</span></div>
        <div className={row}>
          <span className="min-w-0 truncate">{(last && (last.data.detail || last.data.reason)) || "working…"}</span>
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted" />
        </div>
      </>
    );
  } else {
    pill = <><Bot className="h-3.5 w-3.5" /> Agent idle</>;
    rows = (
      <div className={row}><span>Ready. Learned skills load instantly.</span><Zap className="h-3.5 w-3.5 shrink-0 text-muted" /></div>
    );
  }
  const working = Boolean(active || pending);
  return (
    <ArtFrame seed={active ? active.id : `idle${skills.length}`} className="grain min-h-[170px] rounded-[24px] p-4">
      {working && <DriftingOrb className="opacity-60 mix-blend-soft-light" />}
      <Stars seed={active ? active.id : "idle"} count={working ? 10 : 7} from={50} to={96} />
      <div className="relative z-10 flex flex-col gap-2">
        <span className="frost inline-flex w-fit items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] font-medium text-ink">{pill}</span>
        {rows}
      </div>
    </ArtFrame>
  );
}

/* ── composer ─────────────────────────────────────────────────────────────── */
function Composer({ text, setText, inputRef }: { text: string; setText: (t: string) => void; inputRef: React.RefObject<HTMLTextAreaElement | null> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    <Card className="p-2 shadow-[0_10px_30px_-22px_rgba(20,20,19,0.45)] focus-within:border-ink/40">
      <textarea
        ref={inputRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); }}
        placeholder="Give the agent a task: a Hijri date, an IBAN check, a phone number in E.164…"
        aria-label="Task for the agent"
        className="min-h-[76px] w-full resize-none rounded-xl bg-transparent px-3 py-2.5 text-[14.5px] text-ink placeholder:text-[#aaa79f] focus:outline-none"
      />
      <div className="flex flex-wrap items-center gap-2 px-1.5 pb-1">
        <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button key={ex.label} type="button" onClick={() => setText(ex.text)}
              className="rounded-full border border-line bg-panel px-2.5 py-1 text-[11.5px] text-body transition-colors hover:border-line-strong hover:bg-white hover:text-ink">
              {ex.label}
            </button>
          ))}
        </div>
        <span className="hidden font-mono text-[10.5px] text-muted sm:inline">Ctrl + ↵</span>
        <Button onClick={run} loading={busy} disabled={!text.trim()}><Send className="h-3.5 w-3.5" /> Run task</Button>
      </div>
      {error && <p className="px-3 pb-2 text-[12.5px] text-bad">{error}</p>}
    </Card>
  );
}

/* ── gate progress ────────────────────────────────────────────────────────── */
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
    gates,
    total: finished && gates.length ? gates.length : GATES_TOTAL,
    passed: gates.filter((g) => g.data.passed === true).length,
    failed: gates.some((g) => g.data.passed === false),
  };
}

function GateBar({ events, live }: { events: TaskCard["events"]; live: boolean }) {
  const g = gateProgress(events);
  if (!g) return null;
  return (
    <div className="mt-4" aria-label={`Sandbox gates passed: ${g.passed} of ${g.total}`}>
      <div className="mb-1.5 flex items-center justify-between text-[11.5px] text-muted">
        <span className="inline-flex items-center gap-1.5 font-medium text-body"><Shield className="h-3 w-3" /> Sandbox gates</span>
        <span className="tabular-nums">{g.passed}/{g.total}{g.failed ? " · a gate failed" : live && g.gates.length < g.total ? " · running" : ""}</span>
      </div>
      <div className="flex gap-1">
        {Array.from({ length: g.total }, (_, i) => {
          const gate = g.gates[i];
          const state = !gate ? "todo" : gate.data.passed === true ? "pass" : gate.data.passed === false ? "fail" : "todo";
          return (
            <div key={i} title={gate ? `${eventLabel(gate.kind)}: ${state}` : "not run"}
              className={`h-1.5 flex-1 rounded-full transition-colors duration-500 ${state === "pass" ? "bg-good" : state === "fail" ? "bg-bad" : live && i === g.gates.length ? "animate-pulse bg-ink/25" : "bg-panel-2"}`} />
          );
        })}
      </div>
    </div>
  );
}

/* ── approval ─────────────────────────────────────────────────────────────── */
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
    <div className="mt-4 overflow-hidden rounded-2xl border border-warn/30 bg-warn-bg">
      <p className="flex items-center gap-2 border-b border-warn/15 px-4 py-2.5 text-[13px] font-semibold text-warn"><Shield className="h-4 w-4" /> Approval needed: nothing compiles until you decide</p>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 px-4 py-3 text-[13px]">
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
      <div className="flex flex-wrap gap-2 px-4 pb-4">
        <Button size="sm" disabled={busy} onClick={() => decide(true)}><Check className="h-3.5 w-3.5" /> Approve &amp; compile</Button>
        <Button size="sm" variant="danger" disabled={busy} onClick={() => decide(false)}><X className="h-3.5 w-3.5" /> Reject</Button>
      </div>
    </div>
  );
}

/* ── one task card ────────────────────────────────────────────────────────── */
function TaskItem({ card }: { card: TaskCard }) {
  const events = card.events ?? [];
  const st = STATUS[card.status] ?? { label: card.status, tone: "neutral" as const };
  const live = LIVE_STATES.has(card.status);
  const pending = card.status === "NEEDS_APPROVAL";
  const finished = card.status === "DONE" || card.status === "FAILED";
  const [open, setOpen] = useState<boolean | null>(null);
  const showSteps = open ?? !finished;
  const last = events[events.length - 1];
  const gap = events.find((e) => e.kind === "GAP_CHECK");
  const plan: string[] = Array.isArray(gap?.data.plan) ? gap!.data.plan : [];
  const done = events.find((e) => e.kind === "DONE");
  const toolCalls: [string, unknown][] = Array.isArray(done?.data.tool_calls) ? done!.data.tool_calls : [];
  const dur = card.updated && card.created ? Math.max(0, Math.round(card.updated - card.created)) : null;
  const answerIsError = !!card.answer && /^error:/i.test(card.answer);

  return (
    <article className={`rounded-[20px] border bg-white p-5 transition-shadow hover:shadow-[0_10px_30px_-24px_rgba(20,20,19,0.5)] ${pending ? "border-warn/40 shadow-[0_0_0_3px_rgba(138,90,18,0.07)]" : "border-line"}`}>
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 flex-1 text-[15px] font-medium leading-snug tracking-[-0.01em] [overflow-wrap:anywhere]">{card.task}</p>
        <Badge tone={st.tone}>{live && <LiveDot />}{st.label}</Badge>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[12px] text-muted">
        <span className="font-mono">#{card.id}</span>
        <span className="opacity-50">·</span><span>{relTime(card.created)}</span>
        {dur != null && finished && <><span className="opacity-50">·</span><span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" />{fmtDur(dur)}</span></>}
        {card.learned?.map((s) => <Badge key={`l${s}`} tone="good"><Plus className="h-3 w-3" />{s}</Badge>)}
        {card.reused?.map((s) => <Badge key={`r${s}`} tone="info"><Zap className="h-3 w-3" />{s}</Badge>)}
      </div>

      {live && (
        <div className="mt-4 flex animate-fade-in items-center gap-3 rounded-2xl border border-line bg-panel px-4 py-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink text-white"><Loader2 className="h-4 w-4 animate-spin" /></span>
          <div className="min-w-0">
            <p className="text-[13px] font-semibold">{st.label}</p>
            <p className="truncate text-[12px] text-muted">{(last && (last.data.detail || last.data.reason)) || "waiting…"}</p>
          </div>
        </div>
      )}

      {pending && <ApprovalPanel card={card} />}

      {card.answer && (card.status === "DONE" || answerIsError) && (
        answerIsError ? (
          <p className="mt-4 rounded-2xl border border-bad/20 bg-bad-bg px-4 py-3 font-mono text-[12px] text-bad [overflow-wrap:anywhere]">{card.answer}</p>
        ) : (
          <div className="mt-4 rounded-2xl border border-good/25 bg-good-bg/70 px-4 py-3.5">
            <p className="mb-1.5 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-good"><Check className="h-3.5 w-3.5" /> Answer</p>
            <Markdown text={card.answer} className="text-ink" />
            {toolCalls.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5 border-t border-good/15 pt-3">
                {toolCalls.map((t, i) => <ToolChip key={i}><Terminal className="h-3 w-3" />{String(t[0])}</ToolChip>)}
              </div>
            )}
          </div>
        )
      )}

      <GateBar events={events} live={live} />

      {events.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <button onClick={() => setOpen(!showSteps)} aria-expanded={showSteps}
            className="flex w-full items-center gap-1.5 text-[12px] font-medium text-body hover:text-ink">
            <ChevronDown className={`h-3.5 w-3.5 transition-transform duration-300 ${showSteps ? "rotate-180" : ""}`} />
            <span className="shrink-0 whitespace-nowrap">{showSteps ? "Hide" : "Show"} the agent&apos;s {events.length} steps</span>
            {plan.length > 0 && !showSteps && <span className="ml-auto min-w-0 truncate pl-3 text-muted">plan: {plan[0]}</span>}
          </button>
          <div className={`grid transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${showSteps ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
            <div className="overflow-hidden">
              {plan.length > 0 && (
                <div className="mt-3 rounded-[14px] border border-line bg-panel px-3.5 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Agent&apos;s plan</p>
                  <ol className="mb-0 mt-1.5 list-decimal pl-5 text-[13px] leading-relaxed text-body">{plan.map((p, i) => <li key={i}>{p}</li>)}</ol>
                </div>
              )}
              <ul className="timeline mt-3 list-none pl-1">
                {events.map((e, i) => {
                  const sub = e.kind.startsWith("compile.");
                  const detail = eventDetail(e);
                  return (
                    <li key={i} className={`${eventTone(e)}${sub ? " sub" : ""}`}>
                      {AI_STEPS.test(e.kind) && <Star className="mr-1 inline h-2.5 w-2.5 -translate-y-px text-clay" />}
                      <span className="font-semibold">{eventLabel(e.kind)}</span>
                      {detail && <span className="text-muted [overflow-wrap:anywhere]"> · {detail}</span>}
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

/* ── side rail ────────────────────────────────────────────────────────────── */
function Rail({ cards, skills, catalog }: { cards: TaskCard[]; skills: Skill[]; catalog: CatalogRepo[] }) {
  const reuses = cards.reduce((n, c) => n + (c.reused?.length ?? 0), 0);
  const approvals = cards.reduce((n, c) => n + (c.events ?? []).filter((e) => e.kind === "approval.decision" && String(e.data.detail ?? "").startsWith("approved")).length, 0);
  const stats = [
    { v: cards.length, l: "Tasks run", i: <LayoutGrid className="h-3.5 w-3.5" /> },
    { v: skills.length, l: "Skills", i: <Sparkles className="h-3.5 w-3.5" /> },
    { v: reuses, l: "Reuses", i: <Zap className="h-3.5 w-3.5" /> },
    { v: approvals, l: "Approvals", i: <Shield className="h-3.5 w-3.5" /> },
  ];
  return (
    <div className="space-y-4">
      <AgentPanel cards={cards} skills={skills} />
      <div className="grid grid-cols-4 gap-2 lg:grid-cols-2">
        {stats.map((s) => (
          <Card key={s.l} className="px-3.5 py-3">
            <p className="text-[22px] font-medium leading-tight tracking-tight"><CountUp to={s.v} /></p>
            <p className="mt-0.5 flex items-center gap-1.5 text-[11px] font-medium text-muted">{s.i}{s.l}</p>
          </Card>
        ))}
      </div>
      <Card className="p-4">
        <p className="text-[13px] font-semibold">Skill library</p>
        {skills.length === 0 ? <p className="mt-1 text-[12px] text-muted">Empty. The first compile fills it.</p> : (
          <ul className="mt-2 space-y-1.5">
            {skills.map((s) => (
              <li key={s.name} className="flex items-center gap-2 text-[12.5px]">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-good" />
                <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{s.name}</span>
                <span className="shrink-0 text-[11px] text-muted">{s.tools.length} tool{s.tools.length === 1 ? "" : "s"}</span>
              </li>
            ))}
          </ul>
        )}
        {catalog.length > 0 && (
          <>
            <p className="mt-4 text-[13px] font-semibold">Learns from</p>
            <div className="mt-2 flex flex-wrap gap-1">
              {catalog.map((r) => <span key={r.repo} className="rounded-full bg-panel-2 px-2 py-0.5 text-[11px] text-body">{r.repo}</span>)}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

/* ── view ─────────────────────────────────────────────────────────────────── */
export function Tasks({ cards, skills, catalog = [], loaded }: { cards: TaskCard[]; skills: Skill[]; catalog?: CatalogRepo[]; loaded: boolean }) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const useExample = () => { setDraft(EXAMPLES[0].text); inputRef.current?.focus(); };

  return (
    <>
      <Hero
        eyebrow="Task board"
        title={<>Give the agent work. <span className="text-muted">It grows the tools it needs.</span></>}
        sub="When the agent lacks a capability, Zyven finds it in pinned open-source code. You approve, a verified MCP tool is compiled in a sandbox and hot-loaded mid-task, and the skill is kept for next time."
      />
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-4">
          <Reveal><Composer text={draft} setText={setDraft} inputRef={inputRef} /></Reveal>
          {!loaded ? (
            <div className="space-y-3.5"><Skeleton className="h-[140px]" /><Skeleton className="h-[140px]" /></div>
          ) : cards.length === 0 ? (
            <Empty seed="tasks" title="No tasks yet"
              body="Give the agent something that needs a capability it doesn't have, like an IBAN check or a Hijri date. Watch it notice the gap, ask you to approve a compile, and finish with tools it just built."
              action={<Button size="sm" onClick={useExample}>Use the first example</Button>} />
          ) : (
            <div className="flex flex-col gap-3.5">
              {cards.map((c, i) => <Reveal key={c.id} delay={Math.min(i, 5) * 60}><TaskItem card={c} /></Reveal>)}
            </div>
          )}
        </div>
        <Reveal delay={120} className="lg:sticky lg:top-24"><Rail cards={cards} skills={skills} catalog={catalog} /></Reveal>
      </div>
    </>
  );
}
