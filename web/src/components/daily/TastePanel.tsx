"use client";

import { useState } from "react";
import { Ban, Minus, Plus, Trash2 } from "lucide-react";

import type { MemoryBullet } from "@/lib/types";
import { cn } from "@/lib/utils";
import { focusRing } from "@/lib/design";

type Change = { delete?: boolean; weight?: number };

const GROUPS: { title: string; hint: string; pick: (b: MemoryBullet) => boolean }[] = [
  { title: "Dishes you like", hint: "Shown more often", pick: (b) => !b.blocked && b.weight > 0 && b.dimension === "dish" },
  { title: "Places you order from", hint: "", pick: (b) => !b.blocked && b.weight > 0 && b.dimension === "restaurant" },
  { title: "Flavours and cuisines", hint: "", pick: (b) => !b.blocked && b.weight > 0 && ["cuisine", "ingredient"].includes(b.dimension) },
  { title: "From your Instamart basket", hint: "Used for add-ons", pick: (b) => !b.blocked && b.weight > 0 && b.dimension === "grocery" },
  { title: "Showing less of", hint: "", pick: (b) => !b.blocked && b.weight < 0 },
  { title: "Never shown", hint: "", pick: (b) => b.blocked },
];

/** 1–3 filled dots: how strongly this is believed (weights saturate around 6). */
function Strength({ weight }: { weight: number }) {
  const level = Math.min(3, Math.max(1, Math.ceil(Math.abs(weight) / 2)));
  return (
    <span className="flex gap-0.5" aria-label={`Strength ${level} of 3`}>
      {[1, 2, 3].map((n) => (
        <span key={n} className={cn("size-1.5 rounded-full", n <= level ? (weight < 0 ? "bg-warning" : "bg-rating") : "bg-border")} />
      ))}
    </span>
  );
}

export function TastePanel({
  facts,
  bullets,
  onEdit,
  wide = false,
}: {
  wide?: boolean;
  facts: string[];
  bullets: MemoryBullet[];
  onEdit: (b: MemoryBullet, change: Change) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const open = bullets.find((b) => b.id === openId) ?? null;
  const groups = GROUPS.map((g) => ({ ...g, items: bullets.filter(g.pick) })).filter((g) => g.items.length > 0);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="font-heading text-lg font-extrabold">Your taste profile</h2>
        <p className="text-xs text-muted-foreground">
          Learned from what you order, like and skip. Tap anything to correct it.
        </p>
      </div>

      {facts.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {facts.flatMap((f) => f.split(/; | with weekday overrides /)).map((f) => (
            <li key={f} className="rounded-lg bg-muted px-2 py-1 text-xs font-semibold capitalize">
              {f.replace(/=/g, ": ")}
            </li>
          ))}
        </ul>
      )}

      {groups.length === 0 && (
        <p className="rounded-xl border border-dashed border-border p-3 text-sm text-muted-foreground">
          Nothing learned yet. Order a meal or tap the thumbs on a card, and it shows up here.
        </p>
      )}

      <div className={cn("grid gap-x-8 gap-y-5", wide && "md:grid-cols-2")}>
      {groups.map((g) => (
        <section key={g.title} className="flex flex-col gap-2">
          <h3 className="flex items-baseline justify-between text-sm font-bold">
            {g.title}
            {g.hint && <span className="text-[11px] font-medium text-muted-foreground">{g.hint}</span>}
          </h3>
          <ul className="flex flex-wrap gap-1.5">
            {g.items.map((b) => (
              <li key={b.id}>
                <button
                  type="button"
                  aria-expanded={openId === b.id}
                  onClick={() => setOpenId(openId === b.id ? null : b.id)}
                  className={cn(
                    focusRing,
                    "flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-left text-[13px] font-semibold capitalize transition active:scale-95",
                    openId === b.id ? "border-brand-500 bg-brand-50 text-brand-700" : "border-border bg-card hover:border-brand-300",
                    b.blocked && "line-through decoration-danger/60"
                  )}
                >
                  {b.blocked ? <Ban className="size-3 shrink-0 text-danger" aria-hidden /> : <Strength weight={b.weight} />}
                  <span className="line-clamp-1">{b.key.replace(/_/g, " ")}</span>
                </button>
              </li>
            ))}
          </ul>

          {/* the editor opens under the group that owns the selected chip */}
          {open && g.items.some((b) => b.id === open.id) && (
            <div className="flex flex-col gap-2 rounded-xl bg-muted/60 p-3">
              <p className="text-sm">
                <span className="font-bold capitalize">{open.key.replace(/_/g, " ")}</span>
                {open.why && <span className="text-muted-foreground"> · {open.why}</span>}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {!open.blocked && (
                  <>
                    <button type="button" onClick={() => onEdit(open, { weight: open.weight + 2 })} className={cn(focusRing, "flex items-center gap-1 rounded-lg bg-card px-2.5 py-1.5 text-xs font-bold shadow-soft transition hover:text-rating active:scale-95")}>
                      <Plus className="size-3.5" aria-hidden /> Show more
                    </button>
                    <button type="button" onClick={() => onEdit(open, { weight: open.weight - 2 })} className={cn(focusRing, "flex items-center gap-1 rounded-lg bg-card px-2.5 py-1.5 text-xs font-bold shadow-soft transition hover:text-warning active:scale-95")}>
                      <Minus className="size-3.5" aria-hidden /> Show less
                    </button>
                  </>
                )}
                <button
                  type="button"
                  onClick={() => {
                    onEdit(open, { delete: true });
                    setOpenId(null);
                  }}
                  className={cn(focusRing, "flex items-center gap-1 rounded-lg bg-card px-2.5 py-1.5 text-xs font-bold shadow-soft transition hover:text-danger active:scale-95")}
                >
                  <Trash2 className="size-3.5" aria-hidden /> {open.blocked ? "Allow again" : "Forget"}
                </button>
              </div>
            </div>
          )}
        </section>
      ))}
      </div>
    </div>
  );
}

export default TastePanel;
