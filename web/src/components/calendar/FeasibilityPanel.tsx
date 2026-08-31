"use client";

import { motion } from "framer-motion";
import {
  ArrowRight,
  CircleCheck,
  IndianRupee,
  LoaderCircle,
  TriangleAlert,
  UtensilsCrossed,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { FeasibilityOption, FeasibilityReport } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { formatINR } from "./calendar-helpers";

/* Apply keeps its tap beat, but base styling (flat brand-500, focus ring)
   comes from the shared Button component. */
const MotionButton = motion.create(Button);

export interface FeasibilityPanelProps {
  report: FeasibilityReport | null;
  /** Apply one of the suggested fixes (re-plans with the changed settings). */
  onApply?: (option: FeasibilityOption) => void;
  /** An apply is in flight — disables the buttons. */
  applying?: boolean;
  className?: string;
}

/**
 * FeasibilityPanel — explains WHY a budget doesn't fit, in the user's own
 * terms, and offers concrete fixes with real numbers.
 *
 * Replaces a strip that said only "Plan needs Rs 8159" plus the optimizer's
 * generic "raise budget, reduce constraint count, or drop to a smaller portion
 * size". That told the user they had a problem without telling them what would
 * solve it — they had no way to know whether Rs 12,000 would work or whether
 * skipping dinner was enough. Every number here comes from re-running the
 * deterministic optimizer, so the options are guaranteed achievable, not
 * estimates.
 */
export function FeasibilityPanel({
  report,
  onApply,
  applying,
  className,
}: FeasibilityPanelProps) {
  if (!report) return null;

  // When the plan fits, this collapses to a single reassuring line.
  if (report.feasible) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className={cn(
          "flex items-center gap-2.5 rounded-lg border border-success/25 bg-card px-4 py-3 shadow-soft",
          className,
        )}
      >
        <CircleCheck className="size-4 shrink-0 text-success" strokeWidth={2.4} aria-hidden />
        <p className="text-sm text-foreground">{report.headline}</p>
      </motion.div>
    );
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-card shadow-soft",
        className,
      )}
      aria-live="polite"
    >
      {/* Explanation — Swiggy offer-banner family: brand-50 wash on a white card */}
      <div className="flex gap-3 border-b border-border bg-brand-50 px-4 py-3.5 sm:px-5">
        <TriangleAlert
          className="mt-0.5 size-5 shrink-0 text-brand-700"
          strokeWidth={2.4}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <h3 className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
            This budget won&apos;t stretch
          </h3>
          {/* The headline already names the city's real per-meal cost, the meal
              count, and the exact shortfall — no need to repeat any of it. */}
          <p className="mt-1 text-base font-extrabold leading-snug tracking-[-0.02em] text-foreground">
            {report.headline}
          </p>

          <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <UtensilsCrossed className="size-4" strokeWidth={2.4} aria-hidden />
              <span className="font-bold tabular-nums text-foreground">{report.current.slots}</span> meals
            </span>
            <span>
              ~
              <span className="font-bold tabular-nums text-foreground">
                {formatINR(report.current.per_meal)}
              </span>{" "}
              per meal locally
            </span>
            <span>
              Needs{" "}
              <span className="font-bold tabular-nums text-foreground">
                {formatINR(report.floor)}
              </span>{" "}
              minimum
            </span>
          </div>
        </div>
      </div>

      {/* Concrete fixes — the brand-50 header above already carries the
          divider (border-b), so no border-t here; two hairlines would stack
          into a doubled 2px line. */}
      {report.options.length > 0 && (
        <div className="px-4 py-3 sm:px-5">
          <p className="mb-2.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
            What would fit
          </p>
          <div className="flex flex-col gap-2">
            {report.options.map((opt, i) => (
              <OptionRow
                key={`${opt.kind}-${i}`}
                option={opt}
                onApply={onApply}
                applying={applying}
              />
            ))}
          </div>
          <p className="mt-2.5 text-xs text-muted-foreground">
            Pick one of these to make the plan fit. An over-budget plan
            can&apos;t be approved until it does.
          </p>
        </div>
      )}
    </motion.section>
  );
}

function OptionRow({
  option,
  onApply,
  applying,
}: {
  option: FeasibilityOption;
  onApply?: (o: FeasibilityOption) => void;
  applying?: boolean;
}) {
  const isBudget = option.kind === "budget";
  const interactive = Boolean(onApply);

  return (
    <motion.div
      whileTap={{ scale: 0.98 }}
      className={cn(
        "flex items-center gap-3 rounded-lg border border-brand-100 bg-brand-50/70 px-3 py-2.5",
        // Responsive hover — a hairline border shift plus a slightly deeper
        // brand wash so rows feel live before the Apply press lands.
        "transition-colors hover:border-brand-300 hover:bg-brand-50",
      )}
    >
      <span
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-lg",
          isBudget
            ? "bg-brand-50 text-brand-700"
            : "bg-muted text-muted-foreground",
        )}
      >
        {isBudget ? (
          <IndianRupee className="size-4" strokeWidth={2.4} aria-hidden />
        ) : (
          <UtensilsCrossed className="size-4" strokeWidth={2.4} aria-hidden />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-bold text-foreground">
          {option.label}
        </p>
        <p className="truncate text-sm leading-[1.4] text-muted-foreground">
          {option.detail}
        </p>
      </div>

      <span className="shrink-0 text-sm font-bold tracking-[-0.02em] tabular-nums text-foreground">
        {formatINR(option.total)}
      </span>

      {interactive && (
        <MotionButton
          onClick={() => onApply?.(option)}
          disabled={applying}
          size="sm"
          whileTap={{ scale: 0.97 }}
          className="shrink-0 text-xs"
        >
          {applying ? (
            <LoaderCircle className="size-4 animate-spin" strokeWidth={2.4} aria-hidden />
          ) : (
            <>
              Apply
              <ArrowRight className="size-4" strokeWidth={2.4} aria-hidden />
            </>
          )}
        </MotionButton>
      )}
    </motion.div>
  );
}

export default FeasibilityPanel;
