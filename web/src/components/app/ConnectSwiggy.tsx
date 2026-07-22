"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { gradients } from "@/lib/design";
import { Button } from "@/components/ui/button";
import { Loader2, ExternalLink, ShieldCheck } from "lucide-react";

/**
 * "Connect Swiggy" — kicks the backend OAuth flow (opens a browser on the
 * machine running the backend), then polls until connected. On success calls
 * onConnected() so the parent can flip to live mode.
 */
export function ConnectSwiggy({
  onConnected,
  onSkip,
}: {
  onConnected: () => void;
  onSkip?: () => void;
}) {
  const [phase, setPhase] = useState<"idle" | "running" | "failed">("idle");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const connect = async () => {
    setPhase("running");
    try {
      await api.authStart();
    } catch (e) {
      setPhase("failed");
      toast.error(e instanceof ApiError ? e.message : "Could not start login");
      return;
    }
    // poll status until connected / failed
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.authStatus();
        if (s.live || s.status === "connected") {
          if (pollRef.current) clearInterval(pollRef.current);
          toast.success("Swiggy connected!");
          onConnected();
        } else if (s.status === "failed") {
          if (pollRef.current) clearInterval(pollRef.current);
          setPhase("failed");
          toast.error(s.error ?? "Login failed");
        }
      } catch {
        /* transient poll error — keep trying */
      }
    }, 1500);
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-3 rounded-xl border border-border/60 bg-surface-elevated p-3">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-success" />
        <p className="text-xs leading-relaxed text-muted-foreground">
          Connect your Swiggy account to plan with real restaurants near you and
          place real orders. A browser window opens for you to log in securely —
          your token stays on this machine, never in the browser.
        </p>
      </div>

      <Button
        onClick={connect}
        disabled={phase === "running"}
        className={cn("h-11 w-full text-white", gradients.brand)}
      >
        {phase === "running" ? (
          <>
            <Loader2 className="size-4 animate-spin" />
            Waiting for Swiggy login…
          </>
        ) : (
          <>
            <ExternalLink className="size-4" />
            Connect Swiggy
          </>
        )}
      </Button>

      {phase === "running" && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-center text-xs text-muted-foreground"
        >
          Finish logging in on the opened browser tab, then come back here.
        </motion.p>
      )}

      {onSkip && (
        <button
          onClick={onSkip}
          className="text-center text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          Skip for now — use demo mode (mock menu, no real orders)
        </button>
      )}
    </div>
  );
}

export default ConnectSwiggy;
