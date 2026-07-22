// Typed API client for the Budget Meal Planner backend (FastAPI on :8000).
import type {
  ParsedIntake,
  PlanSummary,
  PlanFull,
  WalletSummary,
  DishAlternative,
  NotifyPayload,
  SwiggyAddress,
  ChatResponse,
  ChatSessionState,
  Constraint,
  AppetiteLevel,
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

  getMode: () => req<{ mode: string; live: boolean }>("/mode"),

  createUser: (name: string, area?: string) =>
    req<{ user_id: number }>("/user", { method: "POST", body: { name, area } }),

  addresses: () =>
    req<{ addresses: SwiggyAddress[] }>("/mcp/addresses"),

  intake: (user_id: number, text: string) =>
    req<ParsedIntake>("/intake", { method: "POST", body: { user_id, text } }),

  // Backend merges across turns via session_state.extracted — pass the prior
  // turn's `extracted` back in each call.
  chat: (user_id: number, message: string, prior?: ChatSessionState) =>
    req<ChatResponse>("/chat", {
      method: "POST",
      body: { user_id, message, session_state: prior ? { extracted: prior } : undefined },
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
  }) => req<PlanSummary>("/plan", { method: "POST", body: input }),

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

  alternatives: (slot_id: number, band = 100, veg_only = false) =>
    req<{ alternatives: DishAlternative[] }>(
      `/slot/${slot_id}/alternatives?band=${band}&veg_only=${veg_only}`
    ),

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
