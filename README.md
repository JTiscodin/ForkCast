<p align="center"><img src="web/public/brand/forkcast.png" width="96" alt="Forkcast logo"></p>

# Forkcast

**Your meals for the day, already picked from Swiggy.**

Forkcast is a daily meal recommender built on the [Swiggy MCP](https://mcp.swiggy.com/builders).
Every morning it lays out breakfast, lunch, an evening snack and dinner: real dishes
from restaurants that deliver to you, plus small Instamart add-ons that cover what your
day is missing. It stays inside your monthly food budget, follows your diet, keeps your
allergies off the plate, reacts to the weather, and learns from what you order, like and skip.

You stay in charge of ordering: one tap builds the real Swiggy cart and shows what
you'll pay, a second tap places it.

> **Status:** working prototype against the live Swiggy Food and Instamart MCP servers.
> Built by Vardan Agarwal and Jatin Tilwani.
> Production access application: [`docs/PRODUCTION-APPLICATION.md`](docs/PRODUCTION-APPLICATION.md) ·
> Hosting guide: [`docs/DEPLOY.md`](docs/DEPLOY.md)

## Contents
- [Features](#features)
- [Ordering safety](#ordering-safety)
- [How it works](#how-it-works)
- [Run it locally](#run-it-locally)
- [Configuration](#configuration)
- [Tests](#tests)
- [Security and privacy](#security-and-privacy)
- [Repository map](#repository-map)
- [Known limits](#known-limits)
- [Credits](#credits)

---

## Features

### Four meals a day, each pick with a job
Every meal shows three or four cards, and each card has a role:

| Role | What it means |
|---|---|
| **Your usual** | Something you've ordered or liked before |
| **Fixes your gap** | Closes the nutrient you're shortest on today (protein, iron, calcium…) |
| **Try something new** | A dish you haven't had in the last two weeks |
| **Budget pick** | The cheapest option that still rates well |

A restaurant appears at most once a day, and the same dish never shows up twice, even
under a different name ("Kadchi Plain Rajma-Chawal" and "Rajma Chawal" count as one).

### Real meals, not menu items
Each dish name is classified once (meal, curry, bread, rice, side, snack, sweet, drink)
and the result is stored, so the rules read what a dish *is* instead of guessing from words.

- A curry always arrives with roti or rice from the same restaurant: 2 rotis or 1 rice,
  sized for one person. Sharing packs ("Chapati Tub (6 pcs)", family size) are never used.
- A single idli is not lunch: main meals have a minimum size.
- Sweets and drinks never fill a meal slot, and soft-drink combos are left out.
- Instant noodles are a snack, never dinner.

### Diet rules, including by weekday
Veg, eggetarian, non-veg, Jain or vegan, with per-weekday overrides such as
"Jain on Thursdays". Jain days filter out onion, garlic and root vegetables.

### Allergies handled three ways
| Situation | What happens |
|---|---|
| The dish can't be made without the allergen (paneer for dairy, chikki for peanut) | Hidden, and listed under "Hidden for your allergies" |
| The allergen can be left out (peanuts in poha, a cashew garnish) | Kept, and the order carries a note to the restaurant: *"No peanut please, severe allergy"* |
| Packaged Instamart items, sides and add-ons | Checked by name; anything matching is never offered |

### Budget and rollover savings
You set a monthly food budget. Forkcast turns what's left into an amount for today and
flags cards that go over it. Whatever you don't spend carries into next month's budget,
shown in a budget card on the Today page. This is a running total only: Forkcast never holds money.

### Nutrition
Every card shows calories and protein; the sidebar shows today's energy, protein, carbs,
fat and fibre as rings, and a weekly average for iron, B12, vitamin D, calcium, sodium and
sugar. Values come from the Indian Nutrient Databank (1,014 recipes), with fallbacks for
dishes it doesn't cover, and are labelled as estimates. Meals you eat elsewhere can be
logged in one tap ("Ate at home", "Ordered elsewhere", "Skipped") so the picture stays honest.

### Weather and season
The city's forecast and the season re-rank the day:

- **Rain or monsoon:** pakoras, samosas, soup and chai move up; raw street food moves down.
  A pakora or samosa snack gets a chai from the same restaurant.
- **Hot days and summer:** curd, lassi, chaas and other cooling foods move up.
- **Winter:** soups, khichdi, parathas and other warm, filling dishes move up.

The card says why: "Raining today: chai and pakora weather".

### It learns, and shows you what it learned
Signals: ordering (+3), thumbs up (+3), thumbs down (−3), "not today", "never",
star ratings after a meal, skipping a dish you used to order, dishes picked at setup,
and your past Swiggy orders. Signals fade with a two-week half-life, so new habits win.

The **You** tab shows everything Forkcast believes about you, grouped (dishes, places,
flavours, Instamart basket, showing less of, never shown). Each item shows how strong
the belief is and where it came from ("You liked it", "From your Swiggy orders",
"From your diet plan"), and can be strengthened, weakened or forgotten.

### Upload a diet plan
Next to the Ask button is **Diet plan**. Upload a photo, PDF or text file of a diet
chart and Forkcast reads out the diet type, goal, allergies, foods to eat more of and
foods to avoid. It shows what it understood in the chat and changes nothing until you
tap **Use this plan**. "Avoid fried" also reaches dishes like chole bhature and poori
that don't say "fried" in their name. The file is read once and not stored.

### Chat: Ask Forkcast
A bar at the top of Today and a slide-in panel:

- *"Something spicy under ₹250"* searches with all your rules applied.
- *"I had dal and 2 roti at home"* logs the meal and its nutrition.
- *"What am I low on?"* reads your week.
- *"Stop suggesting paneer"* changes what you see.

The assistant has no ordering tool. Asked to order, it points you to the card's button.

### Your data
Everything learned is visible and editable on the You tab, and
**Delete my account and data** erases the profile, plans, feedback, orders and taste memory.

---

## Ordering safety

- **Dry run is the default.** It builds your real Swiggy cart and stops before ordering.
- **Live mode** needs a second, explicit confirmation to switch on.
- Before the final tap, every order shows a summary from Swiggy's live cart: items,
  amount to pay, delivery address and payment (cash on delivery).
- Carts at ₹1000 or more are refused, as Swiggy requires.
- On a shared server, visitors from the internet cannot switch on Live ordering at all.
- "Powered by Swiggy" / "Powered by Instamart", with the official logos, appear on every
  card, the order summary and the confirmation.

---

## How it works

```
Browser (Next.js 16, web/)
   │  signed token per user
   ▼
FastAPI backend (backend/)
   ├── daily.py           plan builder: candidates → hard filters → scoring → role cards
   ├── dish_profile.py    one AI-classified profile per dish name, stored in SQLite
   ├── plan_quality.py    audits every built day against plain meal rules
   ├── nutrition.py       Indian Nutrient Databank → hand table → fuzzy match → estimate
   ├── diet_plan.py       reads an uploaded diet plan into a proposal the user confirms
   ├── agent.py           chat assistant with read/adjust tools (no ordering tool)
   ├── order_executor.py  update_food_cart → get_food_cart → place_food_order
   ├── instamart.py       Instamart search / cart / checkout
   ├── swiggy_mcp.py      JSON-RPC client for mcp.swiggy.com
   ├── auth.py            per-user signed tokens, ownership checks on every route
   └── SQLite             profiles, feedback, taste weights, plans, orders, dish profiles
```

### Building a day
1. **Candidates.** Dishes from Swiggy Food for your address, plus a few Instamart
   bundles (curd + banana, makhana + chaas).
2. **Hard filters.** Diet, Jain rules, allergies, "never" items, meal size, sharing
   portions, price ceiling. These are filters, never weights: a favourite dish does not
   get past an allergy.
3. **Score.**
   `0.35·preference + 0.25·nutrient gap + 0.15·budget fit + 0.15·novelty + 0.10·weather`
4. **Roles.** The best card for each role is picked, without repeating a restaurant or dish.
5. **Add-on.** One Instamart add-on per meal, on the gap card, if it closes a real gap.
6. **Quality check.** The finished day is audited: not-a-meal, curry without roti or rice,
   oversized side, Jain-unsafe, duplicates, too small, odd add-on. `GET /daily/{user}/quality`
   returns the result, and the nightly job logs it.

### Nightly job
Refreshes the Swiggy token, pulls new Swiggy orders into the taste profile, recomputes
weights and builds tomorrow's plan, so the morning page loads straight away.

### Where AI is used, and where it isn't
Gemini classifies dish names, reads uploaded diet plans and powers chat. The plan itself
comes from deterministic Python, so it cannot invent dishes, prices or cart IDs. Without
a Gemini key the app still runs on keyword rules.

### Swiggy MCP usage
Food: `get_addresses`, `search_restaurants`, `search_menu`, `get_restaurant_menu`,
`update_food_cart`, `get_food_cart`, `place_food_order`, `track_food_order`,
`get_food_orders`. Instamart: `search_products`, `update_cart`, `get_cart`, `checkout`,
`get_orders`. Menus are cached for the day, `Retry-After` is honoured on HTTP 429, and
errors Swiggy returns inside a successful response are raised, not ignored.

---

## Run it locally

Requirements: Python 3.11+, Node 20+.

```bash
# backend
cd backend
pip install -r requirements.txt
python -m uvicorn app:app --port 8343

# website (new terminal)
cd web
npm install
NEXT_PUBLIC_API_URL=http://localhost:8343 npx next dev --port 6001
```

Open http://localhost:6001, tap **Connect Swiggy** and sign in on Swiggy's own page.
Without a Swiggy login the app runs on a built-in demo catalogue. After a restart the
live catalogue takes about three minutes to load.

First run walks through three steps: connect Swiggy, name and delivery address, then
diet, allergies, budget and favourite dishes.

## Configuration

Settings live in `backend/.env` (never committed; see `backend/.env.example`).

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Dish classification, diet-plan reading and chat. Optional. |
| `SWIGGY_MODE` | `mcp` for live Swiggy, `mock` for the demo catalogue. |
| `SWIGGY_MCP_TOKEN` / `SWIGGY_REFRESH_TOKEN` / `SWIGGY_CLIENT_ID` | Written by **Connect Swiggy** (OAuth 2.1 + PKCE). |
| `SWIGGY_ADDRESS_ID` | Optional: pin a saved Swiggy address. |
| `FORKCAST_SECRET` | Signs user tokens. If unset, a random secret is generated into `backend/.auth_secret`. |
| `FORKCAST_ORIGINS` | Comma-separated web origins allowed to call the API (default `http://localhost:6001,http://localhost:3000`). |
| `FORKCAST_ALLOW_LIVE` | `1` lets visitors from the internet switch on Live ordering. Leave unset while the server holds one shared Swiggy login. |
| `DAILY_NIGHTLY_HOUR` | Hour the nightly job runs (default 2). |

## Tests

```bash
cd backend
python -m pytest -q
```

About 280 tests cover the planner rules, allergies, portions, the quality check,
nutrition lookups, learning signals, rollover, weather, diet-plan upload, the order flow
against a fake Swiggy, and access control.

## Security and privacy

- Every user-scoped route needs that user's signed token (HMAC-SHA256, 30-day sliding
  expiry) and checks that it owns the user, plan or slot in the request.
- The API only accepts browser calls from the listed origins.
- Swiggy tokens stay on the server, never in the browser.
- Stored: preferences, feedback, the plans shown, and orders placed through Forkcast.
  Not stored: payment details, the full street address, uploaded diet-plan files.
- Sent to Gemini: dish names, chat messages and an uploaded diet plan. Never Swiggy
  tokens, addresses or order IDs.

## Repository map

| Path | What |
|---|---|
| `backend/` | FastAPI app, planner, Swiggy clients, tests |
| `backend/data/indb.csv` | Indian Nutrient Databank recipes used for nutrition |
| `web/` | Next.js app: Today, You, setup and chat |
| `deploy/` | systemd unit and Caddy config for the server |
| `docs/SPEC-daily-personalization.md` | Product spec for the daily recommender |
| `docs/PRODUCTION-APPLICATION.md` | Answers for Swiggy's production access form |
| `docs/DEPLOY.md` | Free hosting setup: Oracle Cloud VM + Vercel |

## Known limits

- **One Swiggy login per server.** Everyone using a deployment sees restaurants for
  that account's address. Per-user Swiggy sign-in is the main thing left before real users.
- **Diet plans map to presets.** Exact calorie or protein numbers from a plan are turned
  into the nearest goal (lose, maintain, gain, high protein), not stored as targets.
- **Nutrition is an estimate.** Restaurant portions differ from reference recipes.
- **Not medical advice.** Medical conditions (diabetes, blood pressure, PCOS, pregnancy)
  are not handled. Allergen information is estimated per dish: always tell the
  restaurant about a severe allergy yourself.

## Credits

- Food and grocery data: [Swiggy MCP](https://mcp.swiggy.com/builders). Swiggy and
  Instamart logos are used for attribution only.
- Nutrition: Indian Nutrient Databank (Vijayakumar et al., *Current Developments in
  Nutrition*, 2024, [doi:10.1016/j.cdnut.2024.103790](https://doi.org/10.1016/j.cdnut.2024.103790)).
- Weather: [Open-Meteo](https://open-meteo.com).
