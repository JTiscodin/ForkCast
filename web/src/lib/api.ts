// Typed API client for the Budget Meal Planner backend (FastAPI on :8000).
import type {
  ParsedIntake,
  PlanSummary,
  PlanFull,
  WalletSummary,
  DishAlternative,
  MealSlot,
  NotifyPayload,
  SwiggyAddress,
  ChatResponse,
  Constraint,
  AppetiteLevel,
  Blueprint,
  AdjustResponse,
  MealType,
  FeasibilityReport,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function req<T>(
  path: string,
  opts: { method?: string; body?: unknown } = {}
): Promise<T> {
  const res = await fetch(BASE + path, {
    method: opts.method ?? "GET",
    headers: { "Content-Type": "application/json" },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  base: BASE,

  getMode: () =>
    req<{
      mode: string;
      live: boolean;
      needs_auth: boolean;
      /** Saved Swiggy JWT is past expiry — UI should prompt + auto-open re-login. */
      token_expired: boolean;
    }>("/mode"),

  // ---- Swiggy in-app OAuth login ----
  authStart: () =>
    req<{ status: string }>("/auth/swiggy/start", { method: "POST" }),
  authStatus: () =>
    req<{ status: "idle" | "running" | "connected" | "failed"; error: string | null; live: boolean }>(
      "/auth/swiggy/status"
    ),
  authLogout: () =>
    req<{ live: boolean }>("/auth/swiggy/logout", { method: "POST" }),

  createUser: (name: string, area?: string) =>
    req<{ user_id: number }>("/user", { method: "POST", body: { name, area } }),

  addresses: () =>
    req<{ addresses: SwiggyAddress[] }>("/mcp/addresses"),

  /**
   * Pin the addressId all live searches and orders run against. Called with
   * the user's onboarding pick, and again on session restore so a reload
   * re-syncs the backend (which otherwise falls back to the first saved
   * Swiggy address).
   */
  setAddress: (address_id: string) =>
    req<{ status: string; address_id: string }>("/address", {
      method: "POST",
      body: { address_id },
    }),

  intake: (user_id: number, text: string) =>
    req<ParsedIntake>("/intake", { method: "POST", body: { user_id, text } }),

  // Conversational blueprint builder. Echo the prior turn's `blueprint` back so
  // the backend keeps context compact (no full-transcript resend). `history` is
  // the last few messages, used only to nudge the LLM.
  chat: (
    user_id: number,
    message: string,
    blueprint?: Blueprint,
    history?: { role: string; text: string }[]
  ) =>
    req<ChatResponse>("/chat", {
      method: "POST",
      body: { user_id, message, blueprint: blueprint ?? {}, history: history ?? [] },
    }),

  // Apply a natural-language tweak to an existing blueprint ("make it cheaper").
  chatAdjust: (user_id: number, message: string, blueprint: Blueprint) =>
    req<AdjustResponse>("/chat/adjust", {
      method: "POST",
      body: { user_id, message, blueprint },
    }),

  setAppetite: (
    user_id: number,
    appetite_level: AppetiteLevel,
    roti_per_meal?: number,
    rice_katori_per_meal?: number
  ) =>
    req("/appetite", {
      method: "POST",
      body: { user_id, appetite_level, roti_per_meal, rice_katori_per_meal },
    }),

  makePlan: (input: {
    user_id: number;
    month: string;
    budget: number;
    constraints?: Constraint[];
    veg_only?: boolean;
    days?: number;
    /** Which slots to plan. Omit for all three. */
    meals?: MealType[];
    /** Fetch protein-rich dishes — changes the search, not just a filter. */
    high_protein?: boolean;
    /** Taste/diet/dietary profile → backend TasteProfile hard filters + re-rank. */
    taste_prefs?: Record<string, unknown>;
  }) => req<PlanSummary>("/plan", { method: "POST", body: input }),

  /**
   * Why a budget doesn't fit and what specifically would fix it. Probes the
   * deterministic optimizer across budget / meals / appetite, so the UI can
   * give real numbers instead of generic "raise your budget" advice.
   */
  planFeasibility: (input: {
    user_id: number;
    month: string;
    budget: number;
    constraints?: Constraint[];
    veg_only?: boolean;
    days?: number;
    meals?: MealType[];
    high_protein?: boolean;
  }) =>
    req<FeasibilityReport>("/plan/feasibility", {
      method: "POST",
      body: input,
    }),

  getPlan: (plan_id: number) => req<PlanFull>(`/plan/${plan_id}`),

  approvePlan: (plan_id: number) =>
    req<{ status: string; wallet: WalletSummary }>(
      `/plan/${plan_id}/approve`,
      { method: "POST" }
    ),

  notifySlot: (slot_id: number) =>
    req<NotifyPayload>(`/slot/${slot_id}/notify`, { method: "POST" }),

  respondSlot: (
    slot_id: number,
    answer: "yes" | "no" | "later" | "other",
    extra?: { new_day?: number; new_meal_type?: string }
  ) =>
    req<Record<string, unknown>>(`/slot/${slot_id}/respond`, {
      method: "POST",
      body: { answer, ...extra },
    }),

  alternatives: (slot_id: number, opts?: { veg_only?: boolean }) =>
    req<{ alternatives: DishAlternative[] }>(
      `/slot/${slot_id}/alternatives?band=100${opts?.veg_only ? "&veg_only=true" : ""}`
    ),

  /** Persist a chosen alternative into the slot (survives refresh). */
  swapSlot: (slot_id: number, alt: DishAlternative) =>
    req<{ slot: MealSlot }>(`/slot/${slot_id}/swap`, {
      method: "POST",
      body: alt,
    }),

  why: (slot_id: number) =>
    req<{ slot_id: number; why: string; cached: boolean }>(
      `/slot/${slot_id}/why`
    ),

  wallet: (user_id: number, month: string) =>
    req<WalletSummary>(`/wallet/${user_id}/${month}`),

  closeMonth: (user_id: number, month: string) =>
    req<{ rolled_over: number }>(`/wallet/${user_id}/${month}/close`, {
      method: "POST",
    }),
};

export { ApiError };
