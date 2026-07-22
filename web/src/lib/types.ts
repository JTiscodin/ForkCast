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

export interface MealSlot {
  id: number;
  plan_id: number;
  day: number;
  meal_type: MealType;
  dish_id: string;
  dish_name: string;
  restaurant_id: string;
  restaurant_name?: string;
  price: number;
  rating?: number;
  variant: string;
  status: SlotStatus;
  order_id?: string | null;
  image_url?: string;
  why_text?: string;
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

export interface ChatResponse {
  reply: string;
  action: ChatAction;
  extracted: ChatSessionState;
  missing: string[];
}
