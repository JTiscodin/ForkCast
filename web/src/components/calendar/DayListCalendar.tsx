"use client";

import { useMemo, useState, useEffect, useRef } from "react";

import { cn } from "@/lib/utils";
import { prefersReducedMotion } from "@/lib/motion";
import type { MealSlot } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";

import { groupByDay, dayTotal, formatINR } from "./calendar-helpers";
import { splitWeeks } from "./week-helpers";
import { DayListRow } from "./DayListRow";

export interface DayListCalendarProps {
  slots: MealSlot[];
  days?: number;
  onSlotClick?: (slot: MealSlot) => void;
  loading?: boolean;
  /** Slot whose swap request is in flight — shows the inline beat on its card. */
  swappingSlotId?: number | null;
}

/**
 * DayListCalendar — a vertically scrolling, one-day-per-row plan view.
 *
 * Replaces the 7-column week grid, which squeezed each dish card to ~180px and
 * truncated every name to an unreadable stub ("Pan…", "Mas…"). Trading
 * horizontal density for vertical scroll means dish names, restaurants, and
 * curry+bread pairings all render in full.
 *
 * The week pills are kept, but as JUMP LINKS into the scroll rather than as
 * filters — the whole plan stays in the DOM so browser find-in-page works
 * across the entire month.
 */
export function DayListCalendar({
  slots,
  days = 30,
  onSlotClick,
  loading = false,
  swappingSlotId = null,
}: DayListCalendarProps) {
  const groups = useMemo(() => groupByDay(slots, days), [slots, days]);
  const weeks = useMemo(() => splitWeeks(days), [days]);

  // Only days that actually carry meals — with `meals: ["breakfast","lunch"]`
  // the plan legitimately has no dinner, and empty rows would just be noise.
  const filled = useMemo(
    () => groups.filter((g) => g.slots.length > 0),
    [groups],
  );

  const [activeWeek, setActiveWeek] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Track which week is in view so the pill highlights as the user scrolls.
  useEffect(() => {
    const root = containerRef.current;
    if (!root || loading) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (!visible) return;
        const day = Number(visible.target.getAttribute("data-day"));
        if (!Number.isFinite(day)) return;
        setActiveWeek(Math.floor((day - 1) / 7));
      },
      { root: null, rootMargin: "-45% 0px -45% 0px", threshold: 0 },
    );

    const sections = root.querySelectorAll("[data-day]");
    sections.forEach((s) => observer.observe(s));
    return () => observer.disconnect();
  }, [filled, loading]);

  const jumpToWeek = (weekIndex: number) => {
    const week = weeks[weekIndex];
    if (!week) return;
    // Jump to the first day in that week that actually has meals.
    const target = filled.find((g) => g.day >= week.dayStart);
    if (!target) return;
    // Programmatic scrolling bypasses the CSS scroll-behavior reduced-motion
    // rule, so branch on the media query here too.
    const behavior = prefersReducedMotion() ? "auto" : "smooth";
    document
      .getElementById(`day-${target.day}`)
      ?.scrollIntoView({ behavior, block: "start" });
  };

  if (loading) {
    return (
      <div aria-busy className="flex flex-col gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="rounded-lg border border-border bg-card p-4 shadow-soft">
            <Skeleton className="mb-3.5 h-7 w-32 rounded-md" />
            <div className="grid gap-3 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, j) => (
                <Skeleton key={j} className="h-28 w-full rounded-lg" />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (filled.length === 0) {
    return (
      <section className="w-full rounded-lg border border-dashed border-border bg-card p-10 text-center shadow-soft">
        <p className="text-sm text-muted-foreground">No days to plan yet.</p>
      </section>
    );
  }

  const planTotal = filled.reduce((sum, g) => sum + dayTotal(g.slots), 0);

  return (
    <section className="w-full">
      {/* Week jump-bar. Deliberately NOT sticky: WalletBar already owns the
          pinned position at the top of this pane (sticky top-3 z-30), and it
          wraps taller on narrow screens, so a second sticky bar pinned at a
          fixed offset would slide underneath it and hide the week pills. */}
      <div className="-mx-1 mb-4 border-b border-border bg-background px-1 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 overflow-x-auto">
            {weeks.map((w) => {
              const active = w.index === activeWeek;
              return (
                <button
                  key={w.index}
                  type="button"
                  onClick={() => jumpToWeek(w.index)}
                  aria-current={active ? "true" : undefined}
                  className={cn(
                    "shrink-0 rounded-full px-3.5 py-1.5 text-xs transition-colors",
                    "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                    active
                      ? "bg-brand-500 font-bold text-primary-foreground"
                      : "font-medium text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {w.label}
                </button>
              );
            })}
          </div>
          <span className="ml-auto flex shrink-0 items-baseline gap-1.5 pr-1">
            <span className="text-sm text-muted-foreground">Plan total</span>
            <span className="text-sm font-bold tracking-[-0.02em] tabular-nums text-foreground">
              {formatINR(planTotal)}
            </span>
          </span>
        </div>
      </div>

      {/* The days */}
      <div ref={containerRef} className="flex flex-col gap-4">
        {filled.map((group) => (
          <div key={group.day} data-day={group.day}>
            <DayListRow
              group={group}
              onSlotClick={onSlotClick}
              swappingSlotId={swappingSlotId}
            />
          </div>
        ))}
      </div>
    </section>
  );
}

export default DayListCalendar;
