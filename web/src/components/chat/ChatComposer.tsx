"use client";

import * as React from "react";
import { Send } from "lucide-react";

import { cn } from "@/lib/utils";
import { gradients, focusRing } from "@/lib/design";
import { Input } from "@/components/ui/input";

export interface ChatComposerProps {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
}

/**
 * Bottom-pinned input bar. Text field + brand-gradient send button.
 * Enter sends; the button and field disable while a turn is in flight.
 */
export function ChatComposer({
  onSend,
  disabled,
  placeholder = "Describe your meal plan…",
  className,
}: ChatComposerProps) {
  const [value, setValue] = React.useState("");

  const submit = React.useCallback(() => {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue("");
  }, [value, disabled, onSend]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  const canSend = value.trim().length > 0 && !disabled;

  return (
    <div
      className={cn(
        "flex items-center gap-2 border-t border-border bg-surface/60 px-3 py-3 backdrop-blur",
        className
      )}
    >
      <Input
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        aria-label="Message"
        className="h-10 flex-1 rounded-xl text-sm"
      />
      <button
        type="button"
        onClick={submit}
        disabled={!canSend}
        aria-label="Send message"
        className={cn(
          "flex size-10 shrink-0 items-center justify-center rounded-xl text-primary-foreground transition-all",
          "shadow-soft hover:shadow-glow active:translate-y-px",
          "disabled:pointer-events-none disabled:opacity-40",
          gradients.brand,
          focusRing
        )}
      >
        <Send className="size-4" />
      </button>
    </div>
  );
}
