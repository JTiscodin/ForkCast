"use client";

import { useMemo, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight, Star } from "lucide-react";

import { cn } from "@/lib/utils";
import { mealStyle, statusStyle } from "@/lib/design";
import type { MealSlot, MealType } from "@/lib/types";
import { Skeleton } from "@/components/ui/skeleton";

import {
  MEAL_ORDER,
  groupByDay,
  dayTotal,
  formatINR,
  type DayGroup,
} from "./calendar-helpers";
import { splitWeeks } from "./week-helpers";

export interface WeekCalendarProps {
  /** All planned meal slots across the plan. */
  slots: MealSlot[];
  /** Number of days in the plan (1-based, defaults to 30). */
  days?: number;
  /** Fired when a slot cell is activated. */
  onSlotClick?: (slot: MealSlot) => void;
  /**
   * Optional render-prop for a slot. When provided the parent controls the full
   * slot presentation (e.g. inject a non-interactive <DishCard />). When omitted
   * the calendar renders a roomy, image-less fallback cell so it works alone.
   */
  renderSlot?: (slot: MealSlot) => ReactNode;
  /** Show a shimmering skeleton for the active week instead of content. */
  loading?: boolean;
}

/* -------------------------------------------------------------------------
 * Roomy fallback slot cell — image-less, used when no `renderSlot` is passed.
 * ------------------------------------------------------------------------- */
function FallbackSlotCell({ slot }: { slot: MealSlot }) {
  const meal = mealStyle(slot.meal_type);
  const status = statusStyle(slot.status);

  return (
    <div
      className={cn(
        "relative flex h-full w-full flex-col gap-2 rounded-lg border border-border bg-card px-3.5 py-3 text-left transition-colors",
        "hover:bg-muted/40",
      )}
    >
      <span
        aria-hidden
        className={cn("absolute inset-y-2 left-0 w-0.5 rounded-full opacity-60", meal.bg)}
      />
      <div className="flex items-start justify-between gap-2 pl-2">
        <p
          className={cn(
            "line-clamp-2 text-sm font-semibold leading-snug text-foreground",
            slot.status === "skipped" && "line-through opacity-60",
          )}
          title={slot.dish_name}
        >
          {slot.dish_name}
        </p>
        <span className="shrink-0 text-sm font-bold tabular-nums text-foreground">
          {formatINR(slot.price)}
        </span>
      </div>
      <div className="mt-auto flex items-center gap-2 pl-2">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
            meal.soft,
            meal.text,
            meal.border,
          )}
        >
          {meal.label}
        </span>
        {typeof slot.rating === "number" && (
          <span className="inline-flex items-center gap-0.5 rounded bg-rating px-1.5 py-0.5 text-[11px] font-bold leading-[1.4] text-white">
            <Star className="size-2.5 fill-current" strokeWidth={2.4} />
            <span className="tabular-nums">{slot.rating.toFixed(1)}</span>
          </span>
        )}
        {slot.status !== "planned" && (
          <span
            className={cn(
              "ml-auto inline-flex items-center gap-1 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide",
              status.badge,
            )}
          >
            <span className={cn("size-1 rounded-full", status.dot)} />
            {status.label}
          </span>
        )}
      </div>
    </div>
  );
}

/** Soft dashed placeholder for a meal with no slot. */
function EmptyMealCell({ mealType }: { mealType: MealType }) {
  const meal = mealStyle(mealType);
  return (
    <div className="flex h-full min-h-19 w-full items-center justify-center rounded-lg border border-dashed border-border bg-card">
      <span
        className={cn(
          "text-[11px] font-medium uppercase tracking-wide opacity-40",
          meal.text,
        )}
      >
        {meal.label}
      </span>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Day column header — "Day N" + that day's ₹ total.
 * ------------------------------------------------------------------------- */
function DayHeader({ group }: { group: DayGroup }) {
  const total = dayTotal(group.slots);
  const hasSlots = group.slots.length > 0;
  return (
    <div className="flex items-baseline justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2.5">
      <div className="flex items-baseline gap-1.5">
        <span className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
          Day
        </span>
        <span className="font-heading text-lg font-extrabold leading-none tracking-[-0.02em] text-foreground">
          {group.day}
        </span>
      </div>
      {hasSlots && (
        <span className="text-sm font-bold tabular-nums text-foreground">
          {formatINR(total)}
        </span>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Skeleton for the active week (7 columns × header + 3 meal rows).
 * ------------------------------------------------------------------------- */
function WeekSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
      {Array.from({ length: 7 }).map((_, i) => (
        <div key={i} className="flex flex-col gap-3">
          <Skeleton className="h-12 w-full rounded-md" />
          {MEAL_ORDER.map((m) => (
            <Skeleton key={m} className="h-20 w-full rounded-md" />
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * WeekCalendar — a spacious, week-focused plan view. Shows one week of the plan
 * at a time (7 day-columns × breakfast/lunch/dinner rows) with a week switcher
 * and animated transitions between weeks.
 */
export function WeekCalendar({
  slots,
  days = 30,
  onSlotClick,
  renderSlot,
  loading = false,
}: WeekCalendarProps) {
  const weeks = useMemo(() => splitWeeks(days), [days]);
  const groups = useMemo(() => groupByDay(slots, days), [slots, days]);

  const [activeWeek, setActiveWeek] = useState(0);
  // Clamp defensively without a setState-in-effect (React 19 friendly).
  const weekCount = weeks.length;
  const safeWeek =
    weekCount === 0 ? 0 : Math.min(activeWeek, weekCount - 1);
  const week = weeks[safeWeek];

  const weekGroups = useMemo(
    () => (week ? week.days.map((d) => groups[d - 1]) : []),
    [week, groups],
  );

  const weekTotal = useMemo(
    () => weekGroups.reduce((sum, g) => sum + dayTotal(g.slots), 0),
    [weekGroups],
  );

  const goPrev = () => setActiveWeek((w) => Math.max(0, Math.min(w, weekCount - 1) - 1));
  const goNext = () =>
    setActiveWeek((w) => Math.min(weekCount - 1, Math.min(w, weekCount - 1) + 1));

  if (weekCount === 0 || !week) {
    return (
      <section className="w-full rounded-md border border-dashed border-border bg-card p-10 text-center shadow-soft">
        <p className="text-sm text-muted-foreground">No days to plan yet.</p>
      </section>
    );
  }

  return (
    <section className="w-full">
      {/* Week switcher */}
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={goPrev}
            disabled={safeWeek === 0}
            aria-label="Previous week"
            className={cn(
              "inline-flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors",
              "hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40",
              "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            )}
          >
            <ChevronLeft className="size-5" strokeWidth={2.4} />
          </button>

          {/* Week pills */}
          <div className="flex items-center gap-1.5 overflow-x-auto">
            {weeks.map((w) => {
              const active = w.index === safeWeek;
              return (
                <button
                  key={w.index}
                  type="button"
                  onClick={() => setActiveWeek(w.index)}
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

          <button
            type="button"
            onClick={goNext}
            disabled={safeWeek >= weekCount - 1}
            aria-label="Next week"
            className={cn(
              "inline-flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors",
              "hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40",
              "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            )}
          >
            <ChevronRight className="size-5" strokeWidth={2.4} />
          </button>
        </div>

        <div className="flex items-baseline gap-3 sm:ml-auto">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Days {week.dayStart}
            {week.dayEnd !== week.dayStart ? `-${week.dayEnd}` : ""}
          </span>
          <span className="flex items-baseline gap-1.5">
            <span className="text-sm text-muted-foreground">Week total</span>
            <span className="text-base font-bold tabular-nums text-foreground">
              {formatINR(weekTotal)}
            </span>
          </span>
        </div>
      </div>

      {/* Active week body — animated on change */}
      {loading ? (
        <div aria-busy>
          <WeekSkeleton />
        </div>
      ) : (
        <AnimatePresence mode="wait">
          <motion.div
            key={week.index}
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -24 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7"
          >
            {weekGroups.map((group) => (
              <div key={group.day} className="flex flex-col gap-3">
                <DayHeader group={group} />
                <div className="flex flex-col gap-3">
                  {MEAL_ORDER.map((mealType) => {
                    const slot = group.byMeal[mealType];
                    if (!slot) {
                      return <EmptyMealCell key={mealType} mealType={mealType} />;
                    }

                    const content = renderSlot ? (
                      renderSlot(slot)
                    ) : (
                      <FallbackSlotCell slot={slot} />
                    );

                    // Flat cells sit directly on the column — no card-in-card wrapper.
                    const wrapped = content;

                    if (onSlotClick) {
                      return (
                        <button
                          key={mealType}
                          type="button"
                          onClick={() => onSlotClick(slot)}
                          className="block w-full rounded-md text-left outline-none transition-transform hover:-translate-y-0.5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                        >
                          {wrapped}
                        </button>
                      );
                    }

                    return <div key={mealType}>{wrapped}</div>;
                  })}
                </div>
              </div>
            ))}
          </motion.div>
        </AnimatePresence>
      )}
    </section>
  );
}

export default WeekCalendar;
