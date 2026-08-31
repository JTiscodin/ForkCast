"use client";

import { motion } from "framer-motion";
import { Sparkles, UserRound, Bell } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ChatMessage } from "./types";

export interface MessageBubbleProps {
  message: ChatMessage;
  className?: string;
}

/**
 * Renders a single chat message.
 * - user:      right-aligned on a soft brand tint (Swiggy user-side).
 * - assistant: left-aligned white bubble with a small AI avatar.
 *              `pending` swaps the body for an animated typing indicator.
 * - system:    centered, quiet meta line.
 * Notification-kind messages render inside a highlighted brand-tinted card.
 */
export function MessageBubble({ message, className }: MessageBubbleProps) {
  const { role, kind, text, pending } = message;

  if (role === "system") {
    return (
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className={cn("flex justify-center px-2 py-1", className)}
      >
        <span className="text-[11px] leading-[1.4] text-muted-foreground">{text}</span>
      </motion.div>
    );
  }

  const isUser = role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 380, damping: 30 }}
      className={cn(
        "flex w-full items-end gap-2.5",
        isUser ? "justify-end" : "justify-start",
        className
      )}
    >
      {!isUser && <Avatar kind={kind} />}

      <div
        className={cn(
          "max-w-[82%] rounded-xl border px-4 py-2.5 text-sm leading-[1.4]",
          isUser
            ? "rounded-br-md border-brand-100 bg-brand-50 text-foreground"
            : kind === "notification"
              ? "rounded-bl-md border-brand-200 bg-brand-50 text-foreground"
              : "rounded-bl-md border-border bg-card text-foreground shadow-soft"
        )}
      >
        {pending ? (
          <TypingDots />
        ) : (
          <p className="whitespace-pre-wrap break-words">{text}</p>
        )}
      </div>
    </motion.div>
  );
}

function Avatar({ kind }: { kind?: ChatMessage["kind"] }) {
  const Icon = kind === "notification" ? Bell : Sparkles;
  return (
    <div
      className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-500 text-white"
      aria-hidden
    >
      <Icon className="size-4" strokeWidth={2.4} />
    </div>
  );
}

/** Three bouncing dots — the assistant "thinking" indicator. */
function TypingDots() {
  return (
    <div
      className="flex items-center gap-1 py-1"
      role="status"
      aria-label="Assistant is typing"
    >
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="size-1.5 rounded-full bg-muted-foreground"
          animate={{ y: [0, -4, 0], opacity: [0.4, 1, 0.4] }}
          transition={{
            duration: 0.9,
            repeat: Infinity,
            ease: "easeInOut",
            delay: i * 0.15,
          }}
        />
      ))}
    </div>
  );
}

// re-export so callers can spread the user glyph if needed elsewhere
export { UserRound };
