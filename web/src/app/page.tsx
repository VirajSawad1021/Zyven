"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight, ArrowUpRight, BookOpen, ChartColumn, Check, Copy, LayoutGrid, Minus, Network, Plug, Plus, Rocket, Search,
  ShieldCheck, Sparkles, Wrench,
} from "lucide-react";
import { GITHUB, SiteShell } from "../components/site/Chrome";
import { CountUp, Reveal } from "../components/motion";
import { LogoMark } from "../components/Logo";

const INSTALL = "uvx --from git+https://github.com/VirajSawad1021/Zyven zyven verify --discover";

const GATES = [
  ["Policy", "No files, processes or network in the tool code; no eval, exec or locals."],
  ["Import", "The assembled MCP server imports cleanly inside the container."],
  ["Upstream tests", "The library's own test suite still passes against the pinned checkout."],
  ["Input robustness", "Spaces, case and separators change nothing; bad input gets a clear error."],
  ["MCP smoke", "Every tool is listed and called over the real MCP protocol."],
  ["Differential", "Every answer is compared with the library called directly."],
];

const SUITES: [string, string, number, number, number][] = [
  ["Calendar arithmetic", "python-dateutil", 11, 24, 24],
  ["Unit conversion", "pint", 22, 29, 30],
  ["IBAN and Luhn checks", "python-stdnum", 6, 18, 18],
  ["Hijri dates, Jewish holidays, phone numbers", "hijridate · pyluach · phonenumbers", 10, 30, 30],
];

const FAQ: [string, string][] = [
  ["Why not let the model write the code itself?", "Because the model is exactly what gets checksums, calendars and unit factors wrong. The correct, tested logic already exists in open-source libraries. Zyven has a model write only a thin adapter around that code, and the sandbox proves the adapter answers exactly what the library answers."],
  ["Does anything run without my approval?", "No. When the agent finds a gap it proposes a repository from the pinned catalog and waits on the board. Nothing is cloned, compiled or executed until you approve it."],
  ["What does 'verified' mean?", "A skill is verified only for the gates it passed, and they are listed on it: policy, import, the library's own tests, input robustness, an MCP smoke test, and differential tests against the library. A tool that cannot be repaired is dropped and recorded, never shipped unverified."],
  ["Is repository code run on my machine?", "Analysis is static: the source is parsed, never imported. Everything that executes runs in a container with no network, a non-root user, a read-only file system, every capability dropped and resource limits."],
  ["Which models does it use?", "Any OpenAI-compatible model, or a coding agent (Codex, Claude Code, OpenCode, Qoder) for any role. The published skills and results use open-weight models: Gemma 4, and Reflection Beam 1.0 and DeepSeek V4.1 through OpenCode."],
  ["Can it check MCP servers I didn't build?", "Yes. zyven verify connects to any MCP server, reads its tools for hidden instructions, pins their definitions against rug pulls, can call them in the sandbox and reports leaked credentials. It runs locally, needs no account and calls no model."],
];

function CopyCommand() {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(INSTALL); setDone(true); setTimeout(() => setDone(false), 1600); }
    catch { /* the command stays selectable */ }
  };
  return (
    <div className="mt-6 flex max-w-full items-center gap-2 rounded-[10px] border border-line bg-canvas py-1.5 pl-3.5 pr-1.5">
      <span className="select-all truncate font-mono text-[12.5px] text-body"><span className="text-muted">$ </span>{INSTALL}</span>
      <button onClick={copy} aria-label="Copy the command"
        className="ml-auto inline-flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-[12px] text-muted transition-colors hover:bg-panel-2 hover:text-ink">
        {done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{done ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/** The product in a browser frame: the real board layout, with the six gates ticking to pass on load. */
function AppMock() {
  const nav: [typeof LayoutGrid, string, boolean, number?][] = [
    [LayoutGrid, "Tasks", true, 1], [Rocket, "Control", false], [Plug, "Connections", false],
    [Sparkles, "Skills", false, 9], [BookOpen, "Catalog", false], [Network, "Explorer", false], [ChartColumn, "Insights", false],
  ];
  return (
    <div className="overflow-hidden rounded-xl border border-line-strong bg-canvas shadow-[0_32px_80px_-40px_rgba(27,25,21,0.35),0_2px_8px_rgba(27,25,21,0.04)]">
      <div className="flex h-9 items-center gap-1.5 border-b border-line bg-panel px-3.5">
        {[0, 1, 2].map((i) => <span key={i} className="h-2.5 w-2.5 rounded-full bg-line-strong" />)}
        <span className="mx-auto rounded-md bg-canvas px-3 py-0.5 font-mono text-[11px] text-muted">localhost:8765/app</span>
      </div>
      <div className="grid grid-cols-[188px_minmax(0,1fr)] text-left max-md:grid-cols-1">
        <aside className="border-r border-line bg-cream p-3 max-md:hidden">
          <div className="mb-3 flex items-center gap-1.5 px-1"><LogoMark className="h-4 w-4" /><span className="text-[13px] font-semibold tracking-[-0.03em]">zyven</span></div>
          <div className="mb-3 flex h-7 items-center gap-1.5 rounded-md border border-line bg-canvas px-2 text-[11.5px] text-muted">
            <Search className="h-3 w-3" />Search<span className="ml-auto flex gap-0.5"><kbd className="kbd">Ctrl</kbd><kbd className="kbd">K</kbd></span>
          </div>
          {nav.map(([Icon, label, active, n]) => (
            <div key={label} className={`flex h-7 items-center gap-2 rounded-md border px-2 text-[12px] font-medium ${active ? "border-line bg-canvas text-ink" : "border-transparent text-body"}`}>
              <Icon className={`h-3.5 w-3.5 ${active ? "text-ink" : "text-muted"}`} strokeWidth={1.75} />{label}
              {n ? <span className={`ml-auto rounded-[4px] px-1 text-[10px] font-semibold ${active ? "bg-ink text-white" : "bg-panel-2 text-muted"}`}>{n}</span> : null}
            </div>
          ))}
        </aside>
        <div className="p-5 sm:p-7">
          <p className="text-[11.5px] text-muted">Zyven / Tasks</p>
          <p className="mt-3 text-[22px] font-semibold tracking-[-0.02em]">Tasks</p>
          <div className="mt-4 rounded-[10px] border border-line p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="text-[13.5px] font-medium leading-snug">How long is it from 1998-03-09 to 2052-01-31, in calendar years, months and days?</p>
              <span className="shrink-0 rounded-[5px] bg-warn-bg px-1.5 py-0.5 text-[10.5px] font-medium text-warn">Needs approval</span>
            </div>
            <div className="mt-3 rounded-md border border-line bg-panel px-3 py-2.5">
              <p className="text-[11px] text-muted">Capability gap</p>
              <p className="text-[13px] font-medium">Calendar arithmetic, from <span className="font-mono text-[12px]">python-dateutil @ a78cbd8</span></p>
              <div className="mt-2.5 flex gap-1.5">
                <span className="rounded-md bg-ink px-2.5 py-1 text-[11.5px] font-medium text-white">Approve compile</span>
                <span className="rounded-md border border-line-strong bg-canvas px-2.5 py-1 text-[11.5px] font-medium">Reject</span>
              </div>
            </div>
            <p className="mb-1.5 mt-4 text-[11px] text-muted">Sandbox gates</p>
            <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
              {GATES.map(([g], i) => (
                <span key={g} style={{ animationDelay: `${300 + i * 180}ms` }}
                  className="gate-pill inline-flex items-center justify-center gap-1 rounded-[5px] bg-good-bg px-1.5 py-1 text-[10.5px] font-medium text-good">
                  <Check className="h-3 w-3" strokeWidth={2.5} />{g.split(" ")[0]}
                </span>
              ))}
            </div>
            <p className="mt-3 rounded-md bg-good-bg/60 px-3 py-2 text-[12.5px] text-ink">
              <span className="font-medium">53 years, 10 months, 22 days.</span> <span className="text-body">Answered with the verified <span className="font-mono text-[11.5px]">date_arithmetic</span> skill.</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function Faq() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <div className="divide-y divide-line border-y border-line">
      {FAQ.map(([q, a], i) => (
        <div key={q}>
          <button onClick={() => setOpen(open === i ? null : i)} className="flex w-full items-center justify-between gap-6 py-5 text-left" aria-expanded={open === i}>
            <span className="text-[16px] font-medium tracking-[-0.01em] text-ink sm:text-[17px]">{q}</span>
            {open === i ? <Minus className="h-4 w-4 shrink-0 text-muted" /> : <Plus className="h-4 w-4 shrink-0 text-muted" />}
          </button>
          <div className={`grid transition-[grid-template-rows] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] ${open === i ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
            <p className={`max-w-3xl overflow-hidden text-[14.5px] leading-relaxed text-body ${open === i ? "pb-5" : ""}`}>{a}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function Kicker({ children }: { children: React.ReactNode }) {
  return <p className="text-[13px] font-medium text-muted">{children}</p>;
}

function H2({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <h2 className={`max-w-3xl text-[32px] font-semibold leading-[1.1] tracking-[-0.03em] text-ink sm:text-[44px] ${className}`}>{children}</h2>;
}

export default function Landing() {
  return (
    <SiteShell>
      {/* hero */}
      <section className="mx-auto max-w-[1160px] px-5 pb-10 pt-16 sm:px-8 sm:pt-24">
        <Reveal className="max-w-[760px]">
          <p className="mb-5 inline-flex items-center gap-1.5 rounded-full border border-line bg-canvas px-3 py-1 text-[12px] font-medium text-body">
            Open source · runs on your machine · MIT
          </p>
          <h1 className="text-[44px] font-semibold leading-[1.02] tracking-[-0.045em] text-ink sm:text-[68px]">
            Agents that compile their own tools.
          </h1>
          <p className="mt-5 max-w-[600px] text-[17px] leading-relaxed text-body">
            Models are confidently wrong about checksums, calendars and unit factors. Zyven turns the open-source code that gets them
            right into MCP tools, proves each one in a locked-down sandbox, and checks the MCP servers you did not build.
          </p>
          <div className="mt-7 flex flex-wrap gap-2.5">
            <Link href="/app/" className="inline-flex h-11 items-center gap-1.5 rounded-full bg-ink px-5 text-[14.5px] font-medium text-white transition-colors hover:bg-accent-ink">
              Open the board <ArrowRight className="h-4 w-4" />
            </Link>
            <a href={GITHUB} target="_blank" rel="noreferrer" className="inline-flex h-11 items-center gap-1.5 rounded-full border border-line-strong bg-canvas px-5 text-[14.5px] font-medium text-ink transition-colors hover:bg-panel">
              Read the code <ArrowUpRight className="h-4 w-4" />
            </a>
          </div>
          <CopyCommand />
        </Reveal>
      </section>

      <section id="product" className="mx-auto max-w-[1160px] scroll-mt-20 px-3 sm:px-8">
        <Reveal delay={120}><AppMock /></Reveal>
      </section>

      {/* what it does */}
      <section className="mx-auto max-w-[1160px] px-5 py-24 sm:px-8">
        <Reveal>
          <Kicker>Two jobs, one gate</Kicker>
          <H2 className="mt-2">It builds the tools it needs, and checks the ones it is given.</H2>
        </Reveal>
        <div className="mt-12 grid gap-5 lg:grid-cols-2">
          {[
            {
              icon: Wrench, title: "Compile", body: "When the agent lacks a capability, Zyven finds it in a pinned open-source library, has a model write a thin MCP adapter, and keeps the tool only if it passes all six gates.",
              href: "/app/skills/", cta: "See the verified skills",
              ui: (
                <div className="rounded-[10px] border border-line bg-canvas p-3.5">
                  <div className="flex items-center justify-between"><span className="font-mono text-[11.5px] text-muted">unit_conversion</span>
                    <span className="inline-flex items-center gap-1 rounded-[5px] bg-good-bg px-1.5 py-0.5 text-[10.5px] font-medium text-good"><Check className="h-3 w-3" />Verified</span></div>
                  <p className="mt-2 text-[14px] font-semibold">Unit conversion</p>
                  <p className="mt-0.5 text-[12.5px] text-body">From pint 0.26.2 · differential 30/30 · compiled by a 501B open-weight model</p>
                </div>
              ),
            },
            {
              icon: ShieldCheck, title: "Verify", body: "Point it at any MCP server. It reads tools for hidden instructions, pins their definitions against rug pulls, calls them in the sandbox and reports leaked credentials, with no account and no model.",
              href: GITHUB + "#verify-any-mcp-server", cta: "Verify your servers",
              ui: (
                <div className="rounded-[10px] border border-line bg-ink p-3.5 font-mono text-[11.5px] leading-relaxed text-white/80">
                  <p><span className="font-semibold text-[#ff8f80]">FAIL</span>  descriptions  4 suspicious passages</p>
                  <p className="text-white/55">  - redirects messages to a fixed address</p>
                  <p className="text-white/55">  - tool shadowing: send_email</p>
                  <p><span className="font-semibold text-[#7fd49b]">PASS</span>  stability     same definitions twice</p>
                </div>
              ),
            },
          ].map((c, i) => (
            <Reveal key={c.title} delay={i * 100} className="h-full">
              <div className="group flex h-full flex-col rounded-xl border border-line bg-canvas p-6 transition-[border-color,box-shadow] duration-200 hover:border-line-strong hover:shadow-[0_16px_40px_-28px_rgba(27,25,21,0.35)] sm:p-7">
                <div className="flex h-9 w-9 items-center justify-center rounded-[10px] border border-line bg-panel"><c.icon className="h-4 w-4" strokeWidth={1.75} /></div>
                <p className="mt-4 text-[20px] font-semibold tracking-[-0.02em]">{c.title}</p>
                <p className="mt-1.5 max-w-md text-[14.5px] leading-relaxed text-body">{c.body}</p>
                <div className="mt-6 flex-1">{c.ui}</div>
                <Link href={c.href} className="mt-5 inline-flex items-center gap-1 text-[14px] font-medium text-ink">
                  {c.cta} <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* how it works */}
      <section id="how" className="scroll-mt-16 border-y border-line bg-panel/60">
        <div className="mx-auto max-w-[1160px] px-5 py-24 sm:px-8">
          <Reveal>
            <Kicker>How it works</Kicker>
            <H2 className="mt-2">From a repository to a tool you can trust.</H2>
          </Reveal>
          <div className="mt-12 grid gap-5 lg:grid-cols-3">
            {[
              ["1", "Read the repository, never run it", "The analyzer parses the whole library: public functions, call graph, tests and license. The model starts from facts, not guesses.",
                [["stdnum.iban.validate", "tested · pure"], ["stdnum.luhn.checksum", "tested · pure"], ["stdnum.util.get_cc_module", "reads files · skipped"]]],
              ["2", "The model proposes, the harness decides", "Any model or coding agent designs the tools, writes them and writes test cases without seeing the code. Invented names are rejected before anything runs.",
                [["Architect", "3 tools"], ["Compiler", "server.py"], ["Tester", "36 reference cases"]]],
              ["3", "Kept only if it survives the sandbox", "Six gates run in a locked container. A failure gets a bounded repair; a tool that still fails is dropped and recorded.",
                [["Upstream tests", "92 passed"], ["Input robustness", "repaired, then pass"], ["Differential", "36/36"]]],
            ].map(([n, t, b, rows], i) => (
              <Reveal key={n as string} delay={i * 90} className="h-full">
                <div className="flex h-full flex-col rounded-xl border border-line bg-canvas p-6">
                  <span className="font-mono text-[12px] text-muted">0{n as string}</span>
                  <p className="mt-2 text-[17px] font-semibold tracking-[-0.015em]">{t as string}</p>
                  <p className="mt-1.5 text-[14px] leading-relaxed text-body">{b as string}</p>
                  <div className="mt-5 divide-y divide-line rounded-[10px] border border-line">
                    {(rows as string[][]).map(([k, v]) => (
                      <div key={k} className="flex items-center justify-between gap-3 px-3 py-2 text-[12.5px]">
                        <span className="font-mono text-[11.5px] text-ink">{k}</span>
                        <span className={v.includes("skipped") ? "text-warn" : v.includes("repaired") ? "text-warn" : "text-muted"}>{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* gates */}
      <section id="gates" className="scroll-mt-16 bg-ink text-white">
        <div className="mx-auto grid max-w-[1160px] gap-12 px-5 py-24 sm:px-8 lg:grid-cols-[0.85fr_1.4fr]">
          <Reveal>
            <p className="text-[13px] font-medium text-white/50">Six sandbox gates</p>
            <h2 className="mt-2 text-[32px] font-semibold leading-[1.1] tracking-[-0.03em] sm:text-[44px]">The model writes it. The sandbox proves it.</h2>
            <p className="mt-5 max-w-md text-[15px] leading-relaxed text-white/60">
              Every gate runs in a container with no network, a non-root user, a read-only file system and every capability dropped. In a
              mutation test, the gates caught 90% of deliberately planted bugs.
            </p>
          </Reveal>
          <div className="grid gap-px overflow-hidden rounded-xl border border-white/10 bg-white/10 sm:grid-cols-2">
            {GATES.map(([t, b], i) => (
              <Reveal key={t} delay={i * 60} className="h-full">
                <div className="h-full bg-ink p-5 transition-colors hover:bg-[#24211c]">
                  <span className="font-mono text-[11.5px] text-white/35">0{i + 1}</span>
                  <p className="mt-3 text-[15.5px] font-medium">{t}</p>
                  <p className="mt-1 text-[13.5px] leading-relaxed text-white/55">{b}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* results */}
      <section id="results" className="mx-auto max-w-[1160px] scroll-mt-16 px-5 py-24 sm:px-8">
        <Reveal>
          <Kicker>Measured, not claimed</Kicker>
          <H2 className="mt-2">A small model gets the answers right.</H2>
          <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-body">
            Gemma 4 E4B, a 4-billion-parameter open model on one free GPU, with the same questions and budget in both runs. Ground truth comes
            from each library itself; raw records are in the repository.
          </p>
        </Reveal>
        <Reveal delay={100}>
          <div className="mt-10 overflow-hidden rounded-xl border border-line">
            <div className="grid grid-cols-[minmax(0,1fr)_88px_88px] gap-3 border-b border-line bg-panel px-4 py-2.5 text-[12px] text-muted sm:grid-cols-[minmax(0,1fr)_160px_160px]">
              <span>Suite</span><span className="text-right">Model alone</span><span className="text-right">With skills</span>
            </div>
            {SUITES.map(([name, lib, alone, withs, total]) => (
              <div key={name} className="grid grid-cols-[minmax(0,1fr)_88px_88px] items-center gap-3 border-b border-line px-4 py-3.5 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_160px_160px]">
                <div className="min-w-0"><p className="truncate text-[14px] font-medium">{name}</p><p className="truncate font-mono text-[11.5px] text-muted">{lib}</p></div>
                <div className="text-right">
                  <span className="text-[14px] tabular-nums text-body">{alone}/{total}</span>
                  <div className="mt-1.5 hidden h-1.5 rounded-full bg-panel-2 sm:block"><div className="h-1.5 rounded-full bg-line-strong" style={{ width: `${(alone / total) * 100}%` }} /></div>
                </div>
                <div className="text-right">
                  <span className="text-[14px] font-semibold tabular-nums text-ink">{withs}/{total}</span>
                  <div className="mt-1.5 hidden h-1.5 rounded-full bg-panel-2 sm:block"><div className="h-1.5 origin-left animate-[grow_1s_cubic-bezier(0.16,1,0.3,1)_both] rounded-full bg-ink" style={{ width: `${(withs / total) * 100}%` }} /></div>
                </div>
              </div>
            ))}
          </div>
        </Reveal>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            [<><CountUp to={101} /><span className="text-muted">/102</span></>, "answers right with verified skills (49 alone)"],
            [<>3<span className="text-muted">/3</span></>, "published MCP tool-poisoning attacks caught"],
            [<>0</>, "false alarms on the 7 official MCP servers, every tool called"],
            [<>21<span className="text-muted">/22</span></>, "popular community MCP servers pass"],
          ].map(([v, l], i) => (
            <Reveal key={i} delay={i * 60} className="h-full">
              <div className="h-full rounded-[10px] border border-line bg-canvas p-4">
                <p className="text-[28px] font-semibold leading-none tracking-[-0.03em] tabular-nums">{v}</p>
                <p className="mt-2 text-[12.5px] leading-snug text-body">{l as string}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* faq */}
      <section id="faq" className="mx-auto grid max-w-[1160px] scroll-mt-20 gap-10 px-5 pb-24 sm:px-8 lg:grid-cols-[0.75fr_1.25fr]">
        <Reveal><H2>Questions people ask first</H2></Reveal>
        <Reveal delay={80}><Faq /></Reveal>
      </section>

      {/* closing */}
      <section className="mx-auto max-w-[1160px] px-5 pb-24 sm:px-8">
        <Reveal>
          <div className="rounded-xl border border-line bg-panel px-6 py-16 text-center sm:py-20">
            <LogoMark className="mx-auto h-10 w-10" />
            <h2 className="mx-auto mt-6 max-w-2xl text-[32px] font-semibold leading-[1.08] tracking-[-0.035em] sm:text-[48px]">
              Give your agent a repository. Get back a tool it can trust.
            </h2>
            <div className="mt-8 flex flex-wrap justify-center gap-2.5">
              <Link href="/app/" className="inline-flex h-11 items-center gap-1.5 rounded-full bg-ink px-5 text-[14.5px] font-medium text-white hover:bg-accent-ink">
                Open the board <ArrowRight className="h-4 w-4" />
              </Link>
              <a href={GITHUB} target="_blank" rel="noreferrer" className="inline-flex h-11 items-center rounded-full border border-line-strong bg-canvas px-5 text-[14.5px] font-medium text-ink hover:bg-panel">
                Star on GitHub
              </a>
            </div>
          </div>
        </Reveal>
      </section>
    </SiteShell>
  );
}
