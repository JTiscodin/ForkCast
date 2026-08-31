"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Check,
  CircleCheck,
  LoaderCircle,
  TriangleAlert,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { PlanSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { LottiePlayer, usePrefersReducedMotion } from "@/components/ui/LottiePlayer";

import { ConstraintChip } from "./ConstraintChip";
import { formatINR } from "./wallet-helpers";

/* The approve CTA keeps its spring entrance/hover/tap beats, but base styling
   (flat brand-500, focus ring, h-11 via size="lg") comes from the shared
   Button component so it matches WalletBar's CTA height. */
const MotionButton = motion.create(Button);

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

export function ApproveBar({
  plan,
  approving,
  approved,
  onApprove,
  className,
}: ApproveBarProps) {
  // Celebratory burst: purely presentational — plays once (~1.6s) when the
  // plan transitions to approved, as an overlay that never blocks clicks.
  const reducedMotion = usePrefersReducedMotion();
  const [celebrating, setCelebrating] = React.useState(false);
  const wasApprovedRef = React.useRef(false);
  React.useEffect(() => {
    const becameApproved = Boolean(approved) && !wasApprovedRef.current;
    wasApprovedRef.current = Boolean(approved);
    if (!becameApproved || reducedMotion) return;
    setCelebrating(true);
    const t = window.setTimeout(() => setCelebrating(false), 1600);
    return () => window.clearTimeout(t);
  }, [approved, reducedMotion]);

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
      {/* Success confetti — overlay only: no pointer events, no layout shift. */}
      {celebrating && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 z-[1] flex justify-center"
        >
          <LottiePlayer
            path="/animations/confetti-burst.json"
            loop={false}
            className="h-36 w-36 -translate-y-1/3"
          />
        </div>
      )}
      <motion.div
        initial={{ y: 24, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 26 }}
        className={cn(
          "mx-auto flex max-w-4xl flex-col gap-4 rounded-lg border border-border bg-card p-4 text-card-foreground shadow-soft sm:flex-row sm:items-center sm:gap-6",
          infeasible && !approved && "ring-1 ring-danger/30"
        )}
      >
        {/* Left: numbers + feasibility */}
        <div className="min-w-0 flex-1 space-y-2.5">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <div className="flex items-baseline gap-1.5">
              <span className="text-sm uppercase tracking-wide text-muted-foreground">
                Total
              </span>
              <span className="text-lg font-bold leading-[1.4] tabular-nums text-foreground">
                {formatINR(plan.total_cost)}
              </span>
              <span className="text-sm text-muted-foreground">
                / {formatINR(plan.budget)}
              </span>
            </div>

            <div className="flex items-baseline gap-1.5">
              <span className="text-sm uppercase tracking-wide text-muted-foreground">
                {plan.leftover < 0 ? "Over by" : "Leftover"}
              </span>
              <span
                className={cn(
                  "text-sm font-bold leading-[1.4] tabular-nums",
                  plan.leftover < 0 ? "text-danger" : "text-success"
                )}
              >
                {formatINR(Math.abs(plan.leftover))}
              </span>
            </div>

            {/* Feasibility chip */}
            {infeasible ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-danger/25 bg-danger/10 px-2.5 py-0.5 text-sm font-medium text-danger">
                <TriangleAlert className="size-4" strokeWidth={2.4} aria-hidden />
                {plan.message?.trim() ||
                  (shortfall > 0
                    ? `Over by ${formatINR(shortfall)}`
                    : "Over budget")}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-success/25 bg-success/10 px-2.5 py-0.5 text-sm font-medium text-success">
                <CircleCheck className="size-4" strokeWidth={2.4} aria-hidden />
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
                className="inline-flex h-11 items-center gap-2 rounded-lg border border-success/25 bg-success/10 px-5 text-sm font-medium text-success"
              >
                <CircleCheck className="size-5" strokeWidth={2.4} aria-hidden />
                Plan active
                <Check className="size-4" strokeWidth={2.4} aria-hidden />
              </motion.div>
            ) : (
              <MotionButton
                key="cta"
                onClick={onApprove}
                disabled={approving}
                size="lg"
                whileHover={approving ? undefined : { scale: 1.02 }}
                whileTap={approving ? undefined : { scale: 0.98 }}
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                transition={{ type: "spring", stiffness: 300, damping: 22 }}
                className={cn(
                  "group w-full px-6",
                  infeasible && "ring-2 ring-danger/40 ring-offset-2 ring-offset-background",
                  "sm:w-auto"
                )}
                aria-busy={approving || undefined}
              >
                {approving ? (
                  <>
                    <LoaderCircle className="size-5 animate-spin" strokeWidth={2.4} aria-hidden />
                    Activating…
                  </>
                ) : (
                  <>
                    {infeasible ? "Approve anyway" : "Approve & activate"}
                    <ArrowRight
                      strokeWidth={2.4}
                      className="size-4 transition-transform group-hover:translate-x-0.5"
                      aria-hidden
                    />
                  </>
                )}
              </MotionButton>
            )}
          </AnimatePresence>
        </div>
      </motion.div>
    </div>
  );
}

export default ApproveBar;
