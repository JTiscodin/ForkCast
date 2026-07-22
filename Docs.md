# Budget-Based Monthly Meal Planner — Build Spec
### For Swiggy Builders Club (MCP) — Demo first, then working prototype

---

## 1. One-line pitch

> "Tell Swiggy your monthly food budget and your must-haves. It builds you a full month's calendar of breakfast/lunch/dinner within budget, auto-orders on schedule, and rolls unused money into next month as Swiggy Cash — no maid, no tiffin service, just a budget-aware AI meal plan."

This is meaningfully different from what's public so far on Swiggy MCP (voice ordering agents, multi-agent tool routers). The differentiator is **budget-constrained planning + a rollover wallet**, not just conversational ordering.

---

## 2. Two build targets

| | Demo (for Builders Club application) | Full Prototype |
|---|---|---|
| Goal | Prove the concept end-to-end, impress reviewers | Something you'd actually use daily |
| Users | You, hardcoded/mocked | Real auth, multi-user |
| Payments | Simulated wallet (no real money movement) | Real Swiggy checkout integration |
| Orders | Can be mocked or placed on Swiggy sandbox/localhost MCP | Real `place_food_order` calls |
| Notifications | Can be simulated in-app (no real push infra needed) | Real push/WhatsApp via a provider |
| Data | Local DB (SQLite is fine) | Proper DB (Postgres) |

**Recommendation: build the demo first, fully working end-to-end on localhost against Swiggy's MCP tool schemas** (this is explicitly free and requires no approval per their docs). Once that's solid, layer in real infra for the prototype.

---

## 3. System architecture

```
┌─────────────────┐
│   User (chat/UI)  │
└────────┬─────────┘
         │
┌────────▼──────────┐      ┌──────────────────────┐
│   Intake Agent      │◄────►│  LLM (Gemini 2.5 Flash) │
│  (extracts budget,  │      │  - parses NL constraints │
│  constraints, times) │      │  - drives conversation    │
└────────┬──────────┘      └──────────────────────┘
         │ structured constraints
┌────────▼──────────┐
│  Appetite Calculator │  ← plain logic + short questionnaire
│  (portion size,       │
│   meals-per-slot)     │
└────────┬──────────┘
         │ portion multiplier per user
┌────────▼──────────┐
│  Catalog Fetcher    │──── calls Swiggy MCP: search_restaurants, search_menu
│  (builds candidate   │
│   dish pool)         │
└────────┬──────────┘
         │ candidate pool + prices + ratings
┌────────▼──────────┐
│  Plan Optimizer     │  ← plain Python, NOT an LLM call
│  (greedy/knapsack    │
│  solver, 90 slots)   │
└────────┬──────────┘
         │ month plan
┌────────▼──────────┐      ┌──────────────────────┐
│  Calendar UI        │◄────►│  Swap Engine (re-query  │
│  (review/approve)   │      │  catalog ±price band)   │
└────────┬──────────┘      └──────────────────────┘
         │ approved plan + payment
┌────────▼──────────┐
│  Wallet / Ledger    │  ← YOUR database, not Swiggy's
│  (debit/credit,      │
│   rollover logic)     │
└────────┬──────────┘
         │
┌────────▼──────────┐      ┌──────────────────────┐
│  Scheduler/Notifier │◄────►│  LLM (Groq/Llama 3.3 70B)│
│  (fires per meal      │      │  - fast turnaround on     │
│   slot, handles reply) │      │    yes/no/later/other      │
└────────┬──────────┘      └──────────────────────┘
         │ on "yes"
┌────────▼──────────┐
│  Order Executor     │──── calls Swiggy MCP: update_food_cart, place_food_order, track_food_order
└────────────────────┘
```

**Key architectural rule:** the LLM never plans the whole month directly. It extracts constraints and handles conversation; a deterministic optimizer builds the plan. This avoids the exact failure mode already documented publicly (a single agent given too many tools/too much scope hallucinating cart IDs and picking the wrong tool).

---

## 4. Appetite / Portion Calculator

This is the missing piece that turns "10 paneer meals" into an actual quantity/price the optimizer can plan around — without it, the optimizer is guessing at how much food = one meal for this specific person.

**Goal:** produce a per-user *portion multiplier* and, optionally, a rough daily calorie target, both of which feed into the optimizer (bigger appetite → either larger portion sizes or more items per meal slot → higher price per slot, which eats into the budget faster).

### Two ways to gather it (pick one, or offer both)

**A. Quick/simple (recommended for the demo):** ask directly, no biometrics needed.
- "How would you describe your appetite?" → light / moderate / heavy / very heavy
- "How many rotis/how much rice do you usually have in one meal?" (optional, more concrete anchor)
- Maps to a portion multiplier: light = 0.75x, moderate = 1.0x, heavy = 1.3x, very heavy = 1.6x

**B. Calculated (nice-to-have for the prototype):** estimate daily calorie need via the standard Mifflin-St Jeor formula, then split across meals.
```
BMR (men)   = 10*weight(kg) + 6.25*height(cm) - 5*age + 5
BMR (women) = 10*weight(kg) + 6.25*height(cm) - 5*age - 161
TDEE = BMR * activity_factor (1.2 sedentary → 1.725 very active)
```
Split TDEE roughly 25% breakfast / 40% lunch / 35% dinner (adjust to the user's own split if they have a preference), then translate calories into a portion multiplier or a "how many dish-units" recommendation once you know typical calorie counts for the dishes in the catalog (you may not have per-dish calorie data from Swiggy's API — if not, fall back to option A and treat this as a future enhancement).

**For the demo, go with option A.** It's fast to build, doesn't need biometric data collection (less friction, less sensitive data to handle), and is enough to make the optimizer portion-aware.

### How it plugs into the rest of the system
- **Optimizer:** multiplies expected per-meal cost by the portion multiplier when allocating budget (a "heavy" eater needs ~1.3x the ₹ per meal slot compared to "moderate" for the same dish, since they'll need extra quantity or a bigger dish size).
- **Catalog Fetcher:** where a restaurant/dish offers size variants (half/full, regular/large), prefer the variant matching the multiplier; where it doesn't, plan for an extra side/add-on instead.
- **Swap Engine:** should preserve the user's portion multiplier when suggesting alternatives, not just price.

### Data model addition
```
UserAppetiteProfile
  - user_id
  - appetite_level (light / moderate / heavy / very_heavy)  -- Option A
  - portion_multiplier (derived, e.g. 0.75 / 1.0 / 1.3 / 1.6)
  - optional: weight, height, age, gender, activity_level    -- Option B
  - optional: daily_calorie_target                            -- Option B
```

---

## 5. Data models (rough shape, adapt as needed)

```
User
  - id, name, area/location, meal_time_prefs {breakfast, lunch, dinner}

UserAppetiteProfile
  - (see section 4)

MonthlyPlanRequest
  - user_id, month, total_budget, constraints [{type: "min_count", dish: "paneer", count: 10}, ...]

MealSlot
  - plan_id, date, meal_type (breakfast/lunch/dinner)
  - restaurant_id, dish_id, price, rating, portion_variant
  - status (planned / confirmed / skipped / rescheduled)

WalletLedger
  - user_id, month
  - total_deposited, total_spent, total_rolled_over
  - transactions [{meal_slot_id, amount, type: debit/credit/rollover, timestamp}]

NotificationLog
  - meal_slot_id, sent_at, user_response (yes/no/later/other), resolved_at
```

---

## 6. The optimizer (the part that actually needs care)

Not an LLM task. Suggested approach:

1. Pull candidate dishes per meal type per day from the catalog fetcher (rating, price, cuisine tags, portion variants).
2. Score each candidate: `score = w1*rating + w2*(1/price) + w3*constraint_bonus - w4*repeat_penalty`.
3. Adjust expected cost per slot by the user's `portion_multiplier` from the Appetite Calculator.
4. Greedily fill 90 slots (or use a simple ILP via `PuLP`/`OR-Tools` if you want it more rigorous) subject to:
   - `sum(price * portion_multiplier) <= total_budget`
   - `count(dish matches "paneer") >= 10`
   - variety constraint (no same dish more than N times/week)
5. If budget is infeasible for the constraints given the candidate pool prices and the user's appetite level, compute the shortfall and surface it: *"This plan needs ₹X more to hit 10 paneer meals at your portion size — want me to reduce paneer count instead, or should I flag a smaller portion size?"*

Keep this as a standalone, testable module — you'll want to unit test it separately from the LLM/agent code.

---

## 7. Swiggy MCP tool mapping

| Step | MCP Tool |
|---|---|
| Build candidate pool | `search_restaurants`, `search_menu` |
| Check current cart state | `get_food_cart` |
| Modify cart on swap/approval | `update_food_cart` |
| Place the actual order at meal time | `place_food_order` |
| Track delivery | `track_food_order` |

Everything else (wallet, ledger, rollover, appetite profile, scheduling, notifications) is **your own backend** — Swiggy's MCP has no concept of a monthly budget, appetite, or rollover, so don't expect an API for it. This is also exactly why it's a good pitch: you're building the layer Swiggy doesn't have.

---

## 8. Notification / response flow (state machine)

```
[Scheduled: T-30min] → notify user "Should I get your lunch — Paneer Tikka Bowl, ₹180?"

  → "yes"     → Order Executor: place_food_order → status: confirmed
  → "no"      → Wallet: credit ₹180 back as Swiggy Cash → status: skipped
  → "later"   → ask for new time → reschedule slot → re-notify at new time
  → "other"   → Swap Engine: show alternatives in same budget band (± ₹100 toggle),
                respecting the user's portion multiplier
                → user picks → Order Executor places new item
```

For the demo, this can be simulated with a simple in-app button UI ("Yes / No / Later / Something else") instead of real push notifications — reviewers will still see the full logic.

---

## 9. Tech stack recommendation

- **Backend**: Python (FastAPI) — good for both the MCP client calls and the optimizer.
- **LLM for conversation/parsing**: Gemini 2.5 Flash (Google AI Studio free tier) — strong native tool-calling, huge context, frontier quality, genuinely free tier (not a trial).
- **LLM for fast real-time replies**: Groq running Llama 3.3 70B — near-instant responses, good for the "yes/no/later" notification flow where latency matters.
- **Optimizer**: plain Python, optionally `PuLP` for a proper linear program.
- **DB**: SQLite for demo → Postgres for prototype.
- **Frontend**: React + a calendar library (or a custom month-grid) for the plan review UI.
- **Scheduler**: simple cron/APScheduler for demo; a real job queue (Celery/RQ) for prototype.

---

## 10. Suggested build order

1. Wallet/ledger module + data models (foundation, no LLM needed yet).
2. Appetite Calculator (simple questionnaire → portion multiplier).
3. Optimizer module, tested standalone with mock dish data + a mock portion multiplier.
4. Catalog fetcher hitting real Swiggy MCP tools on localhost.
5. Intake agent (LLM) that turns "10k budget, paneer 10x" into structured constraints, and asks the appetite questions.
6. Calendar UI to review/approve the generated plan.
7. Swap engine (± price band re-query, appetite-aware).
8. Scheduler + notification flow (simulated first, real later).
9. Order Executor wired to `place_food_order`/`track_food_order`.
10. Record the demo, apply to Builders Club.

---

## 11. Prompt to hand your AI coding agent to kick this off

```
I'm building a monthly budget-based food meal planner on top of Swiggy's MCP servers
(Food, Instamart, Dineout — search_restaurants, search_menu, update_food_cart,
get_food_cart, place_food_order, track_food_order).

Core concept: user sets a monthly food budget + constraints (e.g. "10k budget,
at least 10 paneer meals") and an appetite level (light/moderate/heavy/very heavy),
the system generates a full month calendar of breakfast/lunch/dinner within budget
using a deterministic optimizer (NOT the LLM) that accounts for portion size via
the appetite level, lets the user review/swap meals, takes one upfront approval,
then sends a notification before each meal asking yes/no/later/something-else, and
rolls unused budget into a wallet as "Swiggy Cash" for skipped meals.

Start with: [pick one — e.g. "the wallet/ledger module and data models"].
Use FastAPI + SQLite for now. Keep the optimizer as a standalone, unit-testable
module separate from any LLM call.
```

Start with step 1 from the build order above and go module by module — that keeps each piece testable before you wire the LLM and MCP calls around it.