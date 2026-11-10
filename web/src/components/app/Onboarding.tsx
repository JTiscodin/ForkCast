"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { motion } from "framer-motion";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api";
import type { SwiggyAddress } from "@/lib/types";
import { cn } from "@/lib/utils";
import { focusRing } from "@/lib/design";
import { DUR, EASE, prefersReducedMotion } from "@/lib/motion";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { LogoMark } from "./Logo";
import { MapPin, Loader2, ArrowRight, AlertTriangle, RefreshCw } from "lucide-react";
import { ConnectSwiggy } from "./ConnectSwiggy";

gsap.registerPlugin(useGSAP);

export function Onboarding({
  live,
  needsAuth = false,
  onConnected,
  onStart,
  onTokenExpired,
}: {
  live: boolean;
  needsAuth?: boolean;
  onConnected?: () => void;
  onStart: (name: string, address: SwiggyAddress | null) => Promise<void> | void;
  /** Fired when a live call 401s on the dead saved JWT — parent auto-relogins. */
  onTokenExpired?: () => void;
}) {
  // When Swiggy is desired but not connected, show the connect step first —
  // unless the user chose to skip into demo mode.
  const [skippedAuth, setSkippedAuth] = useState(false);
  const showConnect = needsAuth && !live && !skippedAuth;

  const [name, setName] = useState("");
  const [addresses, setAddresses] = useState<SwiggyAddress[]>([]);
  // null = user hasn't picked; effective selection defaults to the first address.
  const [picked, setPicked] = useState<SwiggyAddress | null>(null);
  // start in the loading state when live, so we don't sync-setState inside the effect.
  const [loadingAddr, setLoadingAddr] = useState(live);
  // Fetch failure is its own terminal state — distinct from "no addresses" —
  // with a retry affordance; otherwise a flaky network dead-ends onboarding.
  const [addrError, setAddrError] = useState<string | null>(null);
  // Bumped by Retry to re-run the address fetch.
  const [addrReload, setAddrReload] = useState(0);
  const [starting, setStarting] = useState(false);

  // GSAP motion layer (scoped to this component; the hook reverts everything
  // on unmount/update). The card itself keeps its framer-motion entrance —
  // GSAP only drives the hat idle loop and the staggered card CONTENTS.
  const rootRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      if (prefersReducedMotion()) return;

      // Gentle perpetual idle on the chef hat: ±3° tilt with a slight bob,
      // yoyo repeat -1 → ~2.8s round trip, pivoted near its base.
      // Welcome-card contents fade up in reading order: title → subtitle →
      // form/connect block (whichever branch is mounted), 70ms apart.
      gsap.from(".ob-step", {
        opacity: 0,
        y: 14,
        duration: DUR.base,
        stagger: 0.07,
        ease: EASE.soft,
      });
    },
    { scope: rootRef, dependencies: [showConnect], revertOnUpdate: true }
  );

  useEffect(() => {
    if (!live) return;

    // Defer the initial state transition to the next task. This avoids a
    // synchronous setState inside the effect while still clearing any address
    // selected under a previous Swiggy account before the new fetch begins.
    let active = true;
    const timer = window.setTimeout(() => {
      if (!active) return;
      setAddresses([]);
      setPicked(null);
      setLoadingAddr(true);
      setAddrError(null);
      api
        .addresses()
        .then((r) => {
          if (active) setAddresses(r.addresses ?? []);
        })
        .catch((e) => {
          if (!active) return;
          // A dead JWT is recoverable: the parent kicks the OAuth re-login flow
          // (browser opens for a fresh token). Don't dead-end onboarding with a
          // generic error while that's in flight.
          if (e instanceof ApiError && e.status === 401) {
            setAddrError("Swiggy login expired — reopening the login page…");
            onTokenExpired?.();
            return;
          }
          setAddrError(e instanceof ApiError ? e.message : "Could not load addresses");
          toast.error(e instanceof ApiError ? e.message : "Could not load addresses");
        })
        .finally(() => {
          if (active) setLoadingAddr(false);
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [live, addrReload, onTokenExpired]);

  const selected = picked ?? addresses[0] ?? null;
  const setSelected = setPicked;

  // Live mode needs a delivery address, but a failed or empty address fetch
  // must not trap the user: they can continue without one (the backend falls
  // back to the account's first saved address) or retry the fetch.
  const canStart = name.trim().length > 0 && (!live || selected !== null || addrError !== null);

  const start = async () => {
    if (!canStart) return;
    setStarting(true);
    await onStart(name.trim(), selected);
    setStarting(false);
  };

  // Radio-group keyboard support: arrows move the selection, Home/End jump.
  const onListKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (addresses.length === 0) return;
    const keys = ["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"];
    if (!keys.includes(e.key)) return;
    e.preventDefault();
    const idx = selected ? addresses.findIndex((a) => a.id === selected.id) : 0;
    let next = idx;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") next = (idx + 1) % addresses.length;
    else if (e.key === "ArrowUp" || e.key === "ArrowLeft") next = (idx - 1 + addresses.length) % addresses.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = addresses.length - 1;
    setSelected(addresses[next]);
    // Move focus with the selection (roving tabindex).
    rootRef.current
      ?.querySelector<HTMLElement>(`[data-addr-idx="${next}"]`)
      ?.focus();
  };

  return (
    <div
      ref={rootRef}
      className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-background p-6"
    >
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className={cn(
          "w-full max-w-md rounded-lg border border-border bg-card p-8 shadow-soft"
        )}
      >
        <div className="mb-6 flex items-center justify-between">
          <span className="flex items-center gap-2 font-heading text-lg font-extrabold">
            <LogoMark className="ob-hat size-9" /> Forkcast
          </span>
          {/* three real steps: connect, you, tastes */}
          <ol aria-label={`Step ${showConnect ? 1 : 2} of 3`} className="flex gap-1.5">
            {[1, 2, 3].map((n) => (
              <li key={n} className={cn("h-1.5 w-7 rounded-full", n <= (showConnect ? 1 : 2) ? "bg-brand-500" : "bg-muted")} />
            ))}
          </ol>
        </div>

        <h1 className="ob-step font-heading text-3xl font-extrabold tracking-[-0.02em] text-foreground">
          {showConnect ? "Your meals for today, already picked" : "Where should we deliver?"}
        </h1>
        <p className="ob-step mt-2 text-sm leading-[1.4] text-muted-foreground">
          {showConnect
            ? "Forkcast picks breakfast, lunch, a snack and dinner from Swiggy restaurants near you, inside your budget, diet and allergies. Connect Swiggy to see real dishes and prices."
            : "Tell us your name and pick a saved Swiggy address. Next you'll set your diet, allergies and budget."}
        </p>

        {showConnect ? (
          <div className="ob-step mt-7">
            <ConnectSwiggy
              onConnected={() => onConnected?.()}
              onSkip={() => setSkippedAuth(true)}
            />
          </div>
        ) : (
        <div className="ob-step mt-7 flex flex-col gap-4">
          <div>
            <label
              htmlFor="onboarding-name"
              className="mb-1.5 block text-sm font-medium leading-[1.4] text-muted-foreground"
            >
              Your name
            </label>
            <Input
              id="onboarding-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your first name"
              onKeyDown={(e) => e.key === "Enter" && canStart && start()}
              autoFocus
            />
          </div>

          {live && (
            // min-w-0 is load-bearing: a <fieldset> defaults to
            // min-inline-size:min-content, so one long address line would
            // widen it past the card and spill the rows out of the box.
            <fieldset className="min-w-0">
              <legend
                id="onboarding-address-label"
                className="mb-1.5 block text-sm font-medium leading-[1.4] text-muted-foreground"
              >
                Delivery address (from your Swiggy account)
              </legend>
              {loadingAddr ? (
                <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-elevated px-3 py-3 text-sm leading-[1.4] text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" strokeWidth={2.4} /> Loading your addresses…
                </div>
              ) : addrError ? (
                <div className="flex flex-col gap-2.5 rounded-lg border border-danger/30 bg-danger/5 px-3 py-3">
                  <div className="flex items-start gap-2 text-sm leading-[1.4] text-foreground">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" strokeWidth={2.4} />
                    <span>
                      Couldn&apos;t load your addresses. You can retry, or continue
                      and Swiggy&apos;s default address will be used.
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setAddrReload((n) => n + 1)}
                    className={cn(
                      "flex w-fit items-center gap-1.5 rounded-md border border-border bg-surface-elevated px-2.5 py-1.5 text-sm font-medium leading-[1.4] text-foreground transition hover:border-brand-300",
                      focusRing
                    )}
                  >
                    <RefreshCw className="size-3.5" strokeWidth={2.4} /> Retry
                  </button>
                </div>
              ) : (
                <div
                  role="radiogroup"
                  aria-labelledby="onboarding-address-label"
                  onKeyDown={onListKeyDown}
                  className="flex max-h-52 min-w-0 flex-col gap-2 overflow-y-auto pr-1"
                >
                  {addresses.map((a, i) => {
                    const isSel = selected?.id === a.id;
                    return (
                      <button
                        key={a.id}
                        type="button"
                        role="radio"
                        aria-checked={isSel}
                        data-addr-idx={i}
                        tabIndex={isSel || (i === 0 && !selected) ? 0 : -1}
                        onClick={() => setSelected(a)}
                        className={cn(
                          "flex w-full min-w-0 items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left text-sm leading-[1.4] transition",
                          focusRing,
                          isSel
                            ? "border-brand-500 bg-brand-50"
                            : "border-border bg-surface-elevated hover:border-brand-300"
                        )}
                      >
                        <MapPin
                          strokeWidth={2.4}
                          className={cn(
                            "mt-0.5 size-4 shrink-0",
                            isSel ? "text-brand-500" : "text-muted-foreground"
                          )}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium">
                            {a.addressTag ?? a.addressCategory ?? "Address"}
                          </span>
                          {a.addressLine && (
                            <span className="line-clamp-2 block text-sm leading-[1.4] text-muted-foreground">
                              {a.addressLine}
                            </span>
                          )}
                        </span>
                      </button>
                    );
                  })}
                  {addresses.length === 0 && (
                    <div className="flex flex-col gap-1 rounded-lg border border-border bg-surface-elevated px-3 py-3 text-sm leading-[1.4] text-muted-foreground">
                      <span>No saved addresses found on your Swiggy account.</span>
                      <span>
                        Add one in the Swiggy app, or continue and we&apos;ll use
                        Swiggy&apos;s default.
                      </span>
                    </div>
                  )}
                </div>
              )}
            </fieldset>
          )}

          {/* Flat Swiggy-orange CTA — the one loud element on this screen. */}
          <Button
            onClick={start}
            disabled={!canStart || starting}
            size="lg"
            className="mt-1 w-full"
          >
            {starting ? (
              <Loader2 className="size-4 animate-spin" strokeWidth={2.4} />
            ) : (
              <>
                {live && !selected
                  ? "Continue without an address"
                  : "Continue"}{" "}
                <ArrowRight className="size-4" strokeWidth={2.4} />
              </>
            )}
          </Button>

          <p className="text-center text-xs leading-[1.4] text-muted-foreground">
            We store your name, food preferences and what you order through Forkcast to improve your picks.
            Nothing is ordered without your tap, and you can delete everything any time.
          </p>

          {!live && (
            <p className="text-center text-sm leading-[1.4] text-muted-foreground">
              {skippedAuth
                ? "Demo mode: mock catalog, no real orders."
                : "Running in demo mode: mock catalog, no real orders."}
            </p>
          )}
        </div>
        )}
      </motion.div>
    </div>
  );
}

export default Onboarding;
