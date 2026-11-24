import { clearSession, loadSession, saveSession } from "./session";
// Typed API client for the Forkcast backend (FastAPI on :8000).
import type {
  SwiggyAddress,
  DailyProfile,
  TodayView,
  OrderOutcome,
  MemoryBullet,
  DietPlanProposal,
  ChatAnswer,
  CardItem,
  MenuCard,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8343";

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
    headers: {
      "Content-Type": "application/json",
      ...(loadSession().token ? { Authorization: `Bearer ${loadSession().token}` } : {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      // FastAPI 422 detail is a list of {loc, msg}; flatten it so toasts stay readable
      detail = Array.isArray(j.detail)
        ? j.detail.map((d: { loc?: unknown[]; msg?: string }) => `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg}`).join("; ")
        : (j.detail ?? detail);
    } catch {
      /* ignore */
    }
    if (res.status === 403 && /sign in again/i.test(detail)) {
      // our session token is missing or no longer valid: start onboarding fresh
      clearSession();
      if (typeof window !== "undefined") window.location.reload();
    }
    throw new ApiError(res.status, detail);
  }
  // sliding session: the backend sends a renewed token with every signed-in response
  const fresh = res.headers.get("X-Forkcast-Token");
  if (fresh) saveSession({ token: fresh });
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
  authStart: (popup = false) =>
    req<{ status: string }>(`/auth/swiggy/start${popup ? "?popup=true" : ""}`, { method: "POST" }),
  authStatus: () =>
    req<{ status: "idle" | "running" | "connected" | "failed"; error: string | null; live: boolean; url?: string | null }>(
      "/auth/swiggy/status"
    ),
  authLogout: () =>
    req<{ live: boolean }>("/auth/swiggy/logout", { method: "POST" }),

  createUser: (name: string, area?: string, address_id?: string) =>
    req<{ user_id: number; token: string; returning?: boolean }>("/user", { method: "POST", body: { name, area, address_id } }),

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

  // ---- daily personalization ----
  dailyProfile: (user_id: number) =>
    req<{ profile: DailyProfile | null; quiz_picks: string[]; city_guess: string | null }>(`/daily/${user_id}/profile`),
  saveDailyProfile: (user_id: number, body: Partial<DailyProfile> & { quiz_picks?: string[] }) =>
    req<{ profile: DailyProfile; history_items: number }>(`/daily/${user_id}/profile`, {
      method: "POST",
      body,
    }),
  quiz: (diet: string) => req<{ dishes: string[] }>(`/daily/quiz?diet=${diet}`),
  today: (user_id: number) => req<TodayView>(`/daily/${user_id}/today`),
  vapidKey: () => req<{ key: string }>("/push/vapid-public-key"),
  pushSubscribe: (user_id: number, sub: PushSubscriptionJSON) =>
    req<{ status: string }>(`/daily/${user_id}/push`, { method: "POST", body: sub }),
  pushUnsubscribe: (user_id: number, endpoint?: string) =>
    req<{ status: string }>(`/daily/${user_id}/push${endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : ""}`, {
      method: "DELETE",
    }),
  regenerate: (user_id: number, slot?: string) =>
    req<{ ok: boolean }>(`/daily/${user_id}/regenerate${slot ? `?slot=${slot}` : ""}`, {
      method: "POST",
    }),
  readDietPlan: (user_id: number, mime: string, data: string) =>
    req<{ proposal: DietPlanProposal }>(`/daily/${user_id}/diet-plan`, { method: "POST", body: { mime, data } }),
  applyDietPlan: (user_id: number, proposal: DietPlanProposal) =>
    req<{ profile: DailyProfile }>(`/daily/${user_id}/diet-plan/apply`, { method: "POST", body: { proposal } }),
  deleteAccount: (user_id: number) => req<{ deleted: number }>(`/daily/${user_id}`, { method: "DELETE" }),
  cardOptions: (user_id: number, card_id: number) =>
    req<{ sides: (CardItem & { group?: string })[]; addons: CardItem[] }>(`/daily/${user_id}/card/${card_id}/options`),
  editCard: (user_id: number, card_id: number, body: { sides: { id: string; quantity: number }[]; addons: { id: string; quantity: number }[] }) =>
    req<MenuCard>(`/daily/${user_id}/card/${card_id}/edit`, { method: "POST", body }),
  orderCard: (user_id: number, card_id: number, preview = false, address_id?: string) => {
    const q = new URLSearchParams();
    if (preview) q.set("preview", "true");
    if (address_id) q.set("address_id", address_id);
    return req<OrderOutcome>(`/daily/${user_id}/order/${card_id}${q.size ? `?${q}` : ""}`, { method: "POST" });
  },
  feedback: (user_id: number, card_id: number, type: string, value?: number) =>
    req<{ ok: boolean }>(`/daily/${user_id}/feedback`, {
      method: "POST",
      body: { card_id, type, value },
    }),
  logMeal: (user_id: number, slot: string, kind: string, text = "") =>
    req<{ nutrients: Record<string, number> }>(`/daily/${user_id}/log`, {
      method: "POST",
      body: { slot, kind, text },
    }),
  memory: (user_id: number) =>
    req<{ facts: string[]; bullets: MemoryBullet[] }>(`/daily/${user_id}/memory`),
  editMemory: (
    user_id: number,
    body: { dimension: string; key: string; weight?: number; delete?: boolean; block?: boolean }
  ) =>
    req<{ facts: string[]; bullets: MemoryBullet[] }>(`/daily/${user_id}/memory`, {
      method: "POST",
      body,
    }),
  agent: (user_id: number, message: string) =>
    req<ChatAnswer>(`/daily/${user_id}/agent`, { method: "POST", body: { message } }),
};

export { ApiError };
