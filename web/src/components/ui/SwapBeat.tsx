"use client";

import { LoaderCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import { LottiePlayer, usePrefersReducedMotion } from "@/components/ui/LottiePlayer";

export interface SwapBeatProps {
  /** True only while the swap request is genuinely in flight. */
  active: boolean;
  className?: string;
}

/**
 * Swap-in-flight beat: a small looping cutlery Lottie (brand-orange) shown
 * inside the affected meal row while `POST /slot/:id/swap` is pending.
 * Under prefers-reduced-motion it falls back to the plain lucide spinner so
 * the "work happening" signal never disappears entirely. Renders nothing
 * when inactive — it fires ONLY for a real in-flight request.
 */
export function SwapBeat({ active, className }: SwapBeatProps) {
  const reduced = usePrefersReducedMotion();

  if (!active) return null;

  return reduced ? (
    <LoaderCircle
      className={cn("size-5 animate-spin text-brand-500", className)}
      strokeWidth={2.4}
      aria-hidden
    />
  ) : (
    <LottiePlayer
      path="/animations/swap-utensils.json"
      loop
      className={cn("size-10", className)}
    />
  );
}

export default SwapBeat;
