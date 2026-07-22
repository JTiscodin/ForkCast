"use client";

import { motion } from "framer-motion";
import { Sparkles, User, Bell } from "lucide-react";

import { cn } from "@/lib/utils";
import { gradients } from "@/lib/design";
import type { ChatMessage } from "./types";

export interface MessageBubbleProps {
  message: ChatMessage;
  className?: string;
}

/**
 * Renders a single chat message.
 * - user:      right-aligned, brand gradient.
 * - assistant: left-aligned on a glass panel with a small AI avatar.
 *              `pending` swaps the body for an animated typing indicator.
 * - system:    centered, quiet meta line.
 * Notification-kind messages render inside a highlighted brand card.
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
        <span className="text-xs text-muted-foreground">{text}</span>
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
          "max-w-[82%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? cn(
                gradients.brand,
                "rounded-br-md text-primary-foreground shadow-soft"
              )
            : kind === "notification"
              ? "rounded-bl-md border border-brand-500/25 bg-accent text-accent-foreground shadow-soft"
              : "glass-panel rounded-bl-md text-foreground"
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
      className={cn(
        "flex size-7 shrink-0 items-center justify-center rounded-full text-primary-foreground shadow-glow",
        gradients.brand
      )}
      aria-hidden
    >
      <Icon className="size-3.5" />
    </div>
  );
}

/** Three bouncing dots — the assistant "thinking" indicator. */
function TypingDots() {
  return (
    <div className="flex items-center gap-1 py-1" aria-label="Assistant is typing">
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

// re-export so callers can spread the User icon if needed elsewhere
export { User };
