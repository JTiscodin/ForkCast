import { slotTotal, type MealSlot, type MealType } from "@/lib/types";

/** Canonical render order for meal types within a day. */
export const MEAL_ORDER: MealType[] = ["breakfast", "lunch", "dinner"];

/** A single day's bucket: its 1-based day number and slots keyed by meal type. */
export interface DayGroup {
  day: number;
  /** All slots for the day, ordered breakfast → lunch → dinner. */
  slots: MealSlot[];
  /** Slot per meal type (undefined = empty meal). */
  byMeal: Record<MealType, MealSlot | undefined>;
}

/**
 * Group slots into an ordered array of `days` day-buckets (1..days).
 * Within each day, meals are ordered breakfast → lunch → dinner.
 * Days with no slots still appear (empty), so the calendar grid is complete.
 */
export function groupByDay(slots: MealSlot[], days: number): DayGroup[] {
  const total = Math.max(0, Math.floor(days));
  const buckets: DayGroup[] = Array.from({ length: total }, (_, i) => ({
    day: i + 1,
    slots: [],
    byMeal: { breakfast: undefined, lunch: undefined, dinner: undefined },
  }));

  for (const slot of slots) {
    const idx = slot.day - 1;
    if (idx < 0 || idx >= total) continue;
    const bucket = buckets[idx];
    bucket.byMeal[slot.meal_type] = slot;
  }

  // Rebuild ordered slot arrays from byMeal so order is always canonical.
  for (const bucket of buckets) {
    bucket.slots = MEAL_ORDER.map((m) => bucket.byMeal[m]).filter(
      (s): s is MealSlot => Boolean(s),
    );
  }

  return buckets;
}

/**
 * Sum of the full cost of the given slots — accompaniments included, so a
 * day's total matches what the wallet will actually be charged.
 */
export function dayTotal(slots: MealSlot[]): number {
  return slots.reduce((sum, s) => sum + slotTotal(s), 0);
}

/** Format a number as Indian Rupees, no decimals (e.g. 1250 → "₹1,250"). */
export function formatINR(n: number): string {
  const rounded = Math.round(n ?? 0);
  return `₹${rounded.toLocaleString("en-IN")}`;
}
