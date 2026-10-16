"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, Menu, X } from "lucide-react";
import { Logo } from "../Logo";

export const GITHUB = "https://github.com/VirajSawad1021/Zyven";

const links = [
  { href: "/#product", label: "Product" },
  { href: "/#how", label: "How it works" },
  { href: "/#gates", label: "Sandbox gates" },
  { href: "/#results", label: "Results" },
  { href: "/#faq", label: "FAQ" },
];

export function SiteNav() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  return (
    <header className={`sticky top-0 z-40 transition-colors duration-300 ${scrolled || open ? "border-b border-line bg-cream/90 backdrop-blur-md" : "border-b border-transparent"}`}>
      <div className="mx-auto flex h-16 max-w-[1240px] items-center justify-between px-5 sm:px-8">
        <div className="flex items-center gap-10">
          <Logo />
          <nav className="hidden items-center gap-7 lg:flex">
            {links.map((l) => (
              <Link key={l.href} href={l.href} className="text-[14px] text-body transition-colors hover:text-ink">{l.label}</Link>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <a href={GITHUB} target="_blank" rel="noreferrer" className="hidden h-10 items-center gap-1.5 rounded-full bg-cream-2 px-5 text-[14px] font-medium text-ink hover:bg-line-strong/60 sm:inline-flex">
            GitHub <ArrowUpRight className="h-3.5 w-3.5" />
          </a>
          <Link href="/app/" className="inline-flex h-10 items-center gap-1.5 rounded-full bg-ink px-5 text-[14px] font-medium text-white hover:bg-ink-soft">
            Open the board <ArrowRight className="h-4 w-4" />
          </Link>
          <button onClick={() => setOpen(!open)} className="rounded-full p-2 text-ink lg:hidden" aria-label={open ? "Close menu" : "Open menu"}>
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>
      {open && (
        <nav className="border-t border-line px-5 pb-6 pt-2 lg:hidden">
          {links.map((l) => (
            <Link key={l.href} href={l.href} onClick={() => setOpen(false)} className="block border-b border-line py-3.5 text-[16px] text-ink">{l.label}</Link>
          ))}
          <a href={GITHUB} target="_blank" rel="noreferrer" className="mt-4 block text-center text-[15px] font-medium text-body">GitHub</a>
        </nav>
      )}
    </header>
  );
}

export function SiteFooter() {
  const cols: { title: string; items: [string, string][] }[] = [
    { title: "Product", items: [["How it works", "/#how"], ["Sandbox gates", "/#gates"], ["Results", "/#results"], ["FAQ", "/#faq"]] },
    { title: "The board", items: [["Tasks", "/app/"], ["Skills", "/app/skills/"], ["Insights", "/app/insights/"], ["Repo explorer", "/app/explore/"]] },
    { title: "Project", items: [["Source code", GITHUB], ["Issues", `${GITHUB}/issues`], ["Architecture", `${GITHUB}#how-it-works`], ["Frogtoberfest 2026", "https://frogtoberfest.lftechnology.com/"]] },
  ];
  return (
    <footer className="border-t border-line bg-cream">
      <div className="mx-auto max-w-[1240px] px-5 pb-10 pt-16 sm:px-8">
        <div className="grid gap-12 lg:grid-cols-[1.3fr_2fr]">
          <div>
            <Logo />
            <p className="mt-4 max-w-xs text-[14px] leading-relaxed text-body">
              An agent that compiles open-source code into verified tools when it needs them, and keeps only the ones that pass every gate.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
            {cols.map((c) => (
              <div key={c.title}>
                <p className="text-[13px] font-medium text-ink">{c.title}</p>
                <ul className="mt-4 space-y-2.5">
                  {c.items.map(([label, href]) => (
                    <li key={label}>
                      {href.startsWith("http")
                        ? <a href={href} target="_blank" rel="noreferrer" className="text-[13px] text-body hover:text-ink">{label}</a>
                        : <Link href={href} className="text-[13px] text-body hover:text-ink">{label}</Link>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-16 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-6 text-[12px] text-muted">
          <span>Zyven · open source · Frogtoberfest 2026 by Leapfrog</span>
          <span>Open-weight models only · MCP · Docker sandbox</span>
        </div>
      </div>
    </footer>
  );
}

export function SiteShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-cream text-ink">
      <SiteNav />
      <main>{children}</main>
      <SiteFooter />
    </div>
  );
}
