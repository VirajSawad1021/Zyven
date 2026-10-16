import { useEffect, useState, type ReactNode } from "react";
import { BookOpen, ChartColumn, LayoutGrid, Menu, Network, Rocket, Sparkles, X } from "lucide-react";
import { Logo } from "./Logo";
import { Badge, LiveDot } from "./ui";
import { Star, Stars } from "./motion";
import type { Conn } from "../lib/useBoard";

export type ViewId = "tasks" | "control" | "skills" | "insights" | "explore" | "catalog";

const NAV: { id: ViewId; label: string; icon: typeof LayoutGrid }[] = [
  { id: "tasks", label: "Tasks", icon: LayoutGrid },
  { id: "control", label: "Control center", icon: Rocket },
  { id: "skills", label: "Skills", icon: Sparkles },
  { id: "insights", label: "Insights", icon: ChartColumn },
  { id: "explore", label: "Repo explorer", icon: Network },
  { id: "catalog", label: "Catalog", icon: BookOpen },
];

function SideNav({ view, counts, conn, onNavigate }: { view: ViewId; counts: Partial<Record<ViewId, number>>; conn: Conn; onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between pb-6 pl-5 pr-3 pt-4">
        <Logo onClick={onNavigate} />
      </div>
      <p className="px-5 pb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Workspace</p>
      <nav className="space-y-0.5 px-3">
        {NAV.map((it) => {
          const active = it.id === view;
          const n = counts[it.id];
          return (
            <a
              key={it.id}
              href={`#/${it.id}`}
              onClick={onNavigate}
              className={`flex items-center gap-2.5 rounded-xl px-3 py-2 text-[13px] font-medium transition-colors ${
                active ? "bg-white text-ink shadow-[0_1px_2px_rgba(20,20,19,0.06)] ring-1 ring-line" : "text-body hover:bg-white/60 hover:text-ink"
              }`}
            >
              <it.icon className="h-4 w-4" />
              {it.label}
              {n ? <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-clay px-1.5 text-[10px] font-semibold text-white">{n}</span> : null}
            </a>
          );
        })}
      </nav>

      <div className="mt-auto space-y-3 p-3">
        <div className="art art-sage grain relative overflow-hidden rounded-2xl p-2.5">
          <Stars seed="sidebar" count={5} from={55} to={95} />
          <div className="frost relative z-10 rounded-xl p-2.5">
            <p className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-ink"><Star className="h-2.5 w-2.5 text-clay" /> How the agent grows</p>
            <p className="mt-1 text-[11px] leading-relaxed text-body">
              It never compiles anything without your approval, and a skill is only kept after passing every sandbox gate.
            </p>
          </div>
        </div>
        <div className="px-2">
          <Badge tone={conn === "live" ? "good" : "warn"}>
            {conn === "live" ? <LiveDot /> : null}
            {conn === "live" ? "live" : conn === "connecting" ? "connecting…" : "reconnecting…"}
          </Badge>
        </div>
      </div>
    </div>
  );
}

export function Shell({ view, counts, conn, wide, children }: { view: ViewId; counts: Partial<Record<ViewId, number>>; conn: Conn; wide?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
  }, [open]);

  return (
    <div className="min-h-screen bg-white lg:pl-[248px]">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] border-r border-line bg-cream/60 lg:block">
        <SideNav view={view} counts={counts} conn={conn} />
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-white/90 px-4 backdrop-blur lg:hidden">
        <Logo />
        <button onClick={() => setOpen(true)} className="rounded-lg p-2 text-ink hover:bg-panel-2" aria-label="Open menu">
          <Menu className="h-5 w-5" />
        </button>
      </header>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 animate-fade-in bg-ink/30" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[280px] animate-fade-in bg-cream shadow-xl">
            <button onClick={() => setOpen(false)} className="absolute right-3 top-4 rounded-lg p-1.5 text-body hover:bg-white" aria-label="Close menu">
              <X className="h-5 w-5" />
            </button>
            <SideNav view={view} counts={counts} conn={conn} onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}

      <main key={view} className={`mx-auto px-4 py-8 sm:px-8 sm:py-10 ${wide ? "max-w-[1320px]" : "max-w-[1120px]"}`}>
        <div className="animate-fade-in">{children}</div>
      </main>
    </div>
  );
}
