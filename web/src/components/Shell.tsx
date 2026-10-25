"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, ChartColumn, LayoutGrid, Menu, Network, Plug, Rocket, Sparkles, X } from "lucide-react";
import { Logo } from "./Logo";
import { LiveDot } from "./ui";
import { useBoardData } from "../lib/board";

type BadgeKey = "approvals" | "skills";
const NAV: { href: string; label: string; icon: typeof LayoutGrid; badge?: BadgeKey }[] = [
  { href: "/app/", label: "Tasks", icon: LayoutGrid, badge: "approvals" },
  { href: "/app/control/", label: "Control", icon: Rocket },
  { href: "/app/connections/", label: "Connections", icon: Plug },
  { href: "/app/skills/", label: "Skills", icon: Sparkles, badge: "skills" },
  { href: "/app/insights/", label: "Insights", icon: ChartColumn },
  { href: "/app/explore/", label: "Explorer", icon: Network },
  { href: "/app/catalog/", label: "Catalog", icon: BookOpen },
];

const norm = (p: string) => (p.endsWith("/") ? p : `${p}/`);
const isActive = (href: string, path: string) => (href === "/app/" ? path === "/app/" : path.startsWith(href));

function Conn() {
  const { conn } = useBoardData();
  const live = conn === "live";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${live ? "bg-good-bg text-good" : "bg-warn-bg text-warn"}`}>
      {live && <LiveDot />}
      {live ? "Live" : conn === "connecting" ? "Connecting" : "Reconnecting"}
    </span>
  );
}

/** The app frame: a sticky header with a pill navigation (MitraField pattern), content below. */
export function Shell({ children }: { children: ReactNode }) {
  const path = norm(usePathname() ?? "/app/");
  const { cards, skills } = useBoardData();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const counts: Record<BadgeKey, number> = {
    approvals: cards.filter((c) => c.status === "NEEDS_APPROVAL").length,
    skills: skills.length,
  };
  const wide = path.startsWith("/app/explore");

  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 4);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  return (
    <div className="min-h-screen bg-white">
      <header className={`sticky top-0 z-40 border-b transition-colors duration-200 ${scrolled ? "border-line bg-white/85 backdrop-blur-md" : "border-transparent bg-white"}`}>
        <div className="mx-auto flex h-16 max-w-[1320px] items-center gap-4 px-4 sm:px-8">
          <Logo href="/" />
          <nav className="mx-auto hidden items-center gap-0.5 rounded-full bg-panel-2 p-1 lg:flex" aria-label="Workspace">
            {NAV.map((it) => {
              const active = isActive(it.href, path);
              const n = it.badge ? counts[it.badge] : 0;
              return (
                <Link
                  key={it.href}
                  href={it.href}
                  className={`flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-all ${
                    active ? "bg-white text-ink shadow-[0_1px_2px_rgba(20,20,19,0.08)]" : "text-body hover:text-ink"
                  }`}
                >
                  <it.icon className="h-[15px] w-[15px]" />
                  {it.label}
                  {n ? (
                    <span className={`flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-[10px] font-semibold ${
                      it.badge === "approvals" ? "bg-clay text-white" : "bg-cream-2 text-body"}`}>{n}</span>
                  ) : null}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-2 lg:ml-0">
            <Conn />
            <button onClick={() => setOpen((o) => !o)} className="rounded-full p-2 text-ink hover:bg-panel-2 lg:hidden" aria-label={open ? "Close menu" : "Open menu"}>
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>
        {open && (
          <nav className="animate-fade-in border-t border-line bg-white px-4 pb-4 pt-2 lg:hidden" aria-label="Workspace">
            {NAV.map((it) => (
              <Link key={it.href} href={it.href} onClick={() => setOpen(false)}
                className={`flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-[14px] font-medium ${isActive(it.href, path) ? "bg-panel-2 text-ink" : "text-body"}`}>
                <it.icon className="h-4 w-4" /> {it.label}
              </Link>
            ))}
          </nav>
        )}
      </header>

      <main key={path} className={`mx-auto px-4 pb-16 pt-8 sm:px-8 sm:pt-10 ${wide ? "max-w-[1320px]" : "max-w-[1160px]"}`}>
        <div className="animate-fade-in">{children}</div>
      </main>
    </div>
  );
}
