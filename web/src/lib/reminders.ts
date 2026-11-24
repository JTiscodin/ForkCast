// Meal-time reminders are a per-device choice, so they live in this browser only.
// Web Push (public/sw.js + backend VAPID) delivers them with no tab open; the in-page path is the fallback.
import { api } from "@/lib/api";

const KEY = "forkcast.reminders";
const PUSH_KEY = "forkcast.push";

export function remindersOn(): boolean {
  try {
    return typeof window !== "undefined" && localStorage.getItem(KEY) === "1" && "Notification" in window && Notification.permission === "granted";
  } catch {
    return false;
  }
}

export function setReminders(on: boolean) {
  try {
    if (on) localStorage.setItem(KEY, "1");
    else localStorage.removeItem(KEY);
  } catch {
    /* storage blocked: reminders just stay off */
  }
}

/** Milliseconds from `now` until today's HH:MM, or null if that time has passed. */
export function msUntil(hhmm: string, now = new Date()): number | null {
  const [h, m] = hhmm.split(":").map(Number);
  const at = new Date(now);
  at.setHours(h, m, 0, 0);
  const ms = at.getTime() - now.getTime();
  return ms > 0 ? ms : null;
}

/** True when this browser has a live Web Push subscription, so the server sends the reminders. */
export function pushOn(): boolean {
  try {
    return typeof window !== "undefined" && localStorage.getItem(PUSH_KEY) === "1";
  } catch {
    return false;
  }
}

function b64ToBytes(b64: string) {
  const raw = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** Register the service worker and subscribe this browser for server push. Returns false where unsupported. */
export async function enablePush(userId: number): Promise<boolean> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return false;
  const reg = await navigator.serviceWorker.register("/sw.js");
  await navigator.serviceWorker.ready;
  const { key } = await api.vapidKey();
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) }));
  await api.pushSubscribe(userId, sub.toJSON());
  try {
    localStorage.setItem(PUSH_KEY, "1");
  } catch {
    /* storage blocked: in-page reminder may duplicate the push one */
  }
  return true;
}

/** Stop server push. Throws when the server call fails; the flag then stays on, since the server keeps pushing. */
export async function disablePush(userId: number) {
  const sub = "serviceWorker" in navigator ? await (await navigator.serviceWorker.getRegistration())?.pushManager.getSubscription() : null;
  await api.pushUnsubscribe(userId, sub?.endpoint);
  try {
    localStorage.removeItem(PUSH_KEY);
  } catch {
    /* ignore */
  }
  await sub?.unsubscribe();
}
