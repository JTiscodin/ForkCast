"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";
import {
  Ban,
  CheckCircle2,
  ChevronRight,
  Clock,
  CloudRain,
  CloudSun,
  Leaf,
  Loader2,
  MapPin,
  Send,
  Settings,
  ShieldAlert,
  ShoppingBasket,
  Snowflake,
  Star,
  Sun,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Wallet,
  Zap,
} from "lucide-react";

import { api } from "@/lib/api";
import type { CardItem, DailySlot, MemoryBullet, MenuCard, OrderOutcome, TodayView as Today } from "@/lib/types";
import { cn } from "@/lib/utils";
import { focusRing, mealStyle } from "@/lib/design";
import { fadeUp } from "@/lib/motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { LottiePlayer } from "@/components/ui/LottiePlayer";
import { BowlIllustration } from "@/components/ui/illustrations";
import { DishImage } from "@/components/dish/DishImage";
import { DietMarker } from "@/components/dish/DishCard";
import { formatINR } from "@/components/dish/dish-helpers";

gsap.registerPlugin(useGSAP);

const ROLE_LABEL: Record<MenuCard["role"], string> = {
  usual: "Your usual",
  gap: "Fixes your gap",
  new: "Try something new",
  budget: "Budget pick",
  chat: "From chat",
};
const MACROS: { key: string; label: string; unit: string }[] = [
  { key: "kcal", label: "Energy", unit: "kcal" },
  { key: "protein", label: "Protein", unit: "g" },
  { key: "carbs", label: "Carbs", unit: "g" },
  { key: "fat", label: "Fat", unit: "g" },
  { key: "fibre", label: "Fibre", unit: "g" },
];
const MICROS = ["iron", "b12", "vitd", "calcium", "sodium", "sugar"];
const MICRO_LABEL: Record<string, string> = { b12: "B12", vitd: "Vitamin D" };
const LIMITS = new Set(["sodium", "sugar"]);
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function greeting(h: number) {
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

/** Swiggy's rating mark: white star in a solid green circle. */
function RatingDot() {
  return (
    <span className="inline-flex size-[18px] items-center justify-center rounded-full bg-rating" aria-hidden>
      <Star className="size-2.5 fill-white text-white" strokeWidth={2.6} />
    </span>
  );
}

function Ring({ value, target, label, unit }: { value: number; target: number; label: string; unit: string }) {
  const size = 64;
  const stroke = 6;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.min(1, value / Math.max(target, 1));
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90" aria-hidden>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="stroke-muted" />
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            strokeWidth={stroke}
            strokeLinecap="round"
            className="stroke-brand-500"
            strokeDasharray={c}
            initial={{ strokeDashoffset: c }}
            animate={{ strokeDashoffset: c * (1 - pct) }}
            transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-xs font-extrabold tabular-nums">
          {Math.round(pct * 100)}%
        </span>
      </div>
      <span className="text-[11px] font-bold text-foreground/80">{label}</span>
      <span className="text-[11px] tabular-nums text-muted-foreground" aria-label={`${label} ${Math.round(value)} of ${Math.round(target)} ${unit}`}>
        {Math.round(value)}/{Math.round(target)}
        {unit === "g" ? "g" : ""}
      </span>
    </div>
  );
}

function MicroBar({ k, value, target }: { k: string; value: number; target: number }) {
  const pct = Math.min(100, Math.round((value / Math.max(target, 1)) * 100));
  const over = LIMITS.has(k) && value > target;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-xs">
        <span className="font-semibold capitalize">{MICRO_LABEL[k] ?? k}</span>
        <span className="tabular-nums text-muted-foreground">
          ~{Math.round(value)} / {Math.round(target)}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={k} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn("h-full rounded-full transition-[width] duration-700", over ? "bg-danger" : "bg-brand-500")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function sideLine(i: CardItem) {
  const qty = (i.quantity ?? 1) > 1 ? ` ×${i.quantity}` : "";
  return `${i.name}${qty} · ${formatINR(i.price * (i.quantity ?? 1))}`;
}

function MealCard({
  card,
  locked,
  dryRun,
  onOrder,
  onFeedback,
}: {
  card: MenuCard;
  locked: boolean;
  dryRun: boolean;
  onOrder: (c: MenuCard) => Promise<void>;
  onFeedback: (c: MenuCard, type: string) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const main = card.items[0];
  const grocery = main.source === "instamart";
  const sides = grocery ? [] : card.items.slice(1).filter((i) => !i.addon);
  const addon = card.items.find((i) => i.addon);
  const title = grocery ? card.items.filter((i) => !i.addon).map((i) => i.name).join(" + ") : main.name;
  const rating = (main as CardItem & { rating?: number }).rating;
  const warnings = card.reasons.filter((r) => r.startsWith("Above") || r.startsWith("Severe"));
  const why = card.reasons.find((r) => !warnings.includes(r) && !r.startsWith("add "));
  const veg = card.items.every((i) => i.veg);

  return (
    <article data-reveal className={cn("group/meal flex flex-col", locked && "opacity-60")}>
      {/* Swiggy-style photo: label + price on a dark gradient, press-to-shrink */}
      <div className="relative aspect-[4/3] overflow-hidden rounded-2xl bg-muted transition-transform duration-200 ease-out group-hover/meal:scale-[0.97]">
        <div className="absolute inset-0 transition-transform duration-500 ease-out group-hover/meal:scale-105">
          <DishImage src={main.image_url} alt={title} sizes="(min-width: 1280px) 260px, 50vw" />
        </div>
        <div aria-hidden className="absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-black/80 via-black/30 to-transparent" />
        {grocery && (
          <span className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-md bg-white px-1.5 py-0.5 text-[11px] font-extrabold text-meal-snack">
            <ShoppingBasket className="size-3" aria-hidden /> Instamart
          </span>
        )}
        <div className="absolute inset-x-3 bottom-2.5 text-white">
          <p className="text-[11px] font-extrabold uppercase tracking-wide text-white/85">{ROLE_LABEL[card.role]}</p>
          <p className="text-xl font-extrabold leading-tight tracking-[-0.02em] tabular-nums">{formatINR(card.price)}</p>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-1 px-1 pt-2.5">
        <h3 className="flex items-start gap-1.5 text-[15px] font-extrabold leading-snug tracking-[-0.01em]">
          <span className="mt-[3px]">
            <DietMarker veg={veg} />
          </span>
          <span className="line-clamp-2">{title}</span>
        </h3>
        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 whitespace-nowrap text-[13px] font-bold">
          {typeof rating === "number" && !grocery && (
            <>
              <RatingDot />
              <span>{rating.toFixed(1)}</span>
              <span className="text-muted-foreground" aria-hidden>•</span>
            </>
          )}
          <span>~{Math.round(card.nutrients.kcal ?? 0)} kcal</span>
          <span className="text-muted-foreground" aria-hidden>•</span>
          <span>{Math.round(card.nutrients.protein ?? 0)}g protein</span>
        </p>
        <p className="truncate text-sm text-muted-foreground">{grocery ? "Instamart · delivered in minutes" : main.restaurant_name}</p>
        {sides.map((s) => (
          <p key={s.id} className="truncate text-xs text-muted-foreground">
            with {sideLine(s)}
          </p>
        ))}
        {addon && (
          <p className="flex items-center gap-1 truncate text-xs text-meal-snack" title={addon.addon_reason}>
            <ShoppingBasket className="size-3 shrink-0" aria-hidden />
            <span className="sr-only">Instamart add-on: </span>+ {sideLine(addon)}
          </p>
        )}
        {why && <p className="text-xs text-muted-foreground">{why}</p>}
        {warnings.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-0.5">
            {warnings.map((w) => (
              <span
                key={w}
                title={w}
                className={cn(
                  "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-bold",
                  w.startsWith("Severe") ? "bg-danger/10 text-danger" : "bg-warning/12 text-warning"
                )}
              >
                {w.startsWith("Severe") ? <ShieldAlert className="size-3" aria-hidden /> : <Wallet className="size-3" aria-hidden />}
                <span className="sr-only">{w}</span>
                <span aria-hidden>{w.startsWith("Severe") ? (grocery ? "Check label" : "Confirm allergens") : "Over today's cap"}</span>
              </span>
            ))}
          </div>
        )}

        <div className="mt-auto pt-2.5">
          {confirming ? (
            <div className="flex flex-col gap-2">
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    await onOrder(card);
                    setBusy(false);
                    setConfirming(false);
                  }}
                  className={cn(focusRing, "flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-rating px-3 py-2 text-sm font-extrabold uppercase tracking-wide text-white transition active:scale-95 disabled:opacity-80")}
                >
                  {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
                  {busy ? (dryRun ? "Building cart" : "Placing") : `Confirm ${formatINR(card.price)}`}
                </button>
                {!busy && (
                  <button type="button" onClick={() => setConfirming(false)} className={cn(focusRing, "rounded-lg px-3 text-sm font-bold text-muted-foreground hover:text-foreground")}>
                    Cancel
                  </button>
                )}
              </div>
              <p className="text-[11px] leading-snug text-muted-foreground" role="note">
                {dryRun ? "Dry run: builds your real Swiggy cart, nothing is ordered. " : "Places a real order, paid by cash on delivery. "}
                Replaces your current Swiggy cart. Delivery fees and taxes are added at checkout.
              </p>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-1">
              {/* Swiggy's ADD button: white, green bold caps, soft shadow */}
              <button
                type="button"
                disabled={locked}
                onClick={() => setConfirming(true)}
                className={cn(focusRing, "rounded-lg border border-border bg-card px-5 py-1.5 text-sm font-extrabold uppercase tracking-wide text-rating shadow-soft transition hover:bg-muted active:scale-95 disabled:cursor-not-allowed disabled:text-muted-foreground")}
              >
                {locked ? "Done" : "Order"}
              </button>
              <div className="flex">
                {(
                  [
                    ["up", ThumbsUp, "More like this"],
                    ["down", ThumbsDown, "Less like this"],
                    ["not_today", Clock, "Not today"],
                    ["never", Ban, "Never show this"],
                  ] as const
                ).map(([t, Icon, label]) => (
                  <button
                    key={t}
                    type="button"
                    aria-label={label}
                    title={label}
                    onClick={() => onFeedback(card, t)}
                    className={cn(focusRing, "rounded-md p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground active:scale-90")}
                  >
                    <Icon className="size-[15px]" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

function Nudge({ slot, onLog }: { slot: DailySlot; onLog: (kind: string, text?: string) => void }) {
  const [text, setText] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-2xl bg-card p-3 text-sm shadow-soft">
      <span className="font-bold">What did you have for {slot.slot}?</span>
      <Input aria-label="Dish name (optional)" placeholder="dish (optional)" value={text} onChange={(e) => setText(e.target.value)} className="h-8 w-40" />
      <Button size="sm" variant="outline" onClick={() => onLog("elsewhere", text)}>
        Ordered elsewhere
      </Button>
      <Button size="sm" variant="outline" onClick={() => onLog("home", text)}>
        Ate at home
      </Button>
      <Button size="sm" variant="ghost" onClick={() => onLog("skipped")}>
        Skipped
      </Button>
    </div>
  );
}

export function TodayView({ userId, onEditProfile }: { userId: number; onEditProfile: () => void }) {
  const [data, setData] = useState<Today | null>(null);
  const [memory, setMemory] = useState<{ facts: string[]; bullets: MemoryBullet[] }>({ facts: [], bullets: [] });
  const [chat, setChat] = useState<{ role: "you" | "bot"; text: string }[]>([]);
  const [msg, setMsg] = useState("");
  const [thinking, setThinking] = useState(false);
  const [armLive, setArmLive] = useState(false);
  const [cartBar, setCartBar] = useState<{ title: string; outcome: OrderOutcome } | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const chatEnd = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const [t, m] = await Promise.all([api.today(userId), api.memory(userId)]);
      setData(t);
      setMemory(m);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't load today");
    }
  }, [userId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [chat, thinking]);

  useEffect(() => {
    if (!cartBar) return;
    const t = setTimeout(() => setCartBar(null), 7000);
    return () => clearTimeout(t);
  }, [cartBar]);

  // One gentle entrance per day's data; no ambient loops (they read as noise).
  useGSAP(
    () => {
      if (data) fadeUp("[data-reveal]", { y: 12, stagger: 0.035 });
    },
    { scope: rootRef, dependencies: [data?.date] }
  );

  async function order(card: MenuCard) {
    try {
      const r = await api.orderCard(userId, card.id);
      const failed = r.orders.filter((o) => o.status === "failed");
      for (const o of failed) {
        toast.error(`${o.platform === "food" ? "Restaurant" : "Instamart"} order failed: ${o.error ?? ""}`, {
          action: o.fallback_url ? { label: "Open Swiggy", onClick: () => window.open(o.fallback_url!, "_blank") } : undefined,
        });
      }
      if (failed.length < r.orders.length) setCartBar({ title: card.items[0].name, outcome: r });
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Order failed");
    }
  }

  async function feedback(card: MenuCard, type: string) {
    try {
      await api.feedback(userId, card.id, type);
      toast.success(
        { up: "Got it, more like this", down: "Noted, less like this", not_today: "Swapping it out for today", never: "Won't show that again" }[type] ?? "Noted"
      );
      if (type === "never" || type === "not_today") {
        await api.regenerate(userId, data?.slots.find((s) => s.cards.some((c) => c.id === card.id))?.slot);
      }
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  async function logMeal(slot: string, kind: string, text = "") {
    await api.logMeal(userId, slot, kind, text).catch((e) => toast.error(String(e)));
    toast.success("Logged");
    load();
  }

  async function send(text?: string) {
    const m = (text ?? msg).trim();
    if (!m) return;
    setMsg("");
    setChat((c) => [...c, { role: "you", text: m }]);
    setThinking(true);
    try {
      const r = await api.agent(userId, m);
      setChat((c) => [...c, { role: "bot", text: r.reply }]);
      load();
    } catch (e) {
      setChat((c) => [...c, { role: "bot", text: e instanceof Error ? e.message : "Something went wrong" }]);
    } finally {
      setThinking(false);
    }
  }

  async function setMode(next: "live" | "dry_run") {
    setArmLive(false);
    await api.saveDailyProfile(userId, { mode: next });
    toast(next === "live" ? "Live: orders will really be placed (cash on delivery)" : "Dry run: carts only, no orders");
    load();
  }

  async function editMemory(b: MemoryBullet, change: { delete?: boolean; weight?: number }) {
    setMemory(await api.editMemory(userId, { dimension: b.dimension, key: b.key, ...change }));
    load();
  }

  if (!data) {
    // Swiggy-style shimmer of the real layout, not a spinner
    return (
      <div className="mx-auto grid w-full max-w-7xl gap-6 px-4 py-6 lg:grid-cols-[1fr_340px] lg:px-6" aria-busy="true">
        <div className="flex flex-col gap-6">
          <p className="sr-only" role="status">
            Finding meals near you on Swiggy
          </p>
          <Skeleton className="h-16 w-2/3 rounded-xl" />
          <div className="flex gap-6">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="size-24 rounded-full" />
            ))}
          </div>
          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex flex-col gap-2">
                <Skeleton className="aspect-[4/3] rounded-2xl" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
              </div>
            ))}
          </div>
        </div>
        <Skeleton className="hidden h-96 rounded-2xl lg:block" />
      </div>
    );
  }

  const n = data.nutrition;
  const now = new Date();
  const hhmm = now.toTimeString().slice(0, 5);
  const currentSlot = data.slots.find((s) => s.window[0] <= hhmm && hhmm <= s.window[1])?.slot;
  const upcoming = currentSlot ?? data.slots.find((s) => s.window[0] > hhmm)?.slot;
  const overrides = Object.entries(data.profile.weekday_overrides);
  const WeatherIcon = data.weather.rain ? CloudRain : data.weather.hot ? Sun : data.season === "winter" ? Snowflake : CloudSun;
  const live = data.profile.mode === "live";

  const info: { icon: React.ReactNode; label: string; value: string }[] = [
    { icon: <Wallet className="size-4 text-brand-500" />, label: "Today's budget", value: `${formatINR(data.budget.daily_cap)} · ${formatINR(data.budget.remaining)} left this month` },
    { icon: <Zap className="size-4 text-rating" />, label: "Protein so far", value: `${Math.round(n.today.protein ?? 0)} of ${Math.round(n.targets.protein)}g` },
    {
      icon: <Leaf className="size-4 text-diet-veg" />,
      label: "Diet today",
      value: (() => {
        const cap = (d: string) => (d === "nonveg" ? "Non-veg" : d[0].toUpperCase() + d.slice(1));
        const todayIdx = (now.getDay() + 6) % 7; // JS Sunday=0 -> Mon=0 like the backend
        const todayRule = data.profile.weekday_overrides[String(todayIdx)];
        if (todayRule) return `${cap(data.diet)} · your ${DAYS[todayIdx]} rule`;
        const others = overrides.map(([d, v]) => `${DAYS[+d]}: ${cap(v)}`).join(", ");
        return `${cap(data.diet)}${others ? ` · ${others}` : ""}`;
      })(),
    },
    { icon: <WeatherIcon className="size-4 text-meal-dinner" />, label: "Weather", value: `${data.weather.rain ? "Rainy" : data.weather.hot ? "Hot" : data.season[0].toUpperCase() + data.season.slice(1)}${data.profile.city ? ` in ${data.profile.city}` : ""}` },
  ];

  return (
    <div ref={rootRef} className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-6 lg:grid-cols-[1fr_340px] lg:px-6">
      <main className="flex min-w-0 flex-col gap-8">
        {/* Header: plain, bold, Swiggy-white — the food carries the colour */}
        <header data-reveal className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <p className="flex items-center gap-1 text-sm font-semibold text-muted-foreground">
              {greeting(now.getHours())}
              {data.profile.city && (
                <>
                  <span aria-hidden>·</span>
                  <MapPin className="size-3.5" aria-hidden />
                  {data.profile.city}
                </>
              )}
            </p>
            <h1 className="text-[28px] font-extrabold leading-tight tracking-[-0.03em] sm:text-[32px]">
              {upcoming ? `What's for ${mealStyle(upcoming).label.toLowerCase()} today?` : "That's a wrap for today"}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            {/* Going live spends real money: it takes a second, explicit tap */}
            {armLive ? (
              <span className="flex items-center gap-1 rounded-full bg-card p-1 text-xs font-bold shadow-soft">
                <span className="px-2 text-danger">Place real orders?</span>
                <button type="button" onClick={() => setMode("live")} className={cn(focusRing, "rounded-full bg-danger px-2.5 py-1 text-white")}>
                  Go live
                </button>
                <button type="button" onClick={() => setArmLive(false)} className={cn(focusRing, "rounded-full px-2.5 py-1 text-muted-foreground hover:text-foreground")}>
                  Cancel
                </button>
              </span>
            ) : (
              <button
                type="button"
                role="switch"
                aria-checked={live}
                onClick={() => (live ? setMode("dry_run") : setArmLive(true))}
                className={cn(focusRing, "flex items-center gap-2 rounded-full bg-card py-1 pl-3 pr-1 text-xs font-bold shadow-soft")}
              >
                <span className={live ? "text-danger" : "text-muted-foreground"}>{live ? "Live orders" : "Dry run"}</span>
                <span className={cn("relative h-5 w-9 rounded-full transition-colors", live ? "bg-danger" : "bg-muted")}>
                  <span className={cn("absolute top-0.5 size-4 rounded-full bg-white shadow transition-[left]", live ? "left-[18px]" : "left-0.5")} />
                </span>
              </button>
            )}
            <button type="button" aria-label="Edit preferences" onClick={onEditProfile} className={cn(focusRing, "rounded-full bg-card p-2 shadow-soft transition hover:bg-muted")}>
              <Settings className="size-4" />
            </button>
          </div>
        </header>

        {/* "What's on your mind?"-style slot row: round dish photos, jump to the slot */}
        <nav data-reveal aria-label="Meals today" className="-mx-4 flex gap-5 overflow-x-auto px-4 pb-1 sm:gap-8">
          {data.slots.map((s) => {
            const img = s.cards[0]?.items[0];
            const now_ = s.slot === currentSlot;
            return (
              <a key={s.slot} href={`#slot-${s.slot}`} className={cn(focusRing, "group/chip flex shrink-0 flex-col items-center gap-2 rounded-xl")}>
                <span
                  className={cn(
                    "relative size-24 overflow-hidden rounded-full bg-muted ring-offset-2 ring-offset-background transition-transform duration-200 group-hover/chip:scale-95",
                    now_ ? "ring-[3px] ring-brand-500" : s.ordered ? "ring-[3px] ring-rating" : ""
                  )}
                >
                  {img ? <DishImage src={img.image_url} alt="" sizes="96px" /> : <BowlIllustration className="size-full p-4" />}
                  {s.ordered && (
                    <span className="absolute inset-0 flex items-center justify-center bg-black/40">
                      <CheckCircle2 className="size-7 text-white" aria-hidden />
                    </span>
                  )}
                </span>
                <span className="text-center leading-tight">
                  <span className="block text-sm font-extrabold">{mealStyle(s.slot).label}</span>
                  <span className={cn("block text-xs", now_ ? "font-bold text-brand-500" : "text-muted-foreground")}>{now_ ? "Now" : `${s.window[0]}–${s.window[1]}`}</span>
                </span>
              </a>
            );
          })}
        </nav>

        <section data-reveal aria-label="Today at a glance" className="grid grid-cols-1 gap-x-6 gap-y-3 rounded-2xl bg-card p-4 shadow-soft sm:grid-cols-2">
          {info.map((i) => (
            <div key={i.label} className="flex min-w-0 items-center gap-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted">{i.icon}</span>
              <span className="min-w-0">
                <span className="block text-xs font-semibold text-muted-foreground">{i.label}</span>
                <span className="block truncate text-sm font-extrabold">{i.value}</span>
              </span>
            </div>
          ))}
        </section>

        {data.slots.map((s) => (
          <section key={s.slot} id={`slot-${s.slot}`} className="flex scroll-mt-6 flex-col gap-4">
            <div data-reveal className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border pb-3">
              <h2 className="text-xl font-extrabold tracking-[-0.02em]">{mealStyle(s.slot).label}</h2>
              <span className="text-sm text-muted-foreground">
                {s.window[0]}–{s.window[1]}
              </span>
              {s.slot === currentSlot && <span className="text-sm font-bold text-brand-500">● Now</span>}
              {s.ordered && (
                <span className="ml-auto inline-flex items-center gap-1 text-sm font-bold text-rating">
                  <CheckCircle2 className="size-4" aria-hidden />
                  {s.ordered.status === "dry_run" ? "Cart built (dry run)" : "Ordered"}
                </span>
              )}
            </div>

            {s.nudge && !s.ordered && <Nudge slot={s} onLog={(k, t) => logMeal(s.slot, k, t)} />}

            {s.cards.length === 0 ? (
              <div className="flex items-center gap-3 rounded-2xl bg-card p-4 text-sm text-muted-foreground shadow-soft">
                <BowlIllustration className="w-14 opacity-70" />
                Nothing nearby fits your rules for this meal right now.
              </div>
            ) : (
              <div className="grid gap-x-5 gap-y-7 sm:grid-cols-2 xl:grid-cols-4">
                {s.cards.map((c) => (
                  <MealCard key={c.id} card={c} locked={Boolean(s.ordered)} dryRun={!live} onOrder={order} onFeedback={feedback} />
                ))}
              </div>
            )}

            {s.excluded.length > 0 && (
              <details className="rounded-xl bg-card px-4 py-2.5 text-sm shadow-soft">
                <summary className={cn(focusRing, "flex cursor-pointer items-center gap-1.5 font-bold text-danger")}>
                  <ShieldAlert className="size-4" /> Hidden for your allergies ({s.excluded.length})
                </summary>
                <ul className="mt-2 flex flex-col gap-1">
                  {s.excluded.map((e) => (
                    <li key={e.id} className="flex justify-between gap-2">
                      <span className="truncate">{e.items[0]?.name}</span>
                      <span className="shrink-0 text-xs text-danger">contains {e.allergen_hit}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-xs text-muted-foreground">Never recommended. To add one anyway, ask in chat.</p>
              </details>
            )}
          </section>
        ))}
      </main>

      <aside className="flex flex-col gap-5 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:self-start lg:overflow-y-auto">
        <section className="flex flex-col gap-4 rounded-2xl bg-card p-4 shadow-soft">
          <h2 className="font-extrabold">Today&apos;s nutrition</h2>
          <div className="grid grid-cols-3 gap-y-3">
            {MACROS.map((m) => (
              <Ring key={m.key} label={m.label} unit={m.unit} value={n.today[m.key] ?? 0} target={n.targets[m.key]} />
            ))}
          </div>
          <div className="flex flex-col gap-2 border-t border-border pt-3">
            <h3 className="text-sm font-extrabold">This week · daily average</h3>
            {n.days_logged === 0 ? (
              <p className="text-xs text-muted-foreground">No meals logged yet. Unlogged meals count as unknown, not missed.</p>
            ) : (
              MICROS.map((k) => <MicroBar key={k} k={k} value={n.week_avg[k] ?? 0} target={n.targets[k]} />)
            )}
            <p className="text-[11px] text-muted-foreground">Values are estimates</p>
          </div>
        </section>

        <section className="flex flex-col gap-3 rounded-2xl bg-card p-4 shadow-soft">
          <h2 className="font-extrabold">Ask or tell me</h2>
          <div className="flex max-h-72 flex-col gap-2 overflow-y-auto text-sm" aria-live="polite">
            {chat.length === 0 && (
              <div className="flex flex-wrap gap-1.5">
                {["Something spicy under 250", "I had dal and 2 roti at home", "What am I low on?", "Stop suggesting paneer"].map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => send(q)}
                    className={cn(focusRing, "rounded-full border border-border px-2.5 py-1 text-xs font-semibold transition hover:border-brand-500 hover:text-brand-500 active:scale-95")}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
            <AnimatePresence initial={false}>
              {chat.map((c, i) => (
                <motion.p
                  key={i}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={cn("max-w-[85%] rounded-2xl px-3 py-2 leading-snug", c.role === "you" ? "self-end rounded-br-sm bg-brand-500 text-white" : "self-start rounded-bl-sm bg-muted")}
                >
                  {c.text}
                </motion.p>
              ))}
            </AnimatePresence>
            {thinking && (
              <div className="flex items-center gap-2 self-start text-xs text-muted-foreground">
                <LottiePlayer path="/animations/cooking-pot.json" className="size-9" />
                Thinking…
              </div>
            )}
            <div ref={chatEnd} />
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <Input aria-label="Message" placeholder="Ask for a craving or log a meal" value={msg} onChange={(e) => setMsg(e.target.value)} />
            <Button size="icon" type="submit" aria-label="Send" disabled={thinking}>
              <Send />
            </Button>
          </form>
        </section>

        <section className="flex flex-col gap-2 rounded-2xl bg-card p-4 shadow-soft">
          <h2 className="font-extrabold">What we know about you</h2>
          <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
            {memory.facts.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          <ul className="flex flex-col">
            {memory.bullets.map((b) => (
              <li key={b.id} className="group/mem flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-muted/60">
                <span className="min-w-0">
                  <span className={cn("mr-1.5 inline-block size-1.5 rounded-full align-middle", b.blocked ? "bg-danger" : b.weight > 0 ? "bg-rating" : "bg-warning")} aria-hidden />
                  {b.text}
                </span>
                <span className="flex shrink-0 opacity-60 transition-opacity group-hover/mem:opacity-100">
                  {!b.blocked && (
                    <>
                      <Button size="icon" variant="ghost" aria-label={`More ${b.key}`} onClick={() => editMemory(b, { weight: b.weight + 2 })}>
                        <ThumbsUp />
                      </Button>
                      <Button size="icon" variant="ghost" aria-label={`Less ${b.key}`} onClick={() => editMemory(b, { weight: b.weight - 2 })}>
                        <ThumbsDown />
                      </Button>
                    </>
                  )}
                  <Button size="icon" variant="ghost" aria-label={`Forget ${b.key}`} onClick={() => editMemory(b, { delete: true })}>
                    <Trash2 />
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        </section>
      </aside>

      {/* Swiggy's green cart bar: the one piece of feedback an order needs */}
      <AnimatePresence>
        {cartBar && (
          <motion.div
            role="status"
            initial={{ y: 80, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }}
            transition={{ type: "spring", stiffness: 420, damping: 34 }}
            className="fixed inset-x-4 bottom-4 z-50 mx-auto flex max-w-xl items-center justify-between gap-3 rounded-xl bg-rating px-4 py-3 text-white shadow-layered"
          >
            <span className="min-w-0">
              <span className="block truncate text-sm font-extrabold">
                {cartBar.outcome.mode === "dry_run" ? "Cart built on Swiggy" : "Order placed"} · {cartBar.title}
              </span>
              <span className="block text-xs text-white/85">
                {cartBar.outcome.orders
                  .filter((o) => o.status !== "failed")
                  .map((o) => `${o.platform === "food" ? "Restaurant" : "Instamart"} ${formatINR(o.amount)}`)
                  .join(" + ")}{" "}
                to pay{cartBar.outcome.mode === "dry_run" ? " · dry run, nothing ordered" : ""}
              </span>
            </span>
            <a
              href="https://www.swiggy.com/checkout"
              target="_blank"
              rel="noreferrer"
              className={cn(focusRing, "flex shrink-0 items-center text-sm font-extrabold uppercase tracking-wide")}
            >
              View cart <ChevronRight className="size-4" aria-hidden />
            </a>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default TodayView;
