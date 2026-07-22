"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CircleCheckBig,
  LoaderCircle,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { focusRing } from "@/lib/design";
import type { PlanSummary } from "@/lib/types";

import { formatINR } from "./wallet-helpers";

export interface ApproveBarProps {
  /** The generated plan summary, or null (bar renders nothing). */
  plan: PlanSummary | null;
  /** In-flight approve request. */
  approving?: boolean;
  /** Plan has been approved & activated. */
  approved?: boolean;
  /** Fired when the user hits the primary CTA. */
  onApprove: () => void;
  className?: string;
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
          : "border-warning/30 bg-warning/12 text-warning"
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

export function ApproveBar({
  plan,
  approving,
  approved,
  onApprove,
  className,
}: ApproveBarProps) {
  if (!plan) return null;

  const shortfall = plan.leftover < 0 ? Math.abs(plan.leftover) : 0;
  const infeasible = !plan.feasible || plan.leftover < 0;
  const constraints = Object.entries(plan.constraint_status ?? {});

  return (
    <div
      className={cn(
        "fixed inset-x-0 bottom-0 z-50 px-4 pb-4 sm:px-6",
        className
      )}
    >
      <motion.div
        initial={{ y: 24, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 26 }}
        className={cn(
          "glass-panel mx-auto flex max-w-4xl flex-col gap-4 rounded-2xl p-4 shadow-layered sm:flex-row sm:items-center sm:gap-6",
          infeasible && !approved && "ring-1 ring-warning/30"
        )}
      >
        {/* Left: numbers + feasibility */}
        <div className="min-w-0 flex-1 space-y-2.5">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <div className="flex items-baseline gap-1.5">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                Total
              </span>
              <span className="font-mono text-lg font-semibold tabular-nums text-foreground">
                {formatINR(plan.total_cost)}
              </span>
              <span className="text-xs text-muted-foreground">
                / {formatINR(plan.budget)}
              </span>
            </div>

            <div className="flex items-baseline gap-1.5">
              <span className="text-xs uppercase tracking-wide text-muted-foreground">
                {plan.leftover < 0 ? "Over by" : "Leftover"}
              </span>
              <span
                className={cn(
                  "font-mono text-sm font-semibold tabular-nums",
                  plan.leftover < 0 ? "text-warning" : "text-success"
                )}
              >
                {formatINR(Math.abs(plan.leftover))}
              </span>
            </div>

            {/* Feasibility chip */}
            {infeasible ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-warning/30 bg-warning/12 px-2.5 py-0.5 text-xs font-medium text-warning">
                <AlertTriangle className="size-3.5" aria-hidden />
                {plan.message?.trim() ||
                  (shortfall > 0
                    ? `Over by ${formatINR(shortfall)}`
                    : "Over budget")}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-success/25 bg-success/12 px-2.5 py-0.5 text-xs font-medium text-success">
                <CircleCheckBig className="size-3.5" aria-hidden />
                Fits your budget
              </span>
            )}
          </div>

          {/* Constraint chips */}
          {constraints.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              {constraints.map(([tag, s]) => (
                <ConstraintChip
                  key={tag}
                  tag={tag}
                  got={s?.got ?? 0}
                  needed={s?.needed ?? 0}
                />
              ))}
            </div>
          )}
        </div>

        {/* Right: CTA / success morph */}
        <div className="flex shrink-0 items-center sm:justify-end">
          <AnimatePresence mode="wait" initial={false}>
            {approved ? (
              <motion.div
                key="approved"
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
                transition={{ type: "spring", stiffness: 300, damping: 22 }}
                className="inline-flex h-11 items-center gap-2 rounded-xl border border-success/25 bg-success/12 px-5 font-medium text-success"
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
                  "group inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl px-6",
                  "text-sm font-semibold text-white shadow-glow",
                  "bg-gradient-brand",
                  "transition-opacity disabled:cursor-not-allowed disabled:opacity-70",
                  infeasible && "ring-2 ring-warning/40 ring-offset-2 ring-offset-background",
                  focusRing,
                  "sm:w-auto"
                )}
                aria-busy={approving || undefined}
              >
                {approving ? (
                  <>
                    <LoaderCircle className="size-4.5 animate-spin" aria-hidden />
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
      </motion.div>
    </div>
  );
}

export default ApproveBar;
