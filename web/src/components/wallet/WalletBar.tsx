"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  CircleCheck,
  IndianRupee,
  LoaderCircle,
  TriangleAlert,
  Wallet,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  LottiePlayer,
  usePrefersReducedMotion,
} from "@/components/ui/LottiePlayer";
import type { PlanSummary, WalletSummary } from "@/lib/types";

import { ConstraintChip } from "./ConstraintChip";
import { formatINR, pct } from "./wallet-helpers";

/* The approve CTA keeps its spring entrance/hover/tap beats, but base styling
   (flat brand-500, focus ring, h-11 via size="lg") comes from the shared
   Button component so both approve states occupy the same box. */
const MotionButton = motion.create(Button);

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
  tone?: "default" | "success" | "danger";
  emphasis?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col leading-tight">
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          "tabular-nums leading-tight text-foreground",
          emphasis ? "text-base font-extrabold" : "text-sm font-medium",
          tone === "success" && "text-success",
          tone === "danger" && "text-danger"
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
          over ? "bg-danger" : "bg-brand-500"
        )}
        initial={false}
        animate={{ width: `${filled}%` }}
        transition={{ type: "spring", stiffness: 90, damping: 20, mass: 0.8 }}
      />
    </div>
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
  // Rollover reveal: purely presentational — when the cash/leftover figure
  // INCREASES across renders (skip-meal refresh, re-approve, re-plan), play a
  // short coin drop ONCE near the savings number. Mirrors ApproveBar's
  // celebrating pattern: previous-vs-next compared in refs inside an effect.
  // Two independent series (wallet balance / plan leftover) so an async load
  // order on page refresh can never masquerade as an increase. A first
  // sighting only sets the baseline — loading a wallet is not "earning" one.
  const reducedMotion = usePrefersReducedMotion();
  const [celebrating, setCelebrating] = React.useState(false);
  const prevBalanceRef = React.useRef<number | null>(null);
  const prevLeftoverRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    if (reducedMotion) return;
    let increased = false;

    const balance = wallet?.balance;
    if (typeof balance === "number") {
      const prev = prevBalanceRef.current;
      if (prev != null && balance > prev) increased = true;
      prevBalanceRef.current = balance;
    }

    const leftover = plan?.leftover;
    if (typeof leftover === "number") {
      const prev = prevLeftoverRef.current;
      if (prev != null && leftover > prev) increased = true;
      prevLeftoverRef.current = leftover;
    }

    if (!increased) return;
    setCelebrating(true);
    const t = window.setTimeout(() => setCelebrating(false), 1600);
    return () => window.clearTimeout(t);
  }, [wallet, plan, reducedMotion]);

  if (loading) {
    return (
      <div
        className={cn(
          "flex items-center gap-4 rounded-lg border border-border bg-card px-5 py-3.5 text-card-foreground shadow-soft",
          className
        )}
      >
        <Skeleton className="size-9 rounded-md" />
        <div className="space-y-1.5">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-4 w-24" />
        </div>
        <Skeleton className="ml-auto h-11 w-36 rounded-lg" />
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
        "flex min-h-16 flex-wrap items-center gap-x-5 gap-y-3 rounded-lg border border-border bg-card px-5 py-3 text-card-foreground shadow-soft sm:flex-nowrap sm:px-6",
        infeasible && !approved && "ring-1 ring-danger/30",
        className
      )}
    >
      {/* LEFT — wallet cluster (or pre-approval plan preview) */}
      <div className="relative flex min-w-0 shrink-0 items-center gap-3">
        {/* Coin-drop reveal — plays once when cash/leftover increases.
            Overlay only: no pointer events, no layout shift. */}
        {celebrating && (
          <div aria-hidden className="pointer-events-none absolute -top-2 right-2 z-[1]">
            <LottiePlayer
              path="/animations/coin-drop.json"
              loop={false}
              className="h-12 w-12"
            />
          </div>
        )}
        <div className="flex size-9 shrink-0 items-center justify-center self-center rounded-lg border border-border bg-muted text-muted-foreground">
          <Wallet className="size-5" strokeWidth={2.4} aria-hidden />
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
              <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-success/25 bg-success/10 px-2.5 py-0.5 text-sm font-bold tabular-nums text-success">
                <IndianRupee className="size-4" strokeWidth={2.4} aria-hidden />
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
                tone={plan.leftover < 0 ? "danger" : "success"}
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
                  ? "border-danger/25 bg-danger/10 text-danger"
                  : "border-success/25 bg-success/10 text-success",
              )}
              title={plan.message?.trim() || undefined}
            >
              {infeasible ? (
                <TriangleAlert className="size-4" strokeWidth={2.4} aria-hidden />
              ) : (
                <CircleCheck className="size-4" strokeWidth={2.4} aria-hidden />
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
                className="inline-flex h-11 items-center gap-2 rounded-lg border border-success/25 bg-success/10 px-4 text-sm font-medium text-success"
              >
                <CircleCheck className="size-4" strokeWidth={2.4} aria-hidden />
                Plan active
              </motion.div>
            ) : (
              <MotionButton
                key="cta"
                onClick={onApprove}
                disabled={approving || infeasible}
                size="lg"
                title={
                  infeasible
                    ? "Over budget. Apply a suggested fix below first."
                    : undefined
                }
                whileHover={approving ? undefined : { scale: 1.02 }}
                whileTap={approving ? undefined : { scale: 0.98 }}
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                transition={{ type: "spring", stiffness: 300, damping: 22 }}
                className={cn(
                  "group px-5",
                  infeasible &&
                    "ring-2 ring-danger/40 ring-offset-2 ring-offset-background"
                )}
                aria-busy={approving || undefined}
              >
                {approving ? (
                  <>
                    <LoaderCircle
                      className="size-4 animate-spin"
                      strokeWidth={2.4}
                      aria-hidden
                    />
                    Activating…
                  </>
                ) : (
                  <>
                    {infeasible ? "Fix budget to approve" : "Approve & activate"}
                    <ArrowRight
                      className="size-4 transition-transform group-hover:translate-x-0.5"
                      strokeWidth={2.4}
                      aria-hidden
                    />
                  </>
                )}
              </MotionButton>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  );
}

export default WalletBar;
