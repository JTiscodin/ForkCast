"use client";

import { useMemo, type ReactNode } from "react";
import { motion } from "framer-motion";
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
 * A single premium stat tile.
 * ------------------------------------------------------------------------- */
function StatTile({
  icon,
  label,
  value,
  sub,
  accent,
  children,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent?: string;
  children?: ReactNode;
}) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 14 },
        show: { opacity: 1, y: 0 },
      }}
      className={cn(
        // Tiles share a fixed height so the row has one clean baseline even
        // when only one of them carries a progress bar underneath.
        "flex min-h-28 min-w-44 flex-1 flex-col gap-2 rounded-2xl p-4",
        "glass-panel shadow-soft",
      )}
    >
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-flex size-7 shrink-0 items-center justify-center rounded-lg bg-surface-elevated",
            accent ?? "text-accent-brand",
          )}
        >
          {icon}
        </span>
        <span className="truncate text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
      </div>

      {/* Value + sub. A long figure like "₹18,159" plus "of ₹10,000" could not
          fit on one line, so the sub-label wrapped underneath and pushed the
          progress bar out of the tile. The sub now sits on its own line with
          the value clamped to a size that always fits. */}
      <div className="flex min-w-0 flex-col">
        <span className="truncate font-mono text-xl font-semibold leading-tight text-foreground">
          {value}
        </span>
        {sub && (
          <span className="truncate text-[11px] leading-tight text-muted-foreground">
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
 * PlanSummaryStrip — an at-a-glance row of premium stat tiles derived from the
 * plan + slots. Sits above the WeekCalendar so the detailed grid isn't the
 * first thing a user confronts. Scrolls horizontally on narrow widths.
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

  return (
    <motion.div
      variants={{
        hidden: {},
        show: { transition: { staggerChildren: 0.06 } },
      }}
      initial="hidden"
      animate="show"
      className={cn(
        "flex gap-3 overflow-x-auto pb-1 [scrollbar-width:thin] sm:flex-wrap sm:overflow-visible",
        className,
      )}
    >
      {/* Budget vs spend, with slim progress bar */}
      <StatTile
        icon={<Wallet className="size-4" />}
        label="Planned"
        value={formatINR(spent)}
        sub={
          budget > 0
            ? feasible
              ? `of ${formatINR(budget)}`
              : // Say how far over, not just what the budget was — a bar capped
                // at 100% makes 181% look identical to exactly-full.
                `of ${formatINR(budget)} · ${Math.round((spent / budget) * 100)}%`
            : undefined
        }
      >
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <motion.div
            className={cn(
              "h-full rounded-full",
              feasible ? "bg-gradient-brand" : "bg-danger",
            )}
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.6, ease: "easeOut" }}
          />
        </div>
      </StatTile>

      {/* Meals planned */}
      <StatTile
        icon={<UtensilsCrossed className="size-4" />}
        label="Meals"
        value={String(stats.meals)}
        sub="planned"
      />

      {/* Veg percentage */}
      <StatTile
        icon={<Leaf className="size-4" />}
        label="Veg"
        value={`${stats.vegPct}%`}
        sub="vegetarian"
        accent="text-success"
      />

      {/* Average rating */}
      <StatTile
        icon={<Star className="size-4 fill-amber-400 text-amber-400" />}
        label="Avg rating"
        value={stats.avgRating > 0 ? stats.avgRating.toFixed(1) : "—"}
        sub={stats.avgRating > 0 ? "of 5.0" : undefined}
      />

      {/* Distinct restaurants */}
      <StatTile
        icon={<Store className="size-4" />}
        label="Restaurants"
        value={String(stats.restaurants)}
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
