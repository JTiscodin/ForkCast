"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CircleCheckBig,
  LoaderCircle,
  PiggyBank,
  Wallet,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { focusRing } from "@/lib/design";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import type { PlanSummary, WalletSummary } from "@/lib/types";

import { formatINR, pct } from "./wallet-helpers";

export interface WalletBarProps {
  /** The wallet summary for the active cycle, or null when none exists yet. */
  wallet: WalletSummary | null;
  /** The generated plan summary, or null. */
  plan: PlanSummary | null;
  /** In-flight approve request. */
  approving?: boolean;
  /** Plan has been approved & activated. */
  approved?: boolean;
  /** Fired when the user hits the primary CTA. */
  onApprove: () => void;
  /** Show the skeleton loading state (wallet/plan being fetched). */
  loading?: boolean;
  className?: string;
}

/* -------------------------------------------------------------------------
 * Small labeled mono figure — a compact vertical stat used across the strip.
 * ------------------------------------------------------------------------- */
function Figure({
  label,
  value,
  tone = "default",
  emphasis,
}: {
  label: string;
  value: string;
  tone?: "default" | "success" | "warning";
  emphasis?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col leading-tight">
      <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          "font-mono tabular-nums leading-tight",
          emphasis ? "text-base font-semibold" : "text-sm font-medium",
          tone === "success" && "text-success",
          tone === "warning" && "text-warning",
          tone === "default" && !emphasis && "text-foreground",
          tone === "default" && emphasis && "text-gradient-brand"
        )}
      >
        {value}
      </span>
    </div>
  );
}

/** Slim inline spent/budget progress bar. */
function SpendBar({ spent, budget }: { spent: number; budget: number }) {
  const filled = pct(spent, budget);
  const over = spent > budget && budget > 0;
  return (
    <div
      className="h-1.5 w-24 overflow-hidden rounded-full bg-border/70"
      role="progressbar"
      aria-valuenow={Math.round(filled)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Spent of budget"
    >
      <motion.div
        className={cn(
          "h-full rounded-full",
          over ? "bg-warning" : "bg-gradient-brand"
        )}
        initial={false}
        animate={{ width: `${filled}%` }}
        transition={{ type: "spring", stiffness: 90, damping: 20, mass: 0.8 }}
      />
    </div>
  );
}

/** A single constraint chip: "paneer 45/10 ✓" or "paneer 6/10 ✗". */
function ConstraintChip({
  tag,
  got,
  needed,
}: {
  tag: string;
  got: number;
  needed: number;
}) {
  const met = got >= needed;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        met
          ? "border-success/25 bg-success/12 text-success"
          : "border-danger/25 bg-danger/12 text-danger"
      )}
    >
      <span className="capitalize">{tag}</span>
      <span className="font-mono tabular-nums opacity-90">
        {got}/{needed}
      </span>
      {met ? (
        <Check className="size-3" aria-hidden />
      ) : (
        <AlertTriangle className="size-3" aria-hidden />
      )}
    </span>
  );
}

/**
 * Compact, sticky wallet + approve strip. A single horizontal bar combining a
 * condensed wallet readout, plan constraint status, and the approve CTA.
 * Meant to sit sticky at the top of the plan pane.
 */
export function WalletBar({
  wallet,
  plan,
  approving,
  approved,
  onApprove,
  loading,
  className,
}: WalletBarProps) {
  if (loading) {
    return (
      <div
        className={cn(
          "glass-panel flex items-center gap-4 rounded-2xl px-5 py-3.5 shadow-soft backdrop-blur-md",
          className
        )}
      >
        <Skeleton className="size-9 rounded-xl" />
        <div className="space-y-1.5">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-4 w-24" />
        </div>
        <Skeleton className="ml-auto h-10 w-36 rounded-xl" />
      </div>
    );
  }

  // Nothing to show when neither a wallet nor a plan exists.
  if (!wallet && !plan) return null;

  const infeasible = plan ? !plan.feasible || plan.leftover < 0 : false;
  const shortfall = plan && plan.leftover < 0 ? Math.abs(plan.leftover) : 0;
  const constraints = plan ? Object.entries(plan.constraint_status ?? {}) : [];

  // The chip is a fixed-height inline element, so it gets a SHORT status only.
  // Stuffing the optimizer's full sentence in here is what made this bar wrap to
  // three lines and knock the whole row out of alignment; the full explanation
  // now lives in the FeasibilityPanel below the stat tiles, which has room.
  const statusText = infeasible
    ? shortfall > 0
      ? `Over by ${formatINR(shortfall)}`
      : "Over budget"
    : "Fits budget";

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className={cn(
        // items-center + nowrap on desktop keeps every cluster on one baseline.
        // The chip no longer carries a full sentence, so nothing forces a wrap.
        "glass-panel flex min-h-16 flex-wrap items-center gap-x-5 gap-y-3 rounded-2xl px-5 py-3 shadow-soft backdrop-blur-md sm:flex-nowrap sm:px-6",
        infeasible && !approved && "ring-1 ring-warning/25",
        className
      )}
    >
      {/* LEFT — wallet cluster (or pre-approval plan preview) */}
      <div className="flex min-w-0 shrink-0 items-center gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center self-center rounded-xl border border-brand-500/25 bg-accent text-accent-brand">
          <Wallet className="size-4.5" aria-hidden />
        </div>

        {wallet ? (
          // items-baseline so Balance (larger) and Spent (smaller) sit on the
          // same text baseline instead of being centred against each other,
          // which is what made this cluster look tilted.
          <div className="flex items-baseline gap-4">
            <Figure
              label="Balance"
              value={formatINR(wallet.balance)}
              emphasis
            />

            <div className="hidden items-baseline gap-4 sm:flex">
              <Figure label="Spent" value={formatINR(wallet.total_spent)} />
              <div className="self-center">
                <SpendBar
                  spent={wallet.total_spent}
                  budget={wallet.budget_allocated}
                />
              </div>
            </div>

            {wallet.rolled_in > 0 && (
              <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-brand-500/25 bg-amber-400/10 px-2.5 py-0.5 font-mono text-xs font-semibold tabular-nums text-amber-400">
                <PiggyBank className="size-3.5" aria-hidden />
                {formatINR(wallet.rolled_in)}
              </span>
            )}
          </div>
        ) : (
          plan && (
            <div className="flex items-baseline gap-4">
              <Figure
                label="Budget"
                value={formatINR(plan.budget)}
                emphasis
              />
              <div className="hidden sm:block">
                <Figure label="Planned" value={formatINR(plan.total_cost)} />
              </div>
              <Figure
                label={plan.leftover < 0 ? "Over" : "Leftover"}
                value={formatINR(Math.abs(plan.leftover))}
                tone={plan.leftover < 0 ? "warning" : "success"}
              />
            </div>
          )
        )}
      </div>

      {/* MIDDLE — constraint + feasibility chips (only when a plan exists) */}
      {plan && (
        <>
          <Separator
            orientation="vertical"
            className="hidden h-8! shrink-0 bg-border/60! sm:block"
          />

          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
            <span
              className={cn(
                "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium",
                infeasible
                  ? "border-warning/30 bg-warning/12 text-warning"
                  : "border-success/25 bg-success/12 text-success",
              )}
              title={plan.message?.trim() || undefined}
            >
              {infeasible ? (
                <AlertTriangle className="size-3.5" aria-hidden />
              ) : (
                <CircleCheckBig className="size-3.5" aria-hidden />
              )}
              {statusText}
            </span>

            {constraints.map(([tag, s]) => (
              <ConstraintChip
                key={tag}
                tag={tag}
                got={s?.got ?? 0}
                needed={s?.needed ?? 0}
              />
            ))}
          </div>
        </>
      )}

      {/* RIGHT — CTA / success morph. Only relevant when a plan exists. */}
      {plan && (
        <div className="flex shrink-0 items-center sm:ml-auto">
          <AnimatePresence mode="wait" initial={false}>
            {approved ? (
              <motion.div
                key="approved"
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
                transition={{ type: "spring", stiffness: 300, damping: 22 }}
                className="inline-flex h-10 items-center gap-2 rounded-xl border border-success/25 bg-success/12 px-4 text-sm font-medium text-success"
              >
                <CircleCheckBig className="size-4.5" aria-hidden />
                Plan active
                <Check className="size-4" aria-hidden />
              </motion.div>
            ) : (
              <motion.button
                key="cta"
                type="button"
                onClick={onApprove}
                disabled={approving}
                whileHover={approving ? undefined : { scale: 1.02 }}
                whileTap={approving ? undefined : { scale: 0.98 }}
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                transition={{ type: "spring", stiffness: 300, damping: 22 }}
                className={cn(
                  "group inline-flex h-10 items-center justify-center gap-2 rounded-xl px-5",
                  "text-sm font-semibold text-white shadow-glow",
                  "bg-gradient-brand",
                  "transition-opacity disabled:cursor-not-allowed disabled:opacity-70",
                  infeasible &&
                    "ring-2 ring-warning/40 ring-offset-2 ring-offset-background",
                  focusRing
                )}
                aria-busy={approving || undefined}
              >
                {approving ? (
                  <>
                    <LoaderCircle
                      className="size-4.5 animate-spin"
                      aria-hidden
                    />
                    Activating…
                  </>
                ) : (
                  <>
                    {infeasible ? "Approve anyway" : "Approve & activate"}
                    <ArrowRight
                      className="size-4.5 transition-transform group-hover:translate-x-0.5"
                      aria-hidden
                    />
                  </>
                )}
              </motion.button>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  );
}

export default WalletBar;
