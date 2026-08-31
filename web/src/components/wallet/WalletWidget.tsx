"use client";

import { motion } from "framer-motion";
import { IndianRupee, Wallet } from "lucide-react";

import { cn } from "@/lib/utils";
import { surfaces } from "@/lib/design";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import type { WalletSummary } from "@/lib/types";

import { BudgetRing } from "./BudgetRing";
import { formatINR } from "./wallet-helpers";

export interface WalletWidgetProps {
  /** The wallet summary for the active cycle, or null when none exists yet. */
  wallet: WalletSummary | null;
  /** Show the skeleton loading state. */
  loading?: boolean;
  className?: string;
}

/** One labeled stat row: label on the left, mono number on the right. */
function StatRow({
  label,
  value,
  emphasis,
  highlight,
}: {
  label: string;
  value: string;
  /** Larger / stronger value styling (used for Balance). */
  emphasis?: boolean;
  /** Positive-money pill treatment (rolled-in savings) — success green. */
  highlight?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span
        className={cn(
          "text-sm text-muted-foreground",
          highlight && "flex items-center gap-1.5 font-medium text-foreground"
        )}
      >
        {highlight && (
          <IndianRupee
            className="size-4 text-success"
            strokeWidth={2.4}
            aria-hidden
          />
        )}
        {label}
      </span>

      {highlight ? (
        <span className="inline-flex items-center rounded-full border border-success/25 bg-success/10 px-2.5 py-0.5 text-sm font-bold tabular-nums text-success">
          {value}
        </span>
      ) : (
        <span
          className={cn(
            "tabular-nums",
            emphasis
              ? "text-base font-extrabold tracking-[-0.02em] text-foreground"
              : "text-sm text-foreground"
          )}
        >
          {value}
        </span>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const s = status?.toLowerCase();
  const isActive = s === "active" || s === "open";
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 font-medium capitalize",
        isActive
          ? "border-success/25 bg-success/10 text-success"
          : "border-border bg-muted text-muted-foreground"
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          isActive ? "bg-success" : "bg-muted-foreground"
        )}
        aria-hidden
      />
      {status || "unknown"}
    </Badge>
  );
}

export function WalletWidget({ wallet, loading, className }: WalletWidgetProps) {
  if (loading) {
    return (
      <div className={cn(surfaces.card, "p-6 shadow-soft", className)}>
        <div className="flex flex-col items-center gap-8 sm:flex-row sm:items-center">
          <Skeleton className="size-44 shrink-0 rounded-full" />
          <div className="w-full flex-1 space-y-4">
            <Skeleton className="h-5 w-32" />
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex items-center justify-between">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-16" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!wallet) {
    return (
      <div
        className={cn(
          surfaces.card,
          "flex flex-col items-center justify-center gap-4 p-10 text-center shadow-soft",
          className
        )}
      >
        <div className="relative">
          <div className="flex size-16 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
            <Wallet className="size-6" strokeWidth={2.4} aria-hidden />
          </div>
        </div>
        <div className="space-y-1">
          <h3 className="font-heading text-lg font-extrabold tracking-[-0.02em] text-foreground">No wallet yet</h3>
          <p className="max-w-xs text-sm text-muted-foreground">
            Approve a plan to fund your monthly meal wallet.
          </p>
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className={cn(surfaces.card, "overflow-hidden shadow-soft", className)}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-3 border-b border-border/60 px-6 py-4">
        <div className="flex items-center gap-2.5">
          <div className="flex size-9 items-center justify-center rounded-lg border border-border bg-muted text-muted-foreground">
            <Wallet className="size-5" strokeWidth={2.4} aria-hidden />
          </div>
          <div className="leading-tight">
            <p className="font-heading text-sm font-extrabold tracking-[-0.02em] text-foreground">Meal Wallet</p>
            <p className="text-xs text-muted-foreground">{wallet.month}</p>
          </div>
        </div>
        <StatusBadge status={wallet.status} />
      </div>

      {/* Body */}
      <div className="flex flex-col items-center gap-8 p-6 sm:flex-row sm:items-center sm:gap-8">
        <BudgetRing spent={wallet.total_spent} budget={wallet.budget_allocated} />

        <div className="w-full flex-1 space-y-3">
          <StatRow label="Budget" value={formatINR(wallet.budget_allocated)} />
          <StatRow label="Spent" value={formatINR(wallet.total_spent)} />
          <StatRow
            label="Swiggy Cash"
            value={`+${formatINR(wallet.rolled_in)}`}
            highlight
          />
          <Separator className="!bg-border/60" />
          <StatRow label="Balance" value={formatINR(wallet.balance)} emphasis />
        </div>
      </div>
    </motion.div>
  );
}

export default WalletWidget;
