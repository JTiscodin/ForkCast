"use client";

import { motion } from "framer-motion";
import { Star } from "lucide-react";

import { cn } from "@/lib/utils";
import { mealStyle, statusStyle, dietBorder, focusRing } from "@/lib/design";
import type { MealSlot } from "@/lib/types";
import { inferVeg, formatINR } from "./dish-helpers";
import { DishImage } from "./DishImage";

export interface DishCardProps {
  slot: MealSlot;
  onClick?: () => void;
}

/**
 * FSSAI veg/non-veg mark — the classic square-and-dot stamp Swiggy prints
 * beside every dish name (green = veg, brown-red = non-veg). Token-colored.
 */
function DietMarker({ veg }: { veg: boolean }) {
  const color = veg ? "var(--diet-veg)" : "var(--diet-nonveg)";
  return (
    <svg
      width={14}
      height={14}
      viewBox="0 0 14 14"
      aria-hidden
      className="shrink-0"
    >
      <rect
        x="1"
        y="1"
        width="12"
        height="12"
        rx="2"
        fill="none"
        stroke={color}
        strokeWidth="1.5"
      />
      <circle cx="7" cy="7" r="3" fill={color} />
    </svg>
  );
}

/**
 * Compact Swiggy-style meal card for the dense calendar grid.
 * Small by design — image thumb, diet mark + name, price, solid-green rating
 * pill, restaurant, meal-type accent stripe, and a status treatment.
 */
export function DishCard({ slot, onClick }: DishCardProps) {
  const meal = mealStyle(slot.meal_type);
  const status = statusStyle(slot.status);
  const veg = inferVeg(slot.dish_name);
  const isSkipped = slot.status === "skipped";

  // When used inside the calendar, the parent already wraps the card in a
  // clickable <button> (via onSlotClick). Nesting another <button> is invalid
  // HTML and breaks hydration — so render as a non-interactive <div> unless an
  // onClick is passed for standalone use.
  const interactive = Boolean(onClick);
  const Root = interactive ? motion.button : motion.div;
  const rootProps = interactive
    ? ({ type: "button", onClick } as const)
    : {};

  return (
    <Root
      {...rootProps}
      whileHover={{ y: -3 }}
      whileTap={interactive ? { scale: 0.98 } : undefined}
      transition={{ type: "spring", stiffness: 400, damping: 26 }}
      className={cn(
        "group/dish relative flex w-full items-stretch gap-2 overflow-hidden rounded-lg border border-border bg-card p-1.5 text-left shadow-soft",
        // Veg / non-veg signal: colored LEFT BORDER (replaces the old dot).
        // Keep it stable on hover — only the non-left edges pick up the brand
        // tint, and elevation carries the hover affordance.
        dietBorder(veg),
        "transition-[color,box-shadow,border-color] group-hover/slot:border-t-brand-500/50 group-hover/slot:border-r-brand-500/50 group-hover/slot:border-b-brand-500/50 hover:border-t-brand-500/50 hover:border-r-brand-500/50 hover:border-b-brand-500/50 hover:shadow-soft",
        interactive && focusRing,
        // status treatments
        slot.status === "confirmed" && "ring-1 ring-inset ring-success/40",
        slot.status === "rescheduled" && "ring-1 ring-inset ring-warning/30 bg-warning/[0.04]",
        isSkipped && "opacity-55 saturate-50"
      )}
      title={veg ? "Veg" : "Non-veg"}
      aria-label={
        interactive
          ? `${slot.dish_name}, ${veg ? "Veg" : "Non-veg"}, ${meal.label}, ${formatINR(slot.price)}`
          : undefined
      }
    >
      {/* Meal-type accent stripe — inset so it never overlaps the diet
          left-border (the veg/non-veg signal), sitting just inside it. */}
      <span
        aria-hidden
        className={cn("absolute inset-y-0 left-0 w-0.5", meal.bg)}
      />

      {/* Image / fallback thumb */}
      <div className="relative ml-1 size-12 shrink-0 overflow-hidden rounded-md">
        <DishImage
          src={slot.image_url}
          alt={slot.dish_name}
          sizes="48px"
          fallbackClassName="text-xs"
        />
      </div>

      {/* Text block */}
      <div className="flex min-w-0 flex-1 flex-col justify-center gap-0.5 py-0.5 pr-1">
        <span className="flex min-w-0 items-center gap-1.5">
          <DietMarker veg={veg} />
          <span
            className={cn(
              "truncate text-sm font-bold leading-[1.4] tracking-[-0.02em] text-foreground",
              isSkipped && "line-through"
            )}
          >
            {slot.dish_name}
          </span>
        </span>

        {slot.restaurant_name && (
          <span className="line-clamp-1 text-xs leading-[1.4] text-muted-foreground">
            {slot.restaurant_name}
          </span>
        )}

        <div className="mt-0.5 flex items-center gap-1.5">
          <span className="text-sm font-bold leading-[1.4] tabular-nums text-foreground">
            {formatINR(slot.price)}
          </span>
          {/* Signature Swiggy rating pill — always solid green. */}
          {typeof slot.rating === "number" && (
            <span className="inline-flex items-center gap-0.5 rounded bg-rating px-1.5 py-0.5 text-xs font-bold leading-none text-white">
              <Star className="size-2.5 fill-current" strokeWidth={2.4} aria-hidden />
              {slot.rating.toFixed(1)}
            </span>
          )}
        </div>
      </div>

      {/* Status dot indicator, top-right */}
      <span
        aria-hidden
        className={cn(
          "absolute right-1.5 top-1.5 size-1.5 rounded-full",
          status.dot
        )}
        title={status.label}
      />
    </Root>
  );
}

export default DishCard;
