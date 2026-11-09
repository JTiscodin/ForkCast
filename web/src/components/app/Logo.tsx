// Rozana mark: a thali seen from above — the rice mound rises like the day's sun
// inside the plate, two katoris sit on the rim. One glyph, works at 16px.
export function LogoMark({ className = "size-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden>
      <rect width="40" height="40" rx="11" fill="#FC8019" />
      <circle cx="20" cy="21" r="12.5" fill="#fff" />
      <path d="M11.5 24a8.5 8.5 0 0 1 17 0z" fill="#F6B12C" />
      <circle cx="13.5" cy="14" r="3.2" fill="#1F7A4D" />
      <circle cx="26.5" cy="14" r="3.2" fill="#C2410C" />
      <path d="M10 27.5h20" stroke="#FC8019" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
