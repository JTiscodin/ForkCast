"use client";

import * as React from "react";
import Image from "next/image";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, ArrowLeftRight, UtensilsCrossed, Star } from "lucide-react";

import { cn } from "@/lib/utils";
import { mealStyle, statusStyle, focusRing } from "@/lib/design";
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
import { SwapBeat } from "@/components/ui/SwapBeat";
import { inferVeg, dishInitials, formatINR } from "./dish-helpers";

export interface DishDetailModalProps {
  slot: MealSlot | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSwap?: (alt: DishAlternative) => void;
  /** Swap request for this slot is in flight — shows the inline beat. */
  swapping?: boolean;
  /** Blueprint veg preference — filters swap alternatives to veg-only. */
  vegOnly?: boolean;
}

/**
 * FSSAI veg/non-veg mark — the classic square-and-dot stamp Swiggy prints
 * beside every dish name (green = veg, brown-red = non-veg). Token-colored.
 * Kept inline here (mirrors DishCard) rather than in a shared file.
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

/** Veg / non-veg indicator — FSSAI square mark plus a small text label. */
function VegIndicator({ veg }: { veg: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
      <DietMarker veg={veg} />
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
    <div className="flex gap-3 border-b border-border pb-5">
      <span
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-500 text-primary-foreground"
        )}
      >
        <Sparkles className="size-5" strokeWidth={2.4} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="mb-1 font-heading text-sm font-extrabold uppercase tracking-[-0.02em] text-accent-brand">
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

/** One swap alternative as a clean menu row — name, price, orange SWAP chip. */
function AltRow({
  alt,
  onClick,
  disabled,
}: {
  alt: DishAlternative;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={disabled}
      whileTap={{ scale: disabled ? undefined : 0.99 }}
      transition={{ type: "spring", stiffness: 400, damping: 26 }}
      className={cn(
        "flex w-full items-center gap-3 bg-card px-4 py-3 text-left",
        disabled && "cursor-not-allowed opacity-60",
        focusRing
      )}
      title={alt.veg ? "Veg" : "Non-veg"}
    >
      <DietMarker veg={alt.veg} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-bold leading-[1.4] text-foreground">
          {alt.name}
        </span>
        <span className="block truncate text-xs leading-[1.4] text-muted-foreground">
          {alt.restaurant_name}
        </span>
      </span>
      <span className="shrink-0 text-sm font-bold leading-[1.4] tabular-nums text-foreground">
        {formatINR(alt.price)}
      </span>
      <span className="shrink-0 rounded border border-brand-500 bg-card px-3 py-1 text-xs font-bold uppercase tracking-wide text-brand-700 transition-colors hover:bg-brand-50">
        Swap
      </span>
    </motion.button>
  );
}

/** "Swap this meal" section — lazy loads alternatives on first click. */
function SwapSection({
  slotId,
  vegOnly,
  onSwap,
  swapping,
}: {
  slotId: number;
  vegOnly: boolean;
  onSwap?: (alt: DishAlternative) => void;
  /** Swap request in flight — beat strip replaces the list interaction. */
  swapping?: boolean;
}) {
  const [alts, setAlts] = React.useState<DishAlternative[] | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [failed, setFailed] = React.useState(false);

  const load = React.useCallback(() => {
    setLoading(true);
    setFailed(false);
    api
      .alternatives(slotId, { veg_only: vegOnly })
      .then((res) => {
        setAlts(res.alternatives);
        setLoading(false);
      })
      .catch(() => {
        setFailed(true);
        setLoading(false);
      });
  }, [slotId, vegOnly]);

  // Load alternatives as soon as the modal opens — they used to hide behind a
  // "Show alternatives" click, so most users never saw the swap option at all.
  React.useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 font-heading text-sm font-extrabold tracking-[-0.02em] text-foreground">
          <ArrowLeftRight className="size-4 text-accent-brand" strokeWidth={2.4} />
          Swap this meal
        </h3>
        {failed && (
          <Button size="sm" variant="outline" onClick={load}>
            Retry
          </Button>
        )}
      </div>

      {loading && (
        <div className="flex flex-col divide-y divide-border rounded-lg border border-border bg-card">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3 px-4 py-3">
              <Skeleton className="size-3.5 rounded-sm" />
              <div className="min-w-0 flex-1 space-y-1.5">
                <Skeleton className="h-3 w-3/4" />
                <Skeleton className="h-2.5 w-1/2" />
              </div>
              <Skeleton className="h-4 w-12" />
              <Skeleton className="h-6 w-14 rounded" />
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
        swapping ? (
          <div className="flex items-center gap-3 rounded-lg border border-brand-200 bg-brand-50 px-4 py-2.5">
            <SwapBeat active className="size-10 shrink-0" />
            <p className="min-w-0 text-sm font-medium text-muted-foreground">
              Swapping your meal…
            </p>
          </div>
        ) : (
        <motion.div
          initial="hidden"
          animate="show"
          variants={{
            hidden: {},
            show: { transition: { staggerChildren: 0.05 } },
          }}
          className="flex flex-col divide-y divide-border rounded-lg border border-border bg-card"
        >
          {alts.map((alt) => (
            <motion.div
              key={`${alt.dish_id}-${alt.restaurant_id}`}
              variants={{
                hidden: { opacity: 0, y: 8 },
                show: { opacity: 1, y: 0 },
              }}
            >
              <AltRow
                alt={alt}
                onClick={() => onSwap?.(alt)}
                disabled={swapping}
              />
            </motion.div>
          ))}
        </motion.div>
        )
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
  swapping,
  vegOnly,
}: DishDetailModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "max-h-[90vh] gap-0 overflow-y-auto rounded-lg border border-border bg-card p-0 shadow-layered sm:max-w-lg"
        )}
      >
        <AnimatePresence mode="wait">
          {slot && (
            <DishDetailBody
              key={slot.id}
              slot={slot}
              vegOnly={vegOnly ?? false}
              onSwap={onSwap}
              swapping={swapping}
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
  vegOnly,
  onSwap,
  swapping,
}: {
  slot: MealSlot;
  vegOnly: boolean;
  onSwap?: (alt: DishAlternative) => void;
  swapping?: boolean;
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
          <div className="flex size-full items-center justify-center bg-muted">
            <span className="flex size-16 items-center justify-center rounded-md bg-brand-500 text-2xl font-bold text-primary-foreground">
              {dishInitials(slot.dish_name)}
            </span>
          </div>
        )}
        {/* Bottom scrim for legibility of overlaid chips */}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-background/85 via-background/10 to-transparent" />

        {/* Meal-type + status chips */}
        <div className="absolute bottom-3 left-4 right-4 flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
              meal.soft,
              meal.text,
              "ring-1 ring-inset",
              meal.border
            )}
          >
            <UtensilsCrossed className="size-4" strokeWidth={2.4} />
            {meal.label}
          </span>
          <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", status.badge)}>
            {status.label}
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-col gap-5 p-5">
        <div className="flex flex-col gap-2 border-b border-border pb-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <DialogTitle className="flex items-center gap-2 font-heading text-xl font-extrabold leading-tight tracking-[-0.02em] text-foreground">
                <DietMarker veg={veg} />
                <span className="line-clamp-2">{slot.dish_name}</span>
              </DialogTitle>
              {slot.restaurant_name && (
                <DialogDescription className="mt-0.5 text-xs text-muted-foreground">
                  {slot.restaurant_name}
                </DialogDescription>
              )}
            </div>
            {/* Signature Swiggy rating pill — always solid green. */}
            {typeof slot.rating === "number" && (
              <div className="flex shrink-0 flex-col items-end gap-0.5">
                <span className="inline-flex items-center gap-0.5 rounded bg-rating px-1.5 py-0.5 text-xs font-bold leading-none text-white">
                  <Star className="size-2.5 fill-current" strokeWidth={2.4} aria-hidden />
                  {slot.rating.toFixed(1)}
                </span>
                <span className="text-xs text-muted-foreground">
                  based on ratings
                </span>
              </div>
            )}
          </div>

          {/* Price + variant + veg indicator */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="text-lg font-extrabold leading-[1.4] tabular-nums text-foreground">
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
            <div className="rounded-md border border-dashed border-border bg-card px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm text-foreground">
                  + {slot.side_dish_name}
                  {(slot.side_qty ?? 0) > 1 && (
                    <span className="ml-1 text-muted-foreground">
                      ×{slot.side_qty}
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-sm tabular-nums text-muted-foreground">
                  {formatINR(slot.side_price ?? 0)}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Why this dish? */}
        <WhySection slotId={slot.id} />

        {/* Swap this meal */}
        <SwapSection
          slotId={slot.id}
          vegOnly={vegOnly}
          onSwap={onSwap}
          swapping={swapping}
        />
      </div>

      {/* Sticky white footer — the figure the wallet actually gets charged,
          pinned to the bottom of the scrollable dialog. */}
      <div className="sticky bottom-0 z-10 mt-auto flex items-center justify-between gap-3 border-t border-border bg-card px-5 py-3">
        <span className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Meal total
        </span>
        <span className="text-base font-extrabold tabular-nums text-foreground">
          {formatINR(slotTotal(slot))}
        </span>
      </div>
    </motion.div>
  );
}

export default DishDetailModal;
