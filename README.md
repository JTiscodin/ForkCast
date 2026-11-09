# Forkcast

**Your meals for the day, already picked from Swiggy.**

Forkcast is a daily meal recommender built on the [Swiggy MCP](https://mcp.swiggy.com/builders).
Every morning it lays out four short lists (breakfast, lunch, an evening snack and
dinner) of real dishes from restaurants that deliver to you, plus small Instamart
add-ons that cover what your day is missing. It stays inside your monthly food budget,
follows your diet (including rules like "Jain on Thursdays"), keeps your allergies off
the plate, and learns from what you order, like and skip.

You stay in charge of ordering: one tap builds the real Swiggy cart and shows what
you'll pay, a second tap places it.

> Status: working prototype on localhost against the live Swiggy Food and Instamart
> MCP servers. Production access application: [`docs/PRODUCTION-APPLICATION.md`](docs/PRODUCTION-APPLICATION.md).

---

## What it does

| | |
|---|---|
| **Four meals a day** | 3–4 cards per meal, each with a role: *your usual*, *fixes your gap*, *try something new*, *budget pick*. One restaurant appears at most once a day. |
| **Real meals only** | Every dish is profiled (meal, curry, bread, snack, sweet, drink…). A curry always comes with roti or rice from the same restaurant; a lone idli is never lunch; soft-drink combos are out. |
| **Budget** | Monthly budget turns into a daily cap that adapts to what you've already spent. |
| **Diet rules** | Veg, egg, non-veg, Jain, vegan, with per-weekday overrides. Jain filters out onion, garlic and root vegetables. |
| **Allergies** | Dishes built on an allergen (paneer for dairy, chikki for peanut) are hidden. If the allergen can be left out (peanuts in poha), the dish stays and the order carries a note to the restaurant: *"No peanut please, severe allergy."* |
| **Nutrition** | Calories, protein, carbs, fat, fibre and micronutrients per card, from the Indian Nutrient Databank. Daily rings and a weekly average show the gaps the next picks try to close. |
| **Learning** | Thumbs up/down, skips, "not today", ratings, ordering again, and your past Swiggy orders all adjust a taste profile that fades over two weeks, so new habits win over old ones. |
| **Chat** | "Ask Forkcast": *"something spicy under ₹250"*, *"I had dal and 2 roti at home"*, *"stop suggesting paneer"*. The assistant can search and adjust the plan but cannot place orders. |
| **Your data** | "What we know about you" lists everything learned; each item can be strengthened, weakened or forgotten, and one button deletes the account and all its data. |

## Ordering safety

- **Dry run is the default.** It builds your real Swiggy cart and stops before ordering.
- **Live mode** needs a second, explicit confirmation to switch on.
- Every order shows a summary from Swiggy's live cart (items, amount to pay, address,
  cash on delivery) before the final tap.
- Carts at ₹1000 or more are refused, as Swiggy requires. Payment is cash on delivery only.
- "Powered by Swiggy" / "Powered by Instamart" appears on every card and order step.

---

## How it works

```
Browser (Next.js 16, web/)
   │  Bearer token per user
   ▼
FastAPI backend (backend/)
   ├── daily.py           plan builder: candidates → filters → scoring → 4 role cards per meal
   ├── dish_profile.py    one Gemini-classified profile per dish name, cached forever in SQLite
   ├── plan_quality.py    audits every built day (not-a-meal, curry without carb, Jain, duplicates…)
   ├── nutrition.py       INDB lookup → hand table → fuzzy match → LLM estimate
   ├── agent.py           chat assistant with read/adjust tools (no ordering tool)
   ├── order_executor.py  update_food_cart → get_food_cart → place_food_order
   ├── instamart.py       Instamart search / cart / checkout
   ├── swiggy_mcp.py      JSON-RPC client for mcp.swiggy.com (Retry-After on 429, in-band errors raised)
   ├── auth.py            per-user signed tokens; every user-scoped route checks ownership
   └── SQLite             profiles, feedback, taste weights, plans, orders, dish profiles
```

**Scoring.** Each candidate gets
`0.35·preference + 0.25·nutrient gap + 0.15·budget fit + 0.15·novelty + 0.10·weather/season`.
Hard rules (diet, allergies, budget cap, meal size) are filters, not weights.

**Nightly job.** Refreshes the Swiggy token, pulls new Swiggy orders into the taste
profile, recomputes weights and builds tomorrow's plan, so the morning page loads instantly.

**Why the LLM doesn't plan.** Gemini only classifies dish names and powers chat. The
plan itself comes from deterministic Python, so it can't make up dishes, cart IDs or prices.

---

## Run it locally

Requirements: Python 3.11+, Node 20+.

```bash
# backend
cd backend
pip install -r requirements.txt
python -m uvicorn app:app --port 8343

# frontend (new terminal)
cd web
npm install
NEXT_PUBLIC_API_URL=http://localhost:8343 npx next dev --port 6001
```

Open http://localhost:6001, tap **Connect Swiggy** and sign in on Swiggy's own page.
Without a Swiggy login, the app runs on a built-in mock catalogue.

### Configuration (`backend/.env`, never committed)

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Dish classification and chat. Without it, keyword rules and a regex parser take over. |
| `SWIGGY_MODE` | `mcp` for live Swiggy, `mock` for the demo catalogue. |
| `SWIGGY_MCP_TOKEN` / `SWIGGY_REFRESH_TOKEN` | Written by **Connect Swiggy** (OAuth 2.1 + PKCE). |
| `SWIGGY_ADDRESS_ID` | Optional: pin a saved Swiggy address. |
| `FORKCAST_SECRET` | Signs user tokens. If unset, a random secret is generated into `backend/.auth_secret`. |
| `DAILY_NIGHTLY_HOUR` | Hour the nightly job runs (default 2). |

### Tests

```bash
cd backend
python -m pytest -q
```

Covers the planner rules, allergen handling, the quality gate, nutrition lookups,
learning signals, order flow against a fake MCP, and auth.

---

## Repository map

| Path | What |
|---|---|
| `backend/` | FastAPI app, planner, Swiggy clients, tests |
| `backend/data/indb.csv` | Indian Nutrient Databank recipes (1,014) used for nutrition |
| `web/` | Next.js app (Today view, setup, chat, month planner) |
| `docs/SPEC-daily-personalization.md` | Product spec for the daily recommender |
| `docs/PRODUCTION-APPLICATION.md` | Answers for Swiggy's production access form |

The older **Month** tab (a budget-first monthly calendar with Swiggy Cash rollover) is
still available; Forkcast's main screen is the daily view.

## Credits

- Food and grocery data: [Swiggy MCP](https://mcp.swiggy.com/builders). Swiggy and
  Instamart logos are used for attribution only.
- Nutrition: Indian Nutrient Databank (Vijayakumar et al., *Current Developments in
  Nutrition*, 2024, [doi:10.1016/j.cdnut.2024.103790](https://doi.org/10.1016/j.cdnut.2024.103790)).
- Weather: [Open-Meteo](https://open-meteo.com).

Forkcast gives general wellness suggestions, not medical advice. Allergen information
is estimated per dish: always tell the restaurant about a severe allergy yourself.
