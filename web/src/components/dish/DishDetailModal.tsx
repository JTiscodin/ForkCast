"use client";

import * as React from "react";
import Image from "next/image";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, Star, ArrowLeftRight, Utensils } from "lucide-react";

import { cn } from "@/lib/utils";
import { surfaces, mealStyle, statusStyle, dietBorder } from "@/lib/design";
import { api } from "@/lib/api";
import { slotTotal, type MealSlot, type DishAlternative } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import { inferVeg, dishInitials, formatINR, ratingColor } from "./dish-helpers";
import { DishImage } from "./DishImage";

export interface DishDetailModalProps {
  slot: MealSlot | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSwap?: (alt: DishAlternative) => void;
}

/**
 * Veg / non-veg indicator — a small chip carrying the same colored LEFT BORDER
 * used on dish cards, plus a text label. Consistent with `dietBorder`.
 */
function VegIndicator({ veg }: { veg: boolean }) {
  return (
    <span
      className={cn(
        dietBorder(veg, "rounded-md bg-muted/50 pl-2 pr-2.5 py-0.5"),
        "inline-flex items-center text-xs font-medium",
        veg ? "text-diet-veg" : "text-diet-nonveg"
      )}
      title={veg ? "Veg" : "Non-veg"}
    >
      {veg ? "Veg" : "Non-veg"}
    </span>
  );
}

/** "Why this dish?" AI section — fetches on open, shimmer while loading. */
// Mounted fresh per slot (parent keys on slot.id), so state starts clean —
// no synchronous reset inside the effect is needed.
function WhySection({ slotId }: { slotId: number }) {
  const [why, setWhy] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    api
      .why(slotId)
      .then((res) => {
        if (!active) return;
        setWhy(res.why);
        setLoading(false);
      })
      .catch(() => {
        if (!active) return;
        setFailed(true);
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [slotId]);

  // Hide the section entirely on error.
  if (failed) return null;

  return (
    <div
      className={cn(
        surfaces.glass,
        "flex gap-3 p-4"
      )}
    >
      <span
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-full bg-gradient-brand text-primary-foreground shadow-glow"
        )}
      >
        <Sparkles className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-accent-brand">
          Why this dish?
        </p>
        {loading ? (
          <div className="space-y-1.5">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-4/5" />
          </div>
        ) : (
          <motion.p
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className="text-sm leading-relaxed text-foreground/90"
          >
            {why}
          </motion.p>
        )}
      </div>
    </div>
  );
}

/** A mini alternative dish card inside the swap scroll row. */
function AltCard({
  alt,
  onClick,
}: {
  alt: DishAlternative;
  onClick: () => void;
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileHover={{ y: -3 }}
      whileTap={{ scale: 0.97 }}
      transition={{ type: "spring", stiffness: 400, damping: 26 }}
      className={cn(
        "flex w-36 shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-card text-left shadow-soft",
        // Veg / non-veg signal: colored LEFT BORDER (matches DishCard). Hover
        // tints only the non-left edges so the diet cue stays stable.
        dietBorder(alt.veg),
        "transition-[box-shadow,border-color] hover:border-t-brand-500/50 hover:border-r-brand-500/50 hover:border-b-brand-500/50 hover:shadow-layered"
      )}
      title={alt.veg ? "Veg" : "Non-veg"}
    >
      <div className="relative aspect-[4/3] w-full overflow-hidden">
        <DishImage src={alt.image_url} alt={alt.name} sizes="144px" rounded="rounded-none" />
      </div>
      <div className="flex flex-1 flex-col gap-1 p-2">
        <span className="truncate text-xs font-medium text-foreground">
          {alt.name}
        </span>
        <span className="truncate text-[0.65rem] text-muted-foreground">
          {alt.restaurant_name}
        </span>
        <div className="mt-auto flex items-center justify-between pt-1">
          <span className="font-mono text-xs font-semibold text-foreground">
            {formatINR(alt.price)}
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-0.5 font-mono text-[0.7rem] font-semibold",
              ratingColor(alt.rating)
            )}
          >
            <Star className="size-2.5 fill-current" />
            {alt.rating.toFixed(1)}
          </span>
        </div>
      </div>
    </motion.button>
  );
}

/** "Swap this meal" section — lazy loads alternatives on first click. */
function SwapSection({
  slotId,
  onSwap,
}: {
  slotId: number;
  onSwap?: (alt: DishAlternative) => void;
}) {
  const [alts, setAlts] = React.useState<DishAlternative[] | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  const [requested, setRequested] = React.useState(false);

  const load = React.useCallback(() => {
    setRequested(true);
    setLoading(true);
    setFailed(false);
    api
      .alternatives(slotId)
      .then((res) => {
        setAlts(res.alternatives);
        setLoading(false);
      })
      .catch(() => {
        setFailed(true);
        setLoading(false);
      });
  }, [slotId]);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 font-display text-sm font-semibold text-foreground">
          <ArrowLeftRight className="size-4 text-accent-brand" />
          Swap this meal
        </h3>
        {!requested && (
          <Button size="sm" variant="outline" onClick={load}>
            Show alternatives
          </Button>
        )}
      </div>

      {loading && (
        <div className="flex gap-3 overflow-hidden">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="w-36 shrink-0 overflow-hidden rounded-xl border border-border"
            >
              <Skeleton className="aspect-[4/3] w-full rounded-none" />
              <div className="space-y-1.5 p-2">
                <Skeleton className="h-3 w-3/4" />
                <Skeleton className="h-2.5 w-1/2" />
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && failed && (
        <p className="text-sm text-muted-foreground">
          Couldn&apos;t load alternatives right now.
        </p>
      )}

      {!loading && !failed && alts && alts.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No alternatives in this price band.
        </p>
      )}

      {!loading && !failed && alts && alts.length > 0 && (
        <ScrollArea className="w-full whitespace-nowrap">
          <motion.div
            initial="hidden"
            animate="show"
            variants={{
              hidden: {},
              show: { transition: { staggerChildren: 0.05 } },
            }}
            className="flex gap-3 pb-3"
          >
            {alts.map((alt) => (
              <motion.div
                key={`${alt.dish_id}-${alt.restaurant_id}`}
                variants={{
                  hidden: { opacity: 0, y: 8 },
                  show: { opacity: 1, y: 0 },
                }}
              >
                <AltCard alt={alt} onClick={() => onSwap?.(alt)} />
              </motion.div>
            ))}
          </motion.div>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
      )}
    </div>
  );
}

/**
 * Rich Swiggy-detail dialog. Showcase component: hero image, honest rating,
 * an AI "why this dish?" section, and a swap-alternatives row.
 */
export function DishDetailModal({
  slot,
  open,
  onOpenChange,
  onSwap,
}: DishDetailModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "max-h-[90vh] gap-0 overflow-y-auto p-0 sm:max-w-lg"
        )}
      >
        <AnimatePresence mode="wait">
          {slot && (
            <DishDetailBody
              key={slot.id}
              slot={slot}
              onSwap={onSwap}
            />
          )}
        </AnimatePresence>
      </DialogContent>
    </Dialog>
  );
}

/** Inner body split out so entrance animation keys on slot identity. */
function DishDetailBody({
  slot,
  onSwap,
}: {
  slot: MealSlot;
  onSwap?: (alt: DishAlternative) => void;
}) {
  const meal = mealStyle(slot.meal_type);
  const status = statusStyle(slot.status);
  const veg = inferVeg(slot.dish_name);
  const hasImage = Boolean(slot.image_url && slot.image_url.trim());
  const [heroFailed, setHeroFailed] = React.useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
    >
      {/* Hero */}
      <div className="relative h-44 w-full overflow-hidden sm:h-52">
        {hasImage && !heroFailed ? (
          <Image
            src={slot.image_url as string}
            alt={slot.dish_name}
            fill
            sizes="(max-width: 640px) 100vw, 512px"
            className="object-cover"
            unoptimized
            onError={() => setHeroFailed(true)}
            priority
          />
        ) : (
          <div className="flex size-full items-center justify-center bg-gradient-mesh">
            <span className="flex size-16 items-center justify-center rounded-2xl bg-gradient-brand text-2xl font-bold text-primary-foreground shadow-glow">
              {dishInitials(slot.dish_name)}
            </span>
          </div>
        )}
        {/* Bottom scrim for legibility of overlaid chips */}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-background/85 via-background/10 to-transparent" />

        {/* Meal-type + status chips */}
        <div className="absolute bottom-3 left-4 flex items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
              meal.soft,
              meal.text,
              "ring-1 ring-inset",
              meal.border
            )}
          >
            <Utensils className="size-3" />
            {meal.label}
          </span>
          <span className={cn("px-2 py-0.5 text-xs font-medium", status.badge)}>
            {status.label}
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-col gap-5 p-5">
        <div className="flex flex-col gap-2">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <DialogTitle className="font-display text-xl leading-tight text-foreground">
                {slot.dish_name}
              </DialogTitle>
              {slot.restaurant_name && (
                <DialogDescription className="mt-0.5 text-sm">
                  {slot.restaurant_name}
                </DialogDescription>
              )}
            </div>
            {typeof slot.rating === "number" && (
              <div className="flex shrink-0 flex-col items-end">
                <span
                  className={cn(
                    "inline-flex items-center gap-1 font-mono text-lg font-bold",
                    ratingColor(slot.rating)
                  )}
                >
                  <Star className="size-4 fill-current" />
                  {slot.rating.toFixed(1)}
                </span>
                <span className="text-[0.65rem] text-muted-foreground">
                  based on ratings
                </span>
              </div>
            )}
          </div>

          {/* Price + variant + veg indicator */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="font-mono text-lg font-bold text-foreground">
              {formatINR(slot.price)}
            </span>
            {slot.variant && (
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                {slot.variant}
              </span>
            )}
            <span className="ml-auto">
              <VegIndicator veg={veg} />
            </span>
          </div>

          {/* Accompaniment — the bread/rice that completes a curry. Shown here
              too so the modal's figure matches what the wallet is charged. */}
          {slot.side_dish_name && (
            <div className="rounded-xl border border-dashed border-border/70 bg-muted/30 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm text-foreground">
                  + {slot.side_dish_name}
                  {(slot.side_qty ?? 0) > 1 && (
                    <span className="ml-1 text-muted-foreground">
                      ×{slot.side_qty}
                    </span>
                  )}
                </span>
                <span className="shrink-0 font-mono text-sm text-muted-foreground">
                  {formatINR(slot.side_price ?? 0)}
                </span>
              </div>
              <div className="mt-1.5 flex items-center justify-between border-t border-border/60 pt-1.5">
                <span className="text-[0.65rem] font-medium uppercase tracking-wide text-muted-foreground">
                  Meal total
                </span>
                <span className="font-mono text-base font-bold text-accent-brand">
                  {formatINR(slotTotal(slot))}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Why this dish? */}
        <WhySection slotId={slot.id} />

        {/* Swap this meal */}
        <SwapSection slotId={slot.id} onSwap={onSwap} />
      </div>
    </motion.div>
  );
}

export default DishDetailModal;
