"use client";

import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import type { Tone } from "../lib/labels";
import { CountUp, Reveal } from "./motion";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "light";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-ink text-white hover:bg-accent-ink disabled:bg-[#bdb8ad]",
  secondary: "bg-canvas text-ink border border-line-strong hover:border-muted/60 hover:bg-panel disabled:text-muted",
  ghost: "text-body hover:text-ink hover:bg-panel-2",
  danger: "bg-canvas text-bad border border-[#ecd0d0] hover:border-bad hover:bg-bad-bg",
  light: "bg-canvas text-ink border border-line hover:bg-panel",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-2.5 text-[12.5px] lg:h-7",
  md: "h-10 px-3.5 text-[13px] lg:h-9",
  lg: "h-11 px-4.5 text-[14px] lg:h-10",
};
const base =
  "inline-flex items-center justify-center gap-1.5 rounded-md font-medium whitespace-nowrap transition-colors duration-150 " +
  "disabled:cursor-not-allowed disabled:opacity-60";

export function Button({
  variant = "primary", size = "md", loading, className = "", children, ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }) {
  return (
    <button {...props} disabled={props.disabled || loading} className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}>
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ className = "", children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...props} className={`rounded-[10px] border border-line bg-canvas ${className}`}>
      {children}
    </div>
  );
}

const tones: Record<Tone, string> = {
  neutral: "bg-panel-2 text-body",
  good: "bg-good-bg text-good",
  warn: "bg-warn-bg text-warn",
  bad: "bg-bad-bg text-bad",
  info: "bg-info-bg text-info",
  dark: "bg-ink text-white",
};

export function Badge({ tone = "neutral", children, className = "" }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex h-5 items-center gap-1 rounded-[5px] px-1.5 text-[11px] font-medium whitespace-nowrap tabular-nums ${tones[tone]} ${className}`}>
      {children}
    </span>
  );
}

/** A small steady status dot (no pulsing: the label already says it is live). */
export const LiveDot = ({ className = "" }: { className?: string }) => (
  <span className={`inline-block h-1.5 w-1.5 rounded-full bg-current ${className}`} />
);

export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted">{children}</p>;
}

/** The page title block, optional icon tile, a 32px title, one line of description, actions right. */
export function PageHeader({ eyebrow, title, sub, right, icon }: {
  eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode; right?: ReactNode; icon?: ReactNode;
}) {
  return (
    <Reveal className="mb-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          {icon && (
            <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-[10px] border border-line bg-panel text-ink [&_svg]:h-5 [&_svg]:w-5">
              {icon}
            </div>
          )}
          {eyebrow && <p className="mb-1.5 text-[12px] font-medium text-muted">{eyebrow}</p>}
          <h1 className="text-[28px] font-semibold leading-[1.15] tracking-[-0.02em] text-ink sm:text-[32px]">{title}</h1>
          {sub && <p className="mt-2 max-w-[640px] text-[14px] leading-relaxed text-body">{sub}</p>}
        </div>
        {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
      </div>
    </Reveal>
  );
}

/** Kept for the views that call it: now the same calm page header, with the story as its description. */
export function Hero({ eyebrow, title, sub, right, icon }: {
  eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode; right?: ReactNode; icon?: ReactNode;
}) {
  return <PageHeader eyebrow={eyebrow} title={title} sub={sub} right={right} icon={icon} />;
}

export function Stat({ value, label, icon }: { value: ReactNode; label: string; icon?: ReactNode }) {
  return (
    <div className="rounded-[10px] border border-line bg-canvas px-3.5 py-3 transition-colors hover:border-line-strong">
      <p className="flex items-center gap-1.5 text-[11.5px] text-muted">{icon}{label}</p>
      <p className="mt-1 text-[20px] font-semibold leading-tight tracking-[-0.02em] tabular-nums text-ink">
        {typeof value === "number" ? <CountUp to={value} /> : value}
      </p>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-md ${className}`} />;
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="rounded-[10px] border border-[#ecd0d0] bg-bad-bg px-3.5 py-2.5 text-[13px] text-bad">
      {message}
    </div>
  );
}

/** The painted art backgrounds are gone; callers keep working and get a quiet panel surface instead. */
export function artFor(seed: string) {
  void seed;
  return "";
}

export function ArtFrame({ className = "", children }: { seed: string; className?: string; children: ReactNode }) {
  return <div className={`relative overflow-hidden border border-line bg-panel ${className}`}>{children}</div>;
}

export function Empty({ title, body, action, icon }: { title: string; body?: ReactNode; action?: ReactNode; seed?: string; icon?: ReactNode }) {
  return (
    <div className="animate-page rounded-[10px] border border-dashed border-line-strong bg-panel/50 px-6 py-12 text-center">
      {icon && (
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-[10px] border border-line bg-canvas text-muted [&_svg]:h-[18px] [&_svg]:w-[18px]">
          {icon}
        </div>
      )}
      <p className="text-[15px] font-semibold text-ink">{title}</p>
      {body && <p className="mx-auto mt-1 max-w-[440px] text-[13px] leading-relaxed text-body">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ToolChip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex h-5 items-center gap-1 rounded-[5px] border border-line bg-panel px-1.5 font-mono text-[11px] text-body">
      {children}
    </span>
  );
}

/** A titled section surface for charts and lists. */
export function Section({ title, sub, children, className = "" }: { title: string; sub?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={`px-4 pb-3 pt-3.5 ${className}`}>
      <h3 className="text-[14px] font-semibold tracking-[-0.01em] text-ink">{title}</h3>
      {sub && <p className="mb-2.5 mt-0.5 text-[12px] text-muted">{sub}</p>}
      {children}
    </Card>
  );
}

export function Legend({ items }: { items: { color: string; label: string }[] }) {
  return (
    <div className="mb-2 flex flex-wrap gap-3.5 text-[11.5px] text-body">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}

/** A keyboard shortcut hint, e.g. <Kbd>Ctrl K</Kbd>. */
export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}
