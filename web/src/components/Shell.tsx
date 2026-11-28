"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowUpRight, BookOpen, ChartColumn, CornerDownLeft, LayoutGrid, Menu, Network, Plug, Rocket, Search, Sparkles, X,
} from "lucide-react";
import { Logo } from "./Logo";
import { useBoardData } from "../lib/board";

type BadgeKey = "approvals" | "skills";
type NavItem = { href: string; label: string; icon: typeof LayoutGrid; badge?: BadgeKey; hint: string };

const GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Work",
    items: [
      { href: "/app/", label: "Tasks", icon: LayoutGrid, badge: "approvals", hint: "Give the agent work and approve new tools" },
      { href: "/app/control/", label: "Control", icon: Rocket, hint: "Assign work to coding agents and watch it run" },
      { href: "/app/connections/", label: "Connections", icon: Plug, hint: "Connected MCP servers and what they may do" },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/app/skills/", label: "Skills", icon: Sparkles, badge: "skills", hint: "Verified tools the agent can call" },
      { href: "/app/catalog/", label: "Catalog", icon: BookOpen, hint: "Pinned open-source repositories" },
      { href: "/app/explore/", label: "Explorer", icon: Network, hint: "Look inside a repository before compiling it" },
    ],
  },
  {
    label: "Measure",
    items: [{ href: "/app/insights/", label: "Insights", icon: ChartColumn, hint: "What the skills saved, in numbers" }],
  },
];
const NAV = GROUPS.flatMap((g) => g.items);

const norm = (p: string) => (p.endsWith("/") ? p : `${p}/`);
const isActive = (href: string, path: string) => (href === "/app/" ? path === "/app/" : path.startsWith(href));

function useCounts(): Record<BadgeKey, number> {
  const { cards, skills } = useBoardData();
  return {
    approvals: cards.filter((c) => c.status === "NEEDS_APPROVAL").length,
    skills: skills.length,
  };
}

function Status() {
  const { conn } = useBoardData();
  const live = conn === "live";
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-muted">
      <span className={`h-1.5 w-1.5 rounded-full transition-colors ${live ? "bg-good" : "bg-warn"}`} />
      {live ? "Connected" : conn === "connecting" ? "Connecting" : "Reconnecting"}
    </span>
  );
}

function NavLink({ it, active, count, onClick }: { it: NavItem; active: boolean; count: number; onClick?: () => void }) {
  return (
    <Link
      href={it.href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={`group relative flex h-9 items-center gap-2 rounded-md border px-2.5 text-[13px] font-medium transition-colors duration-150 lg:h-8 ${
        active
          ? "border-line bg-canvas text-ink shadow-[0_1px_0_rgba(27,25,21,0.04)]"
          : "border-transparent text-body hover:bg-panel-2 hover:text-ink"
      }`}
    >
      <it.icon className={`h-4 w-4 shrink-0 transition-colors ${active ? "text-ink" : "text-muted group-hover:text-body"}`} strokeWidth={1.75} />
      <span className="truncate">{it.label}</span>
      {count > 0 && (
        <span className={`ml-auto flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] px-1 text-[10.5px] font-semibold tabular-nums ${
          it.badge === "approvals" ? "bg-ink text-white" : "bg-panel-2 text-muted"}`}>{count}</span>
      )}
    </Link>
  );
}

function Sidebar({ path, onNavigate, onSearch }: { path: string; onNavigate?: () => void; onSearch: () => void }) {
  const counts = useCounts();
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center px-4">
        <Logo href="/" onClick={onNavigate} />
      </div>
      <div className="px-3">
        <button
          onClick={onSearch}
          className="flex h-9 w-full items-center gap-2 rounded-md border border-line bg-canvas px-2.5 text-[13px] text-muted transition-colors hover:border-line-strong hover:text-body lg:h-8"
        >
          <Search className="h-3.5 w-3.5" strokeWidth={2} />
          Search or jump to
          <span className="ml-auto hidden items-center gap-0.5 lg:flex"><kbd className="kbd">Ctrl</kbd><kbd className="kbd">K</kbd></span>
        </button>
      </div>
      <nav className="scroll-quiet mt-4 flex-1 space-y-5 overflow-y-auto px-3 pb-4" aria-label="Workspace">
        {GROUPS.map((g) => (
          <div key={g.label}>
            <p className="mb-1 px-2.5 text-[11px] font-medium text-muted">{g.label}</p>
            <div className="space-y-px">
              {g.items.map((it) => (
                <NavLink key={it.href} it={it} active={isActive(it.href, path)} count={it.badge ? counts[it.badge] : 0}
                  onClick={onNavigate} />
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="flex items-center justify-between border-t border-line px-4 py-3">
        <Status />
        <a href="https://github.com/VirajSawad1021/Zyven" target="_blank" rel="noreferrer"
          className="inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[12px] text-muted transition-colors hover:bg-panel-2 hover:text-ink">
          GitHub <ArrowUpRight className="h-3 w-3" />
        </a>
      </div>
    </div>
  );
}

type Command = { id: string; label: string; hint: string; group: string; icon: typeof LayoutGrid; run: () => void };

/** Ctrl K: jump to a page or a skill. Arrow keys move, Enter opens, Esc closes; focus returns to the opener. */
function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { skills } = useBoardData();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const commands = useMemo<Command[]>(() => {
    const go = (href: string) => () => { router.push(href); onClose(); };
    return [
      ...NAV.map((n) => ({ id: n.href, label: n.label, hint: n.hint, group: "Pages", icon: n.icon, run: go(n.href) })),
      ...skills.slice(0, 40).map((s) => ({
        id: `skill:${s.name}`, label: s.title || s.name, hint: s.name, group: "Skills", icon: Sparkles, run: go("/app/skills/"),
      })),
    ];
  }, [router, onClose, skills]);

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? commands.filter((c) => `${c.label} ${c.hint}`.toLowerCase().includes(t)) : commands;
  }, [commands, q]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, shown.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); shown[sel]?.run(); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };

  useEffect(() => {
    listRef.current?.querySelector(`[data-i="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  if (!open) return null;
  let last = "";
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]" onKeyDown={onKey}>
      <div className="absolute inset-0 animate-fade-in bg-ink/20" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal="true" aria-label="Search or jump to"
        className="relative w-full max-w-[560px] animate-rise overflow-hidden rounded-xl border border-line bg-canvas shadow-[0_24px_64px_-16px_rgba(27,25,21,0.28),0_4px_16px_rgba(27,25,21,0.08)]">
        <div className="flex h-12 items-center gap-2.5 border-b border-line px-4">
          <Search className="h-4 w-4 text-muted" />
          <input
            autoFocus value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }}
            placeholder="Search pages and skills"
            className="h-full flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-muted"
            aria-label="Search pages and skills"
          />
          <kbd className="kbd">Esc</kbd>
        </div>
        <div ref={listRef} className="scroll-quiet max-h-[360px] overflow-y-auto p-1.5" role="listbox">
          {shown.length === 0 && <p className="px-3 py-8 text-center text-[13px] text-muted">Nothing matches &ldquo;{q}&rdquo;.</p>}
          {shown.map((c, i) => {
            const head = c.group !== last ? c.group : null;
            last = c.group;
            return (
              <div key={c.id}>
                {head && <p className="px-2.5 pb-1 pt-2.5 text-[11px] font-medium text-muted">{head}</p>}
                <button
                  data-i={i} role="option" aria-selected={i === sel}
                  onMouseMove={() => setSel(i)} onClick={c.run}
                  className={`flex min-h-9 w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left transition-colors ${i === sel ? "bg-accent-soft" : ""}`}
                >
                  <c.icon className="h-4 w-4 shrink-0 text-muted" strokeWidth={1.75} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-ink">{c.label}</span>
                    <span className="block truncate text-[11.5px] text-muted">{c.hint}</span>
                  </span>
                  {i === sel && <CornerDownLeft className="h-3.5 w-3.5 text-muted" />}
                </button>
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-3 border-t border-line bg-panel px-4 py-2 text-[11.5px] text-muted">
          <span className="flex items-center gap-1"><kbd className="kbd">↑</kbd><kbd className="kbd">↓</kbd> move</span>
          <span className="flex items-center gap-1"><kbd className="kbd">Enter</kbd> open</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** The app frame, a quiet sidebar, a breadcrumb bar, and the page on a warm paper canvas. */
export function Shell({ children }: { children: ReactNode }) {
  const path = norm(usePathname() ?? "/app/");
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const page = NAV.find((n) => isActive(n.href, path));
  const wide = path.startsWith("/app/explore");

  const openPalette = () => {
    opener.current = document.activeElement as HTMLElement | null;
    setDrawer(false);
    setPalette(true);
  };
  const closePalette = () => {
    setPalette(false);
    opener.current?.focus?.();
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        opener.current = document.activeElement as HTMLElement | null;
        setPalette((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="min-h-screen bg-canvas">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] border-r border-line bg-cream lg:block">
        <Sidebar path={path} onSearch={openPalette} />
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 animate-fade-in bg-ink/20" onClick={() => setDrawer(false)} aria-hidden />
          <aside className="relative h-full w-[272px] max-w-[85vw] animate-[slide-in_0.22s_cubic-bezier(0.16,1,0.3,1)_both] border-r border-line bg-cream shadow-[12px_0_32px_-20px_rgba(27,25,21,0.35)]">
            <button onClick={() => setDrawer(false)} aria-label="Close menu"
              className="absolute right-2 top-3 rounded-md p-2 text-muted hover:bg-panel-2 hover:text-ink">
              <X className="h-4 w-4" />
            </button>
            <Sidebar path={path} onNavigate={() => setDrawer(false)} onSearch={openPalette} />
          </aside>
        </div>
      )}

      <div className="lg:pl-[248px]">
        <header className="sticky top-0 z-20 flex h-12 items-center gap-2 border-b border-line bg-canvas/95 px-3 sm:px-5">
          <button onClick={() => setDrawer(true)} aria-label="Open menu"
            className="rounded-md p-2 text-body hover:bg-panel-2 hover:text-ink lg:hidden">
            <Menu className="h-4 w-4" />
          </button>
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[13px]">
            <span className="text-muted">Zyven</span>
            <span className="text-line-strong">/</span>
            <span className="flex min-w-0 items-center gap-1.5 font-medium text-ink">
              {page && <page.icon className="h-3.5 w-3.5 shrink-0 text-muted" strokeWidth={1.75} />}
              <span className="truncate">{page?.label ?? "Board"}</span>
            </span>
          </nav>
          <button onClick={openPalette} aria-label="Search or jump to"
            className="ml-auto flex h-8 items-center gap-2 rounded-md px-2 text-[12.5px] text-muted transition-colors hover:bg-panel-2 hover:text-ink">
            <Search className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Search</span>
            <span className="hidden items-center gap-0.5 sm:flex"><kbd className="kbd">Ctrl</kbd><kbd className="kbd">K</kbd></span>
          </button>
        </header>

        <main key={path} className={`mx-auto px-4 pb-20 pt-8 sm:px-8 sm:pt-10 ${wide ? "max-w-[1320px]" : "max-w-[1120px]"}`}>
          <div className="animate-page">{children}</div>
        </main>
      </div>

      <CommandPalette open={palette} onClose={closePalette} />
    </div>
  );
}
