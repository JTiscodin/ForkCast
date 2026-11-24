// Client-side session persistence via localStorage.
//
// We store only NON-SENSITIVE app state so a refresh doesn't lose the user's
// place: their local user_id, name, chosen delivery address, and the current
// plan/month. The Swiggy OAuth token NEVER touches localStorage — it lives
// server-side in the backend's .env only.

import type { SwiggyAddress } from "./types";

const KEY = "meal-planner:session:v1";

export interface Session {
  userId: number | null;
  token?: string;      // per-user API token from POST /user (not the Swiggy token)
  name: string;
  address: SwiggyAddress | null;
}

const EMPTY: Session = {
  userId: null,
  name: "",
  address: null,
};

export function loadSession(): Session {
  if (typeof window === "undefined") return { ...EMPTY };
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return { ...EMPTY };
    return { ...EMPTY, ...(JSON.parse(raw) as Partial<Session>) };
  } catch {
    return { ...EMPTY };
  }
}

export function saveSession(patch: Partial<Session>) {
  if (typeof window === "undefined") return;
  try {
    const next = { ...loadSession(), ...patch };
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* quota / disabled storage — ignore, app still works in-memory */
  }
}

/** Remove this browser's per-device Forkcast settings (reminder and push flags). */
function clearForkcastKeys() {
  for (const k of Object.keys(window.localStorage)) {
    if (k.startsWith("forkcast.")) window.localStorage.removeItem(k);
  }
}

export function clearSession() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(KEY);
    clearForkcastKeys();
  } catch {
    /* ignore */
  }
}
