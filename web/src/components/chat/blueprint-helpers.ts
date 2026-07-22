import type { AppetiteLevel, Blueprint, MealType } from "@/lib/types";

/**
 * Small, pure helpers for the blueprint overview bubble.
 * Kept framework-free so they can be reused for accessibility text,
 * fallbacks, and readiness gating.
 */

/** Human labels for appetite levels. */
export const APPETITE_LABELS: Record<AppetiteLevel, string> = {
  light: "Light",
  moderate: "Moderate",
  heavy: "Heavy",
  very_heavy: "Very heavy",
};

/** Human labels for meal types. */
export const MEAL_LABELS: Record<MealType, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
};

/**
 * Format a number as Indian Rupees, e.g. 12500 -> "₹12,500".
 * Uses the Indian digit-grouping locale. Nullish -> "—".
 */
export function formatINR(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `₹${new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: 0,
  }).format(n)}`;
}

/**
 * A one-line text summary of the blueprint — used for screen-reader
 * announcements and as a plain-text fallback if the card can't render.
 */
export function blueprintSummaryLine(bp: Blueprint): string {
  const parts: string[] = [];

  parts.push(`${formatINR(bp.budget)} budget`);

  if (bp.appetite_level) {
    parts.push(`${APPETITE_LABELS[bp.appetite_level].toLowerCase()} appetite`);
  }

  parts.push(bp.veg_only ? "veg only" : "veg & non-veg");

  const days = bp.days > 0 ? bp.days : 1;
  const mealCount = bp.meals.length;
  const mealWord = mealCount === 1 ? "meal" : "meals";
  parts.push(`${days} ${days === 1 ? "day" : "days"} × ${mealCount} ${mealWord}`);

  if (bp.constraints.length) {
    const musts = bp.constraints
      .map((c) => `${c.min_count}× ${c.dish_tag}`)
      .join(", ");
    parts.push(`must-haves: ${musts}`);
  }

  if (bp.cuisines.length) {
    parts.push(`cuisines: ${bp.cuisines.join(", ")}`);
  }

  return parts.join(" · ");
}

/**
 * The blueprint is "ready" to generate a plan once the two load-bearing
 * fields are present: a budget and an appetite level.
 */
export function isBlueprintReady(bp: Blueprint): boolean {
  return bp.budget != null && bp.appetite_level != null;
}
