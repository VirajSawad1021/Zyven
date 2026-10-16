/** Zyven mark: a dot with a stroke leading to a clay dot, the agent reaching for a new tool. */
export function LogoMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="9" fill="#141413" />
      <circle cx="11" cy="16" r="4.6" fill="#ffffff" />
      <path d="M11 16 C 16.5 16, 17.5 10.5, 23.4 10.9" fill="none" stroke="#ffffff" strokeWidth="3.1" strokeLinecap="round" />
      <circle cx="24" cy="10.7" r="3.1" fill="#e8895a" />
    </svg>
  );
}

export function Logo({ onClick }: { onClick?: () => void }) {
  return (
    <a href="#/tasks" onClick={onClick} className="flex items-center gap-2" aria-label="Zyven home">
      <LogoMark />
      <span className="text-[17px] font-semibold tracking-[-0.02em] text-ink">zyven</span>
    </a>
  );
}
