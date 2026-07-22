// Local chat UI message model. Distinct from the wire types in src/lib/types.ts —
// this is what the ChatPane renders. Map ChatResponse → ChatMessage in ChatPane.

export type ChatRole = "user" | "assistant" | "system";

export type ChatMessageKind = "text" | "quick_replies" | "notification";

export interface QuickReply {
  label: string;
  value: string;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  kind?: ChatMessageKind;
  /** Quick-reply chips shown attached to (or as) this message. */
  quickReplies?: QuickReply[];
  /** For notification bubbles — the meal slot this prompt is about. */
  slotId?: number;
  /** Assistant message awaiting a response — renders the typing indicator. */
  pending?: boolean;
}
