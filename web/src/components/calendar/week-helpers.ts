import type { MealSlot } from "@/lib/types";

import { dayTotal } from "./calendar-helpers";

/** A contiguous 7-day (or shorter, for the tail) window within a plan. */
export interface WeekWindow {
  /** 0-based week index. */
  index: number;
  /** Human tab label, e.g. "Week 2". */
  label: string;
  /** 1-based inclusive first day of the week. */
  dayStart: number;
  /** 1-based inclusive last day of the week. */
  dayEnd: number;
  /** The 1-based day numbers in this week (length 1..7). */
  days: number[];
}

/**
 * Split a plan of `days` days into consecutive weeks of 7.
 * Week 1 = days 1–7, week 2 = days 8–14, … the final week may be short.
 * Returns [] when `days` <= 0.
 */
export function splitWeeks(days: number): WeekWindow[] {
  const total = Math.max(0, Math.floor(days));
  const weeks: WeekWindow[] = [];
  for (let start = 1; start <= total; start += 7) {
    const end = Math.min(start + 6, total);
    const dayNumbers: number[] = [];
    for (let d = start; d <= end; d++) dayNumbers.push(d);
    weeks.push({
      index: weeks.length,
      label: `Week ${weeks.length + 1}`,
      dayStart: start,
      dayEnd: end,
      days: dayNumbers,
    });
  }
  return weeks;
}

/**
 * Keywords that mark a dish as non-veg. MealSlot has no veg flag, so we infer
 * from the dish name — a pragmatic, name-based heuristic.
 */
const NON_VEG_KEYWORDS = [
  "chicken",
  "egg",
  "mutton",
  "fish",
  "prawn",
  "prawns",
  "meat",
  "lamb",
  "beef",
  "pork",
  "keema",
  "kheema",
  "shrimp",
  "crab",
  "seafood",
  "bacon",
  "ham",
  "tikka",
  "kebab",
  "kabab",
  "tandoori",
];

/** Infer whether a dish is vegetarian purely from its name. */
export function inferVegFromName(name: string): boolean {
  const lower = (name ?? "").toLowerCase();
  return !NON_VEG_KEYWORDS.some((kw) => lower.includes(kw));
}

/** Aggregate stats derived from a set of meal slots. */
export interface PlanStats {
  /** Number of meals planned. */
  meals: number;
  /** Percentage (0–100) of meals that are vegetarian (name-inferred). */
  vegPct: number;
  /** Average rating across slots that carry one (0 when none). */
  avgRating: number;
  /** Count of distinct restaurants across the slots. */
  restaurants: number;
  /** Sum of slot prices. */
  total: number;
}

/** Compute headline stats for a plan's slots. */
export function planStats(slots: MealSlot[]): PlanStats {
  const meals = slots.length;
  const total = dayTotal(slots);

  const vegCount = slots.reduce(
    (n, s) => n + (inferVegFromName(s.dish_name) ? 1 : 0),
    0,
  );
  const vegPct = meals > 0 ? Math.round((vegCount / meals) * 100) : 0;

  const rated = slots.filter((s) => typeof s.rating === "number");
  const avgRating =
    rated.length > 0
      ? rated.reduce((sum, s) => sum + (s.rating ?? 0), 0) / rated.length
      : 0;

  const restaurantIds = new Set<string>();
  for (const s of slots) {
    if (s.restaurant_id) restaurantIds.add(s.restaurant_id);
  }

  return {
    meals,
    vegPct,
    avgRating,
    restaurants: restaurantIds.size,
    total,
  };
}
