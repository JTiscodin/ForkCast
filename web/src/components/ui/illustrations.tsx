/**
 * Original flat-doodle food illustrations, drawn by hand in SVG for this app.
 *
 * Deliberately ORIGINAL artwork in a friendly food-delivery empty-state style —
 * not derived from or imitative of any real delivery brand's mascot/logo/art.
 * Pure presentational SVG (no hooks, no state) so no "use client" is needed;
 * size is controlled by the caller via className (e.g. `w-40 h-40`).
 */

type IllustrationProps = {
  className?: string;
};

/* Shared palette — mirrors the app's design tokens. */
const ORANGE = "#FF5200";
const CREAM = "#FFF4E9";
const CHARCOAL = "#282C3F";
const GREEN = "#24963f";
const GRAY = "#7E808C";
const WHITE = "#FFFFFF";

/**
 * Steaming noodle bowl with chopsticks and pea garnish — good for
 * empty chat states and "nothing cooking yet" moments.
 */
export function BowlIllustration({ className }: IllustrationProps) {
  return (
    <svg
      viewBox="0 0 200 200"
      aria-hidden
      className={className}
    >
      <circle cx="98" cy="102" r="78" fill={CREAM} />
      <g transform="rotate(-3 100 120)">
        {/* steam */}
        <path
          d="M70 30 c -8 10 8 15 0 26"
          fill="none"
          stroke={GRAY}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <path
          d="M100 24 c -8 10 8 15 0 26"
          fill="none"
          stroke={ORANGE}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <path
          d="M128 34 c -6 8 6 12 0 20"
          fill="none"
          stroke={GRAY}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        {/* chopsticks */}
        <path
          d="M120 32 L84 102"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="3.5"
          strokeLinecap="round"
        />
        <path
          d="M142 42 L98 104"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="3.5"
          strokeLinecap="round"
        />
        {/* bowl */}
        <path
          d="M42 106 A58 58 0 0 0 158 106 Z"
          fill={WHITE}
          stroke={ORANGE}
          strokeWidth="3.5"
          strokeLinejoin="round"
        />
        <path
          d="M86 162 h28 l6 12 h-40 Z"
          fill={WHITE}
          stroke={ORANGE}
          strokeWidth="3"
          strokeLinejoin="round"
        />
        {/* stripe */}
        <path
          d="M56 128 q 11 -9 22 0 t 22 0 t 22 0 t 22 0"
          fill="none"
          stroke={ORANGE}
          strokeOpacity="0.45"
          strokeWidth="3.5"
          strokeLinecap="round"
        />
        {/* noodles */}
        <path
          d="M50 104 q 9 -11 18 -1 q 9 10 18 0 q 9 -10 18 0 q 9 10 18 0 q 9 -10 18 -1 q 8 8 12 2"
          fill="none"
          stroke={ORANGE}
          strokeWidth="3"
          strokeLinecap="round"
        />
        {/* peas */}
        <circle cx="59" cy="97" r="2.5" fill={GREEN} />
        <circle cx="131" cy="97" r="2.5" fill={GREEN} />
      </g>
    </svg>
  );
}
