# Forkcast — Swiggy MCP production access application

Draft answers to the inputs on the Swiggy Builders production page (9 required,
3 optional). Track: **Individual Developers**.
Items marked **TODO** need a value only the applicant has.

## 1. Who is building it
Two independent developers, applying on the **Individual Developers** track:

- **Vardan Agarwal** (primary contact), Meerut, Uttar Pradesh, India.
  GitHub: [vardanagarwal11](https://github.com/vardanagarwal11). LinkedIn: **TODO**.
  Email: vardanagarwal11@gmail.com. Phone: shared in the application email.
- **Jatin Tilwani**, co-developer. GitHub: **TODO**. LinkedIn: **TODO**.

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
- Production: **TODO** `https://<backend address>/auth/swiggy/callback`
  (backend address = the DuckDNS name set up in `docs/DEPLOY.md`)

## 5. Static egress IPs
**TODO** — the reserved public IP of the Oracle Cloud VM (one address).

## 6. Security contact
vardanagarwal11@gmail.com

## 7. Data handling and privacy
- Stored: diet, allergies, budget, city, meal times, feedback events, the plan
  shown each day, order IDs/status the user placed through Forkcast, and
  the dish names from Swiggy order history (to learn tastes).
- Not stored: payment details (cash on delivery only), full address text
  (only the Swiggy `addressId` and its label), phone or email from Swiggy.
- Swiggy OAuth tokens live server-side only, never in the browser or logs.
- Diet plan upload: a photo, PDF or text file the user chooses is sent to Gemini
  once to be read, shown back to the user for confirmation, and not stored.
- Sent to Gemini: dish names, the user's chat messages and an uploaded diet plan; no Swiggy tokens,
  addresses or order IDs.
- Users can see, adjust and delete each learned preference from the
  "What we know about you" panel, and "Delete my account and data" there
  (`DELETE /daily/{user}`) erases their profile, plans, feedback, orders and
  taste memory. Swiggy-side data (orders, addresses) stays with Swiggy.
- Prices and availability shown are the ones Swiggy returned; the confirm
  step shows the payable amount from the live cart before ordering.

## 8. Infrastructure
- Backend: one Oracle Cloud "Always Free" VM (Ubuntu 24.04, India region) with a
  reserved public IP. FastAPI under systemd, bound to localhost, behind Caddy
  with automatic HTTPS. SQLite on the VM's disk.
- Website: Vercel (Next.js). It talks only to the backend, never to Swiggy.
- Secrets (Swiggy tokens, Gemini key, token-signing secret) live in the VM's
  `backend/.env`, outside git.
- While the server holds a single Swiggy login, visitors from the internet
  cannot switch on Live ordering, never receive the account's street address,
  and their taste profile is never seeded from the account's order history.
- Setup steps: `docs/DEPLOY.md`.

## 9. Terms acknowledgement
- "Powered by Swiggy" / "Powered by Instamart" shown on every card, the order
  summary and the confirmation bar, using the official logos.
- No dark patterns: no pre-ticked orders, no countdowns, totals always shown.
- The applicant, Vardan Agarwal, has read and accepts the Swiggy MCP terms
  (confirmed 11 November 2026).

## 10. Security audit summary (optional)
No external audit. Internal review done: per-user signed tokens with ownership
checks on every user route (tests in `backend/test_auth.py`), CORS allow-list,
Swiggy tokens server-side only, secrets out of git, account deletion.

## 11. SOC2 / ISO certification (optional)
None (individual developer).

## 12. Expected traffic and scaling plan (optional)
Per user per day: one nightly catalogue refresh (about 10–20 `search_restaurants` /
`search_menu` calls, cached for the day) plus a few cart calls per order. Pilot:
under 50 users, well under 2,000 MCP calls a day. `Retry-After` is honoured on 429;
there is no polling and no background scraping.

## How Forkcast follows the ground rules
| Rule | What the app does |
|---|---|
| Don't hide Swiggy's brand | "Powered by Swiggy / Instamart" with official logos on every card, order summary and confirmation |
| Don't misrepresent prices or availability | Card prices are Swiggy's; the amount to pay comes from the live cart before ordering; nutrition is labelled as an estimate |
| No data beyond the APIs | Only documented MCP tools; menus cached for one day; no scraping |
| No manipulating order flows or dark patterns | The user taps twice to order; the assistant has no ordering tool; no timers or pre-selected orders |
| Don't bypass rate limits | One retry after `Retry-After`, otherwise the error is shown |
| User data | Stored data is listed in section 7; users can delete it all in the app |

## Known caveats
- **Access control:** every user-scoped route requires a per-user signed token
  (HMAC-SHA256) and checks that it owns the user, plan or slot in the request;
  others get 403. Tokens expire after 30 days and are renewed on each request, so
  idle sessions end. The API only accepts browser calls from listed origins.
- **Must change before real multi-user launch: one Swiggy login per server.**
  The prototype holds a single Swiggy OAuth token, so it serves one Swiggy
  account. Production needs per-user Swiggy OAuth: each user connects their own
  account, tokens are stored per user (encrypted), and signing in to Forkcast is
  signing in with Swiggy. Until then, getting an expired account back works only
  from the server's own machine, and `/mcp/addresses` is open during setup.
- Nutrition values come from the Indian Nutrient Databank (INDB; Vijayakumar
  et al., Current Developments in Nutrition 2024, doi 10.1016/j.cdnut.2024.103790),
  published as an open-access resource for research, government and the private
  sector. Its GitHub repository has no licence file, and its raw values derive from
  ICMR-NIN's food composition tables, so we credit it in the app and will ask the
  authors (Anuvaad Solutions) for written permission before a commercial launch.
  Restaurant portions differ from home recipes, so values are labelled estimates.
- Swiggy logo files are used for attribution only; confirm they match the
  official brand kit.
