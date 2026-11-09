# Forkcast — Swiggy MCP production access application

Draft answers to the nine inputs the Swiggy Builders production form asks for.
Items marked **TODO** need a value only the applicant has.

## 1. Who is building it
Vardan Agarwal, independent developer (GitHub: vardanagarwal11).

## 2. What it does
Forkcast plans one person's food day. Every morning it shows four short lists —
breakfast, lunch, snack, dinner — of real dishes from Swiggy Food restaurants that
deliver to the user's saved address, plus Instamart add-ons that fill a nutrient
gap (curd, fruit, milk). Picks respect the user's monthly budget, diet (with
weekday rules such as "Jain on Thursdays"), allergies and protein target, and
learn from thumbs up/down, skips, ratings and past Swiggy orders.

The user always places the order themselves: one tap on a card builds the Swiggy
cart, shows the payable total from `get_food_cart`, address and payment
(cash on delivery), and a second tap places it. Orders above ₹1000 are refused.
A dry-run mode builds the real cart without ordering. The in-app chat assistant
can search and explain, but has no order tool.

Allergy handling: dishes whose core ingredient is an allergen are hidden; when an
allergen is removable (peanuts in poha) the dish stays and the order carries
`noteToRestaurant` ("No peanut please, severe allergy").

## 3. Architecture
```
Browser (Next.js 16)  ──HTTPS──>  Forkcast API (FastAPI, Python)
                                    ├── Swiggy MCP  mcp.swiggy.com/food, /im  (OAuth 2.1 + PKCE)
                                    ├── Google Gemini API  (dish classification, chat)
                                    ├── Open-Meteo  (weather for the user's city; no user data sent)
                                    └── SQLite  (profiles, feedback, plans, dish profiles)
```
- Tools used — Food: `get_addresses`, `search_restaurants`, `search_menu`,
  `get_restaurant_menu`, `update_food_cart`, `get_food_cart`, `place_food_order`,
  `track_food_order`, `get_food_orders`. Instamart: `search_products`,
  `update_cart`, `get_cart`, `checkout`, `get_orders`.
- Catalogue calls run once per user per night (plus on-demand regenerate);
  results are cached for the day. On HTTP 429 the client honours `Retry-After`
  and retries once. In-band errors (`success:false`, `errorCodes`) are raised,
  never swallowed.
- Nothing is ordered without an explicit user tap; live mode needs a second
  confirmation to enable.

## 4. Redirect URIs
- Development: `http://localhost:8765/callback`
- Production: **TODO** `https://<your-domain>/auth/swiggy/callback`

## 5. Static egress IPs
**TODO** — the IP(s) of the production host that calls mcp.swiggy.com.

## 6. Security contact
**TODO** — a monitored security email for this app.

## 7. Data handling and privacy
- Stored: diet, allergies, budget, city, meal times, feedback events, the plan
  shown each day, order IDs/status the user placed through Forkcast, and
  the dish names from Swiggy order history (to learn tastes).
- Not stored: payment details (cash on delivery only), full address text
  (only the Swiggy `addressId` and its label), phone or email from Swiggy.
- Swiggy OAuth tokens live server-side only, never in the browser or logs.
- Sent to Gemini: dish names and the user's chat messages; no Swiggy tokens,
  addresses or order IDs.
- Users can see, adjust and delete each learned preference from the
  "What we know about you" panel, and "Delete my account and data" there
  (`DELETE /daily/{user}`) erases their profile, plans, feedback, orders and
  taste memory. Swiggy-side data (orders, addresses) stays with Swiggy.
- Prices and availability shown are the ones Swiggy returned; the confirm
  step shows the payable amount from the live cart before ordering.

## 8. Infrastructure
**TODO** — hosting provider/region, HTTPS termination, DB backups. Current
prototype: single FastAPI process + SQLite; production plan is a managed
Postgres and secrets in the host's secret store.

## 9. Terms acknowledgement
- "Powered by Swiggy" / "Powered by Instamart" shown on every card, the order
  summary and the confirmation bar, using the official logos.
- No dark patterns: no pre-ticked orders, no countdowns, totals always shown.
- **TODO**: accept the Swiggy Builders terms in the form.

## Known caveats
- **Must fix before launch: no per-user authentication yet.** The prototype is
  single-user and trusts the `user_id` in the URL, so anyone who can reach the
  API could read, order for, or delete another user. Production needs a signed
  session (e.g. sign-in via Swiggy OAuth) bound to the user, with every
  `/daily/{user_id}` route, especially order and delete, checking that the
  session owns that id.
- Nutrition values come from the Indian Nutrient Databank (INDB; Vijayakumar
  et al., Current Developments in Nutrition 2024, doi 10.1016/j.cdnut.2024.103790),
  published as an open-access resource for research, government and the private
  sector. Its GitHub repository has no licence file, and its raw values derive from
  ICMR-NIN's food composition tables, so we credit it in the app and will ask the
  authors (Anuvaad Solutions) for written permission before a commercial launch.
  Restaurant portions differ from home recipes, so values are labelled estimates.
- Swiggy logo files are used for attribution only; confirm they match the
  official brand kit.
