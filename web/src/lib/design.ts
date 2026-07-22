import { cn } from "@/lib/utils";

/**
 * Design system helpers for the Budget Meal Planner.
 *
 * These are the canonical, typed constants every component should reach for
 * instead of hand-writing colors/gradients. Class-name strings map to the
 * @utility helpers and tokens defined in `src/app/globals.css`.
 *
 * Usage:
 *   import { cn } from "@/lib/utils"
 *   import { surfaces, gradients, gradientText } from "@/lib/design"
 *   <div className={cn(surfaces.card, "p-6")}>…</div>
 */

/* -------------------------------------------------------------------------
 * Gradient class-name strings (back the @utility helpers in globals.css)
 * ------------------------------------------------------------------------- */
export const gradients = {
  /** Orange → amber. Primary CTAs, brand marks, active accents. */
  brand: "bg-gradient-brand",
  /** Subtle top-down surface elevation. Cards, panels, headers. */
  surface: "bg-gradient-surface",
  /** Radial accent glow from the top. Behind hero / featured content. */
  glow: "bg-gradient-glow",
  /** Multi-stop hero mesh. Full-bleed hero backgrounds only. */
  mesh: "bg-gradient-mesh",
} as const;

export type GradientName = keyof typeof gradients;

/** Orange→amber gradient clipped to text. Reserve for one hero headline. */
export const gradientText = "text-gradient-brand";

/* -------------------------------------------------------------------------
 * Reusable surface / panel className tokens (cn-friendly)
 * ------------------------------------------------------------------------- */
export const surfaces = {
  /** Standard content card. */
  card: "bg-card text-card-foreground border border-border rounded-xl shadow-soft",
  /** Elevated / floating card (popovers, featured tiles). */
  cardElevated:
    "bg-surface-elevated text-card-foreground border border-border rounded-2xl shadow-layered",
  /** Frosted glass panel — sticky navbars, overlays, floating toolbars. */
  glass: "glass-panel rounded-2xl text-foreground",
  /** Inset well for muted / secondary regions. */
  well: "bg-muted/60 border border-border rounded-xl",
  /** Brand-tinted attention panel (tips, AI suggestions). */
  brandPanel:
    "bg-accent text-accent-foreground border border-brand-500/25 rounded-xl",
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
 * Plan status map (planned / confirmed / skipped / rescheduled)
 * ------------------------------------------------------------------------- */
export type PlanStatus = "planned" | "confirmed" | "skipped" | "rescheduled";

export interface StatusStyle {
  /** Text color utility. */
  text: string;
  /** Dot / solid indicator utility. */
  dot: string;
  /** Full badge className (bg + text + ring). */
  badge: string;
  /** Human label. */
  label: string;
}

export const planStatus: Record<PlanStatus, StatusStyle> = {
  planned: {
    text: "text-muted-foreground",
    dot: "bg-muted-foreground",
    badge:
      "bg-muted text-muted-foreground ring-1 ring-inset ring-border rounded-full",
    label: "Planned",
  },
  confirmed: {
    text: "text-success",
    dot: "bg-success",
    badge:
      "bg-success/12 text-success ring-1 ring-inset ring-success/25 rounded-full",
    label: "Confirmed",
  },
  skipped: {
    text: "text-danger",
    dot: "bg-danger",
    badge:
      "bg-danger/12 text-danger ring-1 ring-inset ring-danger/25 rounded-full",
    label: "Skipped",
  },
  rescheduled: {
    text: "text-warning",
    dot: "bg-warning",
    badge:
      "bg-warning/12 text-warning ring-1 ring-inset ring-warning/25 rounded-full",
    label: "Rescheduled",
  },
};

/* -------------------------------------------------------------------------
 * Small typed helpers
 * ------------------------------------------------------------------------- */

/** Compose a gradient utility with extra classes. */
export function gradient(name: GradientName, ...extra: string[]): string {
  return cn(gradients[name], ...extra);
}

/** Get meal-type styling, optionally merging one of its facets with classes. */
export function mealStyle(type: MealType): MealTypeStyle {
  return mealTypes[type];
}

/** Get plan-status styling. */
export function statusStyle(status: PlanStatus): StatusStyle {
  return planStatus[status];
}

/** A veg/non-veg dot color, Swiggy convention (green = veg, red = non-veg). */
export const dietDot = {
  veg: "text-success border-success",
  nonveg: "text-danger border-danger",
} as const;
