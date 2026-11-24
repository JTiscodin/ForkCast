/**
 * Design system helpers for the Forkcast.
 *
 * These are the canonical, typed constants every component should reach for
 * instead of hand-writing colors/gradients. Class-name strings map to the
 * @utility helpers and tokens defined in `src/app/globals.css`.
 *
 * Usage:
 *   import { cn } from "@/lib/utils"
 *   import { surfaces } from "@/lib/design"
 *   <div className={cn(surfaces.card, "p-6")}>…</div>
 *
 * Swiggy look: FLAT solid-orange CTAs on white cards — no gradients, no
 * pop-art shadows. The old `gradients`/`gradientText` helpers are gone;
 * reach for `bg-brand-500` directly instead.
 */

/* -------------------------------------------------------------------------
 * Reusable surface / panel className tokens (cn-friendly)
 * ------------------------------------------------------------------------- */
export const surfaces = {
  /** Standard content card. */
  card: "bg-card text-card-foreground border border-border rounded-md shadow-soft",
  /** Elevated / floating card (popovers, featured tiles). */
  cardElevated:
    "bg-surface-elevated text-card-foreground border border-border rounded-md shadow-layered",
  /** Frosted glass panel — sticky navbars, overlays, floating toolbars. */
  glass: "glass-panel rounded-md text-foreground shadow-soft",
  /** Inset well for muted / secondary regions. */
  well: "bg-muted/60 border border-border rounded-md",
} as const;

/** Focus ring recipe — apply on interactive custom elements. */
export const focusRing =
  "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/* -------------------------------------------------------------------------
 * Meal-type accent map (breakfast / lunch / dinner / snack)
 * Each entry carries token-based classes for the common surfaces so callers
 * never hard-code a hue.
 * ------------------------------------------------------------------------- */
export type MealType = "breakfast" | "lunch" | "dinner" | "snack";

export interface MealTypeStyle {
  /** CSS custom-property name holding the accent color. */
  cssVar: string;
  /** Text color utility. */
  text: string;
  /** Solid background utility (badges, dots). */
  bg: string;
  /** Soft tinted background for chips / rows. */
  soft: string;
  /** Border utility. */
  border: string;
  /** Human label. */
  label: string;
}

export const mealTypes: Record<MealType, MealTypeStyle> = {
  breakfast: {
    cssVar: "--meal-breakfast",
    text: "text-meal-breakfast",
    bg: "bg-meal-breakfast",
    soft: "bg-meal-breakfast/12",
    border: "border-meal-breakfast/30",
    label: "Breakfast",
  },
  lunch: {
    cssVar: "--meal-lunch",
    text: "text-meal-lunch",
    bg: "bg-meal-lunch",
    soft: "bg-meal-lunch/12",
    border: "border-meal-lunch/30",
    label: "Lunch",
  },
  dinner: {
    cssVar: "--meal-dinner",
    text: "text-meal-dinner",
    bg: "bg-meal-dinner",
    soft: "bg-meal-dinner/12",
    border: "border-meal-dinner/30",
    label: "Dinner",
  },
  snack: {
    cssVar: "--meal-snack",
    text: "text-meal-snack",
    bg: "bg-meal-snack",
    soft: "bg-meal-snack/12",
    border: "border-meal-snack/30",
    label: "Snack",
  },
};

/* -------------------------------------------------------------------------
 * Small typed helpers
 * ------------------------------------------------------------------------- */

/** Get meal-type styling, optionally merging one of its facets with classes. */
export function mealStyle(type: MealType): MealTypeStyle {
  return mealTypes[type];
}

/** A veg/non-veg dot color, Swiggy convention (green = veg, red = non-veg). */
export const dietDot = {
  veg: "text-success border-success",
  nonveg: "text-danger border-danger",
} as const;
