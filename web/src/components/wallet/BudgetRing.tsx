"use client";

import { useId } from "react";
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
 * The arc is filled with the brand orange -> amber gradient; the center shows the
 * remaining balance in a big mono gradient number with a "left" label underneath.
 */
export function BudgetRing({ spent, budget, size = 176, className }: BudgetRingProps) {
  const gradId = useId();
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
        <defs>
          <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--brand-500)" />
            <stop offset="55%" stopColor="var(--brand-400)" />
            <stop offset="100%" stopColor="var(--amber-400)" />
          </linearGradient>
        </defs>

        {/* Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth={stroke}
          className="opacity-70"
        />

        {/* Progress arc */}
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={`url(#${gradId})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={false}
          animate={{ strokeDashoffset: dashOffset }}
          transition={{ type: "spring", stiffness: 90, damping: 20, mass: 0.8 }}
          style={{ filter: "drop-shadow(0 0 6px var(--brand-500-a30))" }}
        />
      </svg>

      {/* Center label */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 px-4 text-center">
        <span
          className={cn(
            "font-mono font-semibold tracking-tight text-gradient-brand tabular-nums leading-none",
            over && "text-gradient-brand"
          )}
          style={{ fontSize: Math.max(18, size * 0.16) }}
        >
          {formatINR(Math.abs(balance))}
        </span>
        <span className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
          {over ? "over" : "left"}
        </span>
        <span className="mt-1 font-mono text-[10px] tabular-nums text-muted-foreground/80">
          {Math.round(spentPct)}% spent
        </span>
      </div>
    </div>
  );
}

export default BudgetRing;
