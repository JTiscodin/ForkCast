"use client";

import { useMemo, type ReactNode } from "react";
import { motion } from "framer-motion";
import {
  Wallet,
  UtensilsCrossed,
  Leaf,
  Star,
  Store,
  CheckCircle2,
  AlertTriangle,
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
        "flex min-w-[10.5rem] flex-1 flex-col gap-2 rounded-2xl p-4",
        "glass-panel shadow-soft",
      )}
    >
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-flex size-7 items-center justify-center rounded-lg bg-surface-elevated",
            accent ?? "text-accent-brand",
          )}
        >
          {icon}
        </span>
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="font-mono text-2xl font-semibold text-foreground">
          {value}
        </span>
        {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
      </div>
      {children}
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

  // A short form of the plan's message for the warning chip.
  const shortMessage = useMemo(() => {
    const msg = plan?.message?.trim();
    if (!msg) return "Over budget";
    const firstSentence = msg.split(/[.\n]/)[0].trim();
    return firstSentence.length > 48
      ? `${firstSentence.slice(0, 45)}…`
      : firstSentence;
  }, [plan?.message]);

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
        sub={budget > 0 ? `of ${formatINR(budget)}` : undefined}
      >
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
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

      {/* Feasibility chip */}
      <motion.div
        variants={{
          hidden: { opacity: 0, y: 14 },
          show: { opacity: 1, y: 0 },
        }}
        className={cn(
          "flex min-w-[10.5rem] flex-1 flex-col justify-center gap-2 rounded-2xl p-4 shadow-soft",
          feasible
            ? "bg-success/12 ring-1 ring-inset ring-success/25"
            : "bg-warning/12 ring-1 ring-inset ring-warning/25",
        )}
      >
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Feasibility
        </span>
        <div className="flex items-center gap-2">
          {feasible ? (
            <CheckCircle2 className="size-5 shrink-0 text-success" />
          ) : (
            <AlertTriangle className="size-5 shrink-0 text-warning" />
          )}
          <span
            className={cn(
              "text-sm font-semibold leading-tight",
              feasible ? "text-success" : "text-warning",
            )}
          >
            {feasible ? "Fits budget" : shortMessage}
          </span>
        </div>
      </motion.div>
    </motion.div>
  );
}

export default PlanSummaryStrip;
