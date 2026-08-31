"use client";

import * as React from "react";
import { motion } from "framer-motion";
import {
  Check,
  Leaf,
  Loader2,
  Sparkles,
  UtensilsCrossed,
  Wallet,
  Zap,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { focusRing } from "@/lib/design";
import type { AppetiteLevel, Blueprint } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

/* The Generate CTA keeps its spring hover/tap beat, but the base styling now
   comes from the shared Button component (flat brand-500, focus ring, lg
   height) instead of a hand-rolled recipe that could drift out of sync. */
const MotionButton = motion.create(Button);

/**
 * The "plan blueprint" bubble — a featured card the assistant drops into
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
        "relative w-full overflow-hidden rounded-lg border border-border bg-card text-card-foreground shadow-soft",
        className
      )}
      role="group"
      aria-label={`Plan blueprint. ${blueprintSummaryLine(blueprint)}`}
    >
      {/* Branded offer header — flat brand-tinted strip */}
      <div className="bg-brand-50">
        <div className="flex items-center gap-3 px-5 pt-5 pb-4">
          <div
            className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-500 text-white"
            aria-hidden
          >
            <Sparkles className="size-5" strokeWidth={2.4} />
          </div>
          <div className="min-w-0">
            <h3 className="font-heading text-lg font-extrabold leading-[1.4] tracking-[-0.02em] text-foreground">
              Here&rsquo;s your plan blueprint
            </h3>
            <p className="text-sm leading-[1.4] text-muted-foreground">
              Review it, tweak anything, then generate.
            </p>
          </div>
        </div>
      </div>

      <Separator />

      {/* Fields */}
      <div className="grid gap-4 px-5 py-4">
        {/* Budget */}
        <Row icon={<Wallet className="size-4" strokeWidth={2.4} />} label="Budget">
          {editable ? (
            <div className="flex items-center gap-1.5">
              <span className="text-sm leading-[1.4] font-semibold text-foreground">₹</span>
              <Input
                inputMode="numeric"
                value={budgetDraft}
                onChange={(e) => handleBudgetChange(e.target.value)}
                placeholder="0"
                aria-label="Budget in rupees"
                className="h-8 w-full max-w-28 text-sm leading-[1.4] font-bold tabular-nums"
              />
              <span className="shrink-0 text-sm leading-[1.4] text-muted-foreground">/ month</span>
            </div>
          ) : (
            <span className="text-lg leading-[1.2] font-extrabold tabular-nums text-foreground">
              {formatINR(blueprint.budget)}
              <span className="ml-1 text-sm leading-[1.4] font-normal text-muted-foreground">
                / month
              </span>
            </span>
          )}
        </Row>

        {/* Appetite */}
        <Row icon={<UtensilsCrossed className="size-4" strokeWidth={2.4} />} label="Appetite">
          {editable ? (
            <Select
              value={blueprint.appetite_level ?? ""}
              onValueChange={(v) => handleAppetiteChange(v as AppetiteLevel)}
            >
              <SelectTrigger size="sm" className="w-full max-w-40" aria-label="Appetite level">
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
            <span className="text-sm leading-[1.4] text-muted-foreground">Not set</span>
          )}
        </Row>

        {/* Diet */}
        <Row icon={<Leaf className="size-4" strokeWidth={2.4} />} label="Diet">
          {editable ? (
            <button
              type="button"
              onClick={toggleVegOnly}
              aria-pressed={blueprint.veg_only}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md border px-3 py-1 text-sm leading-[1.4] font-medium transition-colors",
                focusRing,
                blueprint.veg_only
                  ? "border-success/30 bg-success/12 text-success hover:bg-success/20"
                  : "border-border bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              {blueprint.veg_only ? (
                <>
                  <Check className="size-4" strokeWidth={2.4} /> Veg-only
                </>
              ) : (
                "Veg & Non-veg"
              )}
            </button>
          ) : blueprint.veg_only ? (
            <Badge className="border-success/30 bg-success/12 text-success" variant="outline">
              <Leaf className="size-4" strokeWidth={2.4} /> Veg-only
            </Badge>
          ) : (
            <span className="text-sm leading-[1.4] text-muted-foreground">Veg &amp; Non-veg</span>
          )}

          {/* High-protein changes which dishes are SEARCHED for, so surface it
              here — the user needs to see we understood the request. */}
          {blueprint.high_protein && (
            <Badge
              className="ml-2 border-brand-200 bg-brand-50 text-brand-700"
              variant="outline"
            >
              High protein
            </Badge>
          )}
        </Row>

        {/* Must-have dishes */}
        {blueprint.constraints.length > 0 && (
          <Row icon={<Check className="size-4" strokeWidth={2.4} />} label="Must-haves" align="start">
            <div className="flex flex-wrap gap-1.5">
              {blueprint.constraints.map((c, i) => (
                <span
                  key={`${c.dish_tag}-${i}`}
                  className="inline-flex items-center gap-1 rounded-md border border-brand-200 bg-brand-50 px-2.5 py-0.5 text-sm leading-[1.4] text-brand-700"
                >
                  <span className="font-bold tabular-nums">{c.min_count}×</span>
                  {c.dish_tag}
                </span>
              ))}
            </div>
          </Row>
        )}

        {/* Cuisines */}
        {blueprint.cuisines.length > 0 && (
          <Row icon={<Sparkles className="size-4" strokeWidth={2.4} />} label="Cuisines" align="start">
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
        <Row icon={<UtensilsCrossed className="size-4" strokeWidth={2.4} />} label="Coverage" align="start">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm leading-[1.4]">
              <span className="font-semibold tabular-nums">{days}</span>{" "}
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
        <MotionButton
          onClick={onGenerate}
          disabled={generating}
          size="lg"
          whileHover={generating ? undefined : { scale: 1.015 }}
          whileTap={generating ? undefined : { scale: 0.985 }}
          className="w-full"
          aria-label="Generate plan"
        >
          {generating ? (
            <>
              <Loader2 className="size-4 animate-spin" strokeWidth={2.4} />
              Building your plan…
            </>
          ) : (
            <>
              <Zap className="size-4" strokeWidth={2.4} />
              Generate Plan
            </>
          )}
        </MotionButton>
        <p className="mt-2.5 text-center text-sm leading-[1.4] text-muted-foreground">
          You can keep chatting to tweak it, e.g.{" "}
          <span className="font-medium text-foreground">&ldquo;make it cheaper&rdquo;</span>{" "}
          or{" "}
          <span className="font-medium text-foreground">&ldquo;less paneer&rdquo;</span>.
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
          "flex w-24 shrink-0 items-center gap-2 text-[11px] leading-[1.4] font-bold uppercase tracking-wide text-muted-foreground",
          align === "start" && "pt-0.5"
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
