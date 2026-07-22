"use client";

import { cn } from "@/lib/utils";
import { gradients, gradientText } from "@/lib/design";
import type { SwiggyAddress } from "@/lib/types";
import { MapPin } from "lucide-react";

export function AppHeader({
  live,
  address,
}: {
  live: boolean;
  address: SwiggyAddress | null;
}) {
  return (
    <header className="flex items-center justify-between border-b border-border/60 bg-surface/50 px-5 py-3 backdrop-blur-md lg:px-8">
      <div className="flex items-center gap-3">
        <div
          className={cn(
            "flex size-9 items-center justify-center rounded-xl text-lg shadow-soft",
            gradients.brand
          )}
        >
          🍱
        </div>
        <div className="leading-tight">
          <h1 className={cn("font-display text-lg font-semibold tracking-tight", gradientText)}>
            Budget Meal Planner
          </h1>
          <p className="text-xs text-muted-foreground">
            Monthly budget → auto meal calendar → Swiggy Cash rollover
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {address && (
          <div className="hidden items-center gap-1.5 rounded-full border border-border/60 bg-surface-elevated px-3 py-1.5 text-xs text-muted-foreground sm:flex">
            <MapPin className="size-3.5 text-brand-500" />
            <span className="max-w-[180px] truncate">
              {address.addressTag ?? address.addressCategory ?? "Delivery address"}
            </span>
          </div>
        )}
        <span
          className={cn(
            "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium",
            live
              ? "bg-success/15 text-success"
              : "bg-muted-foreground/10 text-muted-foreground"
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
