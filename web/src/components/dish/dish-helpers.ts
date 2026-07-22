// Shared tiny helpers for the dish components.

/** Keywords that mark a dish as non-veg. MealSlot has no veg flag, so we infer. */
const NONVEG_KEYWORDS = [
  "chicken",
  "egg",
  "mutton",
  "fish",
  "prawn",
  "prawns",
  "shrimp",
  "meat",
  "keema",
  "kheema",
  "lamb",
  "beef",
  "pork",
  "bacon",
  "ham",
  "tikka",
  "seekh",
  "tangdi",
  "crab",
];

/**
 * Infer whether a dish is vegetarian purely from its name.
 * Returns true (veg) unless a known non-veg keyword is present.
 */
export function inferVeg(dishName: string): boolean {
  if (!dishName) return true;
  const lower = dishName.toLowerCase();
  return !NONVEG_KEYWORDS.some((kw) => new RegExp(`\\b${kw}\\b`, "i").test(lower));
}

/** Up to two uppercase initials derived from a dish name, for image fallbacks. */
export function dishInitials(name: string): string {
  if (!name) return "??";
  const words = name
    .trim()
    .split(/\s+/)
    .filter((w) => /[a-z0-9]/i.test(w));
  if (words.length === 0) return "??";
  if (words.length === 1) {
    return words[0].slice(0, 2).toUpperCase();
  }
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** Format a number as Indian Rupees with thousands separators (₹1,299). */
export function formatINR(n: number): string {
  const rounded = Math.round(n);
  return "₹" + rounded.toLocaleString("en-IN");
}

/**
 * Map a numeric rating to a semantic text-color utility.
 * >= 4.0 success (green), >= 3.0 warning (amber), else danger (red).
 */
export function ratingColor(r: number): string {
  if (r >= 4.0) return "text-success";
  if (r >= 3.0) return "text-warning";
  return "text-danger";
}
