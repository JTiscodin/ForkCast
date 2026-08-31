"use client";

import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import { focusRing } from "@/lib/design";
import type { QuickReply } from "./types";

export interface QuickRepliesProps {
  replies: QuickReply[];
  onPick: (value: string) => void;
  disabled?: boolean;
  className?: string;
}

/**
 * Compact quick-reply pill chips with a staggered pop-in.
 * Used for onboarding suggestions and the Yes/No/Later/Something-else
 * meal-notification flow. The chip's resting tone is inferred from its value;
 * every chip warms to the brand tint on hover.
 */
export function QuickReplies({
  replies,
  onPick,
  disabled,
  className,
}: QuickRepliesProps) {
  if (!replies.length) return null;

  return (
    <div className={cn("flex min-w-0 max-w-full flex-wrap gap-2 pb-1", className)}>
      {replies.map((r, i) => (
        <motion.button
          key={`${r.value}-${i}`}
          type="button"
          disabled={disabled}
          onClick={() => onPick(r.value)}
          initial={{ opacity: 0, scale: 0.85, y: 6 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={{
            delay: i * 0.05,
            type: "spring",
            stiffness: 480,
            damping: 26,
          }}
          whileHover={disabled ? undefined : { scale: 1.04 }}
          whileTap={disabled ? undefined : { scale: 0.96 }}
          className={cn(
            "inline-flex max-w-full shrink-0 items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-left text-xs leading-[1.4] font-semibold whitespace-normal break-words transition-[background-color,border-color,color,transform] duration-150 ease-out",
            "hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700",
            "disabled:pointer-events-none disabled:opacity-50",
            focusRing,
            toneClasses(r.value, i)
          )}
        >
          {r.label}
        </motion.button>
      ))}
    </div>
  );
}

/**
 * Map the reply's semantic value to a resting tone.
 * Suggested chips (Yes / first discovery pick) sit on the soft brand tint;
 * the rest are quiet white pills that warm to brand on hover.
 */
function toneClasses(value: string, index: number): string {
  const v = value.trim().toLowerCase();

  if (v === "yes") {
    return "border-brand-200 bg-brand-50 text-brand-700";
  }
  if (v === "no" || v === "later") {
    return "border-border bg-card text-muted-foreground";
  }
  if (v === "other" || v === "something_else" || v === "something else") {
    return "border-border bg-card text-foreground";
  }
  // Keep the first discovery suggestion pre-highlighted on the brand lane.
  if (index === 0) {
    return "border-brand-200 bg-brand-50 text-brand-700";
  }
  return "border-border bg-card text-foreground";
}
