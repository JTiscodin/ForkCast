"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { focusRing } from "@/lib/design";
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
    // opened synchronously in the click so the browser allows it; pointed at Swiggy
    // once the backend has the login URL. A tab we opened can close itself afterwards.
    const popup = window.open("about:blank", "swiggy-login");
    let sent = false;
    try {
      await api.authStart(Boolean(popup));
    } catch (e) {
      setPhase("failed");
      toast.error(e instanceof ApiError ? e.message : "Could not start login");
      return;
    }
    // poll status until connected / failed
    pollRef.current = setInterval(async () => {
      try {
        const s = await api.authStatus();
        if (popup && s.url && !sent) {
          sent = true;
          popup.location.href = s.url;
        }
        if (s.live || s.status === "connected") {
          popup?.close();
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
      {/* brand-50 tint panel — Swiggy-style quiet tip card */}
      <div className="flex items-start gap-3 rounded-lg border border-brand-100 bg-brand-50 p-3">
        <ShieldCheck strokeWidth={2.4} className="mt-0.5 size-5 shrink-0 text-brand-700" />
        <p className="text-sm leading-[1.4] text-muted-foreground">
          You sign in on Swiggy&apos;s own page; Forkcast never sees your password. We use the
          connection to read menus and your saved addresses, and to build a cart when you ask.
          Orders are cash on delivery and always need your confirmation.
        </p>
      </div>

      <Button
        onClick={connect}
        disabled={phase === "running"}
        size="lg"
        className="w-full"
      >
        {phase === "running" ? (
          <>
            <Loader2 strokeWidth={2.4} className="size-4 animate-spin" />
            Waiting for Swiggy login…
          </>
        ) : (
          <>
            <ExternalLink strokeWidth={2.4} className="size-4" />
            Connect Swiggy
          </>
        )}
      </Button>

      {phase === "running" && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-center text-sm leading-[1.4] text-muted-foreground"
        >
          Finish logging in on the opened browser tab, then come back here.
        </motion.p>
      )}

      {onSkip && (
        <button
          type="button"
          onClick={onSkip}
          className={cn(
            "rounded-md text-center text-sm leading-[1.4] text-muted-foreground underline-offset-4 hover:text-brand-600 hover:underline",
            focusRing
          )}
        >
          Skip for now and use demo mode (mock menu, no real orders)
        </button>
      )}
    </div>
  );
}

export default ConnectSwiggy;
