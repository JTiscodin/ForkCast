// Placeholder Forkcast mark until the final logo arrives: a fork tine that doubles
// as a forecast bar chart. Swap this component's SVG for the real asset.
export function LogoMark({ className = "size-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden>
      <rect width="40" height="40" rx="11" fill="#FC8019" />
      <path d="M13 11v8M20 11v8M27 11v8M13 19a7 7 0 0 0 14 0M20 26v5" stroke="#fff" strokeWidth="3" strokeLinecap="round" fill="none" />
    </svg>
  );
}
