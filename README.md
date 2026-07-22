# Budget-Based Monthly Meal Planner

Tell it your monthly food budget + must-haves. It builds a full month's calendar of
breakfast/lunch/dinner within budget, orders per meal on your yes/no, and rolls
unused budget into next month as **Swiggy Cash**.

Built on Swiggy MCP tool schemas (Food). Differentiator vs public Swiggy MCP demos:
**budget-constrained planning + rollover wallet**, not just conversational ordering.

Demo status: **working end-to-end on localhost**, mock catalog + simulated wallet.

---

## Money model (MVP — virtual budget, no custody)

We hold **no real money**. The wallet is a ledger of numbers:

- Budget you set = a number deposited into the month's cycle.
- Order placed → **debit**.
- Slot skipped → money simply not spent (stays in balance). No phantom credit.
- Confirmed order cancelled → **credit** (refund).
- Month end → leftover **rolls over** into next month as Swiggy Cash.

Real payment (prototype) happens per-order at Swiggy checkout; the ledger only
*tracks* the budget. Swiggy MCP has no monthly-budget/rollover API — that layer is ours.

---

## Architecture (key rule: LLM never plans the month)

```
intake (LLM/regex)  → parses "10k budget, 10 paneer, veg only, heavy"
appetite calculator → portion multiplier per meal slot (Indian pattern: lunch heaviest)
catalog fetcher     → dishes from mock (demo) or Swiggy MCP (prototype)
optimizer (Python)  → deterministic greedy fill of 90 slots, budget + constraint aware
plan service        → persist plan, notification state machine (yes/no/later/other)
order executor      → mock (demo) or place_food_order (prototype)
wallet/ledger       → virtual budget + rollover (our DB, not Swiggy's)
```

The LLM only extracts constraints and handles chat. A deterministic optimizer builds
the plan — avoids the hallucinated-cart-id failure mode of single over-scoped agents.

---

## Files

| File | What |
|---|---|
| `db.py` | SQLite schema (users, cycles, ledger, plans, slots, notifications) |
| `wallet_service.py` | deposit/debit/credit/balance/close_cycle + rollover |
| `appetite.py` | appetite level → per-slot portion multiplier |
| `catalog.py` | Dish type + mock Indian catalog |
| `catalog_fetcher.py` | mock ↔ Swiggy MCP adapter (same Dish output) |
| `optimizer.py` | deterministic 90-slot budget/constraint solver |
| `intake.py` | NL → constraints (Gemini if key, else regex fallback) |
| `plan_service.py` | plan persistence + notification state machine |
| `order_executor.py` | mock ↔ place_food_order/track_food_order |
| `swap_service.py` | ±price-band alternatives, appetite-aware |
| `app.py` | FastAPI wiring all of it |
| `../frontend/index.html` | React calendar UI (single file, CDN, no build) |

---

## Run

```bash
cd backend
pip install -r requirements.txt

# run tests
python test_wallet.py
python test_optimizer.py
python test_e2e.py

# start API
python -m uvicorn app:app --reload --port 8000

# open frontend/index.html in a browser (talks to localhost:8000)
```

Optional LLM intake: `set GEMINI_API_KEY=...` (Windows) before starting. Without it,
the regex fallback handles the common phrasings — demo never blocks on a key.

### Real Swiggy MCP (live ordering)

Default mode is `mock`. To hit the real Swiggy Food MCP:

```bash
# 1. Link your Swiggy account via OAuth (Claude / MCP Inspector / Postman —
#    localhost redirect is whitelisted) and copy the access token.
set SWIGGY_MODE=mcp
set SWIGGY_MCP_TOKEN=<oauth access token>
# optional: pin an address, else the first saved address is used
set SWIGGY_ADDRESS_ID=<addressId from GET /mcp/addresses>

python -m uvicorn app:app --port 8000
```

Live endpoints: `GET /mode`, `GET /mcp/addresses`, `GET /mcp/tools`.

**Swiggy guardrails enforced** (per official docs): cart total must be < ₹1000,
only OPEN restaurants used, COD-only, order placed against a saved `addressId`.
Client: `swiggy_mcp.py` (JSON-RPC 2.0 over MCP Streamable HTTP, Bearer OAuth,
endpoint `https://mcp.swiggy.com/food`). Verified tool schemas:
`get_addresses`, `search_restaurants(addressId, query, offset)`,
`search_menu(addressId, query, restaurantIdOfAddedItem, vegFilter, offset)`,
`update_food_cart(restaurantId, cartItems, addressId)`, `get_food_cart`,
`place_food_order(addressId, paymentMethod)`, `track_food_order`.

**Live variant caveat (MVP):** the planner stores a simplified variant name per
slot, not the full Swiggy `variantsV2`/`variations` blob. Items that *require* a
variant selection may fall back to Swiggy's default at order time. Storing the raw
variant object per slot is a prototype TODO.

---

## Improvements over the original spec

- **Per-slot portion multipliers** (lunch heaviest) instead of one flat number —
  matches real Indian eating.
- **Constraint-first optimizer pass** — guarantees "10 paneer" if affordable, not
  left to greedy luck; exact shortfall message when infeasible.
- **LLM optional** — deterministic regex fallback makes the demo reproducible and
  offline-safe.
- **Corrected money model** — full budget deposited at approval; skipping a planned
  slot keeps the cash (no double-count), refunds only cancel confirmed orders.

## Prototype TODO (real infra)

- Swap mock catalog fetcher → real `search_restaurants`/`search_menu`.
- Swap mock order executor → real `update_food_cart`/`place_food_order`/`track_food_order`.
- SQLite → Postgres.
- APScheduler → real scheduler firing T-30 notifications per slot.
- Real push/WhatsApp for yes/no/later/other replies.
- Groq Llama 3.3 70B for the fast notification-reply parsing.
