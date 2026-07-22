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
        "group/slot relative w-full rounded-lg border px-2.5 py-2 text-left transition-colors",
        meal.soft,
        meal.border,
        "hover:bg-surface-elevated",
      )}
    >
      {/* meal accent rail */}
      <span
        aria-hidden
        className={cn(
          "absolute inset-y-1 left-0 w-0.5 rounded-full",
          meal.bg,
        )}
      />
      <div className="flex items-start justify-between gap-2 pl-1.5">
        <div className="min-w-0">
          <p
            className={cn(
              "truncate text-[13px] font-medium leading-tight text-foreground",
              slot.status === "skipped" && "line-through opacity-60",
            )}
            title={slot.dish_name}
          >
            {slot.dish_name}
          </p>
          <div className="mt-1 flex items-center gap-1.5">
            <span className={cn("text-[10px] font-medium uppercase tracking-wide", meal.text)}>
              {meal.label}
            </span>
            {typeof slot.rating === "number" && (
              <span className="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground">
                <Star className="size-2.5 fill-amber-400 text-amber-400" />
                <span className="font-mono">{slot.rating.toFixed(1)}</span>
              </span>
            )}
          </div>
        </div>
        <span className="shrink-0 font-mono text-xs font-semibold text-foreground">
          {formatINR(slot.price)}
        </span>
      </div>

      {slot.status !== "planned" && (
        <span
          className={cn(
            "mt-1.5 ml-1.5 inline-flex items-center gap-1 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide",
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
    <div className="flex items-center gap-2 rounded-lg border border-dashed border-border/60 px-2.5 py-2">
      <span className={cn("text-[10px] font-medium uppercase tracking-wide opacity-40", meal.text)}>
        {meal.label}
      </span>
      <span className="ml-auto select-none text-muted-foreground/40">—</span>
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
        "flex h-full flex-col overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10 shadow-soft",
        "transition-shadow hover:shadow-layered",
      )}
    >
      {/* Day header with a subtle brand gradient accent bar */}
      <div className="relative bg-gradient-surface px-3 pb-2 pt-2.5">
        <span
          aria-hidden
          className="absolute inset-x-0 top-0 h-0.5 bg-gradient-brand opacity-80"
        />
        <div className="flex items-baseline justify-between">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
              Day
            </span>
            <span className="font-display text-lg font-semibold leading-none text-foreground">
              {group.day}
            </span>
          </div>
          {hasSlots && (
            <span className="font-mono text-[11px] font-semibold text-accent-brand">
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
                className="block w-full rounded-lg text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
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
