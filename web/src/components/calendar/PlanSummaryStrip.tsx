"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { animate, motion, useReducedMotion } from "framer-motion";
import {
  Wallet,
  UtensilsCrossed,
  Leaf,
  Star,
  Store,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { MealSlot, PlanSummary } from "@/lib/types";

import { formatINR } from "./calendar-helpers";
import { planStats } from "./week-helpers";

export interface PlanSummaryStripProps {
  /** Plan feasibility + budget summary (null while loading / before planning). */
  plan: PlanSummary | null;
  /** All planned meal slots (drives the derived stats). */
  slots: MealSlot[];
  className?: string;
}

/* -------------------------------------------------------------------------
 * CountUp — tweened numeric readout for the big tabular figures.
 *
 * The animation runs on the RAW number; the SAME formatter used for a static
 * render is applied at every frame, so the ₹ prefix, Indian grouping, and
 * integer formatting come out identical mid-flight. First mount counts up
 * from zero (fast, ~400ms) so a fresh plan feels alive; later changes ease
 * from the previous value over ~500ms — new plan generated, fix applied.
 * prefers-reduced-motion skips the tween entirely and shows the final value.
 * ------------------------------------------------------------------------- */

/** Integer figure formatters — intermediates are rounded so counts never
 *  flash decimals while tweening (endpoints match the static render). */
const formatInt = (n: number) => String(Math.round(n));
const formatPct = (n: number) => `${Math.round(n)}%`;
const formatRating = (n: number) => n.toFixed(1);

function CountUp({
  value,
  format,
}: {
  /** Raw number to animate toward. */
  value: number;
  /** Per-frame formatter — receives the interpolated raw number. */
  format: (n: number) => string;
}) {
  const reduceMotion = useReducedMotion();
  // Starts at zero so the very first paint is the bottom of the count-up;
  // reduced-motion users are snapped to the final value in the effect below.
  const [display, setDisplay] = useState(0);
  // Latest value actually painted — an interrupted animation resumes from
  // here rather than snapping back to its old start.
  const fromRef = useRef(0);
  const firstRunRef = useRef(true);

  useEffect(() => {
    const firstRun = firstRunRef.current;
    firstRunRef.current = false;
    // Non-finite values (NaN/undefined leaking through) can't be tweened —
    // snap so the formatter's own guards decide the output, exactly as the
    // static render did.
    if (!Number.isFinite(value)) {
      fromRef.current = 0;
      setDisplay(value);
      return;
    }
    if (reduceMotion) {
      fromRef.current = value;
      setDisplay(value);
      return;
    }
    const controls = animate(fromRef.current, value, {
      duration: firstRun ? 0.4 : 0.5,
      ease: "easeOut",
      onUpdate: (v) => {
        fromRef.current = v;
        setDisplay(v);
      },
    });
    return () => controls.stop();
  }, [value, reduceMotion]);

  return <>{format(display)}</>;
}

/* -------------------------------------------------------------------------
 * One stat cell of the summary card — no border or shadow of its own; the
 * parent strip owns the white surface, hairline dividers, and elevation.
 * ------------------------------------------------------------------------- */
function StatTile({
  icon,
  label,
  value,
  sub,
  accent,
  highlight = false,
  danger = false,
  children,
}: {
  icon: ReactNode;
  label: string;
  /** Big figure line — a CountUp tween (or plain text for the dash case). */
  value: ReactNode;
  sub?: ReactNode;
  accent?: string;
  highlight?: boolean;
  /** Over-budget state — tints this cell with the danger palette. */
  danger?: boolean;
  children?: ReactNode;
}) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 14 },
        show: { opacity: 1, y: 0 },
      }}
      className={cn(
        // Cells share a fixed height so the row has one clean baseline even
        // when only one of them carries a progress bar underneath.
        "flex min-h-28 min-w-44 flex-1 flex-col gap-2 p-4 sm:p-5",
        danger && "bg-danger/10",
      )}
    >
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-flex size-7 shrink-0 items-center justify-center rounded-lg",
            highlight && !danger
              ? "bg-brand-50 text-brand-700"
              : danger
                ? "bg-danger/15 text-danger"
                : cn("bg-muted", accent ?? "text-muted-foreground"),
          )}
        >
          {icon}
        </span>
        <span className="truncate text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
      </div>

      {/* Value + sub. A long figure like "₹18,159" plus "of ₹10,000" could not
          fit on one line, so the sub-label wrapped underneath and pushed the
          progress bar out of the tile. The sub now sits on its own line with
          the value clamped to a size that always fits. */}
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-2xl font-extrabold leading-tight tracking-[-0.02em] tabular-nums text-foreground">
          {value}
        </span>
        {sub && (
          <span
            className={cn(
              "truncate text-xs leading-[1.4]",
              danger ? "font-bold text-danger" : "text-muted-foreground",
            )}
          >
            {sub}
          </span>
        )}
      </div>

      {/* Bar (when present) pinned to the bottom so all tiles align. */}
      {children && <div className="mt-auto pt-1">{children}</div>}
    </motion.div>
  );
}

/**
 * PlanSummaryStrip — one flat white summary card of big-number stat cells,
 * split by thin vertical hairlines, derived from the plan + slots. Sits above
 * the WeekCalendar so the detailed grid isn't the first thing a user
 * confronts. Scrolls horizontally on narrow widths.
 */
export function PlanSummaryStrip({
  plan,
  slots,
  className,
}: PlanSummaryStripProps) {
  const stats = useMemo(() => planStats(slots), [slots]);

  const budget = plan?.budget ?? 0;
  const spent = plan?.total_cost ?? stats.total;
  const pct = budget > 0 ? Math.min(100, Math.round((spent / budget) * 100)) : 0;
  const feasible = plan?.feasible ?? spent <= budget;
  const overBudget = budget > 0 && !feasible;

  return (
    <motion.div
      variants={{
        hidden: {},
        show: { transition: { staggerChildren: 0.06 } },
      }}
      initial="hidden"
      animate="show"
      className={cn(
        // A single flat white card; stat cells sit side by side separated by
        // thin vertical hairlines.
        "flex divide-x divide-border overflow-x-auto rounded-lg border border-border bg-card shadow-soft [scrollbar-width:thin] sm:flex-wrap sm:overflow-hidden",
        className,
      )}
    >
      {/* Budget vs spend, with slim progress bar */}
      <StatTile
        icon={<Wallet className="size-4" strokeWidth={2.4} />}
        label="Planned"
        highlight
        danger={overBudget}
        value={<CountUp value={spent} format={formatINR} />}
        sub={
          budget > 0 ? (
            feasible ? (
              <>
                of <CountUp value={budget} format={formatINR} />
              </>
            ) : (
              // Say how far over, not just what the budget was — a bar capped
              // at 100% makes 181% look identical to exactly-full.
              <>
                of <CountUp value={budget} format={formatINR} /> ·{" "}
                {Math.round((spent / budget) * 100)}%
              </>
            )
          ) : undefined
        }
      >
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <motion.div
            className={cn(
              "h-full rounded-full",
              feasible ? "bg-success" : "bg-danger",
            )}
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.6, ease: "easeOut" }}
          />
        </div>
      </StatTile>

      {/* Meals planned */}
      <StatTile
        icon={<UtensilsCrossed className="size-4" strokeWidth={2.4} />}
        label="Meals"
        value={<CountUp value={stats.meals} format={formatInt} />}
        sub="planned"
      />

      {/* Veg percentage */}
      <StatTile
        icon={<Leaf className="size-4" strokeWidth={2.4} />}
        label="Veg"
        value={<CountUp value={stats.vegPct} format={formatPct} />}
        sub="vegetarian"
        accent="text-success"
      />

      {/* Average rating — the dash guard stays outside the tween, exactly
          as the static render had it. */}
      <StatTile
        icon={<Star className="size-4 fill-rating text-rating" strokeWidth={2.4} />}
        label="Avg rating"
        value={
          stats.avgRating > 0 ? (
            <CountUp value={stats.avgRating} format={formatRating} />
          ) : (
            "N/A"
          )
        }
        sub={stats.avgRating > 0 ? "of 5.0" : undefined}
      />

      {/* Distinct restaurants */}
      <StatTile
        icon={<Store className="size-4" strokeWidth={2.4} />}
        label="Restaurants"
        value={<CountUp value={stats.restaurants} format={formatInt} />}
        sub="distinct"
      />

      {/* No feasibility tile here — it duplicated the WalletBar chip AND the
          FeasibilityPanel below, and its truncated message ("Plan needs Rs
          8159") stated the problem without the explanation or the fix. The
          FeasibilityPanel now owns that story in full. */}
    </motion.div>
  );
}

export default PlanSummaryStrip;
