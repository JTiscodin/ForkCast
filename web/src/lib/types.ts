// Shared domain types mirroring the FastAPI backend response shapes.
// Backend: d:\Studies\Projects\Swiggy-Builder\backend\app.py

export type MealType = "breakfast" | "lunch" | "dinner";
export type SlotStatus = "planned" | "confirmed" | "skipped" | "rescheduled";
export type AppetiteLevel = "light" | "moderate" | "heavy" | "very_heavy";
export type ChatAction = "need_more" | "ready_to_plan" | "chitchat";

export interface Constraint {
  dish_tag: string;
  min_count: number;
}

export interface ParsedIntake {
  budget: number | null;
  constraints: Constraint[];
  veg_only: boolean;
  appetite_level: AppetiteLevel | null;
  days: number;
  source: "llm" | "fallback";
  needs_appetite: boolean;
}

/** Role a dish plays in a meal — see backend/course.py. */
export type Course = "bread" | "staple" | "curry" | "complete" | "side";

export interface MealSlot {
  id: number;
  plan_id: number;
  day: number;
  meal_type: MealType;
  dish_id: string;
  dish_name: string;
  restaurant_id: string;
  restaurant_name?: string;
  /** MAIN dish price only. For the real meal cost use slotTotal(). */
  price: number;
  rating?: number;
  variant: string;
  status: SlotStatus;
  order_id?: string | null;
  image_url?: string;
  why_text?: string;
  // --- meal composition: a curry carries a bread/rice accompaniment ---
  course?: Course;
  side_dish_id?: string;
  side_dish_name?: string;
  side_qty?: number;
  /** qty x unit price, already multiplied. */
  side_price?: number;
  side_restaurant_name?: string;
  side_image_url?: string;
}

/**
 * Full cost of a meal — main dish plus its accompaniment. `price` alone
 * undercounts every paired curry, so all money shown to the user goes
 * through this.
 */
export function slotTotal(s: MealSlot): number {
  return (s.price ?? 0) + (s.side_price ?? 0);
}

export interface ConstraintStatus {
  [tag: string]: { got: number; needed: number };
}

export interface PlanSummary {
  plan_id: number;
  feasible: boolean;
  total_cost: number;
  budget: number;
  leftover: number;
  constraint_status: ConstraintStatus;
  message: string;
}

/** One concrete way to bring a plan inside budget (POST /plan/feasibility). */
export interface FeasibilityOption {
  /** "budget" = raise the budget; "config" = change meals and/or appetite. */
  kind: "budget" | "config";
  label: string;
  detail: string;
  /** What this configuration would cost for the month. */
  total: number;
  fits: boolean;
  changes: {
    budget?: number;
    meals?: MealType[];
    appetite_level?: AppetiteLevel;
  };
}

export interface FeasibilityReport {
  feasible: boolean;
  budget: number;
  /** Cheapest achievable total for what the user actually asked for. */
  floor: number;
  shortfall: number;
  current: {
    appetite: AppetiteLevel;
    meals: MealType[];
    meals_label: string;
    slots: number;
    floor: number;
    per_meal: number;
  };
  options: FeasibilityOption[];
  /** One plain-language sentence explaining the situation. */
  headline: string;
}

export interface PlanFull {
  plan: {
    id: number;
    user_id: number;
    month: string;
    budget: number;
    total_cost: number;
    feasible: number;
    status: string;
    message: string;
  };
  slots: MealSlot[];
}

export interface WalletSummary {
  month: string;
  budget_allocated: number;
  rolled_in: number;
  total_spent: number;
  balance: number;
  status: string;
}

export interface DishAlternative {
  dish_id: string;
  name: string;
  restaurant_id: string;
  restaurant_name: string;
  price: number;
  variant: string;
  rating: number;
  veg: boolean;
  image_url?: string;
}

export interface NotifyPayload {
  slot_id: number;
  prompt: string;
  options: string[];
}

export interface SwiggyAddress {
  id: string;
  addressLine?: string;
  addressCategory?: string;
  addressTag?: string;
}

// Chat orchestration (POST /chat)
export interface ChatSessionState {
  budget?: number | null;
  constraints?: Constraint[];
  veg_only?: boolean;
  appetite_level?: AppetiteLevel | null;
  days?: number;
}

// The running "blueprint" the AI fills conversationally before a plan is built.
export interface Blueprint {
  budget: number | null;
  appetite_level: AppetiteLevel | null;
  veg_only: boolean;
  /** Steers the catalog search toward protein-rich dishes. */
  high_protein?: boolean;
  constraints: Constraint[];
  cuisines: string[];
  meals: MealType[];
  days: number;
  // --- taste / diet (gathered in blueprint chat, sent to /plan taste_prefs) ---
  veg_level?: string;
  allergies?: string[];
  health_goals?: string[];
  spice_preference?: number;
  disliked_foods?: string[];
  portion_size?: string;
  // internal _asked_* flags may also be present; ignore on the client
  [key: string]: unknown;
}

export interface ChatResponse {
  reply: string;
  ready: boolean; // true -> show overview + Generate Plan
  action: ChatAction;
  blueprint: Blueprint; // echo full state back next turn (compact memory)
  extracted: ChatSessionState; // legacy convenience shape
}

export interface AdjustResponse {
  reply: string;
  blueprint: Blueprint;
  public: Blueprint;
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
  budget: { monthly: number; spent: number; remaining: number; days_left: number; daily_cap: number };
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

export interface MemoryBullet {
  id: string;
  dimension: string;
  key: string;
  weight: number;
  blocked: boolean;
  text: string;
}
