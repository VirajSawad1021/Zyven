import Link from "next/link";

/** The split Z: a solid Z cut into three plates. The diagonal plate is the tool passing through the gate between the
 * two bars. One colour (ink on light, white on dark); the same geometry as public/icon.svg. */
export function LogoMark({ className = "h-7 w-7", tone = "ink" }: { className?: string; tone?: "ink" | "light" }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden fill={tone === "light" ? "#ffffff" : "#1b1915"}>
      <path d="M7.2 5.5H24.8A1.7 1.7 0 0 1 26.5 7.2V9.6H5.5V7.2A1.7 1.7 0 0 1 7.2 5.5Z" />
      <path d="M19.8 11.4H26.3L12.2 20.6H5.7Z" />
      <path d="M5.5 22.4H26.5V24.8A1.7 1.7 0 0 1 24.8 26.5H7.2A1.7 1.7 0 0 1 5.5 24.8Z" />
    </svg>
  );
}

export function Logo({ href = "/", onClick, light }: { href?: string; onClick?: () => void; light?: boolean }) {
  return (
    <Link href={href} onClick={onClick} className="flex items-center gap-2" aria-label="Zyven home">
      <LogoMark className="h-[22px] w-[22px]" tone={light ? "light" : "ink"} />
      <span className={`text-[17px] font-semibold tracking-[-0.03em] ${light ? "text-white" : "text-ink"}`}>zyven</span>
    </Link>
  );
}
