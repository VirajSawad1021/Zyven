"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A short entrance (4px rise, 420ms). The content is visible from the first frame: the animation starts from a
 * near-visible state, so a thumbnail, a background tab or a reduced-motion user always sees the whole page. */
export function Reveal({ children, delay = 0, className = "" }: { children: ReactNode; delay?: number; className?: string }) {
  return (
    <div style={{ animationDelay: `${Math.min(delay, 240)}ms` }} className={`animate-page ${className}`}>
      {children}
    </div>
  );
}

/** Shows the true number at all times; when it scrolls into view it counts up to it (eased), and later
 * changes count from the previous value. If the browser never reports visibility or never paints frames
 * (background tab), the correct number is simply shown: the animation is decoration, never the data. */
export function CountUp({ to, duration = 1100, format = (v: number) => v.toLocaleString("en-US") }: {
  to: number; duration?: number; format?: (v: number) => string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const from = useRef(0);
  const seen = useRef(false);
  const [anim, setAnim] = useState<number | null>(null);  // null: show the true value
  useEffect(() => {
    const el = ref.current;
    if (!el || reducedMotion()) {
      from.current = to;
      return;
    }
    let raf = 0;
    let settle = 0;
    const run = () => {
      const start = performance.now();
      const a = from.current;
      // rAF pauses in background tabs: guarantee the true number regardless of whether frames run.
      settle = window.setTimeout(() => {
        cancelAnimationFrame(raf);
        setAnim(null);
        from.current = to;
      }, duration + 60);
      const tick = (t: number) => {
        const p = Math.min(1, (t - start) / duration);
        if (p < 1) {
          setAnim(Math.round(a + (to - a) * (1 - Math.pow(1 - p, 3))));
          raf = requestAnimationFrame(tick);
        } else {
          setAnim(null);
          from.current = to;
        }
      };
      raf = requestAnimationFrame(tick);
    };
    let io: IntersectionObserver | null = null;
    if (seen.current) {
      run();  // already on screen: animate from the previous value
    } else {
      io = new IntersectionObserver(([e]) => {
        if (!e.isIntersecting) return;
        io?.disconnect();
        seen.current = true;
        run();  // from.current is 0 the first time: the reveal count-up
      });
      io.observe(el);
    }
    return () => {
      io?.disconnect();
      cancelAnimationFrame(raf);
      clearTimeout(settle);
      if (seen.current) from.current = to;
    };
  }, [to, duration]);
  return <span ref={ref} className="tabular-nums">{format(anim ?? to)}</span>;
}

/** Four-point star (the ✦ mark used for AI moments). */
export function Star({ className = "", style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} style={style}>
      <path d="M12 0c.6 6.4 5.6 11.4 12 12-6.4.6-11.4 5.6-12 12-.6-6.4-5.6-11.4-12-12C6.4 11.4 11.4 6.4 12 0Z" fill="currentColor" />
    </svg>
  );
}

/** Kept for callers; the twinkling stars and drifting paintings are gone in the calm design. */
export function Stars(props: { seed?: string; count?: number; className?: string; from?: number; to?: number }) {
  void props;
  return null;
}

export function DriftingOrb(props: { className?: string }) {
  void props;
  return null;
}
