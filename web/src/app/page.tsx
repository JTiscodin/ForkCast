"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MotionConfig } from "framer-motion";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type { DailyProfile, SwiggyAddress } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Onboarding } from "@/components/app/Onboarding";
import { loadSession, saveSession } from "@/lib/session";
import { AppHeader } from "@/components/app/AppHeader";
import { TodayView } from "@/components/daily/TodayView";
import { DailyOnboarding } from "@/components/daily/DailyOnboarding";

export default function Home() {
  // session — start EMPTY so the server-rendered HTML matches the first client
  // render (localStorage isn't available on the server). We restore the saved
  // session in the mount effect below, which flips `ready` on the client only,
  // so there's no SSR/client hydration mismatch.
  const [userId, setUserId] = useState<number | null>(null);
  const [live, setLive] = useState(false);
  const [needsAuth, setNeedsAuth] = useState(false);
  // Until /mode answers we don't know whether the Connect Swiggy step is needed.
  const [modeKnown, setModeKnown] = useState(false);
  const [address, setAddress] = useState<SwiggyAddress | null>(null);
  const [ready, setReady] = useState<boolean>(false); // onboarding complete

  // ---- Swiggy login expired ----
  // The saved Swiggy JWT is short-lived and no refresh token is persisted, so it
  // dies mid-session. Go back to the Connect Swiggy step: the user's tap there
  // opens the login popup (a login started from here would open a browser on the server).
  const handleTokenExpired = useCallback(() => {
    setReady(false);
    setLive(false);
    setNeedsAuth(true);
    toast.info("Your Swiggy login expired. Connect again to see live menus.");
  }, []);

  // ---- boot (client-only): restore session + detect mode ----
  useEffect(() => {
    let cancelled = false;
    const saved = loadSession();

    // restore the local session after mount, deferred a tick so we're not calling
    // setState synchronously in the effect body (React 19 rule) — and so the first
    // client render still matches the server (both show the loader, no hydration
    // mismatch), then this promotes to the app.
    if (saved.userId) {
      queueMicrotask(() => {
        if (cancelled) return;
        setUserId(saved.userId);
        setAddress(saved.address);
        setReady(true);
      });
      // Re-sync the saved address pick to the backend — it doesn't persist
      // across backend restarts, and without this a reload would silently
      // fall back to the first saved Swiggy address for searches/orders.
      if (saved.address?.id) {
        api.setAddress(saved.address.id).catch(() => {});
      }
    }

    api
      .getMode()
      .then((m) => {
        if (cancelled) return;
        setLive(m.live);
        setNeedsAuth(Boolean(m.needs_auth));
        setModeKnown(true);
        // Boot with a dead saved JWT: back to the Connect step.
        if (m.token_expired && !m.live) handleTokenExpired();
      })
      .catch(() => {
        if (!cancelled) {
          setLive(false);
          setNeedsAuth(false);
          setModeKnown(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [handleTokenExpired]);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;   // strict mode mounts twice; the first cleanup must not stick
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Re-check mode after an in-app Swiggy connect. Runtime initialization resets
  // the backend address, so re-apply the address currently shown in the UI.
  const recheckMode = useCallback(async () => {
    try {
      const m = await api.getMode();
      if (m.live) {
        // Runtime initialization resets the backend address. Refresh the account's
        // current list before re-pinning, so an old account's address is never sent.
        const current = await api.addresses().catch(() => ({ addresses: [] }));
        const next = current.addresses.find((item) => item.id === address?.id)
          ?? current.addresses[0]
          ?? null;
        // without a session the call is refused and the 403 would sign the user out; handleStart pins it later
        if (next?.id && loadSession()?.token) {
          await api.setAddress(next.id).catch(() => {});
          if (mountedRef.current) setAddress(next);
        }
      }
      if (mountedRef.current) {
        setLive(m.live);
        setNeedsAuth(Boolean(m.needs_auth));
      }
      return m;
    } catch {
      return null;
    }
  }, [address]);

  // Someone already signed in (their Swiggy login had expired) goes straight back
  // to their meals; going through onboarding again would start a new account.
  const handleConnected = useCallback(async () => {
    const m = await recheckMode();
    if (m?.live && userId) setReady(true);
  }, [recheckMode, userId]);

  // ---- onboarding finish ----
  const handleStart = useCallback(
    async (name: string, addr: SwiggyAddress | null) => {
      try {
        const u = await api.createUser(name, addr?.addressTag ?? addr?.addressCategory, addr?.id);
        if (u.returning) toast.success("Welcome back. Your plan and preferences are restored.");
        setUserId(u.user_id);
        setAddress(addr);
        setReady(true);
        saveSession({ userId: u.user_id, token: u.token, name, address: addr });
        // Tell the backend which addressId to search and order against —
        // without this, live mode silently falls back to the FIRST saved
        // Swiggy address regardless of the pick. Best-effort: on failure
        // the backend's fallback still works.
        if (addr?.id) {
          api.setAddress(addr.id).catch(() => {});
        }
      } catch {
        toast.error("Couldn't start your session. Check your connection and try again.");
      }
    },
    []
  );

  // undefined = still loading, null = no daily profile yet -> onboarding form
  const [dailyProfile, setDailyProfile] = useState<DailyProfile | null | undefined>(undefined);
  const [profileFailed, setProfileFailed] = useState(false);   // a load failed; still retrying
  const [view, setView] = useState<"today" | "you" | "setup">("today");
  useEffect(() => {
    if (!ready || !userId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    // A failed load must not look like "no profile": that would open first-run setup and saving it would wipe saved allergies.
    const load = (wait: number) =>
      api
        .dailyProfile(userId)
        .then((r) => !stop && setDailyProfile(r.profile))
        .catch(() => {
          if (stop) return;
          setProfileFailed(true);
          timer = setTimeout(() => load(Math.min(wait * 2, 15000)), wait);
        });
    load(1000);
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [ready, userId]);

  // Re-read the profile before editing: Today can change it (a diet-plan upload adds
  // allergies), and saving the stale copy from boot would drop them.
  const editProfile = useCallback(async () => {
    if (!userId) return;
    try {
      setDailyProfile((await api.dailyProfile(userId)).profile);
    } catch {
      toast.error("Couldn't load your latest preferences. Check them before saving.");
    }
    setView("setup");
  }, [userId]);

  if (!ready || !userId) {
    if (!modeKnown) return <Spinner className="min-h-dvh bg-background" />;
    return (
      // MotionConfig reducedMotion="user" makes every framer-motion animation
      // in the tree (bubble springs, chip pops, entrances) honor the OS
      // prefers-reduced-motion setting, matching the GSAP/Lottie guards.
      <MotionConfig reducedMotion="user">
        <Onboarding
          live={live}
          needsAuth={needsAuth}
          onConnected={handleConnected}
          onStart={handleStart}
          onTokenExpired={handleTokenExpired}
        />
      </MotionConfig>
    );
  }

  const tabs = (
    <nav aria-label="Views" className="flex justify-center border-b border-border bg-surface px-4 py-2">
      {/* one segmented control; the active view is a filled pill */}
      <div className="flex gap-1 rounded-full bg-muted p-1">
        {(["today", "you"] as const).map((v) => {
          const active = view === v || (v === "today" && view === "setup");
          return (
            <button
              key={v}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => setView(v)}
              className={`rounded-full px-5 py-1.5 text-sm font-bold capitalize transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 ${active ? "bg-card text-foreground shadow-soft" : "text-muted-foreground hover:text-foreground"}`}
            >
              {v}
            </button>
          );
        })}
      </div>
    </nav>
  );

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex min-h-dvh flex-col bg-background">
        <AppHeader live={live} address={address} />
        {tabs}
        {dailyProfile === undefined ? (
          <Spinner className="flex-1" note={profileFailed ? "Can't reach Forkcast, retrying…" : undefined} />
        ) : dailyProfile === null || view === "setup" ? (
          <DailyOnboarding
            userId={userId}
            initial={dailyProfile}
            onDone={(p) => {
              setDailyProfile(p);
              setView("today");
            }}
          />
        ) : (
          <TodayView
            userId={userId}
            onEditProfile={editProfile}
            onShowProfile={() => setView("you")}
            section={view === "you" ? "you" : "today"}
            addressLabel={address?.addressTag || address?.addressCategory || undefined}
          />
        )}
      </div>
    </MotionConfig>
  );
}

/** Centered loading spinner; `note` shows visible text next to it. */
function Spinner({ note, className }: { note?: string; className?: string }) {
  return (
    <div role="status" className={cn("flex items-center justify-center gap-2 p-6 text-sm text-muted-foreground", className)}>
      <Loader2 className="size-5 animate-spin" strokeWidth={2.4} aria-hidden />
      {note ?? <span className="sr-only">Loading</span>}
    </div>
  );
}
