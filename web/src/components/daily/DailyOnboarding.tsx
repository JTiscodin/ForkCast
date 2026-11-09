"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";
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
  const [slots, setSlots] = useState<DailySlotName[]>(initial?.slots ?? ["breakfast", "lunch", "dinner"]);
  const [city, setCity] = useState(initial?.city ?? "");
  const [quiz, setQuiz] = useState<string[]>([]);
  const [picks, setPicks] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.quiz(diet).then((r) => setQuiz(r.dishes)).catch(() => setQuiz([]));
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
        city: city || null,
        quiz_picks: picks,
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
        <h1 className="text-2xl font-semibold">Set up your daily meals</h1>
        <p className="text-sm text-muted-foreground">About a minute. You can change any of this later in chat.</p>
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

      <Section n={6} title="Meals to plan">
        {SLOTS.map((s) => (
          <Chip
            key={s}
            on={slots.includes(s)}
            onClick={() => setSlots((x) => (x.includes(s) ? x.filter((y) => y !== s) : [...x, s]))}
          >
            {s}
          </Chip>
        ))}
      </Section>

      <Section n={7} title="City (for weather and season)">
        <Input
          aria-label="City"
          placeholder="e.g. Bengaluru"
          value={city}
          onChange={(e) => setCity(e.target.value)}
          className="w-full sm:w-64"
        />
      </Section>

      <Section n={8} title={`Pick up to 5 dishes you love (${picks.length}/5)`}>
        {quiz.map((d) => (
          <Chip
            key={d}
            on={picks.includes(d)}
            onClick={() =>
              setPicks((p) => (p.includes(d) ? p.filter((x) => x !== d) : p.length < 5 ? [...p, d] : p))
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
