"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api";
import type {
  Blueprint,
  DishAlternative,
  MealSlot,
  NotifyPayload,
  PlanSummary,
  SwiggyAddress,
  WalletSummary,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { gradients, surfaces } from "@/lib/design";

import { ChatPane } from "@/components/chat/ChatPane";
import { WeekCalendar } from "@/components/calendar/WeekCalendar";
import { PlanSummaryStrip } from "@/components/calendar/PlanSummaryStrip";
import { DishCard } from "@/components/dish/DishCard";
import { DishDetailModal } from "@/components/dish/DishDetailModal";
import { WalletBar } from "@/components/wallet/WalletBar";
import { Onboarding } from "@/components/app/Onboarding";
import { loadSession, saveSession } from "@/lib/session";
import { AppHeader } from "@/components/app/AppHeader";

const MONTH = "2026-07";

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

  // dish modal
  const [activeSlot, setActiveSlot] = useState<MealSlot | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  // meal notifications surfaced into chat
  const [notifications, setNotifications] = useState<NotifyPayload[]>([]);

  const [days, setDays] = useState(30);

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
    }

    api
      .getMode()
      .then((m) => {
        if (cancelled) return;
        setLive(m.live);
        setNeedsAuth(Boolean(m.needs_auth));
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

  // re-check mode after an in-app Swiggy connect
  const recheckMode = useCallback(async () => {
    try {
      const m = await api.getMode();
      setLive(m.live);
      setNeedsAuth(Boolean(m.needs_auth));
    } catch {
      /* ignore */
    }
  }, []);

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
        });
        setPlan(summary);
        await refreshPlan(summary.plan_id);
        saveSession({ planId: summary.plan_id, approved: false, month: MONTH });
        if (!summary.feasible) {
          toast.warning("Plan is over budget — tell me to make it cheaper, or adjust.");
        } else {
          toast.success("Month plan ready!");
        }
      } catch (e) {
        toast.error(e instanceof ApiError ? e.message : "Plan build failed");
      } finally {
        setPlanLoading(false);
      }
    },
    [userId, refreshPlan]
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
      toast.success("Plan activated — wallet funded.");
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
      // optimistic: reflect swap locally (backend swap-on-order happens at meal time)
      setSlots((prev) =>
        prev.map((s) =>
          s.id === activeSlot.id
            ? {
                ...s,
                dish_id: alt.dish_id,
                dish_name: alt.name,
                restaurant_id: alt.restaurant_id,
                restaurant_name: alt.restaurant_name,
                price: alt.price,
                rating: alt.rating,
                image_url: alt.image_url,
                why_text: undefined,
              }
            : s
        )
      );
      setModalOpen(false);
      toast.success(`Swapped to ${alt.name}`);
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
        else if (result === "skipped") toast("Meal skipped — money kept as Swiggy Cash.");
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

  if (!ready) {
    return (
    <Onboarding
      live={live}
      needsAuth={needsAuth}
      onConnected={recheckMode}
      onStart={handleStart}
    />
  );
  }

  return (
    <div className="relative flex h-dvh flex-col overflow-hidden bg-background">
      {/* ambient background glow */}
      <div
        className={cn(
          "pointer-events-none absolute inset-0 -z-10 opacity-60",
          gradients.mesh
        )}
      />
      <AppHeader live={live} address={address} />

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 lg:grid-cols-[minmax(360px,420px)_1fr]">
        {/* LEFT — chat */}
        <div className="min-h-0 border-r border-border/60 bg-surface/40 backdrop-blur-sm">
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
          <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-5 py-6 lg:px-8">
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

                {/* at-a-glance overview so the grid isn't the first overwhelming thing */}
                <PlanSummaryStrip plan={plan} slots={slots} />

                <section className="flex flex-col gap-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h2 className="font-display text-xl font-semibold tracking-tight">
                        Your Month Plan
                      </h2>
                      <p className="text-sm text-muted-foreground">
                        One week at a time — tap any dish for details, swap, or the AI pick reason.
                      </p>
                    </div>
                    {plan && approved && firstPlannedSlot && (
                      <button
                        onClick={simulateNextMeal}
                        className={cn(
                          "shrink-0 rounded-full px-4 py-1.5 text-sm font-medium text-white shadow-soft transition hover:shadow-glow",
                          gradients.brand
                        )}
                      >
                        Simulate next meal →
                      </button>
                    )}
                  </div>

                  <WeekCalendar
                    slots={slots}
                    days={days}
                    loading={planLoading}
                    onSlotClick={openDish}
                    renderSlot={(slot) => <DishCard slot={slot} />}
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
      />
    </div>
  );
}

function EmptyArtifact() {
  return (
    <div
      className={cn(
        "flex min-h-[60vh] flex-col items-center justify-center rounded-3xl border border-border/60 p-10 text-center",
        surfaces.glass
      )}
    >
      <div
        className={cn(
          "mb-5 flex size-16 items-center justify-center rounded-2xl text-3xl shadow-glow",
          gradients.brand
        )}
      >
        🍱
      </div>
      <h2 className="font-display text-2xl font-semibold tracking-tight">
        Tell me your food budget
      </h2>
      <p className="mt-2 max-w-md text-muted-foreground">
        Chat on the left — your budget, must-have dishes, and appetite. I&apos;ll
        build a full month of breakfast, lunch &amp; dinner within budget, right here.
      </p>
    </div>
  );
}
