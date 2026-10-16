import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import type { Tone } from "../lib/labels";
import { CountUp, Reveal, Star } from "./motion";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "light";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-ink text-white hover:bg-ink-soft disabled:bg-[#b9b6ae]",
  secondary: "bg-white text-ink border border-line-strong hover:border-ink/40 disabled:text-muted",
  ghost: "text-body hover:text-ink hover:bg-panel-2",
  danger: "bg-white text-bad border border-[#ecd0d0] hover:border-bad",
  light: "bg-white text-ink hover:bg-cream",
};
const sizes: Record<Size, string> = { sm: "h-8 px-3.5 text-[12px]", md: "h-10 px-4.5 text-[13px]", lg: "h-12 px-6 text-[14px]" };
const base =
  "inline-flex items-center justify-center gap-2 rounded-full font-semibold whitespace-nowrap transition-all duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100";

export function Button({
  variant = "primary", size = "md", loading, className = "", children, ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }) {
  return (
    <button {...props} disabled={props.disabled || loading} className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ className = "", children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...props} className={`rounded-2xl border border-line bg-white ${className}`}>
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
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold whitespace-nowrap ${tones[tone]} ${className}`}>
      {children}
    </span>
  );
}

export const LiveDot = ({ className = "" }: { className?: string }) => (
  <span className={`inline-block h-1.5 w-1.5 rounded-full bg-current animate-pulse-dot ${className}`} />
);

export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">{children}</p>;
}

export function PageHeader({ eyebrow, title, sub, right }: { eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="mb-1.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">{eyebrow}</p>}
        <h1 className="text-[28px] font-semibold leading-tight tracking-tight text-ink sm:text-[32px]">{title}</h1>
        {sub && <p className="mt-1.5 max-w-2xl text-[14px] leading-relaxed text-body">{sub}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

/** The signature display header: large, tight headline on the left, story on the right, both fading up. */
export function Hero({ eyebrow, title, sub, right }: { eyebrow?: ReactNode; title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="relative mb-8 grid items-end gap-6 lg:grid-cols-[1.15fr_1fr] lg:gap-10">
      <Reveal>
        {eyebrow && (
          <p className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">
            <Star className="h-3 w-3 text-clay" /> {eyebrow}
          </p>
        )}
        <h1 className="text-[38px] font-medium leading-[1.02] tracking-[-0.035em] text-ink sm:text-[52px]">{title}</h1>
      </Reveal>
      <Reveal delay={120}>
        {sub && <p className="max-w-[520px] text-[15px] leading-relaxed text-body lg:pb-1.5">{sub}</p>}
        {right && <div className="mt-4 flex flex-wrap items-center gap-2">{right}</div>}
      </Reveal>
    </div>
  );
}

export function Stat({ value, label, icon }: { value: ReactNode; label: string; icon?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-line bg-white px-4 py-3.5">
      <p className="text-[22px] font-medium leading-tight tracking-tight tabular-nums">
        {typeof value === "number" ? <CountUp to={value} /> : value}
      </p>
      <p className="mt-1 flex items-center gap-1.5 text-[11px] font-medium text-muted">{icon}{label}</p>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-xl ${className}`} />;
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="rounded-xl border border-[#ecd0d0] bg-bad-bg px-4 py-3 text-[13px] text-bad">
      {message}
    </div>
  );
}

/* ── art ──────────────────────────────────────────────────────────────────── */
const ARTS = ["art-warm", "art-sage", "art-orb"] as const;
export function artFor(seed: string): (typeof ARTS)[number] {
  return ARTS[[...seed].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % ARTS.length];
}

/** Painted background with frosted content floating on it (the InstaJob dashboard pattern). */
export function ArtFrame({ seed, className = "", children }: { seed: string; className?: string; children: ReactNode }) {
  return <div className={`art ${artFor(seed)} relative overflow-hidden ${className}`}>{children}</div>;
}

export function Empty({ title, body, action, seed = "empty" }: { title: string; body?: ReactNode; action?: ReactNode; seed?: string }) {
  return (
    <ArtFrame seed={seed} className="rounded-3xl px-6 py-14 text-center animate-fade-in">
      <div className="frost mx-auto max-w-[460px] rounded-[20px] px-5 py-6 shadow-[0_1px_2px_rgba(20,20,19,0.08)]">
        <p className="text-[16px] font-semibold text-ink">{title}</p>
        {body && <p className="mx-auto mt-1.5 text-[13px] leading-relaxed text-body">{body}</p>}
        {action && <div className="mt-4">{action}</div>}
      </div>
    </ArtFrame>
  );
}

export function ToolChip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-lg border border-line bg-white px-2 py-0.5 font-mono text-[11px] text-body">
      {children}
    </span>
  );
}

/** A white chart/section card with a title and subtitle. */
export function Section({ title, sub, children, className = "" }: { title: string; sub?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={`px-[18px] pb-3 pt-4 ${className}`}>
      <h3 className="text-[14px] font-semibold tracking-tight">{title}</h3>
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
