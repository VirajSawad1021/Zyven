"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, Minus, Plus } from "lucide-react";
import { GITHUB, SiteShell } from "../components/site/Chrome";
import { Showcase } from "../components/site/Showcase";
import { CountUp, Reveal, Star, Stars } from "../components/motion";

const LEARNS_FROM = ["python-stdnum", "phonenumbers", "hijridate", "pyluach", "py-nepali", "sympy", "MCP", "Docker sandbox", "Gemma 4 · open weights", "FastAPI", "Next.js"];

const FAQ: [string, string][] = [
  ["Why not just let the model write the code itself?", "Because the model is exactly what gets checksums, calendars and validation rules wrong. The correct, tested logic already exists in open-source libraries. Zyven has the model write only a thin adapter around that code, and the sandbox proves the adapter answers exactly what the library answers."],
  ["Does anything run without my approval?", "No. When the agent finds a gap it proposes a repository from the pinned catalog and waits. Nothing is cloned, compiled or executed until you approve the card on the board."],
  ["What does 'verified' actually mean?", "A skill is verified only for the gates it passed, and they are listed on it: policy, import, the library's own upstream tests, input robustness, an MCP smoke test, and differential tests against the library. Tools that cannot be repaired are dropped from the package and recorded, never shipped unverified."],
  ["Is repository code run on my machine?", "Analysis is static: the source is parsed, never imported. Everything that executes does so in a Docker container with no network, a non-root user, a read-only filesystem, every Linux capability dropped and resource limits."],
  ["Which models does it use?", "Open-weight models only, across the whole pipeline. The published results use gemma-4-26b-a4b-it through any OpenAI-compatible host, with automatic failover to a second host."],
  ["Does it get faster over time?", "Yes. Verified skills are stored with their provenance and health. The next task that needs the same capability reuses the skill instead of compiling, which is why a reuse takes seconds and a compile takes minutes."],
];

function Faq() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <div className="divide-y divide-line border-y border-line">
      {FAQ.map(([q, a], i) => (
        <div key={q}>
          <button onClick={() => setOpen(open === i ? null : i)} className="flex w-full items-center justify-between gap-6 py-6 text-left" aria-expanded={open === i}>
            <span className="text-[18px] tracking-[-0.01em] text-ink sm:text-[20px]">{q}</span>
            {open === i ? <Minus className="h-5 w-5 shrink-0 text-muted" /> : <Plus className="h-5 w-5 shrink-0 text-muted" />}
          </button>
          <div className={`grid transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${open === i ? "grid-rows-[1fr] pb-6 opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
            <p className="max-w-3xl overflow-hidden text-[15px] leading-relaxed text-body">{a}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

const ROWS = [
  {
    n: "01", id: "discover", t: "Read the repository, never run it",
    b: "The analyzer walks the AST of the whole repository: public symbols, call graph, tests, doctests, side effects and license. It links each function to the tests that exercise it, so the model starts from facts, not guesses.",
    art: "/art/sage.webp",
    vis: (
      <div className="space-y-2.5">
        {[["stdnum.iban.validate", "tested · pure"], ["stdnum.luhn.checksum", "tested · pure"], ["stdnum.util.get_cc_module", "reads files · skipped"]].map(([s, m], i) => (
          <div key={s} className="flex items-center justify-between gap-3 rounded-2xl bg-white/90 px-4 py-3 shadow-sm backdrop-blur" style={{ marginLeft: i * 18 }}>
            <span className="font-mono text-[13px]">{s}</span>
            <span className={`text-[12px] ${i === 2 ? "text-warn" : "text-muted"}`}>{m}</span>
          </div>
        ))}
      </div>
    ),
  },
  {
    n: "02", id: "compile", t: "The model proposes. The harness decides.",
    b: "Scout picks capabilities, Architect designs the tools, Compiler writes them and Tester writes reference cases without ever seeing the adapter. Every name the model writes is resolved against the analysis; invented or ambiguous ones are rejected before any code runs.",
    art: "/art/warm.webp",
    vis: (
      <div className="space-y-2.5">
        {[["Scout", "2 capabilities"], ["Architect", "3 tools · lint passed"], ["Compiler", "server.py"], ["Tester", "reference cases"]].map(([r, v]) => (
          <div key={r} className="flex items-center justify-between rounded-2xl bg-white/90 px-4 py-3 shadow-sm backdrop-blur">
            <span className="flex items-center gap-2 text-[14px] font-medium"><Star className="h-3 w-3 text-clay" />{r}</span>
            <span className="text-[13px] text-muted">{v}</span>
          </div>
        ))}
      </div>
    ),
  },
  {
    n: "03", id: "verify", t: "Kept only if it survives the sandbox",
    b: "Six gates run in a locked-down container. A failure goes to a bounded Repair step and is verified again; a tool that still fails is dropped and recorded. What is left ships with its provenance: repository, pinned commit and the exact gates it passed.",
    art: "/art/orb.webp",
    vis: (
      <div className="space-y-2.5">
        {[["Upstream tests", "pass"], ["Input robustness", "repaired, then pass"], ["Differential vs library", "pass"]].map(([c, v]) => (
          <div key={c} className="flex items-center justify-between gap-3 rounded-2xl bg-white/90 px-4 py-3 shadow-sm backdrop-blur">
            <span className="text-[14px]">{c}</span>
            <span className={`text-[12px] font-medium ${v === "pass" ? "text-good" : "text-warn"}`}>{v}</span>
          </div>
        ))}
      </div>
    ),
  },
];

const GATES = [
  { t: "Policy", b: "Generated code is checked before it runs: import allowlist, no eval, exec or locals.", svg: <path d="M40 10 64 20v18c0 16-10 26-24 32-14-6-24-16-24-32V20z" /> },
  { t: "Import", b: "The assembled MCP server must import cleanly inside the container.", svg: <><rect x="14" y="22" width="52" height="40" rx="6" /><path d="M14 34h52" /></> },
  { t: "Upstream tests", b: "The library's own test suite runs against the pinned checkout and must still pass.", svg: <><path d="M20 42l12 12 28-28" /><circle cx="40" cy="40" r="30" /></> },
  { t: "Input robustness", b: "Spaces, lowercase, separators and junk: tools must answer, not crash.", svg: <><path d="M12 40c8-14 16-14 24 0s16 14 24 0 8-14 8-14" /></> },
  { t: "MCP smoke", b: "Every tool is listed and called over the real MCP protocol.", svg: <><circle cx="24" cy="40" r="10" /><circle cx="56" cy="40" r="10" /><path d="M34 40h12" /></> },
  { t: "Differential", b: "Tool answers are compared with the library called directly. This gate caught a silent wrong-algorithm bug.", svg: <><rect x="10" y="24" width="26" height="32" rx="4" /><rect x="44" y="24" width="26" height="32" rx="4" /><path d="M36 40h8" /></> },
];

const SUITES = [
  { name: "Global standard numbers", repo: "python-stdnum", what: "IBAN validity, IBAN check digits, Luhn", alone: 0, with: 18, total: 18 },
  { name: "Calendars and phone numbers", repo: "hijridate · pyluach · phonenumbers", what: "Hijri and Gregorian, Jewish holidays, phone validity and E.164", alone: 18, with: 27, total: 30 },
  { name: "Bikram Sambat calendar", repo: "py-nepali", what: "Date conversions, weekdays, phone operators", alone: 9, with: 40, total: 40 },
];

function SuiteBars({ s }: { s: (typeof SUITES)[number] }) {
  const bar = (v: number, cls: string, label: string) => (
    <div>
      <div className="flex items-baseline justify-between text-[12px]">
        <span className="text-body">{label}</span>
        <span className="font-mono tabular-nums text-ink">{v}/{s.total}</span>
      </div>
      <div className="mt-1.5 h-2.5 rounded-full bg-panel-2">
        <div className={`h-2.5 origin-left animate-[grow_1.2s_cubic-bezier(0.16,1,0.3,1)_both] rounded-full ${cls}`} style={{ width: `${Math.max(1.5, (v / s.total) * 100)}%` }} />
      </div>
    </div>
  );
  return (
    <div className="flex h-full flex-col rounded-[24px] border border-line bg-white p-6">
      <p className="text-[13px] text-muted">{s.repo}</p>
      <p className="mt-1 text-[19px] font-medium tracking-[-0.02em]">{s.name}</p>
      <p className="mt-1 text-[13px] leading-relaxed text-body">{s.what}</p>
      <p className="mt-6 text-[56px] font-medium leading-none tracking-[-0.04em]">
        <CountUp to={Math.round((s.with / s.total) * 100)} /><span className="text-[28px] text-muted">%</span>
      </p>
      <p className="mt-1 text-[12px] text-muted">correct with compiled skills</p>
      <div className="mt-auto space-y-3 pt-6">
        {bar(s.alone, "bg-line-strong", "Model alone")}
        {bar(s.with, "bg-clay", "Model + Zyven skills")}
      </div>
    </div>
  );
}

export default function Landing() {
  return (
    <SiteShell>
      {/* ---------------- hero ---------------- */}
      <section className="relative mx-auto max-w-[1240px] px-5 pb-12 pt-16 sm:px-8 sm:pt-24">
        <div className="grid items-end gap-10 lg:grid-cols-2">
          <Reveal>
            <p className="mb-5 inline-flex items-center rounded-full border border-line-strong bg-white/60 px-3 py-1 text-[12px] font-medium text-body">
              Open source · open-weight models only
            </p>
            <h1 className="text-[46px] font-medium leading-[1.02] tracking-[-0.035em] text-ink sm:text-[72px]">
              Agents that compile
              <br />
              their own tools.
            </h1>
          </Reveal>
          <Reveal delay={120}>
            <div className="lg:pb-3">
              <p className="max-w-[520px] text-[17px] leading-relaxed text-body">
                Models are confidently wrong about checksums, calendars and validation rules. Zyven turns the open-source code that gets them right
                into MCP tools, proves each one in a locked-down sandbox, and lets the agent keep what passes.
              </p>
              <div className="mt-7 flex flex-wrap gap-3">
                <Link href="/app/" className="inline-flex h-12 items-center gap-2 rounded-full bg-ink px-6 text-[15px] font-medium text-white transition-colors hover:bg-ink-soft">
                  Open the board <ArrowRight className="h-4 w-4" />
                </Link>
                <a href={GITHUB} target="_blank" rel="noreferrer" className="inline-flex h-12 items-center gap-1.5 rounded-full border border-line-strong bg-white/60 px-6 text-[15px] font-medium text-ink transition-colors hover:bg-white">
                  Read the code <ArrowUpRight className="h-4 w-4" />
                </a>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---------------- product showcase ---------------- */}
      <section id="product" className="mx-auto max-w-[1240px] scroll-mt-20 px-3 sm:px-8">
        <Reveal delay={200}>
          <Showcase />
        </Reveal>
      </section>

      {/* ---------------- marquee ---------------- */}
      <section className="mx-auto mt-16 max-w-[1240px] px-5 sm:px-8">
        <p className="text-center text-[13px] text-muted">Learns from open source, built on open tools</p>
        <div className="relative mt-5 overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]">
          <div className="flex w-max animate-[marquee_38s_linear_infinite] gap-14">
            {[...LEARNS_FROM, ...LEARNS_FROM].map((s, i) => (
              <span key={i} className="whitespace-nowrap text-[20px] font-medium tracking-[-0.02em] text-ink/40">{s}</span>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------- two cards ---------------- */}
      <section className="mx-auto max-w-[1240px] px-5 py-28 sm:px-8">
        <Reveal>
          <h2 className="max-w-3xl text-[36px] font-medium leading-[1.08] tracking-[-0.03em] sm:text-[52px]">
            It notices what it can&apos;t do. <span className="text-muted">Then it learns, with your permission.</span>
          </h2>
        </Reveal>
        <div className="mt-14 grid gap-6 lg:grid-cols-2">
          {[
            {
              who: "The self-extending agent", title: "Finds the gap, proposes a repository, waits for you", href: "/app/", cta: "Try it on the board",
              art: "/art/warm.webp",
              ui: (
                <div className="space-y-2">
                  <div className="rounded-xl bg-white p-3 shadow-sm">
                    <p className="text-[11px] text-muted">Capability gap</p>
                    <p className="text-[15px] font-semibold">Validate a phone number in E.164</p>
                    <p className="text-[12px] text-body">Proposed source: phonenumbers @ pinned commit</p>
                  </div>
                  <div className="flex gap-2">
                    <span className="rounded-full bg-ink px-3 py-1.5 text-[12px] font-medium text-white">Approve compile</span>
                    <span className="rounded-full bg-white/90 px-3 py-1.5 text-[12px] font-medium text-ink">Reject</span>
                  </div>
                </div>
              ),
            },
            {
              who: "The skill library", title: "Keeps every verified skill, with its provenance and health", href: "/app/skills/", cta: "Browse the skills",
              art: "/art/sage.webp",
              ui: (
                <div className="space-y-2">
                  <div className="rounded-xl bg-white p-3 shadow-sm">
                    <p className="flex items-center justify-between text-[15px] font-semibold">iban_validation <span className="text-[11px] font-medium text-good">6/6 gates</span></p>
                    <p className="font-mono text-[11px] text-body">validate_iban · format_iban · calculate_iban_check_digits</p>
                  </div>
                  <div className="rounded-xl bg-white/90 p-3 text-[12px] text-body shadow-sm">Reused in seconds next time. A compile takes minutes.</div>
                </div>
              ),
            },
          ].map((c, i) => (
            <Reveal key={c.who} delay={i * 120}>
              <div className="group flex h-full flex-col">
                <p className="text-[15px] text-muted">{c.who}</p>
                <p className="mt-1 max-w-md text-[22px] font-medium leading-snug tracking-[-0.02em]">{c.title}</p>
                <div className="relative mt-6 flex min-h-[300px] flex-1 items-end overflow-hidden rounded-[28px] bg-cover bg-center p-6 sm:p-8" style={{ backgroundImage: `url(${c.art})` }}>
                  <Stars seed={c.who} count={6} from={55} to={95} />
                  <div className="relative w-full max-w-sm transition-transform duration-700 group-hover:-translate-y-1">{c.ui}</div>
                </div>
                <Link href={c.href} className="mt-5 inline-flex items-center gap-1.5 text-[15px] font-medium text-ink hover:gap-2.5 hover:underline">
                  {c.cta} <ArrowRight className="h-4 w-4 transition-all" />
                </Link>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---------------- how it works ---------------- */}
      <section id="how" className="scroll-mt-16 border-y border-line bg-white">
        <div className="mx-auto max-w-[1240px] px-5 py-28 sm:px-8">
          <Reveal>
            <p className="text-[15px] text-muted">How it works</p>
            <h2 className="mt-2 max-w-3xl text-[36px] font-medium leading-[1.08] tracking-[-0.03em] sm:text-[52px]">From a repository to a tool you can trust.</h2>
          </Reveal>
          <div className="mt-20 space-y-28">
            {ROWS.map((row, i) => (
              <div key={row.n} id={row.id} className={`grid items-center gap-10 lg:grid-cols-2 lg:gap-20 ${i % 2 ? "lg:[&>*:first-child]:order-2" : ""}`}>
                <Reveal>
                  <div className="relative overflow-hidden rounded-[28px] bg-cover bg-center px-6 py-14 sm:px-12" style={{ backgroundImage: `url(${row.art})` }}>
                    <div className="relative mx-auto max-w-md">{row.vis}</div>
                  </div>
                </Reveal>
                <Reveal delay={120}>
                  <p className="font-mono text-[13px] text-muted">{row.n}</p>
                  <h3 className="mt-3 text-[28px] font-medium leading-tight tracking-[-0.025em] sm:text-[34px]">{row.t}</h3>
                  <p className="mt-4 max-w-lg text-[16px] leading-relaxed text-body">{row.b}</p>
                </Reveal>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------- gates ---------------- */}
      <section id="gates" className="relative scroll-mt-16 overflow-hidden bg-ink text-white">
        <div className="mx-auto grid max-w-[1240px] gap-12 px-5 py-28 sm:px-8 lg:grid-cols-[0.9fr_1.3fr]">
          <Reveal>
            <p className="text-[15px] text-white/50">Six sandbox gates</p>
            <h2 className="mt-2 text-[36px] font-medium leading-[1.08] tracking-[-0.03em] sm:text-[52px]">The model writes it. The sandbox proves it.</h2>
            <p className="mt-5 max-w-md text-[16px] leading-relaxed text-white/60">
              Every gate runs in Docker with no network, a non-root user, a read-only filesystem and every capability dropped. A skill is verified
              only for the gates it actually passed.
            </p>
            <div className="mt-8 rounded-[20px] border border-white/10 bg-white/[0.04] p-5">
              <p className="text-[12px] font-medium uppercase tracking-[0.08em] text-clay">Caught in development</p>
              <p className="mt-2 text-[14px] leading-relaxed text-white/70">
                A generated &ldquo;Luhn&rdquo; tool silently ran a different checksum. Every other gate passed. The differential gate disagreed with
                the library on 3 of 8 cases, and the build now scopes imports per tool.
              </p>
            </div>
          </Reveal>
          <div className="grid gap-4 sm:grid-cols-2">
            {GATES.map((c, i) => (
              <Reveal key={c.t} delay={i * 70}>
                <div className="h-full rounded-[24px] border border-white/10 bg-white/[0.03] p-6 transition-colors hover:bg-white/[0.06]">
                  <div className="flex items-start justify-between">
                    <svg viewBox="0 0 80 80" className="h-12 w-12 fill-none stroke-white/70" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">{c.svg}</svg>
                    <span className="font-mono text-[12px] text-white/35">0{i + 1}</span>
                  </div>
                  <p className="mt-6 text-[17px] font-medium">{c.t}</p>
                  <p className="mt-2 text-[14px] leading-relaxed text-white/55">{c.b}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------------- results ---------------- */}
      <section id="results" className="mx-auto max-w-[1240px] scroll-mt-16 px-5 py-28 sm:px-8">
        <Reveal>
          <p className="text-[15px] text-muted">Measured, not claimed</p>
          <h2 className="mt-2 max-w-3xl text-[36px] font-medium leading-[1.08] tracking-[-0.03em] sm:text-[52px]">
            Same model, same budget. <span className="text-muted">The only difference is the tools.</span>
          </h2>
          <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-body">
            Open-weight <span className="font-mono text-[13px]">gemma-4-26b-a4b-it</span> in every condition, with ground truth computed by the source library
            itself. Raw records are in the repository.
          </p>
        </Reveal>
        <div className="mt-12 grid gap-5 lg:grid-cols-3">
          {SUITES.map((s, i) => (
            <Reveal key={s.name} delay={i * 100} className="h-full">
              <SuiteBars s={s} />
            </Reveal>
          ))}
        </div>
        <p className="mt-5 text-[12.5px] leading-relaxed text-muted">
          Calendars and phone numbers: no Jewish-holiday skill in this run, because the hosted endpoint timed out on that compile, so that category ran without a skill in both conditions.
        </p>
      </section>

      {/* ---------------- faq ---------------- */}
      <section id="faq" className="mx-auto grid max-w-[1240px] scroll-mt-20 gap-10 px-5 pb-28 sm:px-8 lg:grid-cols-[0.8fr_1.2fr]">
        <Reveal>
          <h2 className="text-[36px] font-medium leading-[1.08] tracking-[-0.03em] sm:text-[48px]">Questions people ask first</h2>
        </Reveal>
        <Reveal delay={100}>
          <Faq />
        </Reveal>
      </section>

      {/* ---------------- final cta ---------------- */}
      <section className="mx-auto max-w-[1240px] px-5 pb-28 sm:px-8">
        <Reveal>
          <div className="relative overflow-hidden rounded-[36px] bg-[#f8f4eb] px-6 py-20 text-center sm:py-28">
            <div aria-hidden className="pointer-events-none absolute inset-0 animate-[drift_12s_ease-in-out_infinite] bg-[url(/art/orb.webp)] bg-[length:auto_150%] bg-center bg-no-repeat" />
            <Stars seed="cta" count={9} />
            <div className="relative">
              <h2 className="mx-auto max-w-3xl text-[40px] font-medium leading-[1.04] tracking-[-0.035em] sm:text-[64px]">Give your agent a repository. Get back a tool it can trust.</h2>
              <div className="mt-9 flex flex-wrap justify-center gap-3">
                <Link href="/app/" className="inline-flex h-12 items-center gap-2 rounded-full bg-ink px-6 text-[15px] font-medium text-white hover:bg-ink-soft">
                  Open the board <ArrowRight className="h-4 w-4" />
                </Link>
                <a href={GITHUB} target="_blank" rel="noreferrer" className="inline-flex h-12 items-center rounded-full bg-white/80 px-6 text-[15px] font-medium text-ink backdrop-blur hover:bg-white">
                  Star on GitHub
                </a>
              </div>
            </div>
          </div>
        </Reveal>
      </section>
    </SiteShell>
  );
}
