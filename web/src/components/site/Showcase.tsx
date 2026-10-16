"use client";

import { useEffect, useState } from "react";
import { Bot, Check, FileCode2, GitBranch, Loader2, ShieldCheck, User } from "lucide-react";
import { Star } from "../motion";

/* ------------------------------------------------------------------------------------------- */
/* Every number below comes from a real Zyven run: the sympy analysis on the board's explorer, */
/* the python-stdnum IBAN skill (verified on all six gates) and the open-model evaluation.     */
/* ------------------------------------------------------------------------------------------- */

function useTicker(active: boolean, steps: number, ms: number) {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setN((x) => (x < steps ? x + 1 : x)), ms);
    return () => clearInterval(t);
  }, [active, steps, ms]);
  return active ? n : 0;
}

const FUNNEL = [
  { stage: "Symbols in source modules", count: 22655 },
  { stage: "Public callables", count: 11016 },
  { stage: "Side-effect free", count: 10932 },
  { stage: "MCP-able signature", count: 10496 },
  { stage: "With upstream tests", count: 9117 },
  { stage: "Capability entry points", count: 7 },
];

function DiscoverDemo({ active }: { active: boolean }) {
  const n = useTicker(active, FUNNEL.length + 1, 520);
  const repo = "github.com/sympy/sympy";
  const chars = useTicker(active, repo.length, 28);
  return (
    <div className="grid h-full gap-4 p-5 md:grid-cols-[0.85fr_1.15fr] md:p-6">
      <div className="flex flex-col">
        <p className="text-[12px] text-muted">Repository</p>
        <p className="mt-2 flex items-center gap-2 rounded-2xl bg-panel p-4 font-mono text-[13px] text-ink">
          <GitBranch className="h-4 w-4 shrink-0 text-muted" />
          {repo.slice(0, chars)}
          <span className="inline-block h-4 w-[2px] animate-pulse bg-ink" />
        </p>
        <div className="mt-4 grid grid-cols-2 gap-2">
          {[["425,281", "lines of Python"], ["882", "modules"], ["44,489", "upstream tests"], ["103 s", "to analyse"]].map(([v, l], i) => (
            <div key={l} className={`rounded-2xl border border-line bg-white p-3 transition-all duration-500 ${n > i ? "opacity-100" : "translate-y-2 opacity-0"}`}>
              <p className="text-[20px] font-semibold tabular-nums tracking-tight">{v}</p>
              <p className="text-[11px] text-muted">{l}</p>
            </div>
          ))}
        </div>
        <p className="mt-auto pt-4 text-[12px] leading-relaxed text-body">
          Static analysis only: the AST is read, repository code never runs outside the sandbox.
        </p>
      </div>
      <div className="rounded-2xl border border-line bg-white p-4">
        <div className="flex items-baseline justify-between">
          <p className="text-[15px] font-semibold tracking-tight">What can become a tool</p>
          <p className="text-[12px] text-muted">sympy @ pinned commit</p>
        </div>
        <div className="mt-4 space-y-3">
          {FUNNEL.map((f, i) => {
            const w = Math.max(3, (Math.log10(f.count + 1) / Math.log10(22656)) * 100);
            const last = i === FUNNEL.length - 1;
            return (
              <div key={f.stage}>
                <div className="flex items-baseline justify-between text-[12px]">
                  <span className={last ? "font-medium text-ink" : "text-body"}>{f.stage}</span>
                  <span className="font-mono tabular-nums text-ink">{f.count.toLocaleString("en-US")}</span>
                </div>
                <div className="mt-1 h-2 rounded-full bg-panel-2">
                  <div
                    className={`h-2 rounded-full transition-all duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] ${last ? "bg-clay" : "bg-ink"}`}
                    style={{ width: n > i ? `${w}%` : "0%" }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <p className="mt-4 text-[11px] text-muted">Bar lengths are on a log scale.</p>
      </div>
    </div>
  );
}

const ROLES = [
  { role: "Scout", text: "Found an IBAN capability: validate, format, check digits" },
  { role: "Architect", text: "3 tools · string in, JSON out · lint passed" },
  { role: "Compiler", text: "Wrote the tool bodies against stdnum.iban" },
  { role: "Tester", text: "Differential cases, written without seeing the adapter" },
];

const CODE = [
  "@mcp.tool()",
  "def validate_iban(number: str) -> dict:",
  '    """Check an IBAN\'s country, length and check digits."""',
  "    from stdnum import iban",
  "    try:",
  '        return {"valid": True, "iban": iban.validate(number)}',
  "    except Exception as e:",
  '        return {"valid": False, "reason": type(e).__name__}',
];

function CompileDemo({ active }: { active: boolean }) {
  const n = useTicker(active, ROLES.length + CODE.length, 380);
  return (
    <div className="grid h-full gap-4 p-5 md:grid-cols-[0.9fr_1.1fr] md:p-6">
      <div className="space-y-2">
        <p className="text-[12px] text-muted">Four open-weight model roles</p>
        {ROLES.map((r, i) => {
          const done = n > i + 1;
          const now = n === i + 1 || (i === 0 && n === 0);
          return (
            <div key={r.role} className={`flex gap-3 rounded-2xl border border-line bg-white p-3 transition-all duration-500 ${n >= i ? "opacity-100" : "translate-y-2 opacity-0"}`}>
              <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${done ? "bg-good-bg text-good" : "bg-panel-2 text-clay"}`}>
                {done ? <Check className="h-3.5 w-3.5" /> : now ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Star className="h-3 w-3" />}
              </span>
              <div>
                <p className="text-[13px] font-semibold text-ink">{r.role}</p>
                <p className="text-[12px] leading-snug text-body">{r.text}</p>
              </div>
            </div>
          );
        })}
      </div>
      <div className="overflow-hidden rounded-2xl bg-ink text-white">
        <div className="flex items-center gap-2 border-b border-white/10 px-4 py-2.5 text-[11px] text-white/50">
          <FileCode2 className="h-3.5 w-3.5" /> skills/iban_validation/server.py <span className="ml-auto">abridged</span>
        </div>
        <pre className="overflow-x-auto px-4 py-3 font-mono text-[11.5px] leading-[1.7]">
          {CODE.map((line, i) => (
            <div key={i} className={`transition-opacity duration-300 ${n > ROLES.length - 2 + i ? "opacity-100" : "opacity-0"}`}>
              <span className={line.startsWith("@") ? "text-clay" : line.includes('"""') ? "text-white/45" : "text-white/90"}>{line || " "}</span>
            </div>
          ))}
        </pre>
        <p className="border-t border-white/10 px-4 py-2.5 text-[11px] text-white/50">
          Every symbol the model names is resolved against the analysis. Invented names are rejected.
        </p>
      </div>
    </div>
  );
}

const GATES = [
  { g: "Policy", d: "Import allowlist; no eval, exec or locals" },
  { g: "Import", d: "The server imports cleanly in the sandbox" },
  { g: "Upstream tests", d: "The library's own test suite still passes" },
  { g: "Input robustness", d: "Spaces, lowercase, junk: no crashes" },
  { g: "MCP smoke", d: "Each tool lists and answers over MCP" },
  { g: "Differential", d: "Every answer matches the library itself" },
];

function VerifyDemo({ active }: { active: boolean }) {
  const n = useTicker(active, GATES.length + 1, 650);
  return (
    <div className="h-full p-5 md:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[15px] font-semibold tracking-tight">iban_validation · 3 tools</p>
        <p className="font-mono text-[11px] text-muted">docker · no network · non-root · read-only · cap-drop ALL</p>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {GATES.map((x, i) => {
          const done = n > i;
          return (
            <div key={x.g} className={`flex gap-3 rounded-2xl border bg-white px-4 py-3 transition-all duration-500 ${done ? "border-line" : "border-dashed border-line-strong"}`}>
              <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-colors ${done ? "bg-good-bg text-good" : "bg-panel-2 text-muted"}`}>
                {done ? <Check className="h-3.5 w-3.5" /> : n === i ? <Loader2 className="h-3 w-3 animate-spin" /> : <span className="font-mono text-[10px]">{i + 1}</span>}
              </span>
              <div>
                <p className="text-[13px] font-medium text-ink">{x.g}</p>
                <p className="text-[12px] text-body">{x.d}</p>
              </div>
            </div>
          );
        })}
      </div>
      <div className={`mt-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-good-bg px-4 py-3 text-[12px] text-good transition-opacity duration-500 ${n > GATES.length ? "opacity-100" : "opacity-0"}`}>
        <span className="flex items-center gap-1.5 font-medium"><ShieldCheck className="h-4 w-4" /> Verified on 6 of 6 gates · added to the skill library</span>
        <span>provenance: python-stdnum @ 006192e</span>
      </div>
    </div>
  );
}

const CHAT = [
  { who: "user", text: "Is GB82 WEST 1234 5698 7654 32 a valid IBAN?" },
  { who: "agent", text: "I can't check this reliably by hand. python-stdnum in the catalog can. Compile an IBAN skill from it?", ask: true },
  { who: "user", text: "Approve" },
  { who: "tool", text: 'validate_iban("GB82 WEST 1234 5698 7654 32") → {"valid": true}' },
  { who: "agent", text: "Yes, it's valid: a UK IBAN with check digits 82. I'll reuse this skill next time without compiling." },
];

function UseDemo({ active }: { active: boolean }) {
  const n = useTicker(active, CHAT.length, 1300);
  const shown = CHAT.slice(0, Math.max(1, n));
  return (
    <div className="grid h-full gap-4 p-5 md:grid-cols-[1.3fr_0.7fr] md:p-6">
      <div className="space-y-2.5 overflow-hidden">
        {shown.map((t, i) =>
          t.who === "tool" ? (
            <div key={i} className="ml-9 animate-fade-in rounded-xl border border-line bg-panel px-3 py-2 font-mono text-[11.5px] text-body">{t.text}</div>
          ) : (
            <div key={i} className={`flex gap-2 animate-fade-in ${t.who === "user" ? "flex-row-reverse" : ""}`}>
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${t.who === "user" ? "bg-cream-2 text-ink" : "bg-ink text-white"}`}>
                {t.who === "user" ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
              </span>
              <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-[12.5px] leading-relaxed ${t.who === "user" ? "rounded-tr-md bg-ink text-white" : "rounded-tl-md bg-panel-2 text-ink"}`}>
                {"ask" in t && <span className="mb-0.5 block text-[10px] font-semibold uppercase tracking-wider text-clay">Needs your approval</span>}
                {t.text}
              </div>
            </div>
          ),
        )}
      </div>
      <div className="flex flex-col gap-2.5">
        <div className="rounded-2xl border border-line bg-white p-4">
          <p className="text-[11px] text-muted">Model alone, same questions</p>
          <p className="mt-1 text-[30px] font-semibold tabular-nums tracking-tight">0 / 18</p>
          <p className="text-[12px] text-body">IBAN and card checks</p>
        </div>
        <div className="rounded-2xl border border-line bg-white p-4">
          <p className="text-[11px] text-muted">With the compiled skill</p>
          <p className="mt-1 text-[30px] font-semibold tabular-nums tracking-tight text-good">18 / 18</p>
          <p className="text-[12px] text-body">gemma-4-26b-a4b-it, open weights</p>
        </div>
      </div>
    </div>
  );
}

const TABS = [
  { key: "discover", label: "Discover", sub: "Static analysis", C: DiscoverDemo },
  { key: "compile", label: "Compile", sub: "Model roles, harness rules", C: CompileDemo },
  { key: "verify", label: "Verify", sub: "Six sandbox gates", C: VerifyDemo },
  { key: "use", label: "Use", sub: "The agent, extended", C: UseDemo },
];
const DURATION = 9000;

export function Showcase() {
  const [i, setI] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const t = setTimeout(() => setI((x) => (x + 1) % TABS.length), DURATION);
    return () => clearTimeout(t);
  }, [i, paused]);

  return (
    <div
      className="relative overflow-hidden rounded-[32px] bg-cover bg-center p-3 sm:p-6 md:p-10"
      style={{ backgroundImage: "url(/art/warm.webp)" }}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="mx-auto mb-4 flex w-fit max-w-full gap-1 overflow-x-auto rounded-full bg-white/70 p-1 backdrop-blur-md">
        {TABS.map((t, idx) => (
          <button
            key={t.key}
            onClick={() => setI(idx)}
            className={`relative overflow-hidden whitespace-nowrap rounded-full px-4 py-2 text-[13px] font-medium transition-colors sm:px-5 ${idx === i ? "bg-white text-ink shadow-sm" : "text-body hover:text-ink"}`}
          >
            <span className="mr-1.5 font-mono text-[11px] text-muted">0{idx + 1}</span>
            {t.label}
            {idx === i && !paused && (
              <span key={i} className="absolute inset-x-3 bottom-1 h-[2px] origin-left rounded-full bg-ink/15">
                <span className="block h-full origin-left animate-[grow_9s_linear_forwards] rounded-full bg-ink/60" />
              </span>
            )}
          </button>
        ))}
      </div>
      <div className="mx-auto max-w-[980px] overflow-hidden rounded-[22px] bg-white shadow-[0_24px_60px_-24px_rgba(60,30,10,0.35)]">
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <p className="text-[12px] text-muted">{TABS[i].sub}</p>
          <p className="flex items-center gap-1.5 text-[12px] text-muted"><Star className="h-2.5 w-2.5 text-clay" /> based on a real run</p>
        </div>
        <div className="min-h-[430px]">
          {TABS.map((t, idx) => (idx === i ? <t.C key={t.key} active /> : null))}
        </div>
      </div>
    </div>
  );
}
