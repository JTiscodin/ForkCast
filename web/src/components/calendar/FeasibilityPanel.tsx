"use client";

import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  CircleCheckBig,
  LoaderCircle,
  TrendingUp,
  UtensilsCrossed,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { focusRing } from "@/lib/design";
import type { FeasibilityOption, FeasibilityReport } from "@/lib/types";
import { formatINR } from "./calendar-helpers";

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
          "flex items-center gap-2.5 rounded-2xl border border-success/25 bg-success/[0.07] px-4 py-3",
          className,
        )}
      >
        <CircleCheckBig className="size-4 shrink-0 text-success" aria-hidden />
        <p className="text-sm text-foreground">{report.headline}</p>
      </motion.div>
    );
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "overflow-hidden rounded-2xl border border-warning/25 bg-warning/[0.05]",
        className,
      )}
      aria-live="polite"
    >
      {/* Explanation */}
      <div className="flex gap-3 px-4 py-3.5 sm:px-5">
        <AlertTriangle
          className="mt-0.5 size-4.5 shrink-0 text-warning"
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <h3 className="text-[0.7rem] font-semibold uppercase tracking-widest text-warning">
            This budget won&apos;t stretch
          </h3>
          {/* The headline already names the city's real per-meal cost, the meal
              count, and the exact shortfall — no need to repeat any of it. */}
          <p className="mt-1 text-sm leading-relaxed text-foreground">
            {report.headline}
          </p>

          <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <UtensilsCrossed className="size-3" aria-hidden />
              {report.current.slots} meals
            </span>
            <span>
              ~
              <span className="font-mono tabular-nums text-foreground">
                {formatINR(report.current.per_meal)}
              </span>{" "}
              per meal locally
            </span>
            <span>
              Needs{" "}
              <span className="font-mono tabular-nums text-warning">
                {formatINR(report.floor)}
              </span>{" "}
              minimum
            </span>
          </div>
        </div>
      </div>

      {/* Concrete fixes */}
      {report.options.length > 0 && (
        <div className="border-t border-warning/20 bg-background/40 px-4 py-3 sm:px-5">
          <p className="mb-2.5 text-[0.7rem] font-semibold uppercase tracking-widest text-muted-foreground">
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
            Or keep this plan as-is — you can approve it and adjust later.
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
    <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-3 py-2.5">
      <span
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-lg",
          isBudget
            ? "bg-brand-500/12 text-accent-brand"
            : "bg-muted text-muted-foreground",
        )}
      >
        {isBudget ? (
          <TrendingUp className="size-4" aria-hidden />
        ) : (
          <UtensilsCrossed className="size-4" aria-hidden />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">
          {option.label}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {option.detail}
        </p>
      </div>

      <span className="shrink-0 font-mono text-sm font-semibold tabular-nums text-foreground">
        {formatINR(option.total)}
      </span>

      {interactive && (
        <button
          type="button"
          onClick={() => onApply?.(option)}
          disabled={applying}
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium transition-colors",
            "hover:border-brand-500/40 hover:bg-accent hover:text-accent-brand",
            "disabled:cursor-not-allowed disabled:opacity-50",
            focusRing,
          )}
        >
          {applying ? (
            <LoaderCircle className="size-3 animate-spin" aria-hidden />
          ) : (
            <>
              Use
              <ArrowRight className="size-3" aria-hidden />
            </>
          )}
        </button>
      )}
    </div>
  );
}

export default FeasibilityPanel;
