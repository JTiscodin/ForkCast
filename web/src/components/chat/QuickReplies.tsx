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
 * Pill-shaped quick-reply chips with a staggered pop-in.
 * Used for onboarding suggestions and the Yes/No/Later/Something-else
 * meal-notification flow. The chip's visual tone is inferred from its value.
 */
export function QuickReplies({
  replies,
  onPick,
  disabled,
  className,
}: QuickRepliesProps) {
  if (!replies.length) return null;

  return (
    <div className={cn("flex flex-wrap gap-2", className)}>
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
            "inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors",
            "disabled:pointer-events-none disabled:opacity-50",
            focusRing,
            toneClasses(r.value)
          )}
        >
          {r.label}
        </motion.button>
      ))}
    </div>
  );
}

/**
 * Map the reply's semantic value to a tone.
 * Yes = brand/success, No/Later = muted, Something else = outline.
 * Everything else (onboarding suggestions) uses a soft brand-tinted chip.
 */
function toneClasses(value: string): string {
  const v = value.trim().toLowerCase();

  if (v === "yes") {
    return "border-success/30 bg-success/12 text-success hover:bg-success/20";
  }
  if (v === "no" || v === "later") {
    return "border-border bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground";
  }
  if (v === "other" || v === "something_else" || v === "something else") {
    return "border-border bg-transparent text-foreground hover:bg-muted";
  }
  // Default: soft brand suggestion chip.
  return "border-brand-500/25 bg-accent text-accent-foreground hover:bg-accent/70";
}
