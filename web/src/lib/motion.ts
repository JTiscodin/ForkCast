import gsap from "gsap";

/**
 * Shared GSAP motion recipes for the Budget Meal Planner.
 *
 * Pacing follows the Swiggy-style feel: quick (0.4–0.7s), springy-but-subtle,
 * never blocking interaction. Every helper honors prefers-reduced-motion by
 * doing nothing — targets simply stay at their natural, fully-visible spot.
 *
 * Client-only: import from 'use client' components (GSAP touches the DOM).
 */

/** True when the user asked the OS/browser to reduce motion. SSR-safe. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Durations in seconds — quick delivery-app pacing, never sluggish. */
export const DUR = {
  /** Snappy feedback-scale moves (chips, pulses). */
  quick: 0.4,
  /** Default entrances (headers, sections, copy). */
  base: 0.55,
  /** Slower set-piece moves (upper bound of the design range). */
  slow: 0.7,
} as const;

/** Eases — gentle power curves and one low-overshoot pop. No cartoon bounce. */
export const EASE = {
  /** Standard deceleration (entrances). */
  out: "power2.out",
  /** Softer, longer tail for staggered copy. */
  soft: "power3.out",
  /** Subtle overshoot for scale pop-ins. */
  pop: "back.out(1.4)",
  /** Smooth symmetric curve for perpetual idle loops. */
  loop: "sine.inOut",
} as const;

export interface FadeUpOptions {
  /** Vertical offset in px (default 16). */
  y?: number;
  /** Per-element duration in seconds (default DUR.base). */
  duration?: number;
  /** Stagger between elements in seconds (default 0 — move together). */
  stagger?: number;
  /** Delay before the first element moves, in seconds (default 0). */
  delay?: number;
}

/**
 * Fade-up entrance recipe: targets rise from `y` px below into place while
 * fading in. Skipped entirely under prefers-reduced-motion.
 *
 * Call inside useGSAP (so the tween joins the hook's context for cleanup):
 *
 *   useGSAP(() => { fadeUp(".step", { stagger: 0.07 }); }, { scope: rootRef });
 *
 * Returns the created tween, or undefined when reduced motion skipped it.
 */
export function fadeUp(
  targets: gsap.TweenTarget,
  { y = 16, duration = DUR.base, stagger = 0, delay = 0 }: FadeUpOptions = {},
): gsap.core.Tween | undefined {
  if (prefersReducedMotion()) return undefined;
  return gsap.from(targets, {
    opacity: 0,
    y,
    duration,
    stagger,
    delay,
    ease: EASE.soft,
  });
}
