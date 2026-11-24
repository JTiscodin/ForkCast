// Shared domain types mirroring the FastAPI backend response shapes.
// Backend: d:\Studies\Projects\Swiggy-Builder\backend\app.py

export interface SwiggyAddress {
  id: string;
  addressLine?: string;
  addressCategory?: string;
  addressTag?: string;
}

// ---- daily personalization (docs/SPEC-daily-personalization.md) ----
export type DailySlotName = "breakfast" | "lunch" | "snack" | "dinner";
export type DietType = "veg" | "eggetarian" | "nonveg" | "jain" | "vegan";
export type Goal = "lose" | "maintain" | "gain" | "high_protein";

export interface DailyProfile {
  user_id: number;
  diet_type: DietType;
  weekday_overrides: Record<string, DietType>;
  allergies: { name: string; severe: boolean }[];
  goal: Goal;
  slots: DailySlotName[];
  windows: Record<DailySlotName, [string, string]>;
  monthly_budget: number;
  city: string | null;
  mode: "live" | "dry_run";
}

export interface CardItem {
  source: "food" | "instamart";
  id: string;
  name: string;
  restaurant_name: string;
  price: number;
  image_url: string;
  veg: boolean;
  addon?: boolean;
  addon_reason?: string;
  side?: boolean;      // a curry's roti/rice from the same restaurant
  quantity?: number;
  note?: string;       // allergy note sent to the restaurant with the order
}

export type Nutrients = Record<string, number> & { confidence?: number };

export interface MenuCard {
  id: number;
  role: "usual" | "gap" | "new" | "budget" | "chat";
  position: number;
  items: CardItem[];
  price: number;
  nutrients: Nutrients;
  score: number;
  reasons: string[];
  deliveries: number;
}

export interface DailySlot {
  slot: DailySlotName;
  window: [string, string];
  cards: MenuCard[];
  excluded: { id: number; items: CardItem[]; allergen_hit: string }[];
  ordered: { status: string; platform: string; card_id: number } | null;
  nudge: boolean;
}

export interface TodayView {
  date: string;
  diet: DietType;
  season: string;
  weather: { hot?: boolean; rain?: boolean };
  profile: DailyProfile;
  budget: { monthly: number; spent: number; remaining: number; days_left: number; daily_cap: number; rollover: number; saved_so_far: number;
    /** the budget month renews on the signup day: first and last day, ISO dates */
    cycle_start: string; cycle_end: string };
  nutrition: {
    today: Nutrients;
    week_avg: Nutrients;
    days_logged: number;
    targets: Nutrients;
    gap: Nutrients;
  };
  slots: DailySlot[];
}

export interface OrderOutcome {
  mode: "live" | "dry_run";
  orders: { platform: string; order_id: string | null; status: string; amount: number; eta_min: number | null;
    error: string | null; fallback_url: string | null }[];
}

/** What Forkcast read from an uploaded diet plan; applied only after the user confirms. */
export interface DietPlanProposal {
  diet_type: string | null;
  goal: string | null;
  allergies: string[];
  prefer: string[];
  avoid: string[];
  summary: string;
}

/** One dish found by Ask Forkcast; "add N" puts it into today's plan. */
export interface ChatResult {
  index: number;
  name: string;
  price: number;
  restaurant: string;
  rating: number | null;
  image_url: string;
  source: "food" | "instamart";
  veg: boolean;
  kcal: number;
}

/** A place to go in person (outside the delivery area): from a Google-grounded lookup, no ordering. */
export interface ChatPlace {
  name: string;
  area: string;
  known_for: string;
  price: string;
  maps_url: string;
}

export interface ChatAnswer {
  reply: string;
  results?: ChatResult[];
  places?: ChatPlace[];
  sources?: { title: string; uri: string }[];
  /** Google's Search Suggestions chip (HTML), shown with grounded answers as the Gemini API terms require. */
  suggest_html?: string;
  maps_url?: string;
}

export interface MemoryBullet {
  id: string;
  dimension: string;
  key: string;
  weight: number;
  blocked: boolean;
  text: string;
  why?: string;   // plain-words source of the belief
}
