/**
 * FSSAI veg/non-veg mark — the classic square-and-dot stamp Swiggy prints
 * beside every dish name (green = veg, brown-red = non-veg). Token-colored.
 */
export function DietMarker({ veg }: { veg: boolean }) {
  const color = veg ? "var(--diet-veg)" : "var(--diet-nonveg)";
  return (
    <svg
      width={14}
      height={14}
      viewBox="0 0 14 14"
      aria-hidden
      className="shrink-0"
    >
      <rect
        x="1"
        y="1"
        width="12"
        height="12"
        rx="2"
        fill="none"
        stroke={color}
        strokeWidth="1.5"
      />
      <circle cx="7" cy="7" r="3" fill={color} />
    </svg>
  );
}
