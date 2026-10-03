# Spec — Daily Personalized Meals (Swiggy + Instamart)

Status: agreed (grill session, 2026-10-03) · Stage: pitch to Swiggy · Demo: local laptop · Deadline: none

Builds on the existing Swiggy-Builder app. The monthly planner is replaced by a daily, learning,
nutrition-aware recommender for Indian users. Goal: least-friction personalization.

---

## 1. Product decisions

### 1.1 Daily cards (replaces monthly plan as main screen)
- Main screen = **Today**. Month view survives only as budget envelope + history.
- Slots: breakfast, lunch, dinner, optional evening snack. Each slot toggleable in onboarding.
- Default windows (editable in settings): breakfast 07:00–10:00, lunch 12:00–15:00,
  snack 16:30–18:30, dinner 19:30–22:30.
- 3–4 cards per active slot, each with a **role label**:
  - **Your usual** — safe favourite
  - **Fixes your gap** — best nutrient-gap fit
  - **Try something new** — novelty within constraints
  - **Budget pick** — cheapest card that still passes quality bar
- A card is a restaurant meal **or** an Instamart bundle (breakfast/snack: curd, fruit, eggs,
  ready-to-eat). Any card may carry an Instamart **gap add-on** ("add curd for calcium").
- Generation: nightly batch for next day; on open, re-check stock / restaurant open / price and
  replace stale cards.
- Repetition: same dish not shown within 3 days (except in *Your usual*); a restaurant appears at
  most once per day across all cards.
- **Excluded for allergies** section per slot: good dishes rejected only because of an allergen.
  Never recommended, but user may add one manually.

### 1.2 Ordering
- Tap card → one confirm → real order via Swiggy MCP.
- Restaurant main + Instamart add-on = **one tap, two orders**; card shows "2 deliveries" + both ETAs.
- Guardrails: COD only, order total < Rs 1000.
- Settings toggle: **Live** (places order) / **Dry-run** (builds real cart, stops before
  `place_food_order` / Instamart `checkout`). Dry-run is the demo default.
- Fallback when MCP checkout fails: deep link to Swiggy.

### 1.3 Budget
- Monthly budget set at onboarding.
- Daily soft cap = remaining budget / days left in cycle.
- Cards above cap still shown, flagged. "Swiggy Cash" rollover story kept.

### 1.4 Onboarding (tap form → taste quiz → history pull)
~60 s tappable steps, chat only for later edits:
1. Diet type: veg / eggetarian / non-veg / Jain / vegan
2. Per-weekday override: any weekday can use any of the 5 types (e.g. Tue = veg, Thu = Jain)
3. Allergies (multi-select + free text), flag severe ones (peanut, shellfish, …)
4. Goal: lose / maintain / gain / high-protein
5. Monthly budget
6. Meal slots on/off
7. Swiggy login + address (city drives weather/season)
8. Taste quiz: pick 5 dishes you love from a grid
9. Pull Instamart `get_orders` + `your_go_to_items` as cold-start signal

Out of scope v1: medical conditions (diabetes, BP, PCOS, pregnancy) — wellness disclaimer shown.
Fasting calendars (Navratri, Shravan, Ekadashi) — v2 opt-in.

### 1.5 Nutrition tracking ("stomach database")
- Tracked: calories, protein, carbs, fat, fibre + iron, B12, vitamin D, calcium, sodium, sugar.
- Targets: ICMR-NIN RDA (Indian reference), adjusted by goal.
- Source: map dish → canonical dish in Indian food DB (IFCT 2017 / INDB), scale by portion;
  unmatched → Gemini estimate. Every value carries `source` + `confidence`. UI shows "~".
- Steering: **macros per day** (running total re-ranks remaining slots today);
  **micros on 7-day rolling window**.
- Off-app food: logged in chat ("had dal and 2 roti at home"). Unlogged slots = **unknown**, never
  "missed".

### 1.6 Weather & season
- City from Swiggy address. Season rules (summer → cooling, monsoon → avoid raw salads / street
  food, winter → warm, heavier) + free weather API (heatwave, rain today).
- Soft re-rank only. Never a hard filter.

### 1.7 Self-learning
- Signals, explicit weighted above implicit:
  - Explicit: thumbs up/down, "not today", "never show", rating after delivery, memory edits.
  - Implicit: card picked (and its position), cards shown but skipped, off-plan order, no re-order.
- **Post-meal nudge**: if no card picked by window end → "What did you have?" one tap:
  ordered elsewhere / ate at home / skipped meal, optional dish name. Covers the blind spot:
  Swiggy Food MCP has **no order-history API**, so orders placed directly in the Swiggy app are
  invisible otherwise. (Pitch ask to Swiggy: expose food order history in MCP.)
- Cadence: explicit signals apply instantly; nightly recompute of all weights + regenerate memory MD.
  Signals decay (fade over ~4 weeks). "Never show" is permanent.
- Storage: structured weights in DB drive ranking; per-user markdown **taste memory** regenerated
  from them, read by the chat agent.
- UI: **What we know about you** — readable bullets, each with edit / delete. Edits write back to
  weights.

### 1.8 Chat agent (Gemini, behind one adapter)
Tools the agent can call:
- Craving recommend + search: "something spicy under 250" → live `search_menu` / Instamart
  `search_products`, through the same hard filters as cards.
- Add / order: place chosen dish into today's slot → confirm → order.
- Log off-app food → consumption log.
- Edit preferences + explain: "stop suggesting paneer", "why this card?", "what am I low on?"

### 1.9 User unit
Single person v1. Profile schema keyed so a household can be added later.

---

## 2. Current state (facts from code, 2026-10-03)

| Area | Today | Gap for this spec |
|---|---|---|
| Plan | Monthly, B/L/D only, 4-pass optimizer `backend/optimizer.py:192` | New daily ranker, snack slot |
| Budget | Monthly virtual ledger `wallet_service.py` | Daily soft cap |
| Onboarding | Name + address `web/src/components/app/Onboarding.tsx`; rest via blueprint chat | New tap form + quiz |
| Diet filters | Only `veg_only` applied to mains `optimizer.py:230` | Jain / allergy / dislike / weekday rules on mains |
| Taste profile | In-memory, never persisted `taste_profile.py:84` | Persisted weights + memory MD |
| Nutrition | None; `food_knowledge.py` has no macros | Nutrient DB + estimator |
| Food MCP | `search_menu`, `get_restaurant_menu`, cart + `place_food_order` (COD, < Rs 1000) | — |
| Food order history | Not available in MCP | Post-meal nudge |
| Instamart | Only `search_products`; `update_cart` / `checkout` unwired `instamart.py:15-19` | Wire cart + checkout |
| Instamart history | `get_orders`, `your_go_to_items` listed, unwired | Wire for cold start |
| Auth | OAuth PKCE, token in `.env`; refresh never used `swiggy_mcp.py:32-51` | Refresh token (nightly batch depends on it) |
| Ordering bug | `plan_service.py:183` drops `raw_variant` | Fix before live orders |
| Chat | Blueprint fill + `/chat/adjust` rebuilds whole plan | Tool-calling agent |
| Storage | SQLite (WAL) `db.py` | New tables below |
| LLM | Gemini flash-lite with fallbacks `gemini.py:26-37` | Keep; add agent tool loop |

---

## 3. Architecture

### 3.1 Reuse vs retire
- **Reuse**: `catalog_fetcher.py`, `food_classifier.py`, `food_knowledge.py`, `swap_service.py`
  (alternatives logic), `swiggy_mcp.py`, `swiggy_auth.py`, `order_executor.py`, wallet ledger.
- **Retire from UI**: monthly 4-pass optimizer path and blueprint "Generate Plan" flow.
- **New**: daily ranker, profile + rules, nutrition module, learning module, agent tools.

### 3.2 Daily ranking pipeline
```
candidates (search_menu fan-out + Instamart search, seeded by prefs/gaps/season)
  -> hard filters: weekday diet type, allergies (-> excluded bucket), never-show,
                   in stock, restaurant open, guardrail price, repetition window
  -> score = a*preference + b*gap_fit + c*weather_season + d*budget_fit + e*novelty
  -> role assignment: best per role (usual / gap / new / budget), restaurant-once-per-day
  -> attach Instamart gap add-on if a nutrient gap remains
  -> persist daily_menu
```
Weights a–e are config, tuned during build.

### 3.3 New data model (SQLite)
| Table | Purpose |
|---|---|
| `user_profile` | diet_type, weekday_overrides (json), allergies (json, severity), goal, slots (json), windows (json), monthly_budget, city, mode (live/dry_run) |
| `daily_menu` | user, date, slot, generated_at, refreshed_at |
| `menu_card` | menu id, role, items (json: source food/instamart, ids, raw_variant), price, nutrients (json), score, reasons |
| `excluded_card` | menu id, items, allergen hit |
| `consumption_log` | user, date, slot, source (app_order / chat_log / nudge), items, nutrients, confidence |
| `feedback_event` | user, ts, type, card/dish/restaurant/cuisine ref, position, value |
| `pref_weight` | user, dimension (dish/cuisine/restaurant/spice/price_band/ingredient), key, weight, updated_at, hard_block |
| `nutrition_ref` | canonical dish, per-serving nutrients, source (ifct/indb/llm), confidence |
| `order_record` | card ref, platform (food/instamart), order id, status, mode |

Taste memory: `data/taste/<user_id>.md`, regenerated nightly + on explicit edit.

### 3.4 Learning: starting values (tune later)
| Event | Effect |
|---|---|
| Ordered card | +3 dish, +1 cuisine/restaurant |
| Thumbs up / rating ≥ 4 | +3 |
| Thumbs down / rating ≤ 2 | −3 |
| Shown, not picked | −0.3 |
| "Not today" | −0.5, short decay (mood) |
| Off-plan order (nudge/chat) | +2 to that dish/cuisine |
| "Never show" | hard block, no decay |

Decay: exponential, ~2-week half-life (fades over ~4 weeks).

### 3.5 Jobs
- Nightly (local scheduler): refresh token → recompute weights → regenerate memory MD →
  build next-day menus.
- On open: stale-check today's cards.
- Window end: fire post-meal nudge if slot has no order/log.

---

## 4. Build order & done criteria

| # | Pillar | Done when |
|---|---|---|
| 0 | Prereqs | Token refresh works; `raw_variant` passed through; Instamart cart + checkout wired; dry-run toggle |
| 1 | Daily cards | Today screen shows 3–4 role-labelled cards per active slot; one-tap order (dry-run + live); repetition + restaurant rules hold; excluded-for-allergies section |
| 2 | Onboarding | Tap form + quiz + Instamart history pull persist to `user_profile` / `pref_weight`; weekday overrides change cards |
| 3 | Nutrition | Every card + log has nutrients with confidence; daily macro rings, weekly micro bars; gap re-ranks remaining slots |
| 4 | Learning | Events recorded; weights move as table above; decay + nightly regen; "What we know" page edit/delete round-trips |
| 5 | Chat agent | Craving search, add/order, log food, edit prefs, explain — all through the same filters |

---

## 5. Deferred (v2+)
- Fasting / festival calendars (Navratri, Shravan, Ekadashi)
- Medical conditions
- Household / family profiles and shared cart
- Push / WhatsApp notifications
- Gmail receipt or screenshot import of Swiggy food history
- Deployed hosting (non-localhost OAuth redirect, Postgres)

## 6. Risks
- Allergen detection is name/ingredient based — cannot guarantee. Severe allergens show
  "confirm with restaurant" on every card.
- Nutrition is estimated for restaurant food; always shown as approximate.
- Nightly batch depends on a valid Swiggy token — refresh must be solid.
- Live orders on stage — keep dry-run as demo default.
