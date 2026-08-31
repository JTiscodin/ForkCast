"use client";

import { useRef } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";

import { cn } from "@/lib/utils";
import type { SwiggyAddress } from "@/lib/types";
import { DUR, EASE, prefersReducedMotion } from "@/lib/motion";
import { MapPin, UtensilsCrossed } from "lucide-react";

gsap.registerPlugin(useGSAP);

export function AppHeader({
  live,
  address,
}: {
  live: boolean;
  address: SwiggyAddress | null;
}) {
  const rootRef = useRef<HTMLElement>(null);

  // One-time entrance: slide down into place while fading in (~0.5s). Sticky
  // chrome, so it stays subtle — a short drop, no bounce, transform/opacity only.
  useGSAP(
    () => {
      if (!rootRef.current || prefersReducedMotion()) return;
      gsap.from(rootRef.current, {
        y: -24,
        opacity: 0,
        duration: DUR.base,
        ease: EASE.out,
      });
    },
    { scope: rootRef }
  );

  return (
    <header
      ref={rootRef}
      className="flex items-center justify-between border-b border-border bg-surface px-5 py-3 lg:px-8"
    >
      <div className="flex min-w-0 items-center gap-3">
        {/* brand mark: flat orange tile + meals glyph (icon system, no emoji) */}
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-500 text-white">
          <UtensilsCrossed className="size-5" strokeWidth={2.4} aria-hidden />
        </div>
        <div className="min-w-0 leading-tight">
          <h1 className="truncate font-heading text-lg font-extrabold tracking-[-0.02em] text-foreground">
            Budget Meal Planner
          </h1>
          {/* Tagline is a fixed-width string; hide it below md so the header
              never outgrows a phone viewport (the status pill must survive). */}
          <p className="hidden text-sm leading-[1.4] text-muted-foreground md:block">
            Monthly budget · auto meal calendar · Swiggy Cash rollover
          </p>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        {address && (
          <div className="hidden items-center gap-1.5 rounded-full border border-border bg-surface-elevated px-3 py-1.5 text-sm leading-[1.4] text-muted-foreground sm:flex">
            <MapPin className="size-3.5 text-brand-500" strokeWidth={2.4} aria-hidden />
            <span className="max-w-[180px] truncate">
              {address.addressTag ?? address.addressCategory ?? "Delivery address"}
            </span>
          </div>
        )}
        <span
          className={cn(
            "flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-semibold leading-[1.4]",
            live
              ? "border-success/25 bg-success/12 text-success"
              : "border-border bg-muted/60 text-muted-foreground"
          )}
        >
          <span
            className={cn(
              "size-1.5 rounded-full",
              live ? "bg-success animate-pulse" : "bg-muted-foreground"
            )}
          />
          {live ? "Live · Swiggy" : "Demo mode"}
        </span>
      </div>
    </header>
  );
}

export default AppHeader;
