"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { prefersReducedMotion } from "@/lib/motion";
import type { Blueprint, NotifyPayload } from "@/lib/types";

import { ScrollArea } from "@/components/ui/scroll-area";
import { LottiePlayer } from "@/components/ui/LottiePlayer";
import { MessageBubble } from "./MessageBubble";
import { QuickReplies } from "./QuickReplies";
import { ChatComposer } from "./ChatComposer";
import { OverviewCard } from "./OverviewCard";
import type { ChatMessage, QuickReply } from "./types";

export interface ChatPaneProps {
  userId: number;
  /** Build a plan from the gathered blueprint (deterministic — no LLM). */
  onGenerate: (blueprint: Blueprint) => Promise<void> | void;
  /** True while a plan build is in flight (drives the Generate button spinner). */
  generating?: boolean;
  /** True once a plan already exists — enables conversational tweaks. */
  hasPlan?: boolean;
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
  onGenerate,
  generating,
  hasPlan,
  onRespondSlot,
  notifications,
  className,
}: ChatPaneProps) {
  const [messages, setMessages] = React.useState<ChatMessage[]>(() => [
    {
      id: uid("greet"),
      role: "assistant",
      text: "Hey! I'm Forkcast. Tell me your monthly budget and what you're craving: veg or non-veg, any must-have dishes, how big your appetite runs. I'll build a plan that fits.",
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

  // Running blueprint across turns — echoed back to the backend each call so
  // context stays compact (no full-transcript resend).
  const blueprintRef = React.useRef<Blueprint | undefined>(undefined);
  // Track which notification slot_ids we've already surfaced.
  const seenSlotsRef = React.useRef<Set<number>>(new Set());

  // -- Auto-scroll to the newest message -----------------------------------
  const scrollRootRef = React.useRef<HTMLDivElement>(null);
  const scrollToBottom = React.useCallback(() => {
    const root = scrollRootRef.current;
    if (!root) return;
    const viewport = root.querySelector<HTMLElement>(
      '[data-slot="scroll-area-viewport"]'
    );
    if (viewport) {
      // Programmatic scrolling bypasses the CSS scroll-behavior reduced-motion
      // rule, so branch on the media query here too.
      const behavior = prefersReducedMotion() ? "auto" : "smooth";
      viewport.scrollTo({ top: viewport.scrollHeight, behavior });
    }
  }, []);

  React.useEffect(() => {
    // rAF so layout settles (entrance animations) before we measure.
    const raf = requestAnimationFrame(scrollToBottom);
    return () => cancelAnimationFrame(raf);
  }, [messages, scrollToBottom]);

  // Presentational: keep the cooking banner in view once it appears.
  React.useEffect(() => {
    if (!generating) return;
    const raf = requestAnimationFrame(scrollToBottom);
    return () => cancelAnimationFrame(raf);
  }, [generating, scrollToBottom]);

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
        // Once a plan exists, further chat is a TWEAK: adjust the blueprint and
        // rebuild deterministically. Before that, it's the gathering conversation.
        if (hasPlan && blueprintRef.current) {
          const res = await api.chatAdjust(userId, text, blueprintRef.current);
          blueprintRef.current = res.blueprint;
          setMessages((prev) =>
            prev
              .filter((m) => m.id !== pendingId)
              .concat({ id: uid("reply"), role: "assistant", text: res.reply, kind: "text" })
          );
          await onGenerate(res.public); // rebuild with the adjusted blueprint
          setSending(false);
          return;
        }

        const res = await api.chat(userId, text, blueprintRef.current);
        blueprintRef.current = res.blueprint;

        const replyMsgs: ChatMessage[] = [
          { id: uid("reply"), role: "assistant", text: res.reply, kind: "text" },
        ];

        // Offer appetite chips while appetite is still missing.
        const bpAppetite = res.blueprint?.appetite_level;
        if (!res.ready && res.blueprint?.budget != null && bpAppetite == null) {
          replyMsgs.push({
            id: uid("appetite"),
            role: "assistant",
            text: "",
            kind: "quick_replies",
            quickReplies: APPETITE_CHIPS,
          });
        }

        // When ready, drop the OverviewCard bubble with a Generate Plan button.
        if (res.ready) {
          replyMsgs.push({
            id: uid("overview"),
            role: "assistant",
            text: "",
            kind: "overview",
            blueprint: res.blueprint,
          });
        }

        setMessages((prev) => prev.filter((m) => m.id !== pendingId).concat(replyMsgs));
      } catch {
        setMessages((prev) =>
          prev
            .filter((m) => m.id !== pendingId)
            .concat({
              id: uid("error"),
              role: "assistant",
              text: "Sorry, something went wrong reaching the planner. Mind trying that again?",
              kind: "text",
            })
        );
      } finally {
        setSending(false);
      }
    },
    [sending, userId, hasPlan, onGenerate]
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

  // Inline edits on an overview card update both that bubble and the running ref.
  const handleOverviewEdit = React.useCallback(
    (msgId: string, patch: Partial<Blueprint>) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId && m.blueprint
            ? { ...m, blueprint: { ...m.blueprint, ...patch } }
            : m
        )
      );
      if (blueprintRef.current) {
        blueprintRef.current = { ...blueprintRef.current, ...patch };
      }
    },
    []
  );

  return (
    <div
      className={cn(
        "flex h-full min-h-0 flex-col overflow-hidden border-r border-border bg-surface",
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
              ) : m.kind === "overview" && m.blueprint ? (
                <div key={m.id} className="pl-9">
                  <OverviewCard
                    blueprint={m.blueprint}
                    generating={generating}
                    onEdit={(patch) => handleOverviewEdit(m.id, patch)}
                    onGenerate={() => {
                      const bp = messages.find((x) => x.id === m.id)?.blueprint;
                      if (bp) void onGenerate(bp);
                    }}
                  />
                </div>
              ) : (
                <MessageBubble key={m.id} message={m} />
              )
            )}
          </AnimatePresence>

          {/* Plan-build moment: slim cooking banner while `generating`. */}
          <AnimatePresence>
            {generating && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="pl-9"
              >
                <div
                  role="status"
                  aria-live="polite"
                  className="flex items-center gap-3 rounded-xl border border-border bg-brand-50 px-4 py-2.5"
                >
                  <LottiePlayer
                    path="/animations/cooking-pot.json"
                    className="h-20 w-20 shrink-0"
                  />
                  <p className="min-w-0 text-sm leading-[1.4] text-muted-foreground">
                    Building your month…
                  </p>
                </div>
              </motion.div>
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
    <div className="flex items-center gap-2.5 border-b border-border bg-card px-4 py-3">
      <div
        className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-500 text-white"
        aria-hidden
      >
        <Sparkles className="size-4" strokeWidth={2.4} />
      </div>
      <div className="min-w-0">
        <h2 className="font-heading text-sm font-extrabold leading-[1.4] tracking-[-0.02em] text-foreground">
          Forkcast
        </h2>
        <p className="truncate text-sm leading-[1.4] text-muted-foreground">
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
