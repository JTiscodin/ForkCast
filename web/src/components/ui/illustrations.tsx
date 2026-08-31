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
const ORANGE = "#FC8019";
const CREAM = "#FFF4E9";
const CHARCOAL = "#282C3F";
const GREEN = "#24963f";
const GRAY = "#7E808C";
const WHITE = "#FFFFFF";

/**
 * Top-down plate with fork + spoon, a doodled curry mound, steam wisps,
 * and a little veg marker parked on the rim. Good for meal/dish contexts.
 */
export function PlateIllustration({ className }: IllustrationProps) {
  return (
    <svg
      viewBox="0 0 200 200"
      role="img"
      aria-label="Illustration of a steaming plate of food with cutlery"
      className={className}
    >
      <circle cx="107" cy="97" r="76" fill={CREAM} />
      <g transform="rotate(-5 100 110)">
        {/* steam wisps */}
        <path
          d="M86 40 c -7 9 7 13 0 23"
          fill="none"
          stroke={GRAY}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <path
          d="M112 34 c -7 9 7 13 0 23"
          fill="none"
          stroke={GRAY}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        {/* plate + inner rim */}
        <circle cx="100" cy="112" r="58" fill={WHITE} stroke={ORANGE} strokeWidth="3" />
        <circle
          cx="100"
          cy="112"
          r="45"
          fill="none"
          stroke={ORANGE}
          strokeOpacity="0.3"
          strokeWidth="2.5"
        />
        {/* curry mound */}
        <circle cx="86" cy="114" r="15" fill={ORANGE} />
        <circle cx="106" cy="103" r="17" fill={ORANGE} />
        <circle cx="119" cy="119" r="12" fill={ORANGE} />
        <circle cx="94" cy="99" r="3" fill={WHITE} />
        <circle cx="112" cy="117" r="3" fill={GREEN} />
        <circle cx="101" cy="112" r="2.5" fill={CHARCOAL} />
        {/* veg marker resting on the rim */}
        <rect
          x="127"
          y="55"
          width="15"
          height="15"
          rx="3.5"
          fill={WHITE}
          stroke={GREEN}
          strokeWidth="2.5"
        />
        <circle cx="134.5" cy="62.5" r="3.5" fill={GREEN} />
        {/* fork */}
        <path
          d="M25 70 v14 a8.5 8.5 0 0 0 17 0 V70"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M33.5 70 v12" fill="none" stroke={CHARCOAL} strokeWidth="3" strokeLinecap="round" />
        <path
          d="M33.5 92.5 V148"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="3.5"
          strokeLinecap="round"
        />
        {/* spoon */}
        <ellipse cx="167" cy="80" rx="9" ry="12" fill={WHITE} stroke={CHARCOAL} strokeWidth="3" />
        <path
          d="M167 93 V150"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="3.5"
          strokeLinecap="round"
        />
      </g>
    </svg>
  );
}

/**
 * Puffy chef hat with sparkles — for onboarding / success moments
 * ("we're cooking up your plan").
 */
export function ChefHatIllustration({ className }: IllustrationProps) {
  return (
    <svg
      viewBox="0 0 200 200"
      role="img"
      aria-label="Illustration of a puffy chef hat surrounded by sparkles"
      className={className}
    >
      <circle cx="100" cy="104" r="78" fill={CREAM} />
      <g transform="rotate(-4 100 105)">
        {/* sparkles */}
        <path
          d="M42 36 v16 M34 44 h16"
          fill="none"
          stroke={ORANGE}
          strokeWidth="3.5"
          strokeLinecap="round"
        />
        <path
          d="M158 62 v12 M152 68 h12"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <circle cx="154" cy="140" r="3" fill={ORANGE} />
        <circle cx="46" cy="132" r="2.5" fill={GRAY} />
        {/* puffy crown */}
        <path
          d="M64 116 C48 116 42 96 56 88 C52 68 74 58 86 68 C92 54 116 54 122 68 C136 60 154 74 146 90 C158 98 152 116 138 116 Z"
          fill={WHITE}
          stroke={ORANGE}
          strokeWidth="3.5"
          strokeLinejoin="round"
        />
        {/* band + pleats */}
        <rect x="60" y="113" width="82" height="25" rx="8" fill={WHITE} stroke={ORANGE} strokeWidth="3" />
        <path
          d="M82 121 v9 M101 121 v11 M120 121 v9"
          fill="none"
          stroke={GRAY}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </g>
    </svg>
  );
}

/**
 * Delivery scooter with a strapped parcel box and speed lines — generic
 * courier doodle, not any real brand's scooter art. Good for "on its way".
 */
export function ScooterIllustration({ className }: IllustrationProps) {
  return (
    <svg
      viewBox="0 0 200 200"
      role="img"
      aria-label="Illustration of a delivery scooter speeding along"
      className={className}
    >
      <circle cx="100" cy="100" r="78" fill={CREAM} />
      {/* dotted ground */}
      <path
        d="M22 161 H184"
        fill="none"
        stroke={GRAY}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray="1 12"
      />
      {/* speed lines (kept level while the scooter tilts) */}
      <path d="M6 92 H26" fill="none" stroke={ORANGE} strokeWidth="4" strokeLinecap="round" />
      <path d="M0 108 H20" fill="none" stroke={GRAY} strokeWidth="3" strokeLinecap="round" />
      <path d="M8 124 H28" fill="none" stroke={ORANGE} strokeWidth="3" strokeLinecap="round" />
      <g transform="rotate(-4 100 112)">
        {/* wheels */}
        <circle cx="58" cy="141" r="16" fill={WHITE} stroke={CHARCOAL} strokeWidth="3.5" />
        <circle cx="58" cy="141" r="4" fill={CHARCOAL} />
        <circle cx="150" cy="141" r="16" fill={WHITE} stroke={CHARCOAL} strokeWidth="3.5" />
        <circle cx="150" cy="141" r="4" fill={CHARCOAL} />
        {/* fenders */}
        <path
          d="M38 139 A20 20 0 0 1 77 134"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="3.5"
          strokeLinecap="round"
        />
        <path
          d="M130 139 A20 20 0 0 1 169 134"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="3.5"
          strokeLinecap="round"
        />
        {/* parcel box */}
        <rect x="30" y="72" width="42" height="44" rx="9" fill={ORANGE} />
        <path d="M41 72 V116" stroke={CREAM} strokeWidth="4" />
        <path d="M61 72 V116" stroke={CREAM} strokeWidth="4" />
        {/* seat */}
        <rect x="74" y="100" width="28" height="11" rx="5.5" fill={CHARCOAL} />
        <path
          d="M88 111 V118"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="4"
          strokeLinecap="round"
        />
        {/* floorboard, steering column, fork */}
        <path
          d="M78 118 H130"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="5"
          strokeLinecap="round"
        />
        <path
          d="M130 118 L145 76"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="5"
          strokeLinecap="round"
        />
        <path
          d="M145 78 L151 125"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="4"
          strokeLinecap="round"
        />
        {/* handlebar + grip */}
        <path
          d="M134 71 L160 65"
          fill="none"
          stroke={CHARCOAL}
          strokeWidth="5"
          strokeLinecap="round"
        />
        <circle cx="161" cy="65" r="3.5" fill={ORANGE} />
        {/* headlight + beam */}
        <path d="M147 87 l 19 -8 -5 16 Z" fill={ORANGE} fillOpacity="0.3" />
        <circle cx="141" cy="91" r="5" fill={CREAM} stroke={ORANGE} strokeWidth="2.5" />
      </g>
    </svg>
  );
}

/**
 * Steaming noodle bowl with chopsticks and pea garnish — good for
 * empty chat states and "nothing cooking yet" moments.
 */
export function BowlIllustration({ className }: IllustrationProps) {
  return (
    <svg
      viewBox="0 0 200 200"
      role="img"
      aria-label="Illustration of a steaming bowl of noodles with chopsticks"
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
