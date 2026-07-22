"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";
import { gradients } from "@/lib/design";
import { api } from "@/lib/api";
import type { ChatSessionState, NotifyPayload } from "@/lib/types";

import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageBubble } from "./MessageBubble";
import { QuickReplies } from "./QuickReplies";
import { ChatComposer } from "./ChatComposer";
import type { ChatMessage, QuickReply } from "./types";

export interface ChatPaneProps {
  userId: number;
  /** Fired once the backend reports action === "ready_to_plan". */
  onReadyToPlan: (extracted: ChatSessionState) => void;
  /** Wire the Yes/No/Later/Something-else meal-notification replies. */
  onRespondSlot?: (slotId: number, answer: string) => Promise<void>;
  /** Queue of meal prompts to surface as notification bubbles. */
  notifications?: NotifyPayload[];
  className?: string;
}

const ONBOARDING_SUGGESTIONS: QuickReply[] = [
  { label: "₹10k, 10 paneer meals, veg, heavy eater", value: "₹10k, 10 paneer meals, veg, heavy eater" },
  { label: "₹15k, mix of veg & non-veg", value: "₹15k, mix of veg & non-veg" },
  { label: "Just breakfast & lunch, ₹6k", value: "Just breakfast & lunch, ₹6k" },
];

const APPETITE_CHIPS: QuickReply[] = [
  { label: "Light", value: "Light appetite" },
  { label: "Moderate", value: "Moderate appetite" },
  { label: "Heavy", value: "Heavy appetite" },
  { label: "Very heavy", value: "Very heavy appetite" },
];

const NOTIFY_REPLIES: QuickReply[] = [
  { label: "Yes", value: "yes" },
  { label: "No", value: "no" },
  { label: "Later", value: "later" },
  { label: "Something else", value: "other" },
];

let _seq = 0;
const uid = (p: string) => `${p}-${Date.now()}-${_seq++}`;

/**
 * The conversational left pane. Owns its message list, threads the merged
 * `extracted` session state across turns, and surfaces meal notifications.
 */
export function ChatPane({
  userId,
  onReadyToPlan,
  onRespondSlot,
  notifications,
  className,
}: ChatPaneProps) {
  const [messages, setMessages] = React.useState<ChatMessage[]>(() => [
    {
      id: uid("greet"),
      role: "assistant",
      text: "Hey! I'm your meal planner. Tell me your monthly budget and what you're craving — veg or non-veg, any must-have dishes, how big your appetite runs — and I'll build a plan that fits.",
      kind: "text",
    },
    {
      id: uid("greet-chips"),
      role: "assistant",
      text: "",
      kind: "quick_replies",
      quickReplies: ONBOARDING_SUGGESTIONS,
    },
  ]);
  const [sending, setSending] = React.useState(false);

  // Merged extraction across turns — passed back to the backend each call.
  const extractedRef = React.useRef<ChatSessionState>({});
  // Track which notification slot_ids we've already surfaced.
  const seenSlotsRef = React.useRef<Set<number>>(new Set());
  const readyFiredRef = React.useRef(false);

  // -- Auto-scroll to the newest message -----------------------------------
  const scrollRootRef = React.useRef<HTMLDivElement>(null);
  const scrollToBottom = React.useCallback(() => {
    const root = scrollRootRef.current;
    if (!root) return;
    const viewport = root.querySelector<HTMLElement>(
      '[data-slot="scroll-area-viewport"]'
    );
    if (viewport) {
      viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
    }
  }, []);

  React.useEffect(() => {
    // rAF so layout settles (entrance animations) before we measure.
    const raf = requestAnimationFrame(scrollToBottom);
    return () => cancelAnimationFrame(raf);
  }, [messages, scrollToBottom]);

  // -- Surface incoming meal notifications ---------------------------------
  React.useEffect(() => {
    if (!notifications?.length) return;
    const fresh = notifications.filter(
      (n) => !seenSlotsRef.current.has(n.slot_id)
    );
    if (!fresh.length) return;
    fresh.forEach((n) => seenSlotsRef.current.add(n.slot_id));

    setMessages((prev) => [
      ...prev,
      ...fresh.flatMap((n): ChatMessage[] => [
        {
          id: uid("notify"),
          role: "assistant",
          text: n.prompt,
          kind: "notification",
          slotId: n.slot_id,
        },
        {
          id: uid("notify-chips"),
          role: "assistant",
          text: "",
          kind: "quick_replies",
          quickReplies: NOTIFY_REPLIES,
          slotId: n.slot_id,
        },
      ]),
    ]);
  }, [notifications]);

  // -- Core send flow ------------------------------------------------------
  const send = React.useCallback(
    async (text: string) => {
      if (sending) return;
      setSending(true);

      const pendingId = uid("pending");
      setMessages((prev) => [
        ...prev,
        { id: uid("user"), role: "user", text, kind: "text" },
        { id: pendingId, role: "assistant", text: "", kind: "text", pending: true },
      ]);

      try {
        const prior = extractedRef.current;
        const res = await api.chat(
          userId,
          text,
          Object.keys(prior).length ? prior : undefined
        );

        // Merge extraction forward for the next turn.
        extractedRef.current = { ...extractedRef.current, ...res.extracted };

        const replyMsgs: ChatMessage[] = [
          {
            id: uid("reply"),
            role: "assistant",
            text: res.reply,
            kind: "text",
          },
        ];

        // Offer appetite chips when that's the missing field.
        if (
          res.action === "need_more" &&
          res.missing?.includes("appetite_level")
        ) {
          replyMsgs.push({
            id: uid("appetite"),
            role: "assistant",
            text: "",
            kind: "quick_replies",
            quickReplies: APPETITE_CHIPS,
          });
        }

        setMessages((prev) =>
          prev
            .filter((m) => m.id !== pendingId)
            .concat(replyMsgs)
        );

        if (res.action === "ready_to_plan" && !readyFiredRef.current) {
          readyFiredRef.current = true;
          setMessages((prev) => [
            ...prev,
            {
              id: uid("building"),
              role: "system",
              text: "Building your plan…",
              kind: "text",
            },
          ]);
          onReadyToPlan(extractedRef.current);
        }
      } catch {
        setMessages((prev) =>
          prev
            .filter((m) => m.id !== pendingId)
            .concat({
              id: uid("error"),
              role: "assistant",
              text: "Sorry — something went wrong reaching the planner. Mind trying that again?",
              kind: "text",
            })
        );
      } finally {
        setSending(false);
      }
    },
    [sending, userId, onReadyToPlan]
  );

  // -- Quick-reply / notification pick -------------------------------------
  const handlePick = React.useCallback(
    (value: string, msg: ChatMessage) => {
      // Meal-notification chip → answer the slot, not the chat endpoint.
      if (msg.slotId != null && isNotifyValue(value)) {
        // Echo the user's choice and drop the chip row.
        setMessages((prev) =>
          prev
            .filter((m) => m.id !== msg.id)
            .concat({
              id: uid("user"),
              role: "user",
              text: notifyLabel(value),
              kind: "text",
            })
        );
        void onRespondSlot?.(msg.slotId, value);
        return;
      }

      // Onboarding / appetite chip → drop the row, send as a normal message.
      setMessages((prev) => prev.filter((m) => m.id !== msg.id));
      void send(value);
    },
    [onRespondSlot, send]
  );

  return (
    <div
      className={cn(
        "flex h-full min-h-0 flex-col overflow-hidden bg-surface/40",
        className
      )}
    >
      <ChatHeader />

      <div ref={scrollRootRef} className="min-h-0 flex-1 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="flex flex-col gap-4 px-4 py-5">
          <AnimatePresence initial={false}>
            {messages.map((m) =>
              m.kind === "quick_replies" ? (
                <motion.div
                  key={m.id}
                  layout
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0, height: 0 }}
                  className="flex pl-9"
                >
                  <QuickReplies
                    replies={m.quickReplies ?? []}
                    disabled={sending}
                    onPick={(v) => handlePick(v, m)}
                  />
                </motion.div>
              ) : (
                <MessageBubble key={m.id} message={m} />
              )
            )}
          </AnimatePresence>
          </div>
        </ScrollArea>
      </div>

      <ChatComposer onSend={send} disabled={sending} />
    </div>
  );
}

function ChatHeader() {
  return (
    <div className="flex items-center gap-2.5 border-b border-border bg-surface/60 px-4 py-3 backdrop-blur">
      <div
        className={cn(
          "flex size-8 items-center justify-center rounded-xl text-primary-foreground shadow-glow",
          gradients.brand
        )}
        aria-hidden
      >
        <Sparkles className="size-4" />
      </div>
      <div className="min-w-0">
        <p className="font-display text-sm font-semibold leading-tight">
          Meal Planner
        </p>
        <p className="truncate text-xs text-muted-foreground">
          Let&apos;s build your month
        </p>
      </div>
    </div>
  );
}

function isNotifyValue(v: string): v is "yes" | "no" | "later" | "other" {
  return v === "yes" || v === "no" || v === "later" || v === "other";
}

function notifyLabel(v: string): string {
  return (
    NOTIFY_REPLIES.find((r) => r.value === v)?.label ?? v
  );
}
