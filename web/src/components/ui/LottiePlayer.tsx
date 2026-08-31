"use client";

import * as React from "react";
import nextDynamic from "next/dynamic";
import type { LottieHandle } from "lottie-react";

import { cn } from "@/lib/utils";

// Client-only: this Next version allows `ssr: false` only inside client
// components (see bundled docs `01-app/02-guides/lazy-loading.md`). The
// wrapper is a client component, so lottie-react is never evaluated on the
// server and ships in its own lazily-loaded chunk.
const LottieClient = nextDynamic(() => import("./LottiePlayerInner"), {
  ssr: false,
});

export interface LottiePlayerProps {
  /** Parsed animation JSON (e.g. imported or fetched). */
  animationData?: object;
  /** URL/path to fetch the animation JSON from (e.g. `/animations/x.json`). */
  path?: string;
  /** Loop playback. Default true. */
  loop?: boolean;
  className?: string;
  /** Playback rate multiplier. */
  speed?: number;
}

/**
 * True when the user has asked for reduced motion. SSR-safe: false until the
 * media query can be read on the client.
 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = React.useState(false);
  React.useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/**
 * Decorative Lottie wrapper. Renders nothing during SSR and the first client
 * paint; pauses while scrolled offscreen; under `prefers-reduced-motion` it
 * renders a static first frame instead of animating.
 */
export function LottiePlayer({
  animationData,
  path,
  loop = true,
  className,
  speed,
}: LottiePlayerProps) {
  const [mounted, setMounted] = React.useState(false);
  const reduced = usePrefersReducedMotion();
  const containerRef = React.useRef<HTMLDivElement>(null);
  const handleRef = React.useRef<LottieHandle | null>(null);

  React.useEffect(() => setMounted(true), []);

  // Pause offscreen so background tabs/scroll positions don't burn frames.
  React.useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      ([entry]) => {
        const handle = handleRef.current;
        if (!handle) return;
        if (entry.isIntersecting && !reduced) handle.play();
        else handle.pause();
      },
      { threshold: 0 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reduced]);

  const src = path ?? animationData;

  if (!mounted || !src) {
    return <div ref={containerRef} className={className} aria-hidden="true" />;
  }

  return (
    <div ref={containerRef} className={cn(className)} aria-hidden="true">
      <LottieClient
        // Re-mount when reduced-motion flips so autoplay is honored.
        key={reduced ? "static" : "motion"}
        src={src}
        loop={!reduced && loop}
        // Reduced motion → static first frame (autoplay off draws frame 0).
        autoplay={!reduced}
        speed={speed}
        className="h-full w-full"
        handleRef={handleRef}
      />
    </div>
  );
}
