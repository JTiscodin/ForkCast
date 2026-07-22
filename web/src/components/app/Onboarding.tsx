"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api";
import type { SwiggyAddress } from "@/lib/types";
import { cn } from "@/lib/utils";
import { gradients, gradientText, surfaces } from "@/lib/design";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MapPin, Loader2, ArrowRight } from "lucide-react";
import { ConnectSwiggy } from "./ConnectSwiggy";

export function Onboarding({
  live,
  needsAuth = false,
  onConnected,
  onStart,
}: {
  live: boolean;
  needsAuth?: boolean;
  onConnected?: () => void;
  onStart: (name: string, address: SwiggyAddress | null) => Promise<void> | void;
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
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!live) return;
    let cancelled = false;
    api
      .addresses()
      .then((r) => {
        if (!cancelled) setAddresses(r.addresses ?? []);
      })
      .catch((e) =>
        toast.error(e instanceof ApiError ? e.message : "Could not load addresses")
      )
      .finally(() => {
        if (!cancelled) setLoadingAddr(false);
      });
    return () => {
      cancelled = true;
    };
  }, [live]);

  const selected = picked ?? addresses[0] ?? null;
  const setSelected = setPicked;

  const canStart = name.trim().length > 0 && (!live || selected);

  const start = async () => {
    if (!canStart) return;
    setStarting(true);
    await onStart(name.trim(), selected);
    setStarting(false);
  };

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-background p-6">
      <div className={cn("pointer-events-none absolute inset-0 -z-10", gradients.mesh)} />
      <div
        className={cn(
          "pointer-events-none absolute left-1/2 top-0 -z-10 h-105 w-180 -translate-x-1/2 blur-3xl",
          gradients.glow
        )}
      />

      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className={cn(
          "w-full max-w-md rounded-3xl border border-border/60 p-8 shadow-layered",
          surfaces.glass
        )}
      >
        <div
          className={cn(
            "mb-6 flex size-14 items-center justify-center rounded-2xl text-3xl shadow-glow",
            gradients.brand
          )}
        >
          🍱
        </div>

        <h1 className={cn("font-display text-3xl font-semibold tracking-tight", gradientText)}>
          {showConnect ? "Connect your Swiggy" : "Plan your month of meals"}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          {showConnect
            ? "Link Swiggy for real restaurants and orders — or skip to try it in demo mode."
            : "Set a monthly food budget and your must-haves. I'll build a full calendar of breakfast, lunch & dinner within budget — and roll unused money into next month as Swiggy Cash."}
        </p>

        {showConnect ? (
          <div className="mt-7">
            <ConnectSwiggy
              onConnected={() => onConnected?.()}
              onSkip={() => setSkippedAuth(true)}
            />
          </div>
        ) : (
        <div className="mt-7 flex flex-col gap-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              Your name
            </label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Jatin"
              onKeyDown={(e) => e.key === "Enter" && canStart && start()}
              autoFocus
            />
          </div>

          {live && (
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Delivery address (from your Swiggy account)
              </label>
              {loadingAddr ? (
                <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-surface-elevated px-3 py-3 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" /> Loading your addresses…
                </div>
              ) : (
                <div className="flex max-h-52 flex-col gap-2 overflow-y-auto pr-1">
                  {addresses.map((a) => (
                    <button
                      key={a.id}
                      onClick={() => setSelected(a)}
                      className={cn(
                        "flex items-start gap-2.5 rounded-xl border px-3 py-2.5 text-left text-sm transition",
                        selected?.id === a.id
                          ? "border-brand-500 bg-brand-500/10"
                          : "border-border/60 bg-surface-elevated hover:border-border"
                      )}
                    >
                      <MapPin
                        className={cn(
                          "mt-0.5 size-4 shrink-0",
                          selected?.id === a.id ? "text-brand-500" : "text-muted-foreground"
                        )}
                      />
                      <span className="min-w-0">
                        <span className="block font-medium">
                          {a.addressTag ?? a.addressCategory ?? "Address"}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {a.addressLine}
                        </span>
                      </span>
                    </button>
                  ))}
                  {addresses.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      No saved addresses found on your Swiggy account.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          <Button
            onClick={start}
            disabled={!canStart || starting}
            className={cn("mt-1 h-11 w-full text-white", gradients.brand)}
          >
            {starting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <>
                Start planning <ArrowRight className="size-4" />
              </>
            )}
          </Button>

          {!live && (
            <p className="text-center text-xs text-muted-foreground">
              {skippedAuth
                ? "Demo mode — mock catalog, no real orders."
                : "Running in demo mode — mock catalog, no real orders."}
            </p>
          )}
        </div>
        )}
      </motion.div>
    </div>
  );
}

export default Onboarding;
