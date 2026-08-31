"use client";

import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { formatINR, pct } from "./wallet-helpers";

export interface BudgetRingProps {
  /** Amount spent so far. */
  spent: number;
  /** Total budget for the cycle. */
  budget: number;
  /** Outer diameter in px. Default 176. */
  size?: number;
  className?: string;
}

/**
 * Animated circular progress ring (SVG + framer-motion) showing spent vs budget.
 * The arc is a solid brand-orange stroke (danger-red once over budget); the
 * center shows the remaining balance as a big extrabold charcoal figure with a
 * "left" label underneath.
 */
export function BudgetRing({ spent, budget, size = 176, className }: BudgetRingProps) {
  const stroke = Math.max(10, Math.round(size * 0.075));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;

  const spentPct = pct(spent, budget);
  const balance = (Number.isFinite(budget) ? budget : 0) - (Number.isFinite(spent) ? spent : 0);
  const over = balance < 0;

  // Fraction of the ring that should be filled (0..1).
  const fraction = spentPct / 100;
  const dashOffset = circumference * (1 - fraction);

  return (
    <div
      className={cn("relative shrink-0", className)}
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${formatINR(balance)} left of ${formatINR(budget)} budget`}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="-rotate-90"
      >
        {/* Track — flat Swiggy hairline gray */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth={stroke}
        />

        {/* Progress arc — solid brand orange, danger red when over */}
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={over ? "var(--danger)" : "var(--brand-500)"}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={false}
          animate={{ strokeDashoffset: dashOffset }}
          transition={{ type: "spring", stiffness: 90, damping: 20, mass: 0.8 }}
          style={{ filter: "none" }}
        />
      </svg>

      {/* Center label */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 px-4 text-center">
        <span
          className={cn(
            "font-display font-extrabold tracking-[-0.02em] tabular-nums leading-none text-foreground",
            over && "text-danger"
          )}
          style={{ fontSize: Math.max(18, size * 0.16) }}
        >
          {formatINR(Math.abs(balance))}
        </span>
        <span
          className={cn(
            "text-xs font-bold uppercase tracking-wide",
            over ? "text-danger" : "text-muted-foreground"
          )}
        >
          {over ? "over" : "left"}
        </span>
        <span className="mt-1 text-xs font-medium tabular-nums text-muted-foreground">
          {Math.round(spentPct)}% spent
        </span>
      </div>
    </div>
  );
}

export default BudgetRing;
