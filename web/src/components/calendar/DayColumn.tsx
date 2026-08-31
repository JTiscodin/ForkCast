"use client";

import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { Star } from "lucide-react";

import { cn } from "@/lib/utils";
import { mealStyle, statusStyle } from "@/lib/design";
import type { MealSlot, MealType } from "@/lib/types";

import { MEAL_ORDER, dayTotal, formatINR, type DayGroup } from "./calendar-helpers";

/* -------------------------------------------------------------------------
 * Fallback cell — image-less slot render used when the parent does not pass
 * a `renderSlot`. Shows name + ₹price + meal accent + rating + status.
 * ------------------------------------------------------------------------- */
function FallbackSlotCell({ slot }: { slot: MealSlot }) {
  const meal = mealStyle(slot.meal_type);
  const status = statusStyle(slot.status);

  return (
    <div
      className={cn(
        "group/slot relative w-full rounded-lg border border-border bg-card px-2.5 py-2 text-left transition-colors",
        "hover:bg-muted/40",
      )}
    >
      {/* meal accent rail */}
      <span
        aria-hidden
        className={cn(
          "absolute inset-y-1 left-0 w-0.5 rounded-full opacity-60",
          meal.bg,
        )}
      />
      <div className="flex items-start justify-between gap-2 pl-1.5">
        <div className="min-w-0">
          <p
            className={cn(
              "truncate text-sm font-semibold leading-[1.4] text-foreground",
              slot.status === "skipped" && "line-through opacity-60",
            )}
            title={slot.dish_name}
          >
            {slot.dish_name}
          </p>
          <div className="mt-1 flex items-center gap-1.5">
            <span
              className={cn(
                "inline-flex items-center rounded-full border px-1.5 py-px text-[11px] font-semibold uppercase tracking-wide",
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
          </div>
        </div>
        <span className="shrink-0 text-sm font-bold tabular-nums text-foreground">
          {formatINR(slot.price)}
        </span>
      </div>

      {slot.status !== "planned" && (
        <span
          className={cn(
            "mt-1.5 ml-1.5 inline-flex items-center gap-1 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide",
            status.badge,
          )}
        >
          <span className={cn("size-1 rounded-full", status.dot)} />
          {status.label}
        </span>
      )}
    </div>
  );
}

/** Faint placeholder for a meal that has no slot. */
function EmptyMealCell({ mealType }: { mealType: MealType }) {
  const meal = mealStyle(mealType);
  return (
    <div className="flex items-center gap-2 rounded-lg border border-dashed border-border px-2.5 py-2">
      <span className={cn("text-[11px] font-medium uppercase tracking-wide opacity-40", meal.text)}>
        {meal.label}
      </span>
    </div>
  );
}

export interface DayColumnProps {
  group: DayGroup;
  onSlotClick?: (slot: MealSlot) => void;
  renderSlot?: (slot: MealSlot) => ReactNode;
}

/** A single day cell: gradient-accented header + 3 stacked meal slots. */
export function DayColumn({ group, onSlotClick, renderSlot }: DayColumnProps) {
  const total = dayTotal(group.slots);
  const hasSlots = group.slots.length > 0;

  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 12 },
        show: { opacity: 1, y: 0 },
      }}
      whileHover={{ y: -3 }}
      transition={{ type: "spring", stiffness: 320, damping: 26 }}
      className={cn(
        "flex h-full flex-col overflow-hidden rounded-lg border border-border bg-card shadow-soft",
      )}
    >
      {/* Quiet day header — flat white, thin bottom divider */}
      <div className="border-b border-border px-3 pb-2 pt-2.5">
        <div className="flex items-baseline justify-between">
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
      </div>

      {/* Meal slots, breakfast → lunch → dinner */}
      <div className="flex flex-1 flex-col gap-1.5 p-2.5 pt-2">
        {MEAL_ORDER.map((mealType) => {
          const slot = group.byMeal[mealType];
          if (!slot) return <EmptyMealCell key={mealType} mealType={mealType} />;

          const content = renderSlot ? renderSlot(slot) : <FallbackSlotCell slot={slot} />;

          if (onSlotClick) {
            return (
              <button
                key={mealType}
                type="button"
                onClick={() => onSlotClick(slot)}
                className="block w-full rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
              >
                {content}
              </button>
            );
          }

          return <div key={mealType}>{content}</div>;
        })}
      </div>
    </motion.div>
  );
}
