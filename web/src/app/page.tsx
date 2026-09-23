"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { MotionConfig } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api";
import type {
  Blueprint,
  DishAlternative,
  FeasibilityOption,
  FeasibilityReport,
  MealSlot,
  NotifyPayload,
  PlanSummary,
  SwiggyAddress,
  WalletSummary,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { focusRing } from "@/lib/design";
import type { MealType } from "@/lib/design";
import { DUR, EASE, fadeUp, prefersReducedMotion } from "@/lib/motion";

import { ChatPane } from "@/components/chat/ChatPane";
import { DayListCalendar } from "@/components/calendar/DayListCalendar";
import { PlanSummaryStrip } from "@/components/calendar/PlanSummaryStrip";
import { FeasibilityPanel } from "@/components/calendar/FeasibilityPanel";
import { DishDetailModal } from "@/components/dish/DishDetailModal";
import { WalletBar } from "@/components/wallet/WalletBar";
import { Onboarding } from "@/components/app/Onboarding";
import { clearSession, loadSession, saveSession } from "@/lib/session";
import { AppHeader } from "@/components/app/AppHeader";
import { Button } from "@/components/ui/button";
import { PlateIllustration } from "@/components/ui/illustrations";

// Plan for the CURRENT month — this was hardcoded to "2026-07", so once July
// passed the app silently planned (and budgeted the wallet) for a past month.
const MONTH = new Date().toISOString().slice(0, 7);

gsap.registerPlugin(useGSAP);

export default function Home() {
  // session — start EMPTY so the server-rendered HTML matches the first client
  // render (localStorage isn't available on the server). We restore the saved
  // session in the mount effect below, which flips `ready` on the client only,
  // so there's no SSR/client hydration mismatch.
  const [userId, setUserId] = useState<number | null>(null);
  const [live, setLive] = useState(false);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [address, setAddress] = useState<SwiggyAddress | null>(null);
  const [ready, setReady] = useState<boolean>(false); // onboarding complete

  // plan + data
  const [plan, setPlan] = useState<PlanSummary | null>(null);
  const [slots, setSlots] = useState<MealSlot[]>([]);
  const [wallet, setWallet] = useState<WalletSummary | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [approved, setApproved] = useState<boolean>(false);

  // Why an over-budget plan doesn't fit, and what would. Fetched alongside the
  // plan so the explanation is ready the moment the numbers land.
  const [feasibility, setFeasibility] = useState<FeasibilityReport | null>(null);
  // The blueprint the current plan was built from — needed to re-plan when the
  // user applies one of the suggested fixes.
  const [lastBlueprint, setLastBlueprint] = useState<Blueprint | null>(null);
  // The boot effect is declared before the callback below. Keep a stable ref so
  // it can invoke the latest callback without re-running boot.
  const handleTokenExpiredRef = useRef<() => void>(() => {});

  // dish modal
  const [activeSlot, setActiveSlot] = useState<MealSlot | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  // Slot whose swap request is in flight — drives the inline Lottie beat.
  const [swappingId, setSwappingId] = useState<number | null>(null);

  // meal notifications surfaced into chat
  const [notifications, setNotifications] = useState<NotifyPayload[]>([]);

  const [days, setDays] = useState(30);

  // Calendar view filter — "all" shows every meal; otherwise just that meal.
  // Purely a VIEW filter: the summary strip keeps showing whole-plan numbers.
  const [mealFilter, setMealFilter] = useState<"all" | MealType>("all");

  // ---- boot (client-only): restore session + detect mode ----
  useEffect(() => {
    let cancelled = false;
    const saved = loadSession();

    // restore the local session after mount, deferred a tick so we're not calling
    // setState synchronously in the effect body (React 19 rule) — and so the first
    // client render still matches the server (both show onboarding, no hydration
    // mismatch), then this promotes to the app.
    if (saved.userId) {
      queueMicrotask(() => {
        if (cancelled) return;
        setUserId(saved.userId);
        setAddress(saved.address);
        setApproved(saved.approved);
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
        // Boot with a dead saved JWT: jump straight into the re-login flow —
        // the onboarding Connect step would otherwise wait for a click.
        if (m.token_expired && !m.live) handleTokenExpiredRef.current?.();
      })
      .catch(() => {
        if (!cancelled) {
          setLive(false);
          setNeedsAuth(false);
        }
      });

    // async-restore the saved plan + wallet
    if (saved.userId && saved.planId) {
      api
        .getPlan(saved.planId)
        .then((full) => {
          if (cancelled) return;
          setSlots(full.slots);
          setPlan({
            plan_id: full.plan.id,
            feasible: Boolean(full.plan.feasible),
            total_cost: full.plan.total_cost,
            budget: full.plan.budget,
            leftover: Math.round((full.plan.budget - full.plan.total_cost) * 100) / 100,
            constraint_status: {},
            message: full.plan.message,
          });
        })
        .catch(() => {/* plan gone — start fresh */});
      api.wallet(saved.userId, saved.month).then((w) => !cancelled && setWallet(w)).catch(() => {});
    }
    return () => {
      cancelled = true;
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
        if (next?.id) {
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

  // ---- auto re-login on JWT expiry -------------------------------------
  // The saved Swiggy JWT is short-lived and no refresh token is persisted, so
  // it dies mid-session. Keep recovery reachable by returning to onboarding
  // until the OAuth flow has completed successfully.
  const reloginRef = useRef(false);
  const reloginPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reloginTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      reloginRef.current = false;
      if (reloginPollRef.current) clearInterval(reloginPollRef.current);
      if (reloginTimeoutRef.current) clearTimeout(reloginTimeoutRef.current);
    };
  }, []);

  const handleTokenExpired = useCallback(() => {
    if (reloginRef.current) return;
    reloginRef.current = true;
    setReady(false);
    setLive(false);
    setNeedsAuth(true);
    toast.info(
      "Swiggy login expired — opening the login page to refresh it. Finish logging in, then the app reconnects by itself.",
      { duration: 8000 }
    );

    const finish = (kind: "connected" | "failed" | "timeout", message?: string) => {
      if (!reloginRef.current) return;
      reloginRef.current = false;
      if (reloginPollRef.current) clearInterval(reloginPollRef.current);
      if (reloginTimeoutRef.current) clearTimeout(reloginTimeoutRef.current);
      reloginPollRef.current = null;
      reloginTimeoutRef.current = null;
      if (!mountedRef.current) return;
      if (kind === "connected") {
        toast.success("Swiggy reconnected.");
        void recheckMode().then((m) => {
          if (mountedRef.current && m?.live) setReady(true);
        });
      } else {
        toast.error(message ?? "Re-login failed — click Connect Swiggy to try again.");
      }
    };

    reloginTimeoutRef.current = setTimeout(
      () => finish("timeout", "Login window timed out. Click Connect Swiggy to try again."),
      90_000,
    );

    api.authStart().then(() => {
      if (!reloginRef.current) return;
      let inFlight = false;
      reloginPollRef.current = setInterval(async () => {
        if (!reloginRef.current || inFlight) return;
        inFlight = true;
        try {
          const s = await api.authStatus();
          if (s.status === "connected" || s.live) finish("connected");
          else if (s.status === "failed") finish("failed", s.error ?? undefined);
        } catch {
          // The timeout above still ends recovery when status repeatedly fails.
        } finally {
          inFlight = false;
        }
      }, 1500);
    }).catch(() => {
      finish("failed", "Could not start the Swiggy re-login. Click Connect Swiggy to try again.");
    });
  }, [recheckMode]);

  // The boot effect above invokes this stable ref after mount. Updating it in
  // an effect avoids mutating refs during render, which React's lint rules ban.
  useEffect(() => {
    handleTokenExpiredRef.current = handleTokenExpired;
  }, [handleTokenExpired]);

  const refreshWallet = useCallback(
    async (uid: number) => {
      try {
        setWallet(await api.wallet(uid, MONTH));
      } catch {
        /* wallet only exists after approval */
      }
    },
    []
  );

  const refreshPlan = useCallback(async (planId: number) => {
    const full = await api.getPlan(planId);
    setSlots(full.slots);
  }, []);

  // ---- onboarding finish ----
  const handleStart = useCallback(
    async (name: string, addr: SwiggyAddress | null) => {
      try {
        const u = await api.createUser(name, addr?.addressTag ?? addr?.addressCategory);
        setUserId(u.user_id);
        setAddress(addr);
        setReady(true);
        saveSession({ userId: u.user_id, name, address: addr, month: MONTH });
        // Tell the backend which addressId to search and order against —
        // without this, live mode silently falls back to the FIRST saved
        // Swiggy address regardless of the pick. Best-effort: on failure
        // the backend's fallback still works.
        if (addr?.id) {
          api.setAddress(addr.id).catch(() => {});
        }
      } catch (e) {
        toast.error(e instanceof ApiError ? e.message : "Could not start session");
      }
    },
    []
  );

  // ---- Generate Plan from the gathered blueprint (deterministic — no LLM) ----
  // Also used for conversational tweaks: the chat adjusts the blueprint then calls
  // this to rebuild the whole month.
  const handleGenerate = useCallback(
    async (bp: Blueprint) => {
      if (!userId) return;
      const budget = bp.budget ?? 10000;
      const planDays = bp.days ?? 30;
      setDays(planDays);
      setPlanLoading(true);
      setApproved(false);
      try {
        if (bp.appetite_level) {
          await api.setAppetite(userId, bp.appetite_level);
        }
        const summary = await api.makePlan({
          user_id: userId,
          month: MONTH,
          budget,
          constraints: bp.constraints ?? [],
          veg_only: bp.veg_only ?? false,
          days: planDays,
          // The chat has always gathered which meals the user wants; this is
          // the last link in the chain — without it the backend planned (and
          // budgeted for) all three regardless of what they asked for.
          meals: bp.meals?.length ? bp.meals : undefined,
          high_protein: bp.high_protein ?? false,
          taste_prefs: {
            veg_level: bp.veg_level,
            allergies: bp.allergies ?? [],
            health_goals: bp.health_goals ?? [],
            spice_preference: bp.spice_preference,
            disliked_foods: bp.disliked_foods ?? [],
            portion_size: bp.portion_size,
          },
        });
        setPlan(summary);
        setLastBlueprint(bp);
        await refreshPlan(summary.plan_id);
        saveSession({ planId: summary.plan_id, approved: false, month: MONTH });

        // Explain the budget in concrete terms. Never let this break planning —
        // a failed probe just means no panel, not a failed plan.
        try {
          setFeasibility(
            await api.planFeasibility({
              user_id: userId,
              month: MONTH,
              budget,
              constraints: bp.constraints ?? [],
              veg_only: bp.veg_only ?? false,
              days: planDays,
              meals: bp.meals?.length ? bp.meals : undefined,
              high_protein: bp.high_protein ?? false,
            }),
          );
        } catch {
          setFeasibility(null);
        }

        if (!summary.feasible) {
          toast.warning("Over budget. See the options below the summary.");
        } else {
          toast.success("Month plan ready!");
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          // Stale session: the saved user no longer exists server-side (DB was
          // reset). Clear the local session and restart onboarding — one click
          // and the user is back, no manual cache-clearing needed.
          clearSession();
          toast.error("Session expired. Starting fresh: pick your name again.");
          setPlan(null);
          setSlots([]);
          setUserId(null);
          setReady(false);
        } else if (e instanceof ApiError && e.status === 401) {
          // Live catalog died on the dead JWT — the backend has already flipped
          // its expired flags; kick the auto re-login flow.
          handleTokenExpired();
        } else {
          const msg = e instanceof ApiError ? `Plan build failed (${e.status}): ${e.message}` : "Plan build failed";
          console.error("[plan] makePlan failed:", e);
          toast.error(msg);
        }
      } finally {
        setPlanLoading(false);
      }
    },
    [userId, refreshPlan, handleTokenExpired]
  );

  // ---- apply a suggested fix from the feasibility panel ----
  // Each option carries the exact settings that make it fit, so applying one is
  // just a re-plan with those fields merged over the blueprint.
  const handleApplyFix = useCallback(
    (option: FeasibilityOption) => {
      const bp = lastBlueprint;
      if (!bp) return;
      const { budget, meals, appetite_level } = option.changes;
      void handleGenerate({
        ...bp,
        ...(budget != null ? { budget } : {}),
        ...(meals ? { meals } : {}),
        ...(appetite_level ? { appetite_level } : {}),
      });
    },
    [handleGenerate, lastBlueprint]
  );

  // ---- approve ----
  const handleApprove = useCallback(async () => {
    if (!plan) return;
    setApproving(true);
    try {
      const res = await api.approvePlan(plan.plan_id);
      setWallet(res.wallet);
      setApproved(true);
      saveSession({ approved: true });
      toast.success("Plan activated. Wallet funded.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Approve failed");
    } finally {
      setApproving(false);
    }
  }, [plan]);

  // ---- dish click ----
  const openDish = useCallback((slot: MealSlot) => {
    setActiveSlot(slot);
    setModalOpen(true);
  }, []);

  // ---- swap from modal ----
  const handleSwap = useCallback(
    async (alt: DishAlternative) => {
      if (!activeSlot) return;
      setSwappingId(activeSlot.id);
      try {
        // Persist server-side first — a client-only swap used to vanish on
        // refresh. The backend returns the updated slot, so we render exactly
        // what's stored (side pairing cleared, why_text reset).
        const { slot } = await api.swapSlot(activeSlot.id, alt);
        setSlots((prev) => prev.map((s) => (s.id === slot.id ? slot : s)));
        setModalOpen(false);
        toast.success(`Swapped to ${alt.name}`);
      } catch (e) {
        toast.error(e instanceof ApiError ? e.message : "Swap failed");
      } finally {
        setSwappingId(null);
      }
    },
    [activeSlot]
  );

  // ---- meal notify + respond (demo: notify the first planned slot) ----
  const handleRespondSlot = useCallback(
    async (slotId: number, answer: string) => {
      try {
        const res = await api.respondSlot(
          slotId,
          answer as "yes" | "no" | "later" | "other"
        );
        if (userId) await refreshWallet(userId);
        if (plan) await refreshPlan(plan.plan_id);
        const result = (res as { result?: string }).result;
        if (result === "ordered") toast.success("Order placed on Swiggy!");
        else if (result === "skipped") toast("Meal skipped. Money kept as Swiggy Cash.");
        else if (result === "rescheduled") toast("Meal rescheduled.");
      } catch (e) {
        toast.error(e instanceof ApiError ? e.message : "Could not respond");
      }
    },
    [userId, plan, refreshWallet, refreshPlan]
  );

  const firstPlannedSlot = useMemo(
    () => slots.find((s) => s.status === "planned"),
    [slots]
  );

  // slots surviving the rail filter, + per-meal counts for the chip badges
  const visibleSlots = useMemo(
    () =>
      mealFilter === "all"
        ? slots
        : slots.filter((s) => s.meal_type === mealFilter),
    [slots, mealFilter]
  );
  const mealCounts = useMemo(() => {
    const c: Partial<Record<MealType, number>> = {};
    for (const s of slots) c[s.meal_type] = (c[s.meal_type] ?? 0) + 1;
    return c;
  }, [slots]);

  const simulateNextMeal = useCallback(async () => {
    if (!firstPlannedSlot) {
      toast("No planned meals left to simulate.");
      return;
    }
    try {
      const notif = await api.notifySlot(firstPlannedSlot.id);
      setNotifications((prev) => [...prev, notif]);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Notify failed");
    }
  }, [firstPlannedSlot]);

  // ---- GSAP motion layer (client-only; hooks stay above any early return) ----
  const artifactRef = useRef<HTMLDivElement>(null);
  const hasArtifact = Boolean(plan || planLoading);

  // One-time entrance when the plan artifact first renders: summary strip →
  // feasibility panel → calendar section, staggered 80ms. A plain timeline
  // keyed on arrival — deliberately no ScrollTrigger and no listeners on the
  // inner scrolling div. The [data-plan-step] nodes are thin wrappers around
  // PlanSummaryStrip/FeasibilityPanel so we never double-drive the framer
  // entrances those components animate on their own roots.
  useGSAP(
    () => {
      if (!artifactRef.current || !hasArtifact || prefersReducedMotion()) return;
      gsap.from("[data-plan-step]", {
        opacity: 0,
        y: 18,
        duration: DUR.base,
        stagger: 0.08,
        ease: EASE.soft,
      });
    },
    { scope: artifactRef, dependencies: [hasArtifact] }
  );

  if (!ready) {
    return (
      // MotionConfig reducedMotion="user" makes every framer-motion animation
      // in the tree (bubble springs, chip pops, entrances) honor the OS
      // prefers-reduced-motion setting, matching the GSAP/Lottie guards.
      <MotionConfig reducedMotion="user">
        <Onboarding
          live={live}
          needsAuth={needsAuth}
          onConnected={recheckMode}
          onStart={handleStart}
          onTokenExpired={handleTokenExpired}
        />
      </MotionConfig>
    );
  }

  return (
    <MotionConfig reducedMotion="user">
    <div className="relative flex h-dvh flex-col overflow-hidden bg-background">
      <AppHeader live={live} address={address} />

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 lg:grid-cols-[minmax(360px,420px)_1fr]">
        {/* LEFT — chat. ChatPane draws its own hairline divider, so the
            wrapper carries no border (the old 3px orange stripe doubled up). */}
        <div className="min-h-0 bg-surface">
          {userId && (
            <ChatPane
              userId={userId}
              onGenerate={handleGenerate}
              generating={planLoading}
              hasPlan={Boolean(plan)}
              onRespondSlot={handleRespondSlot}
              notifications={notifications}
              className="h-full"
            />
          )}
        </div>

        {/* RIGHT — artifact */}
        <div className="min-h-0 overflow-y-auto">
          <div
            ref={artifactRef}
            className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-5 py-6 lg:px-8"
          >
            {plan || planLoading ? (
              <>
                {/* compact wallet + approve, sticky at top of the plan pane */}
                <WalletBar
                  wallet={wallet}
                  plan={plan}
                  approving={approving}
                  approved={approved}
                  onApprove={handleApprove}
                  className="sticky top-3 z-30"
                />

                {/* at-a-glance overview so the grid isn't the first overwhelming thing.
                    Thin wrapper = GSAP entrance target (see useGSAP above); the strip's
                    own framer stagger runs untouched inside it. */}
                <div data-plan-step>
                  <PlanSummaryStrip plan={plan} slots={slots} />
                </div>

                {/* Explains an over-budget plan in real numbers and offers
                    concrete, one-click fixes. Collapses to a single line when
                    the plan already fits. Wrapper only renders with a report so
                    no phantom flex gap appears when the panel is hidden. */}
                {feasibility && (
                  <div data-plan-step>
                    <FeasibilityPanel
                      report={feasibility}
                      onApply={handleApplyFix}
                      applying={planLoading}
                    />
                  </div>
                )}

                <section data-plan-step className="flex flex-col gap-4">
                  <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
                    <div className="min-w-0">
                      <h2 className="font-heading text-xl font-extrabold tracking-[-0.02em]">
                        Your Month Plan
                      </h2>
                      <p className="text-sm leading-[1.4] text-muted-foreground">
                        One week at a time. Tap any dish for details, swap, or the AI pick reason.
                      </p>
                    </div>
                    {plan && approved && firstPlannedSlot && (
                      <Button onClick={simulateNextMeal} className="shrink-0">
                        Simulate next meal
                        <ArrowRight className="size-4" strokeWidth={2.4} aria-hidden />
                      </Button>
                    )}
                  </div>

                  {/* Swiggy-style category rail — filter the plan by meal */}
                  <MealFilterRail
                    value={mealFilter}
                    onChange={setMealFilter}
                    counts={mealCounts}
                  />

                  <DayListCalendar
                    slots={visibleSlots}
                    days={days}
                    loading={planLoading}
                    onSlotClick={openDish}
                    swappingSlotId={swappingId}
                  />
                </section>
              </>
            ) : (
              <EmptyArtifact />
            )}
          </div>
        </div>
      </div>

      <DishDetailModal
        slot={activeSlot}
        open={modalOpen}
        onOpenChange={setModalOpen}
        onSwap={handleSwap}
        swapping={swappingId === activeSlot?.id}
        vegOnly={lastBlueprint?.veg_only ?? false}
      />
    </div>
    </MotionConfig>
  );
}

/* Swiggy category-rail pattern: horizontally scrollable pill chips, active =
   solid orange, resting = white card with a soft hover tint. Counts give the
   rail real utility (how many of each meal the plan holds). */
const FILTERS: { value: "all" | MealType; label: string }[] = [
  { value: "all", label: "All meals" },
  { value: "breakfast", label: "Breakfast" },
  { value: "lunch", label: "Lunch" },
  { value: "dinner", label: "Dinner" },
];

function MealFilterRail({
  value,
  onChange,
  counts,
}: {
  value: "all" | MealType;
  onChange: (v: "all" | MealType) => void;
  counts: Partial<Record<MealType, number>>;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const appearedRef = useRef(false);

  // Re-runs when the active filter changes: the first run pops every chip in
  // (staggered scale/fade); later runs only emphasize the newly-active chip.
  useGSAP(
    () => {
      if (prefersReducedMotion()) return;

      if (!appearedRef.current) {
        appearedRef.current = true;
        gsap.from("[data-filter-chip]", {
          opacity: 0,
          scale: 0.85,
          duration: DUR.quick,
          stagger: 0.05,
          ease: EASE.pop,
        });
        return;
      }

      const active = rootRef.current?.querySelector<HTMLElement>(
        "[aria-pressed='true']"
      );
      if (!active) return;
      gsap
        .timeline()
        .to(active, { scale: 1.04, duration: 0.12, ease: EASE.out })
        .to(active, {
          scale: 1,
          duration: 0.18,
          ease: EASE.out,
          clearProps: "transform",
        });
    },
    { scope: rootRef, dependencies: [value] }
  );

  return (
    <div
      ref={rootRef}
      className="flex items-center gap-2 overflow-x-auto pb-1"
      aria-label="Filter plan by meal"
    >
      {FILTERS.map((f) => {
        const active = f.value === value;
        const n = counts[f.value as MealType];
        return (
          <button
            key={f.value}
            type="button"
            data-filter-chip
            aria-pressed={active}
            onClick={() => onChange(f.value)}
            className={cn(
              // Both states carry a 1px border so switching filters never
              // shifts the chip's box size.
              "shrink-0 rounded-full border px-4 py-1.5 text-sm font-semibold transition-colors",
              focusRing,
              active
                ? "border-brand-500 bg-brand-500 text-primary-foreground"
                : "border-border bg-card text-foreground hover:border-brand-300 hover:bg-brand-50"
            )}
          >
            {f.label}
            {n != null && n > 0 && (
              <span
                className={cn(
                  "ml-1.5 text-xs",
                  active ? "text-primary-foreground/75" : "text-muted-foreground"
                )}
              >
                {n}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function EmptyArtifact() {
  const rootRef = useRef<HTMLDivElement>(null);

  // Idle life for the empty state: perpetual gentle float (±6px) plus a very
  // slow rotate wobble (±2°). The two periods differ so the drift feels
  // organic rather than metronomic. Copy fades up once.
  useGSAP(
    () => {
      if (prefersReducedMotion()) return;

      const plate = rootRef.current?.querySelector(".empty-plate");
      if (plate) {
        gsap.to(plate, { y: -6, duration: 1.8, ease: EASE.loop, repeat: -1, yoyo: true });
        gsap.to(plate, { rotation: 2, duration: 3.4, ease: EASE.loop, repeat: -1, yoyo: true });
      }

      fadeUp("[data-empty-copy]", { y: 12, stagger: 0.08 });
    },
    { scope: rootRef }
  );

  return (
    <div
      ref={rootRef}
      className="flex min-h-[60vh] flex-col items-center justify-center rounded-lg border border-border bg-card p-10 text-center"
    >
      {/* original food-doodle illustration — Swiggy-style friendly empty state */}
      <PlateIllustration className="empty-plate mb-6 h-44 w-44" />
      <h2 data-empty-copy className="font-heading text-2xl font-bold tracking-[-0.02em]">
        Tell me your food budget
      </h2>
      <p data-empty-copy className="mt-2 max-w-md text-sm leading-[1.4] text-muted-foreground">
        Chat on the left: your budget, must-have dishes, and appetite. I&apos;ll
        build a full month of breakfast, lunch &amp; dinner within budget, right here.
      </p>
    </div>
  );
}
