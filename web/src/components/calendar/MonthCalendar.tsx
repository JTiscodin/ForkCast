"use client";

import { useMemo, type ReactNode } from "react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { mealStyle } from "@/lib/design";
import type { MealSlot } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";

import { DayColumn } from "./DayColumn";
import { MEAL_ORDER, groupByDay, dayTotal, formatINR } from "./calendar-helpers";

export interface MonthCalendarProps {
  /** All planned meal slots across the month. */
  slots: MealSlot[];
  /** Number of days to render (1-based, defaults to 30). */
  days?: number;
  /** Fired when a slot cell is clicked. */
  onSlotClick?: (slot: MealSlot) => void;
  /**
   * Optional render-prop for a slot. When provided, the parent controls the
   * full slot presentation (e.g. inject <DishCard />). When omitted, the
   * calendar renders a lightweight, image-less fallback cell so it works
   * standalone.
   */
  renderSlot?: (slot: MealSlot) => ReactNode;
  /** Show a shimmering skeleton grid instead of content. */
  loading?: boolean;
}

/* -------------------------------------------------------------------------
 * Skeleton grid — mirrors the real day-card layout while loading.
 * ------------------------------------------------------------------------- */
function CalendarSkeleton({ days }: { days: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-7">
      {Array.from({ length: days }).map((_, i) => (
        <div
          key={i}
          className="flex flex-col overflow-hidden rounded-lg border border-border bg-card shadow-soft"
        >
          <div className="border-b border-border px-3 pb-2 pt-2.5">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-10" />
              <Skeleton className="h-3 w-8" />
            </div>
          </div>
          <div className="flex flex-col gap-1.5 p-2.5 pt-2">
            {MEAL_ORDER.map((m) => (
              <Skeleton key={m} className="h-12 w-full rounded-lg" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * MonthCalendar — a premium month planner grid. Renders `days` day-cards in a
 * responsive calendar grid (up to 7 per row on desktop), each stacking its
 * breakfast → lunch → dinner slots.
 */
export function MonthCalendar({
  slots,
  days = 30,
  onSlotClick,
  renderSlot,
  loading = false,
}: MonthCalendarProps) {
  const groups = useMemo(() => groupByDay(slots, days), [slots, days]);

  const monthTotal = useMemo(() => dayTotal(slots), [slots]);
  const plannedDays = useMemo(
    () => groups.filter((g) => g.slots.length > 0).length,
    [groups],
  );

  if (loading) {
    return (
      <section aria-busy className="w-full">
        <CalendarSkeleton days={days} />
      </section>
    );
  }

  return (
    <section className="w-full">
      {/* Summary strip */}
      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex items-baseline gap-2">
          <span className="font-heading text-xl font-extrabold tracking-[-0.02em] text-foreground">
            {days}-Day Plan
          </span>
          <span className="text-sm text-muted-foreground">
            {plannedDays} day{plannedDays === 1 ? "" : "s"} planned
          </span>
        </div>
        <div className="flex items-center gap-4 sm:ml-auto">
          {/* Meal legend */}
          <div className="hidden items-center gap-3 sm:flex">
            {MEAL_ORDER.map((m) => {
              const meal = mealStyle(m);
              return (
                <span
                  key={m}
                  className="inline-flex items-center gap-1.5 text-sm text-muted-foreground"
                >
                  <span className={cn("size-2 rounded-full opacity-60", meal.bg)} />
                  {meal.label}
                </span>
              );
            })}
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-sm text-muted-foreground">Total</span>
            <span className="text-base font-bold tabular-nums text-foreground">
              {formatINR(monthTotal)}
            </span>
          </div>
        </div>
      </div>

      {/* Day grid */}
      <motion.div
        variants={{
          hidden: {},
          show: { transition: { staggerChildren: 0.025 } },
        }}
        initial="hidden"
        animate="show"
        className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-7"
      >
        {groups.map((group) => (
          <DayColumn
            key={group.day}
            group={group}
            onSlotClick={onSlotClick}
            renderSlot={renderSlot}
          />
        ))}
      </motion.div>
    </section>
  );
}

export default MonthCalendar;
