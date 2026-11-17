"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Minus, Plus, ShoppingBasket, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import type { CardItem, MenuCard } from "@/lib/types";
import { cn } from "@/lib/utils";
import { focusRing } from "@/lib/design";
import { formatINR } from "@/components/dish/dish-helpers";

type Option = CardItem & { group?: string };

/** Swap a card's sides (anything the restaurant sells) and its Instamart add-on, or drop them. */
export function CustomiseCard({ userId, card, onSaved }: { userId: number; card: MenuCard; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [opts, setOpts] = useState<{ sides: Option[]; addons: Option[] } | null>(null);
  const [qty, setQty] = useState<Record<string, number>>({});
  const [addonId, setAddonId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!open || opts) return;
    api
      .cardOptions(userId, card.id)
      .then(setOpts)
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : "Couldn't load the options");
        setOpen(false);
      });
  }, [open, opts, userId, card.id]);

  function start() {
    setQty(Object.fromEntries(card.items.filter((i) => i.side).map((i) => [i.id, i.quantity ?? 1])));
    setAddonId(card.items.find((i) => i.addon)?.id ?? "");
    setOpen(true);
  }

  const main = card.items.filter((i) => !i.side && !i.addon);
  const total = useMemo(() => {
    if (!opts) return card.price;
    const sides = opts.sides.reduce((t, o) => t + o.price * (qty[o.id] ?? 0), 0);
    const add = opts.addons.find((a) => a.id === addonId)?.price ?? 0;
    return main.reduce((t, i) => t + i.price * (i.quantity ?? 1), 0) + sides + add;
  }, [opts, qty, addonId, main, card.price]);

  async function save() {
    setSaving(true);
    try {
      await api.editCard(userId, card.id, {
        sides: Object.entries(qty)
          .filter(([, n]) => n > 0)
          .map(([id, quantity]) => ({ id, quantity })),
        addon_id: addonId || null,
      });
      toast.success("Updated");
      setOpen(false);
      onSaved();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button type="button" onClick={start} className={cn(focusRing, "inline-flex w-fit items-center gap-1.5 rounded-full text-xs font-bold text-brand-600 hover:underline dark:text-brand-400")}>
        <SlidersHorizontal className="size-3.5" aria-hidden /> Change sides and add-on
      </button>
    );
  }

  const shown = (opts?.sides ?? []).filter((o) => !q || o.name.toLowerCase().includes(q.toLowerCase()) || (qty[o.id] ?? 0) > 0);
  const groups = [...new Set(shown.map((o) => o.group ?? "Sides"))];

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-brand-500/40 bg-brand-500/5 p-3 text-[13px]">
      {!opts ? (
        <p className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden /> Loading the menu…
        </p>
      ) : (
        <>
          {opts.sides.length > 8 && (
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search this restaurant's menu"
              aria-label="Search sides"
              className="h-9 rounded-lg border border-border bg-card px-3 text-sm"
            />
          )}
          <div className="flex max-h-72 flex-col gap-3 overflow-y-auto pr-1">
            {groups.map((g) => (
              <fieldset key={g} className="flex flex-col gap-1">
                <legend className="mb-1 text-xs font-bold text-muted-foreground">{g}</legend>
                {shown
                  .filter((o) => (o.group ?? "Sides") === g)
                  .map((o) => {
                    const n = qty[o.id] ?? 0;
                    return (
                      <div key={o.id} className={cn("flex items-center gap-2 rounded-lg px-2 py-1.5", n > 0 && "bg-card")}>
                        <span className="min-w-0 flex-1">
                          <span className="font-semibold">{o.name}</span>
                          <span className="ml-1 text-muted-foreground tabular-nums">{formatINR(o.price)}</span>
                        </span>
                        <span className="flex shrink-0 items-center gap-1">
                          {n > 0 && (
                            <>
                              <button type="button" aria-label={`One less ${o.name}`} onClick={() => setQty((x) => ({ ...x, [o.id]: n - 1 }))} className={cn(focusRing, "rounded-md border border-border p-1")}>
                                <Minus className="size-3" aria-hidden />
                              </button>
                              <span className="w-4 text-center font-bold tabular-nums">{n}</span>
                            </>
                          )}
                          <button
                            type="button"
                            aria-label={`Add ${o.name}`}
                            disabled={n >= 6}
                            onClick={() => setQty((x) => ({ ...x, [o.id]: n + 1 }))}
                            className={cn(focusRing, "rounded-md border border-border p-1 disabled:opacity-40", n === 0 && "border-brand-500 text-brand-600 dark:text-brand-400")}
                          >
                            <Plus className="size-3" aria-hidden />
                          </button>
                        </span>
                      </div>
                    );
                  })}
              </fieldset>
            ))}
            {!opts.sides.length && <p className="text-muted-foreground">This restaurant has nothing else that fits your diet.</p>}

            <fieldset className="flex flex-col gap-1">
              <legend className="mb-1 flex items-center gap-1 text-xs font-bold text-muted-foreground">
                <ShoppingBasket className="size-3.5" aria-hidden /> Instamart add-on
              </legend>
              {[{ id: "", name: "No add-on", price: 0, addon_reason: "" } as Option, ...opts.addons].map((a) => (
                <label key={a.id || "none"} className={cn("flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5", addonId === a.id && "bg-card")}>
                  <input type="radio" name={`addon-${card.id}`} checked={addonId === a.id} onChange={() => setAddonId(a.id)} className="accent-brand-500" />
                  <span className="min-w-0 flex-1">
                    <span className="font-semibold">{a.name}</span>
                    {a.addon_reason && <span className="block text-xs text-muted-foreground">To {a.addon_reason.replace(/^add /, "add ")}</span>}
                  </span>
                  {a.id && <span className="shrink-0 text-muted-foreground tabular-nums">{formatINR(a.price)}</span>}
                </label>
              ))}
            </fieldset>
          </div>
          <div className="flex items-center gap-2 border-t border-border pt-2">
            <span className="flex-1 font-bold tabular-nums">New total {formatINR(total)}</span>
            <button type="button" onClick={() => setOpen(false)} className={cn(focusRing, "rounded-lg px-3 py-1.5 font-bold text-muted-foreground")}>
              Cancel
            </button>
            <button
              type="button"
              disabled={saving || total >= 1000}
              title={total >= 1000 ? "Swiggy orders must stay under ₹1000" : undefined}
              onClick={save}
              className={cn(focusRing, "inline-flex items-center gap-1.5 rounded-lg bg-brand-500 px-3 py-1.5 font-extrabold text-white disabled:opacity-50")}
            >
              {saving && <Loader2 className="size-3.5 animate-spin" aria-hidden />} Save
            </button>
          </div>
        </>
      )}
    </div>
  );
}
