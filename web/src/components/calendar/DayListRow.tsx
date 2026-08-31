"use client";

import { motion } from "framer-motion";
import { Star, Plus } from "lucide-react";

import { cn } from "@/lib/utils";
import { mealStyle, statusStyle, dietBorder, focusRing } from "@/lib/design";
import { slotTotal, type MealSlot } from "@/lib/types";
import { inferVeg } from "@/components/dish/dish-helpers";
import { DishImage } from "@/components/dish/DishImage";
import { SwapBeat } from "@/components/ui/SwapBeat";
import { formatINR, MEAL_ORDER, dayTotal, type DayGroup } from "./calendar-helpers";

/* -------------------------------------------------------------------------
 * Wide meal card — the readable counterpart to the dense grid DishCard.
 *
 * The 7-column week grid gave each card ~180px, minus a 48px thumb, leaving
 * ~110px for the name at text-xs + truncate. "Paneer Butter Masala" simply
 * cannot render in that space, so every card showed "Pan…". Here the card owns
 * a full row, so names wrap in full at a readable size and the restaurant,
 * course, and any accompaniment all have room.
 * ------------------------------------------------------------------------- */
function WideMealCard({
  slot,
  onClick,
  swapping,
}: {
  slot: MealSlot;
  onClick?: () => void;
  /** Swap request for this slot is in flight — beat over the thumbnail. */
  swapping?: boolean;
}) {
  const meal = mealStyle(slot.meal_type);
  const status = statusStyle(slot.status);
  const veg = inferVeg(slot.dish_name);
  const isSkipped = slot.status === "skipped";
  const hasSide = Boolean(slot.side_dish_name);
  const total = slotTotal(slot);

  const interactive = Boolean(onClick) && !swapping;
  const Root = interactive ? motion.button : motion.div;

  return (
    <Root
      {...(interactive ? ({ type: "button", onClick } as const) : {})}
      whileHover={interactive ? { y: -2 } : undefined}
      whileTap={interactive ? { scale: 0.995 } : undefined}
      transition={{ type: "spring", stiffness: 400, damping: 28 }}
      className={cn(
        "relative flex w-full flex-col gap-0 overflow-hidden rounded-lg border border-border bg-card text-left shadow-soft",
        dietBorder(veg),
        "hover:border-brand-200",
        // Interactive cards rise via whileHover above; deepening to the
        // layered elevation token while hovered makes the lift read as
        // physical rather than a bare translate. Non-interactive cards stay
        // flat but keep their existing border-color transition.
        interactive
          ? "transition-[border-color,box-shadow] duration-200 hover:shadow-layered"
          : "transition-colors",
        interactive && focusRing,
        slot.status === "confirmed" && "ring-1 ring-inset ring-success/40",
        slot.status === "rescheduled" && "ring-1 ring-inset ring-warning/30",
        isSkipped && "opacity-55 saturate-50",
      )}
      aria-label={
        interactive
          ? `${slot.dish_name}${hasSide ? ` with ${slot.side_dish_name}` : ""}, ${
              veg ? "Veg" : "Non-veg"
            }, ${meal.label}, ${formatINR(total)}`
          : undefined
      }
    >
      {/* Main dish row */}
      <div className="flex items-start gap-3.5 p-3.5">
        <div className="relative size-20 shrink-0 overflow-hidden rounded-md sm:size-24">
          <DishImage
            src={slot.image_url}
            alt={slot.dish_name}
            sizes="96px"
            fallbackClassName="text-xs"
          />
          {/* Swap-in-flight beat: cutlery Lottie over the affected dish,
              only while the request is genuinely pending. */}
          {swapping && (
            <span className="absolute inset-0 flex items-center justify-center bg-brand-50/85">
              <SwapBeat active className="size-10" />
            </span>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {/* Name gets the room it needs — wraps to 2 lines, never truncates
              to an unreadable stub. */}
          <div className="flex items-start justify-between gap-3">
            <p
              className={cn(
                "line-clamp-2 text-sm font-semibold leading-[1.4] tracking-[-0.02em] text-foreground",
                isSkipped && "line-through",
              )}
            >
              {slot.dish_name}
            </p>
            <span className="shrink-0 text-sm font-bold tabular-nums text-foreground">
              {formatINR(slot.price)}
            </span>
          </div>

          {slot.restaurant_name && (
            <p className="truncate text-sm leading-[1.4] text-muted-foreground">
              {slot.restaurant_name}
            </p>
          )}

          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            {/* Diet runs on the dedicated --diet-veg / --diet-nonveg tokens,
                matching DishCard and DishDetailModal. The card's colored left
                border (dietBorder) stays the primary signal; this pill only
                spells it out, in the same hue. */}
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-xs font-medium",
                veg
                  ? "bg-diet-veg/12 text-diet-veg"
                  : "bg-diet-nonveg/12 text-diet-nonveg",
              )}
            >
              <span
                className={cn(
                  "size-1.5 rounded-full",
                  veg ? "bg-diet-veg" : "bg-diet-nonveg",
                )}
              />
              {veg ? "Veg" : "Non-veg"}
            </span>

            {typeof slot.rating === "number" && (
              <span className="inline-flex items-center gap-0.5 rounded bg-rating px-1.5 py-0.5 text-[11px] font-bold leading-[1.4] text-white">
                <Star className="size-2.5 fill-current" strokeWidth={2.4} />
                {slot.rating.toFixed(1)}
              </span>
            )}

            {slot.course && slot.course !== "complete" && (
              <span className="rounded-full bg-muted/70 px-1.5 py-0.5 text-xs font-medium capitalize text-muted-foreground">
                {slot.course}
              </span>
            )}

            {slot.status !== "planned" && (
              <span
                className={cn(
                  "inline-flex items-center gap-1 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide",
                  status.badge,
                )}
              >
                <span className={cn("size-1 rounded-full", status.dot)} />
                {status.label}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Accompaniment — a curry is not a meal on its own, so the bread/rice
          that completes it is shown as part of the SAME card, with a combined
          total. Two separate cards would read as two meals. */}
      {hasSide && (
        <div className="mx-3.5 mb-3.5 rounded-lg border border-dashed border-border bg-muted/30 px-3 py-2">
          <div className="flex items-center gap-2.5">
            <Plus className="size-4 shrink-0 text-muted-foreground" strokeWidth={2.4} />
            <div className="relative size-9 shrink-0 overflow-hidden rounded-md">
              <DishImage
                src={slot.side_image_url}
                alt={slot.side_dish_name ?? ""}
                sizes="36px"
                fallbackClassName="text-[10px]"
              />
            </div>
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-xs font-medium text-foreground">
                {slot.side_dish_name}
                {(slot.side_qty ?? 0) > 1 && (
                  <span className="ml-1 text-muted-foreground">
                    ×{slot.side_qty}
                  </span>
                )}
              </span>
              {slot.side_restaurant_name && (
                <span className="truncate text-xs text-muted-foreground">
                  {slot.side_restaurant_name}
                </span>
              )}
            </div>
            <span className="shrink-0 text-sm font-bold tabular-nums text-muted-foreground">
              {formatINR(slot.side_price ?? 0)}
            </span>
          </div>

          <div className="mt-2 flex items-center justify-between border-t border-border/60 pt-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Meal total
            </span>
            <span className="text-sm font-bold tabular-nums text-foreground">
              {formatINR(total)}
            </span>
          </div>
        </div>
      )}
    </Root>
  );
}

/* -------------------------------------------------------------------------
 * One day = one row, meals stacked beneath a day header.
 * ------------------------------------------------------------------------- */
export interface DayListRowProps {
  group: DayGroup;
  onSlotClick?: (slot: MealSlot) => void;
  /** Slot whose swap request is in flight. */
  swappingSlotId?: number | null;
}

export function DayListRow({ group, onSlotClick, swappingSlotId }: DayListRowProps) {
  const total = dayTotal(group.slots);
  const present = MEAL_ORDER.filter((m) => group.byMeal[m]);

  if (present.length === 0) return null;

  return (
    <section
      id={`day-${group.day}`}
      className="scroll-mt-28 rounded-lg border border-border bg-card p-3.5 shadow-soft sm:p-4"
    >
      {/* Day header */}
      <header className="mb-3.5 flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Day
          </span>
          <span className="font-heading text-2xl font-extrabold leading-none tracking-[-0.02em] text-foreground">
            {group.day}
          </span>
          <span className="text-sm text-muted-foreground">
            {present.length} {present.length === 1 ? "meal" : "meals"}
          </span>
        </div>
        <span className="text-sm font-bold tabular-nums text-foreground">
          {formatINR(total)}
        </span>
      </header>

      {/* Meals — one per row on mobile, side by side once there's width. */}
      <div
        className={cn(
          "grid gap-3",
          present.length >= 3
            ? "lg:grid-cols-3"
            : present.length === 2
              ? "lg:grid-cols-2"
              : "lg:grid-cols-1",
        )}
      >
        {present.map((mealType) => {
          const slot = group.byMeal[mealType]!;
          const meal = mealStyle(mealType);
          return (
            <div key={mealType} className="flex flex-col gap-1.5">
              <span
                className={cn(
                  "inline-flex w-fit items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
                  meal.soft,
                  meal.text,
                  meal.border,
                )}
              >
                {meal.label}
              </span>
              <WideMealCard
                slot={slot}
                swapping={swappingSlotId === slot.id}
                onClick={onSlotClick ? () => onSlotClick(slot) : undefined}
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default DayListRow;
