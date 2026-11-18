"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { disablePush, enablePush, remindersOn, setReminders } from "@/lib/reminders";
import type { DailyProfile, DailySlotName, DietType, Goal } from "@/lib/types";
import { cn } from "@/lib/utils";
import { focusRing, surfaces } from "@/lib/design";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const DIETS: DietType[] = ["veg", "eggetarian", "nonveg", "jain", "vegan"];
const GOALS: { id: Goal; label: string }[] = [
  { id: "lose", label: "Lose weight" },
  { id: "maintain", label: "Maintain" },
  { id: "gain", label: "Gain" },
  { id: "high_protein", label: "High protein" },
];
const SLOTS: DailySlotName[] = ["breakfast", "lunch", "snack", "dinner"];
// same as backend daily.DEFAULT_WINDOWS
const DEFAULT_WINDOWS: Record<DailySlotName, [string, string]> = {
  breakfast: ["07:00", "10:00"],
  lunch: ["12:00", "15:00"],
  snack: ["16:30", "18:30"],
  dinner: ["19:30", "22:30"],
};
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const COMMON_ALLERGENS = ["peanut", "shellfish", "dairy", "gluten", "soy", "egg", "tree nut", "fish"];
const SEVERE_DEFAULT = new Set(["peanut", "shellfish", "tree nut"]);

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        focusRing,
        "rounded-full border px-3 py-1.5 text-sm capitalize transition-colors",
        on ? "border-brand-500 bg-brand-500 text-white" : "border-border bg-card hover:bg-muted"
      )}
    >
      {children}
    </button>
  );
}

function Section({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-2xl bg-card p-4 shadow-soft">
      <h2 className="text-sm font-bold text-foreground">
        {n}. {title}
      </h2>
      <div className="flex flex-wrap gap-2">{children}</div>
    </section>
  );
}

export function DailyOnboarding({
  userId,
  initial,
  onDone,
}: {
  userId: number;
  initial?: DailyProfile | null;
  onDone: (p: DailyProfile) => void;
}) {
  const [diet, setDiet] = useState<DietType>(initial?.diet_type ?? "veg");
  const [overrides, setOverrides] = useState<Record<string, DietType>>(initial?.weekday_overrides ?? {});
  const [allergies, setAllergies] = useState<{ name: string; severe: boolean }[]>(initial?.allergies ?? []);
  const [otherAllergy, setOtherAllergy] = useState("");
  const [goal, setGoal] = useState<Goal>(initial?.goal ?? "maintain");
  const [budget, setBudget] = useState(String(initial?.monthly_budget ?? 6000));
  const [slots, setSlots] = useState<DailySlotName[]>(initial?.slots ?? ["breakfast", "lunch", "snack", "dinner"]);
  const [windows, setWindows] = useState<Record<DailySlotName, [string, string]>>(initial?.windows ?? DEFAULT_WINDOWS);
  const [remind, setRemind] = useState(() => remindersOn());
  const [city, setCity] = useState(initial?.city ?? "");
  const [quiz, setQuiz] = useState<string[]>([]);
  const [picks, setPicks] = useState<string[]>([]);
  const [saved, setSaved] = useState<string[]>([]);   // picked on an earlier visit

  useEffect(() => {
    api
      .dailyProfile(userId)
      .then((r) => {
        setSaved(r.quiz_picks);
        setPicks((p) => (p.length ? p : r.quiz_picks));
        if (r.city_guess) setCity((c) => c || r.city_guess!);
      })
      .catch(() => {});
  }, [userId]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let stale = false;   // a slow reply for the previous diet must not show meat dishes under "veg"
    api.quiz(diet).then((r) => !stale && setQuiz(r.dishes)).catch(() => !stale && setQuiz([]));
    return () => {
      stale = true;
    };
  }, [diet]);

  const toggleAllergy = (name: string) =>
    setAllergies((a) =>
      a.some((x) => x.name === name) ? a.filter((x) => x.name !== name) : [...a, { name, severe: SEVERE_DEFAULT.has(name) }]
    );

  const cycleOverride = (d: number) =>
    setOverrides((o) => {
      // none -> veg -> … -> vegan -> none
      const order: (DietType | undefined)[] = [undefined, ...DIETS];
      const next = order[(order.indexOf(o[String(d)]) + 1) % order.length];
      const copy = { ...o };
      if (next) copy[String(d)] = next;
      else delete copy[String(d)];
      return copy;
    });

  async function save() {
    const amount = Number(budget);
    if (!amount || amount <= 0) return toast.error("Enter a monthly budget");
    if (!slots.length) return toast.error("Pick at least one meal slot");
    const badTime = slots.find((s) => !(windows[s][0] && windows[s][1] && windows[s][0] < windows[s][1]));
    if (badTime) return toast.error(`Set a ${badTime} time where the start is before the end`);
    setSaving(true);
    try {
      const extra = otherAllergy
        .split(",")
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean)
        .map((name) => ({ name, severe: false }));
      const r = await api.saveDailyProfile(userId, {
        diet_type: diet,
        weekday_overrides: overrides,
        allergies: [...allergies, ...extra],
        goal,
        monthly_budget: amount,
        slots,
        windows,
        city: city || null,
        quiz_picks: picks.filter((p) => !saved.includes(p.toLowerCase())),   // only new picks are learned again
      });
      if (r.history_items) toast.success(`Learned from ${r.history_items} Instamart items you buy`);
      onDone(r.profile);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-6">
      <header>
        {!initial && (
          <ol aria-label="Step 3 of 3" className="mb-3 flex gap-1.5">
            {[1, 2, 3].map((n) => (
              <li key={n} className="h-1.5 w-7 rounded-full bg-brand-500" />
            ))}
          </ol>
        )}
        <h1 className="font-heading text-2xl font-extrabold tracking-[-0.02em]">{initial ? "Your preferences" : "What do you like to eat?"}</h1>
        <p className="text-sm text-muted-foreground">{initial ? "Changes apply from your next plan." : "About a minute. Your first plan is built as soon as you save."}</p>
      </header>

      <Section n={1} title="Diet">
        {DIETS.map((d) => (
          <Chip key={d} on={diet === d} onClick={() => setDiet(d)}>
            {d === "nonveg" ? "non-veg" : d}
          </Chip>
        ))}
      </Section>

      <Section n={2} title="Different on some days? Tap a day to cycle its diet">
        {DAYS.map((label, i) => (
          <Chip key={label} on={Boolean(overrides[String(i)])} onClick={() => cycleOverride(i)}>
            {label}
            {overrides[String(i)] ? ` · ${overrides[String(i)]}` : ""}
          </Chip>
        ))}
      </Section>

      <Section n={3} title="Allergies (tap again on a selected one to mark severe)">
        {COMMON_ALLERGENS.map((a) => {
          const hit = allergies.find((x) => x.name === a);
          return (
            <Chip
              key={a}
              on={Boolean(hit)}
              onClick={() =>
                hit && !hit.severe
                  ? setAllergies((all) => all.map((x) => (x.name === a ? { ...x, severe: true } : x)))
                  : toggleAllergy(a)
              }
            >
              {a}
              {hit?.severe ? " · severe" : ""}
            </Chip>
          );
        })}
        <Input
          aria-label="Other allergies, comma separated"
          placeholder="Other (comma separated)"
          value={otherAllergy}
          onChange={(e) => setOtherAllergy(e.target.value)}
          className="w-full sm:w-64"
        />
      </Section>

      <Section n={4} title="Goal">
        {GOALS.map((g) => (
          <Chip key={g.id} on={goal === g.id} onClick={() => setGoal(g.id)}>
            {g.label}
          </Chip>
        ))}
      </Section>

      <Section n={5} title="Monthly food budget (Rs)">
        <Input
          aria-label="Monthly budget in rupees"
          inputMode="numeric"
          value={budget}
          onChange={(e) => setBudget(e.target.value.replace(/[^\d]/g, ""))}
          className="w-40"
        />
      </Section>

      <Section n={6} title="Meals to plan, and when you usually eat them">
        <div className="flex w-full flex-col gap-2">
          {SLOTS.map((s) => {
            const on = slots.includes(s);
            return (
              <div key={s} className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <span className="w-28">
                  <Chip on={on} onClick={() => setSlots((x) => (x.includes(s) ? x.filter((y) => y !== s) : [...x, s]))}>
                    {s}
                  </Chip>
                </span>
                {on && (
                  <span className="flex items-center gap-2 text-sm text-muted-foreground">
                    {([0, 1] as const).map((i) => (
                      <span key={i} className="contents">
                        {i === 1 && <span>to</span>}
                        <input
                          type="time"
                          aria-label={`${s} ${i ? "ends" : "starts"}`}
                          value={windows[s][i]}
                          onChange={(e) =>
                            setWindows((w) => ({ ...w, [s]: (i ? [w[s][0], e.target.value] : [e.target.value, w[s][1]]) as [string, string] }))
                          }
                          className="h-9 rounded-lg border border-border bg-card px-2 font-semibold text-foreground tabular-nums"
                        />
                      </span>
                    ))}
                  </span>
                )}
              </div>
            );
          })}
          <label className="mt-1 flex cursor-pointer items-start gap-2.5 rounded-xl bg-muted/60 p-3 text-sm">
            <input
              type="checkbox"
              checked={remind}
              onChange={async (e) => {
                const want = e.target.checked;
                if (want && "Notification" in window && Notification.permission !== "granted") {
                  if ((await Notification.requestPermission()) !== "granted") {
                    toast.error("Your browser blocked notifications. Allow them in site settings to get reminders.");
                    return;
                  }
                }
                setReminders(want);
                setRemind(want);
                // push failing (unsupported browser, no HTTPS) leaves the in-page reminder working
                (want ? enablePush(userId) : disablePush(userId)).catch(() => {});
              }}
              className="mt-0.5 size-4 accent-brand-500"
            />
            <span>
              <span className="block font-bold">Remind me at meal times</span>
              <span className="text-muted-foreground">
                When a meal&apos;s time starts, Forkcast sends a notification with its top pick and where it will deliver, so you can order in one tap.
              </span>
            </span>
          </label>
        </div>
      </Section>

      <Section n={7} title={`Pick up to 5 dishes you love (${picks.length}/5)`}>
        {quiz.map((d) => (
          <Chip
            key={d}
            on={picks.some((p) => p.toLowerCase() === d.toLowerCase())}
            onClick={() =>
              setPicks((p) => {
                const same = (x: string) => x.toLowerCase() === d.toLowerCase();
                return p.some(same) ? p.filter((x) => !same(x)) : p.length < 5 ? [...p, d] : p;
              })
            }
          >
            {d}
          </Chip>
        ))}
      </Section>

      <p className={cn(surfaces.well, "p-3 text-xs text-muted-foreground")}>
        Wellness guidance only, not medical advice. Medical conditions (diabetes, BP, PCOS, pregnancy) aren&apos;t
        handled yet. Allergens are estimated per dish and can be wrong. For a severe allergy we add a note to the
        restaurant, but always tell them yourself too.
      </p>

      {/* sticky on phones so saving never needs a scroll to the bottom */}
      <div className="sticky bottom-0 -mx-4 bg-gradient-to-t from-background via-background to-transparent px-4 pb-4 pt-6 sm:static sm:mx-0 sm:bg-none sm:p-0">
        <Button onClick={save} disabled={saving} size="lg" className="w-full sm:w-auto">
          {saving ? "Saving…" : "Show my meals for today"}
        </Button>
      </div>
    </div>
  );
}

export default DailyOnboarding;
