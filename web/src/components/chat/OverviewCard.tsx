"use client";

import * as React from "react";
import { motion } from "framer-motion";
import {
  Check,
  Leaf,
  Loader2,
  Sparkles,
  Utensils,
  Wallet,
  Zap,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { gradients, focusRing } from "@/lib/design";
import type { AppetiteLevel, Blueprint } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  APPETITE_LABELS,
  MEAL_LABELS,
  blueprintSummaryLine,
  formatINR,
} from "./blueprint-helpers";

export interface OverviewCardProps {
  blueprint: Blueprint;
  /** Fires the deterministic /plan build. */
  onGenerate: () => void;
  /** Inline edits update the blueprint. When omitted, the card is read-only. */
  onEdit?: (patch: Partial<Blueprint>) => void;
  /** Plan build in flight. */
  generating?: boolean;
  className?: string;
}

const APPETITE_ORDER: AppetiteLevel[] = [
  "light",
  "moderate",
  "heavy",
  "very_heavy",
];

/**
 * The "plan blueprint" bubble — a premium glass card the assistant drops into
 * the chat once it has gathered enough requirements. Summarizes the plan and
 * offers a prominent "Generate Plan" CTA. When `onEdit` is provided, budget,
 * appetite, and diet get lightweight inline controls; otherwise it renders
 * read-only.
 */
export function OverviewCard({
  blueprint,
  onGenerate,
  onEdit,
  generating = false,
  className,
}: OverviewCardProps) {
  const editable = typeof onEdit === "function";

  // Budget is edited as a controlled text field so partial input never
  // clobbers the blueprint; commit to a number on change. We track the last
  // blueprint.budget we synced from so an outside change (e.g. the user says
  // "make it cheaper" in chat) re-seeds the draft — adjusting state during
  // render instead of in an effect (React's "storing info from prior renders"
  // pattern), which avoids a ref read and an extra paint.
  const [budgetDraft, setBudgetDraft] = React.useState<string>(
    blueprint.budget != null ? String(blueprint.budget) : ""
  );
  const [syncedBudget, setSyncedBudget] = React.useState<number | null>(
    blueprint.budget
  );
  if (syncedBudget !== blueprint.budget) {
    setSyncedBudget(blueprint.budget);
    setBudgetDraft(blueprint.budget != null ? String(blueprint.budget) : "");
  }

  const handleBudgetChange = (raw: string) => {
    // Digits only; empty string is allowed while typing.
    const cleaned = raw.replace(/[^\d]/g, "");
    setBudgetDraft(cleaned);
    onEdit?.({ budget: cleaned === "" ? null : Number(cleaned) });
  };

  const handleAppetiteChange = (value: AppetiteLevel) => {
    onEdit?.({ appetite_level: value });
  };

  const toggleVegOnly = () => {
    onEdit?.({ veg_only: !blueprint.veg_only });
  };

  const days = blueprint.days > 0 ? blueprint.days : 1;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 260, damping: 26 }}
      className={cn(
        "glass-panel relative w-full overflow-hidden rounded-2xl shadow-glow",
        "border border-brand-500/25",
        className
      )}
      role="group"
      aria-label={`Plan blueprint. ${blueprintSummaryLine(blueprint)}`}
    >
      {/* Brand-tinted header band */}
      <div className="relative overflow-hidden">
        <div
          className={cn(gradients.glow, "pointer-events-none absolute inset-0")}
          aria-hidden
        />
        <div className="relative flex items-center gap-3 px-5 pt-5 pb-4">
          <div
            className={cn(
              "flex size-9 shrink-0 items-center justify-center rounded-xl text-primary-foreground shadow-glow",
              gradients.brand
            )}
            aria-hidden
          >
            <Sparkles className="size-4.5" />
          </div>
          <div className="min-w-0">
            <h3 className="font-display text-lg leading-tight font-semibold">
              Here&rsquo;s your plan blueprint
            </h3>
            <p className="text-xs text-muted-foreground">
              Review it, tweak anything, then generate.
            </p>
          </div>
        </div>
      </div>

      <Separator />

      {/* Fields */}
      <div className="grid gap-4 px-5 py-4">
        {/* Budget */}
        <Row icon={<Wallet className="size-4" />} label="Budget">
          {editable ? (
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-sm text-muted-foreground">₹</span>
              <Input
                inputMode="numeric"
                value={budgetDraft}
                onChange={(e) => handleBudgetChange(e.target.value)}
                placeholder="0"
                aria-label="Budget in rupees"
                className="h-8 w-28 font-mono text-sm"
              />
              <span className="text-xs text-muted-foreground">/ month</span>
            </div>
          ) : (
            <span className="font-mono text-sm font-medium">
              {formatINR(blueprint.budget)}
              <span className="ml-1 text-xs font-normal text-muted-foreground">
                / month
              </span>
            </span>
          )}
        </Row>

        {/* Appetite */}
        <Row icon={<Utensils className="size-4" />} label="Appetite">
          {editable ? (
            <Select
              value={blueprint.appetite_level ?? ""}
              onValueChange={(v) => handleAppetiteChange(v as AppetiteLevel)}
            >
              <SelectTrigger size="sm" className="w-40" aria-label="Appetite level">
                <SelectValue placeholder="Pick appetite" />
              </SelectTrigger>
              <SelectContent>
                {APPETITE_ORDER.map((level) => (
                  <SelectItem key={level} value={level}>
                    {APPETITE_LABELS[level]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : blueprint.appetite_level ? (
            <Badge variant="secondary" className="font-medium">
              {APPETITE_LABELS[blueprint.appetite_level]}
            </Badge>
          ) : (
            <span className="text-sm text-muted-foreground">Not set</span>
          )}
        </Row>

        {/* Diet */}
        <Row icon={<Leaf className="size-4" />} label="Diet">
          {editable ? (
            <button
              type="button"
              onClick={toggleVegOnly}
              aria-pressed={blueprint.veg_only}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium transition-colors",
                focusRing,
                blueprint.veg_only
                  ? "border-success/30 bg-success/12 text-success hover:bg-success/20"
                  : "border-border bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              {blueprint.veg_only ? (
                <>
                  <Check className="size-3.5" /> Veg-only
                </>
              ) : (
                "Veg & Non-veg"
              )}
            </button>
          ) : blueprint.veg_only ? (
            <Badge className="border-success/30 bg-success/12 text-success" variant="outline">
              <Leaf className="size-3" /> Veg-only
            </Badge>
          ) : (
            <span className="text-sm text-muted-foreground">Veg &amp; Non-veg</span>
          )}

          {/* High-protein changes which dishes are SEARCHED for, so surface it
              here — the user needs to see we understood the request. */}
          {blueprint.high_protein && (
            <Badge
              className="ml-2 border-brand-500/30 bg-accent text-accent-brand"
              variant="outline"
            >
              High protein
            </Badge>
          )}
        </Row>

        {/* Must-have dishes */}
        {blueprint.constraints.length > 0 && (
          <Row icon={<Check className="size-4" />} label="Must-haves" align="start">
            <div className="flex flex-wrap gap-1.5">
              {blueprint.constraints.map((c, i) => (
                <span
                  key={`${c.dish_tag}-${i}`}
                  className="inline-flex items-center gap-1 rounded-full border border-brand-500/25 bg-accent px-2.5 py-0.5 text-xs text-accent-foreground"
                >
                  <span className="font-mono font-medium">{c.min_count}×</span>
                  {c.dish_tag}
                </span>
              ))}
            </div>
          </Row>
        )}

        {/* Cuisines */}
        {blueprint.cuisines.length > 0 && (
          <Row icon={<Sparkles className="size-4" />} label="Cuisines" align="start">
            <div className="flex flex-wrap gap-1.5">
              {blueprint.cuisines.map((cuisine, i) => (
                <Badge key={`${cuisine}-${i}`} variant="outline" className="capitalize">
                  {cuisine}
                </Badge>
              ))}
            </div>
          </Row>
        )}

        {/* Coverage: days + meals */}
        <Row icon={<Utensils className="size-4" />} label="Coverage" align="start">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm">
              <span className="font-mono font-medium">{days}</span>{" "}
              {days === 1 ? "day" : "days"}
            </span>
            {blueprint.meals.length > 0 && (
              <>
                <span className="text-muted-foreground" aria-hidden>
                  ·
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {blueprint.meals.map((m) => (
                    <Badge key={m} variant="secondary" className="capitalize">
                      {MEAL_LABELS[m]}
                    </Badge>
                  ))}
                </div>
              </>
            )}
          </div>
        </Row>
      </div>

      <Separator />

      {/* CTA */}
      <div className="px-5 py-4">
        <motion.button
          type="button"
          onClick={onGenerate}
          disabled={generating}
          whileHover={generating ? undefined : { scale: 1.015 }}
          whileTap={generating ? undefined : { scale: 0.985 }}
          className={cn(
            "flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-primary-foreground",
            "shadow-soft transition-shadow hover:shadow-glow",
            "disabled:pointer-events-none disabled:opacity-70",
            gradients.brand,
            focusRing
          )}
          aria-label="Generate plan"
        >
          {generating ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Building your plan…
            </>
          ) : (
            <>
              <Zap className="size-4" />
              Generate Plan
            </>
          )}
        </motion.button>
        <p className="mt-2.5 text-center text-xs text-muted-foreground">
          You can keep chatting to tweak it — e.g.{" "}
          <span className="text-foreground/80">&ldquo;make it cheaper&rdquo;</span>{" "}
          or{" "}
          <span className="text-foreground/80">&ldquo;less paneer&rdquo;</span>.
        </p>
      </div>
    </motion.div>
  );
}

/** A labeled field row: icon + label on the left, value/control on the right. */
function Row({
  icon,
  label,
  align = "center",
  children,
}: {
  icon: React.ReactNode;
  label: string;
  align?: "center" | "start";
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex gap-3",
        align === "center" ? "items-center" : "items-start"
      )}
    >
      <div
        className={cn(
          "flex w-28 shrink-0 items-center gap-2 text-xs font-medium tracking-wide text-muted-foreground uppercase",
          align === "start" && "pt-1"
        )}
      >
        <span className="text-brand-500" aria-hidden>
          {icon}
        </span>
        {label}
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
