"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Fades content up once when it scrolls into view (InstaJob Reveal). Respects reduced motion. */
export function Reveal({ children, delay = 0, className = "" }: { children: ReactNode; delay?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Reduced motion needs no branch here: the global CSS rule makes the transition instant.
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setShown(true);
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={`transition-all duration-[900ms] ease-[cubic-bezier(0.16,1,0.3,1)] ${shown ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0"} ${className}`}
    >
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

/** A seeded linear congruential generator: the same seed always gives the same sequence. */
function rng(seed: string) {
  let h = [...seed].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 2166136261);
  return () => ((h = (h * 1664525 + 1013904223) >>> 0) / 4294967296);
}

/** A quiet field of twinkling stars layered over painted art. Positions are deterministic per seed. */
export function Stars({ seed = "z", count = 9, className = "", from = 4, to = 96 }: {
  seed?: string; count?: number; className?: string; from?: number; to?: number;
}) {
  const rnd = rng(seed);
  const stars = Array.from({ length: count }, () => ({
    left: from + rnd() * (to - from), top: 8 + rnd() * 80, size: 9 + rnd() * 11, delay: rnd() * 3.2, dur: 2.6 + rnd() * 2.2,
  }));
  return (
    <div aria-hidden className={`pointer-events-none absolute inset-0 ${className}`}>
      {stars.map((s, i) => (
        <Star
          key={i}
          className="absolute text-[#fffaf0] drop-shadow-[0_0_5px_rgba(133,91,46,0.55)] animate-twinkle"
          style={{ left: `${s.left}%`, top: `${s.top}%`, width: s.size, height: s.size, animationDelay: `${s.delay}s`, animationDuration: `${s.dur}s` }}
        />
      ))}
    </div>
  );
}

/** The slowly drifting orb painting, as a background layer (InstaJob final CTA). */
export function DriftingOrb({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-0 animate-drift bg-[url(/art/orb.webp)] bg-[length:auto_150%] bg-center bg-no-repeat ${className}`}
    />
  );
}
