"""FastAPI app — wires the whole demo end-to-end.

Flow:
  POST /intake          NL text -> parsed constraints (+ ask appetite if missing)
  POST /appetite        set appetite level -> portion profile
  POST /plan            run optimizer -> save draft plan + slots
  GET  /plan/{id}       fetch plan + calendar slots
  POST /plan/{id}/approve   deposit budget, activate plan
  POST /slot/{id}/notify    simulate T-30 notification
  POST /slot/{id}/respond   yes|no|later|other  (drives state machine + wallet)
  GET  /slot/{id}/alternatives   swap options
  GET  /wallet/{user}/{month}    balance + rollover summary
  POST /wallet/{user}/{month}/close   month close -> rollover
"""
import os
import time as _time
import config  # noqa: F401 — loads .env before anything reads os.environ
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from db import init_db, get_conn
from wallet_service import WalletService
from appetite import build_profile, AppetiteProfile
import taste_profile
from catalog_fetcher import CatalogFetcher
from optimizer import optimize, Constraint
from plan_service import PlanService
from order_executor import OrderExecutor
from swap_service import alternatives, apply_swap, SwapError
from intake import parse_intake
import gemini
import blueprint_chat
import feasibility

# ---- runtime state (mutable so we can switch mock -> live after in-app login) ----
# 'mock' = demo, 'mcp' = real Swiggy. When SWIGGY_MODE=mcp but the token is
# missing/invalid, we DON'T crash — we boot in mock and report needs_auth so the
# frontend can offer a "Connect Swiggy" button.
ADDRESS_ID = os.environ.get("SWIGGY_ADDRESS_ID")

STATE = {
    "mode": os.environ.get("SWIGGY_MODE", "mock").lower(),
    "client": None,
    "fetcher": None,
    "needs_auth": False,   # True when mcp desired but no valid token
    "token_expired": False,  # True when the saved JWT is past its exp claim
    # The addressId every live search/order runs against. Defaults to the
    # SWIGGY_ADDRESS_ID env var; the frontend overrides it with the user's
    # onboarding pick via POST /address (see _set_address).
    "address_id": ADDRESS_ID,
}


def _build_client():
    """Try to build a live Swiggy client. Returns client or None (never raises)."""
    from swiggy_mcp import SwiggyMCPClient, SwiggyMCPError
    try:
        return SwiggyMCPClient()
    except SwiggyMCPError as e:
        if getattr(e, "expired", False):
            import swiggy_auth
            if swiggy_auth.refresh():
                try:
                    return SwiggyMCPClient()
                except SwiggyMCPError as e2:
                    e = e2
        print(f"[auth] no live Swiggy client: {e}")
        # Distinguish a dead JWT from a missing token: an expired JWT must
        # prompt a re-login (the .env token is stale), a missing one just
        # means nobody has connected yet.
        if getattr(e, "expired", False):
            STATE["token_expired"] = True
        return None


def _init_runtime():
    """(Re)build client + fetcher from current env/token. Safe to call anytime.

    Also resets the active address to the env default — after a login/logout
    the account (and its saved addresses) may have changed, so a pick from a
    previous session must not survive. The frontend re-syncs its pick via
    POST /address right after onboarding / session restore.
    """
    _CATALOG_CACHE.clear()
    STATE["address_id"] = ADDRESS_ID
    STATE["token_expired"] = False
    if STATE["mode"] == "mcp":
        client = _build_client()
        if client is None:
            # desired live, but no token -> degrade to mock + flag for the UI
            STATE["needs_auth"] = True
            STATE["client"] = None
            STATE["fetcher"] = CatalogFetcher(mode="mock", address_id=ADDRESS_ID)
        else:
            STATE["needs_auth"] = False
            STATE["client"] = client
            STATE["fetcher"] = CatalogFetcher(mode="mcp", mcp_client=client,
                                              address_id=ADDRESS_ID)
    else:
        STATE["needs_auth"] = False
        STATE["client"] = None
        STATE["fetcher"] = CatalogFetcher(mode="mock", address_id=ADDRESS_ID)


_CATALOG_CACHE = {}    # cache_key -> [Dish]
_CATALOG_AT = {}       # cache_key -> fetch time (live TTL)
CATALOG_TTL_S = int(os.environ.get("CATALOG_TTL_S", "1800"))

init_db()
_init_runtime()

app = FastAPI(title="Budget Meal Planner")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

class _AppetiteCache(dict):
    """user_id -> AppetiteProfile.

    The in-memory cache dies on restart (or another worker serves the next
    request), but /appetite persists every profile to the appetite_profiles
    table — so on a miss we reload from there instead of letting every planner
    path silently fall back to "moderate" portions.
    """

    def get(self, key, default=None):
        prof = super().get(key)
        if prof is not None:
            return prof
        try:
            conn, _, _ = svc()
        except Exception:
            return default
        try:
            row = conn.execute(
                "SELECT appetite_level FROM appetite_profiles WHERE user_id=?",
                (key,)).fetchone()
        except Exception:
            row = None
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if row is None:
            return default
        try:
            prof = build_profile(key, row["appetite_level"])
        except ValueError:
            return default  # corrupt row — behave like "not set"
        self[key] = prof
        return prof


_APPETITE_CACHE = _AppetiteCache()


def _live():
    """True when a live Swiggy client is actually available."""
    return STATE["mode"] == "mcp" and STATE["client"] is not None


def get_catalog(veg_only=False, high_protein=False):
    """Catalog for a given diet. Cached per (diet, protein, address) combination.

    The cache key MUST include high_protein: the seed queries differ, so a
    non-veg high-protein pool is a genuinely different set of dishes, not a
    filtered view of the veg one. It must also include the active addressId:
    search_menu is address-scoped, so a pool built around one address is wrong
    for another (different restaurants, prices, availability).
    """
    key = (("veg" if veg_only else "all")
           + ("+protein" if high_protein else "")
           + f"@{STATE['address_id']}")
    # live menus go stale (sold out, closed); refetch after the TTL so the daily
    # on-open stale check sees it. A failed refetch keeps the old pool.
    expired = _live() and _time.time() - _CATALOG_AT.get(key, 0) > CATALOG_TTL_S
    if key not in _CATALOG_CACHE or expired:
        # Pass the CURRENT address explicitly — the fetcher's own address_id
        # was baked in at construction and may predate the user's pick.
        try:
            fresh = STATE["fetcher"].fetch(
                address_id=STATE["address_id"],
                veg_only=veg_only, high_protein=high_protein)
            # per-query failures (429s) are swallowed upstream and can yield an empty
            # pool; caching that would blank every menu until the TTL ran out
            if not fresh and _live():
                raise RuntimeError("live catalog fetch returned no dishes")
            _CATALOG_CACHE[key] = fresh
            _CATALOG_AT[key] = _time.time()
        except Exception:
            if key not in _CATALOG_CACHE:
                raise
    return _CATALOG_CACHE[key]


def _swap_catalog():
    """Whole-neighbourhood catalog for validating / re-pairing swaps.

    A swap can arrive for any slot of any plan, so it must be checked against
    every diet pool we know about, not just one cached view. Reuses warm
    caches (deduped by dish_id) and only falls back to a fresh default fetch
    when nothing was fetched yet — a live fetch failure degrades to "whatever
    is already cached" instead of 500ing the endpoint.
    """
    by_id = {}
    pools = list(_CATALOG_CACHE.values())
    try:
        pools.append(get_catalog())
    except RuntimeError:
        pass  # live fetch unavailable; validate against the cached pools only
    for dishes in pools:
        for d in dishes:
            by_id.setdefault(d.dish_id, d)
    return list(by_id.values())


def _executor():
    mode = "mcp" if _live() else "mock"
    return OrderExecutor(mode=mode, mcp_client=STATE["client"],
                         address_id=STATE["address_id"])


def svc():
    conn = get_conn()
    return conn, WalletService(conn), PlanService(conn, WalletService(conn),
                                                  _executor(), _raw_variant_of)


def _raw_variant_of(dish_id):
    for dishes in _CATALOG_CACHE.values():
        for d in dishes:
            if d.dish_id == dish_id:
                return d.variants.get("_raw")
    return None


# ---------- models ----------
class IntakeIn(BaseModel):
    user_id: int
    text: str


class AppetiteIn(BaseModel):
    user_id: int
    appetite_level: str = "moderate"
    roti_per_meal: int = None
    rice_katori_per_meal: int = None


class PlanIn(BaseModel):
    user_id: int
    month: str
    budget: float
    constraints: list = []       # [{"dish_tag","min_count"}]
    veg_only: bool = False
    days: int = 30
    # Which meal slots to plan. Comes straight from the blueprint's `meals`
    # field — the chat gathered it all along, but /plan used to ignore it and
    # always build all three, so "breakfast and lunch only" still produced (and
    # budgeted for) 30 dinners.
    meals: list = ["breakfast", "lunch", "dinner"]
    # Steers the catalog search toward protein-rich dishes (see
    # catalog_fetcher.PROTEIN_QUERIES). Filtering can't add dishes that were
    # never fetched, so this has to reach the search, not just the optimizer.
    high_protein: bool = False
    # Free-form taste/diet preferences — merged into a TasteProfile (taste_profile.py)
    # and used to hard-filter and re-rank pairing candidates. All keys optional:
    # veg_level, allergies, health_goals, spice_preference, favorite_cuisines,
    # disliked_foods, portion_size, notes.
    taste_prefs: dict = {}

    @field_validator("days")
    @classmethod
    def _days_positive(cls, v):
        if v < 1:
            raise ValueError("days must be >= 1")
        return v

    @field_validator("meals")
    @classmethod
    def _meals_valid(cls, v):
        if not v:
            raise ValueError("meals must not be empty")
        bad = [m for m in v if m not in ("breakfast", "lunch", "dinner")]
        if bad:
            raise ValueError(f"invalid meal types: {bad}")
        return v

    @field_validator("budget")
    @classmethod
    def _budget_positive(cls, v):
        if v <= 0:
            raise ValueError("budget must be positive")
        return v


class RespondIn(BaseModel):
    answer: str
    new_day: int = None
    new_meal_type: str = None


class SwapIn(BaseModel):
    dish_id: str
    name: str = ""
    restaurant_id: str = ""
    restaurant_name: str = ""
    image_url: str = ""
    price: float
    rating: float = 0.0
    variant: str = "regular"


class UserIn(BaseModel):
    name: str
    area: str = None


class ChatIn(BaseModel):
    user_id: int
    message: str
    session_state: dict = {}      # legacy: {extracted:{...}} — still accepted
    blueprint: dict = {}          # running blueprint echoed back each turn (compact context)
    history: list = []            # optional recent [{role,text}] — only last few used


class AdjustIn(BaseModel):
    user_id: int
    message: str
    blueprint: dict = {}          # the current plan's blueprint to tweak


# ---------- endpoints ----------
@app.post("/user")
def create_user(body: UserIn):
    conn, w, _ = svc()
    uid = w.create_user(body.name, body.area)
    conn.close()
    return {"user_id": uid}


@app.get("/mode")
def get_mode():
    return {
        "mode": "mcp" if _live() else "mock",
        "live": _live(),
        "needs_auth": STATE["needs_auth"],  # mcp desired but no valid token yet
        "token_expired": STATE["token_expired"],  # saved JWT past exp — re-login
    }


# ---------- in-app Swiggy OAuth login ----------
# The OAuth flow opens the system browser and waits for the localhost callback,
# so it runs in a background thread; the frontend polls /auth/swiggy/status.
_AUTH = {"status": "idle", "error": None}  # idle|running|connected|failed


def _run_auth():
    import swiggy_auth
    _AUTH["status"] = "running"
    _AUTH["error"] = None
    try:
        swiggy_auth.run()          # opens browser, catches callback, writes .env + env
        STATE["mode"] = "mcp"
        _init_runtime()            # rebuild client from the fresh token
        if _live():
            _AUTH["status"] = "connected"
        else:
            _AUTH["status"] = "failed"
            _AUTH["error"] = "token saved but client did not initialize"
    except Exception as e:  # noqa: BLE001
        _AUTH["status"] = "failed"
        _AUTH["error"] = f"{type(e).__name__}: {e}"
        print(f"[auth] flow failed: {e}")


@app.post("/auth/swiggy/start")
def auth_start():
    """Kick off the Swiggy OAuth flow. Opens a browser on THIS machine (the one
    running the backend). Returns immediately; poll /auth/swiggy/status."""
    if _AUTH["status"] == "running":
        return {"status": "running"}
    if _live():
        return {"status": "connected"}
    import threading
    threading.Thread(target=_run_auth, daemon=True).start()
    return {"status": "running"}


@app.get("/auth/swiggy/status")
def auth_status():
    return {
        "status": _AUTH["status"],       # idle|running|connected|failed
        "error": _AUTH["error"],
        "live": _live(),
    }


@app.post("/auth/swiggy/logout")
def auth_logout():
    """Drop the live client and fall back to mock (does not delete the .env token)."""
    STATE["mode"] = "mock"
    _init_runtime()
    _AUTH["status"] = "idle"
    _AUTH["error"] = None
    return {"live": False}


def _mark_expired_token(e):
    """A live call died on a dead JWT: flip the auth flags so the frontend's
    next /mode poll prompts a re-login (and auto-opens the OAuth browser tab)
    instead of showing a generic 502. Returns True when the error WAS expiry,
    so callers can tailor the message they raise."""
    if getattr(e, "expired", False):
        STATE["needs_auth"] = True
        STATE["token_expired"] = True
        STATE["client"] = None          # dead client — /mode reports mock+expired
        STATE["fetcher"] = CatalogFetcher(mode="mock", address_id=STATE["address_id"])
        return True
    return False


@app.get("/mcp/addresses")
def mcp_addresses():
    """Live only: list saved Swiggy addresses to pick an addressId for ordering.

    Normalizes the raw Swiggy payload to the shape the frontend expects:
    {"addresses": [{id, addressLine, addressCategory, addressTag, label}]}.
    Swiggy has been observed wrapping the list in "addresses" OR "data" and
    naming the id "id" OR "addressId"; the backend resolvers already tolerate
    both, so the picker endpoint must too — otherwise the UI shows a false
    "no saved addresses" state (and a dead-ended onboarding) on the other shape.
    """
    if not _live():
        raise HTTPException(400, "not connected to Swiggy")
    try:
        raw = STATE["client"].call("get_addresses", {})
    except Exception as e:  # noqa: BLE001 - surface as a clean 502 for the UI
        if _mark_expired_token(e):
            raise HTTPException(401, "Swiggy login expired — please reconnect.")
        # Never echo the raw exception to the client — SwiggyMCPError embeds
        # the upstream response body, which isn't ours to forward.
        print(f"[addresses] lookup failed: {e}")
        raise HTTPException(502, "Swiggy address lookup failed")
    if isinstance(raw, dict) and raw.get("isError"):
        raise HTTPException(502, "Swiggy rejected the address lookup")
    entries = raw.get("addresses") or raw.get("data") or [] if isinstance(raw, dict) else []
    if not isinstance(entries, list):
        entries = []
    out = []
    for a in entries:
        if not isinstance(a, dict):
            continue
        aid = a.get("id") or a.get("addressId")
        if aid is None:
            continue  # an entry with no id can't be selected or ordered against
        out.append({
            "id": str(aid),
            "addressLine": a.get("addressLine") or a.get("address") or a.get("label"),
            "addressCategory": a.get("addressCategory") or a.get("type"),
            "addressTag": a.get("addressTag") or a.get("label"),
            "label": a.get("label"),
        })
    return {"addresses": out}


class AddressIn(BaseModel):
    address_id: str


@app.post("/address")
def set_address(body: AddressIn):
    """Pin the addressId all live searches and orders run against.

    Called from onboarding (the user's pick) and again on session restore, so
    a page reload re-syncs the backend. The pick always wins over the
    SWIGGY_ADDRESS_ID env default; changing it invalidates the address-scoped
    catalog caches.
    """
    aid = (body.address_id or "").strip()
    if not aid:
        raise HTTPException(400, "address_id is required")
    if aid != STATE["address_id"]:
        STATE["address_id"] = aid
        _CATALOG_CACHE.clear()
        if STATE["fetcher"] is not None:
            STATE["fetcher"].address_id = aid
    return {"status": "ok", "address_id": aid}


@app.get("/mcp/tools")
def mcp_tools():
    """Live only: introspect the real Swiggy MCP tool list."""
    if not _live():
        raise HTTPException(400, "not connected to Swiggy")
    return STATE["client"].list_tools()


@app.get("/im/search")
def im_search(query: str, offset: int = 0, limit: int = 40):
    """Live only: search Swiggy Instamart (groceries, quick commerce).

    Same OAuth token as the food server (one token, all Swiggy MCP servers).
    Returns flat product rows — id (spinId, orderable), name, brand, quantity,
    price, mrp, rating, image — one per product's cheapest in-stock variation.
    Read-only by design: update_cart/checkout exist on the Instamart server
    but stay unwired until deliberately enabled.
    """
    if not _live():
        raise HTTPException(400, "not connected to Swiggy")
    from instamart import InstamartClient, search as im_search_inner
    from swiggy_mcp import SwiggyMCPError

    # search_products needs an addressId. Same resolution order as the food
    # catalog: the env/picked one, else the account's first saved address —
    # cached in STATE so repeat searches don't re-fetch the address list.
    aid = STATE["address_id"]
    if not aid:
        try:
            raw = STATE["client"].call("get_addresses", {})
            entries = raw.get("addresses") or raw.get("data") or []
            if not entries:
                raise HTTPException(502, "no saved Swiggy address for Instamart")
            aid = str(entries[0].get("id") or entries[0].get("addressId"))
            STATE["address_id"] = aid
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            if _mark_expired_token(e):
                raise HTTPException(401, "Swiggy login expired — please reconnect.")
            print(f"[im] address lookup failed: {e}")
            raise HTTPException(502, "Swiggy address lookup failed")

    try:
        client = InstamartClient(token=STATE["client"].token)
        products = im_search_inner(
            client, aid, query,
            offset=offset, limit=min(max(limit, 1), 40))
    except Exception as e:  # noqa: BLE001 - clean 4xx/5xx for the UI
        if _mark_expired_token(e):
            raise HTTPException(401, "Swiggy login expired — please reconnect.")
        # Raw exception stays server-side (upstream bodies aren't ours to leak).
        print(f"[im] search failed: {e}")
        raise HTTPException(502, "Instamart search failed")
    return {"query": query, "products": products}


@app.post("/intake")
def intake(body: IntakeIn):
    parsed = parse_intake(body.text)
    return {
        "budget": parsed.budget,
        "constraints": parsed.constraints,
        "veg_only": parsed.veg_only,
        "appetite_level": parsed.appetite_level,
        "days": parsed.days,
        "source": parsed.source,
        "needs_appetite": parsed.needs_appetite,
    }


@app.post("/appetite")
def set_appetite(body: AppetiteIn):
    try:
        prof = build_profile(body.user_id, body.appetite_level,
                             body.roti_per_meal, body.rice_katori_per_meal)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _APPETITE_CACHE[body.user_id] = prof
    # Persist too — the in-memory cache dies on restart, and the
    # appetite_profiles table existed but was never written.
    import json as _json
    conn, _, _ = svc()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO appetite_profiles "
            "(user_id, appetite_level, base_multiplier, roti_per_meal, rice_katori, per_slot_json) "
            "VALUES (?,?,?,?,?,?)",
            (body.user_id, prof.appetite_level, prof.base_multiplier,
             prof.roti_per_meal, prof.rice_katori_per_meal,
             _json.dumps(prof.per_slot)))
        conn.commit()
    finally:
        conn.close()
    return prof.to_row()


@app.post("/plan")
def make_plan(body: PlanIn):
    import sqlite3 as _sqlite3
    import traceback as _tb
    conn = None
    try:
        prof = _APPETITE_CACHE.get(body.user_id) or build_profile(body.user_id, "moderate")
        # Normalize at the boundary: constraints can arrive as bare strings from an
        # LLM-authored blueprint, and indexing those as dicts crashed /plan with a
        # 500. Never trust the shape of model-generated input.
        # Pairing constraints (dish_kind/slot_type/frequency, empty tag) survive
        # normalization; pass them through so PASS 4 can add desserts/drinks.
        constraints = [
            Constraint(c["dish_tag"], c["min_count"],
                       dish_kind=c.get("dish_kind", ""),
                       slot_type=c.get("slot_type", ""),
                       frequency=c.get("frequency", ""))
            for c in blueprint_chat._normalize_constraints(body.constraints)
        ]
        catalog = get_catalog(body.veg_only, body.high_protein)

        # Pairing constraints ("beverages with lunch") can draw from Instamart
        # groceries at retail prices alongside restaurant menus — often far
        # cheaper for the same drink/sweet. Fetch the pool only when the plan
        # actually has pairing constraints (a plain plan pays zero extra
        # latency). Instamart failure degrades to restaurant-only pairings —
        # never blocks the plan.
        extra_pairings = None
        pairing_kinds = {c.dish_kind for c in constraints if c.dish_kind and c.slot_type}
        taste = taste_profile.build_profile(
            body.user_id,
            {"veg_level": "veg" if body.veg_only else "nonveg",
             **body.taste_prefs},
        )
        if pairing_kinds and STATE["mode"] == "mcp" and STATE["client"]:
            try:
                from instamart import InstamartClient, pairing_pool
                aid = STATE["address_id"]
                if not aid:
                    # same resolution order as /im/search: first saved address
                    raw = STATE["client"].call("get_addresses", {})
                    entries = raw.get("addresses") or raw.get("data") or []
                    if entries:
                        aid = str(entries[0].get("id") or entries[0].get("addressId"))
                        STATE["address_id"] = aid
                if aid:
                    im = InstamartClient(token=STATE["client"].token)
                    extra_pairings = pairing_pool(im, aid,
                                               sorted(pairing_kinds),
                                               taste_profile=taste)
                    if extra_pairings:
                        print(f"[plan] instamart pairing pool: {len(extra_pairings)} items")
            except Exception as e:  # noqa: BLE001 - degrade, don't block
                if getattr(e, "expired", False):
                    raise
                print(f"[plan] instamart pool unavailable, restaurant-only pairings: {e}")

        result = optimize(catalog, prof,
                          body.budget, days=body.days, constraints=constraints,
                          veg_only=body.veg_only, meals=body.meals,
                          extra_pairing_dishes=extra_pairings,
                          taste_profile=taste)
        conn, _, plan_svc = svc()
        plan_id = plan_svc.save_plan(body.user_id, body.month, result)
        return {
            "plan_id": plan_id,
            "feasible": result.feasible,
            "total_cost": result.total_cost,
            "budget": result.budget,
            "leftover": result.leftover,
            "constraint_status": result.constraint_status,
            "message": result.message,
        }
    except _sqlite3.IntegrityError as e:
        # Almost always a stale session: the browser's saved user_id no longer
        # exists (DB was reset). 404 tells the frontend to restart onboarding
        # instead of showing a dead-end error.
        print(f"[plan] integrity error: {e}\n{_tb.format_exc()}")
        raise HTTPException(404, "User session expired — please start again from onboarding.")
    except _sqlite3.OperationalError as e:
        msg = str(e)
        if "locked" in msg or "busy" in msg:
            print(f"[plan] DB busy: {e}\n{_tb.format_exc()}")
            raise HTTPException(503, "Database busy — please retry")
        print(f"[plan] DB error: {e}\n{_tb.format_exc()}")
        raise HTTPException(500, "Database error — see server logs")
    except RuntimeError as e:
        # catalog empty (live mode token/network failure) — actionable 502
        if _mark_expired_token(e):
            raise HTTPException(401, "Swiggy login expired — please reconnect.")
        print(f"[plan] catalog/runtime error: {e}\n{_tb.format_exc()}")
        raise HTTPException(502, str(e))
    except ValueError as e:
        # Bad days/meals from a hand-authored blueprint (optimize validates at
        # its boundary) — a clean 400 beats an opaque 500.
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[plan] unexpected: {type(e).__name__}: {e}\n{_tb.format_exc()}")
        raise HTTPException(500, "Plan generation failed — see server logs")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@app.post("/plan/feasibility")
def plan_feasibility(body: PlanIn):
    """Why a budget doesn't fit, and what specifically would make it fit.

    Probes the deterministic optimizer across the levers the user controls
    (budget / meals / appetite) and returns concrete numbers, so the UI can say
    "Rs 10,000 won't cover 90 meals here, the cheapest dishes near you are about
    Rs 197 each" instead of generic advice.
    """
    cached = _APPETITE_CACHE.get(body.user_id)
    level = cached.appetite_level if cached else "moderate"
    return feasibility.analyse(
        catalog=get_catalog(body.veg_only, body.high_protein),
        profile_builder=build_profile,
        user_id=body.user_id,
        appetite_level=level,
        budget=body.budget,
        days=body.days,
        constraints=body.constraints,
        meals=body.meals,
        veg_only=body.veg_only,
        # same diet filters as /plan, or the quoted floor uses dishes /plan rejects
        taste_profile=taste_profile.build_profile(
            body.user_id,
            {"veg_level": "veg" if body.veg_only else "nonveg", **body.taste_prefs}),
    )


@app.get("/plan/{plan_id}")
def get_plan(plan_id: int):
    conn, _, plan_svc = svc()
    try:
        plan, slots = plan_svc.get_plan(plan_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        conn.close()
    return {"plan": plan, "slots": slots}


@app.post("/plan/{plan_id}/approve")
def approve(plan_id: int):
    conn, _, plan_svc = svc()
    try:
        summary = plan_svc.approve_plan(plan_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()
    return {"status": "active", "wallet": summary}


@app.post("/slot/{slot_id}/notify")
def notify(slot_id: int):
    conn, _, plan_svc = svc()
    try:
        return plan_svc.notify(slot_id)
    finally:
        conn.close()


@app.post("/slot/{slot_id}/respond")
def respond(slot_id: int, body: RespondIn):
    conn, _, plan_svc = svc()
    try:
        return plan_svc.respond(slot_id, body.answer, body.new_day, body.new_meal_type)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


@app.get("/slot/{slot_id}/alternatives")
def alts(slot_id: int, band: int = 100, veg_only: bool = False):
    conn, _, plan_svc = svc()
    try:
        s = plan_svc._slot(slot_id)
        plan = conn.execute("SELECT user_id FROM plans WHERE id=?",
                            (s["plan_id"],)).fetchone()
        prof = _APPETITE_CACHE.get(plan["user_id"])
        mult = prof.base_multiplier if prof else 1.0
        # Repetition-penalty input: how often each dish already appears in this
        # plan (keyed by both id and name), so alternatives demote the dishes
        # the month already hammers instead of offering them again.
        used_counts = {}
        for r in conn.execute(
                "SELECT dish_id, dish_name FROM meal_slots WHERE plan_id=?",
                (s["plan_id"],)):
            for key in (r["dish_id"], r["dish_name"]):
                if key:
                    used_counts[key] = used_counts.get(key, 0) + 1
        return {"alternatives": alternatives(dict(s), get_catalog(veg_only),
                                             mult, band, veg_only,
                                             used_counts=used_counts)}
    finally:
        conn.close()


@app.post("/slot/{slot_id}/swap")
def swap(slot_id: int, body: SwapIn):
    """Persist a dish swap chosen from /alternatives.

    The UI used to apply swaps client-side only, so a refresh silently
    reverted them. Now the write itself is hardened: the posted dish must
    exist in the catalog with matching name/price/rating (SwapIn used to be
    trusted blindly), a bare bread/rice can't be posted as a whole meal, a
    swapped-in curry gets a fresh accompaniment instead of losing its side,
    and the plan's total_cost/feasible are recomputed so the approve guard
    stops running on stale money numbers.
    """
    conn, _, plan_svc = svc()
    try:
        s = plan_svc._slot(slot_id)
        if s["status"] == "confirmed":
            raise HTTPException(400, "can't swap a meal that's already ordered")
        plan = conn.execute("SELECT user_id FROM plans WHERE id=?",
                            (s["plan_id"],)).fetchone()
        prof = _APPETITE_CACHE.get(plan["user_id"]) if plan else None
        mult = prof.base_multiplier if prof else 1.0
        catalog = _swap_catalog()
        if not catalog:
            raise HTTPException(503, "catalog unavailable — cannot validate swap")
        try:
            slot_row = apply_swap(conn, s, body.model_dump(), catalog, mult)
        except SwapError as e:
            raise HTTPException(400, str(e))
        return {"slot": slot_row}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        conn.close()


def _appetite_level_for_plan(conn, plan_id):
    """Best-effort appetite level for the plan's user (cache, else 'moderate')."""
    row = conn.execute("SELECT user_id FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        return "moderate"
    prof = _APPETITE_CACHE.get(row["user_id"])
    return prof.appetite_level if prof else "moderate"


def _why_fallback(s, appetite):
    """Deterministic one-liner when Gemini is unavailable (no key / error)."""
    name = s["dish_name"] or "This dish"
    rating = s["rating"] or 0
    return (f"{name} is a solid {s['meal_type']} pick at Rs {round(s['price'])} — "
            f"{rating}-star rated and sized for your {appetite} appetite.")


@app.get("/slot/{slot_id}/why")
def why(slot_id: int):
    """One short AI sentence on why this dish fits the plan. Cached in why_text;
    Gemini is called at most once per slot. Falls back deterministically."""
    conn, _, plan_svc = svc()
    try:
        s = plan_svc._slot(slot_id)
        if s["why_text"]:
            return {"slot_id": slot_id, "why": s["why_text"], "cached": True}
        appetite = _appetite_level_for_plan(conn, s["plan_id"])
        text = ""
        if gemini.has_key():
            system = ("You explain, in ONE friendly sentence of at most 25 words, "
                      "why a specific dish fits a user's monthly meal plan. "
                      "Mention value/rating. No preamble, just the sentence.")
            prompt = (f"Dish: {s['dish_name']}. Price: Rs {round(s['price'])}. "
                      f"Rating: {s['rating']} stars. Meal: {s['meal_type']}. "
                      f"User appetite level: {appetite}. "
                      f"Restaurant: {s['restaurant_name'] or 'a nearby spot'}. "
                      f"Write the one-sentence 'why this dish?' explanation.")
            text = gemini.chat(prompt, system=system)
        if not text:
            text = _why_fallback(s, appetite)
        conn.execute("UPDATE meal_slots SET why_text=? WHERE id=?", (text, slot_id))
        conn.commit()
        return {"slot_id": slot_id, "why": text, "cached": False}
    finally:
        conn.close()


def _merge_extracted(prior, parsed):
    """Merge a fresh ParsedIntake over prior extracted dict (later turn wins when set)."""
    merged = dict(prior or {})

    def put(k, v, empty=None):
        if v not in (None, empty):
            merged[k] = v

    put("budget", parsed.budget)
    if parsed.constraints:
        merged["constraints"] = parsed.constraints
    merged.setdefault("constraints", (prior or {}).get("constraints", []))
    if parsed.veg_only:
        merged["veg_only"] = True
    merged.setdefault("veg_only", bool((prior or {}).get("veg_only", False)))
    put("appetite_level", parsed.appetite_level)
    if parsed.days and parsed.days != 30:
        merged["days"] = parsed.days
    merged.setdefault("days", (prior or {}).get("days", 30))
    return merged


@app.post("/chat")
def chat(body: ChatIn):
    """Conversational blueprint builder. One LLM call per turn: it extracts fields
    into a compact blueprint, asks for the next missing/nice-to-have thing, and flags
    when there's enough to generate a plan. The LLM never builds the plan itself.

    Token-frugal: the client echoes `blueprint` back each turn (the memory), so we
    don't resend the whole transcript — only the state + last few messages.
    Backwards-compatible: also accepts legacy session_state.extracted as the seed.
    """
    prev = body.blueprint or (body.session_state or {}).get("extracted", {})
    bp, reply, ready = blueprint_chat.turn(prev, body.message, body.history)
    pub = blueprint_chat.public_blueprint(bp)
    return {
        "reply": reply,
        "ready": ready,                       # True -> show overview + Generate Plan
        "action": "ready_to_plan" if ready else "need_more",
        "blueprint": bp,                      # echo full state (incl _asked flags) back
        "extracted": {                        # legacy shape for older callers
            "budget": pub.get("budget"),
            "constraints": pub.get("constraints", []),
            "veg_only": bool(pub.get("veg_only", False)),
            "appetite_level": pub.get("appetite_level"),
            "days": pub.get("days", 30),
        },
    }


@app.post("/chat/adjust")
def chat_adjust(body: AdjustIn):
    """Apply a natural-language tweak to an existing blueprint ('make it cheaper',
    'less paneer', 'add south indian'). Returns the updated blueprint + a short
    confirmation. The frontend then re-calls /plan to rebuild deterministically."""
    bp, reply = blueprint_chat.adjust(body.blueprint, body.message)
    return {"reply": reply, "blueprint": bp,
            "public": blueprint_chat.public_blueprint(bp)}


def _chat_reply(action, extracted, missing):
    """Phrase the assistant reply. Uses Gemini if available, else deterministic."""
    budget = extracted.get("budget")
    appetite = extracted.get("appetite_level")
    cons = extracted.get("constraints", [])
    veg = extracted.get("veg_only")
    # Pairing constraints (empty dish_tag) have nothing user-readable to show
    # here; only the named must-have dishes make sense in a sentence.
    cons_txt = ", ".join(
        f"{c['min_count']} {c['dish_tag']}"
        for c in blueprint_chat._normalize_constraints(cons)
        if c.get("dish_tag")) or "no specific"

    if gemini.has_key():
        system = ("You are a friendly budget meal-planning assistant. Reply in ONE or two "
                  "short sentences. Do NOT invent a meal plan or dish list. If action is "
                  "ready_to_plan, warmly confirm the details and say you're building the "
                  "month plan now. If need_more, conversationally ask ONLY for the missing "
                  "fields. Use 'Rs' not the rupee symbol.")
        prompt = (f"action={action}. Known so far -> budget: {budget}, "
                  f"appetite: {appetite}, constraints: {cons_txt}, "
                  f"veg_only: {veg}. Missing fields: {missing or 'none'}. "
                  f"Write the reply.")
        text = gemini.chat(prompt, system=system)
        if text:
            return text

    if action == "ready_to_plan":
        bits = [f"Rs {int(budget)}", f"{appetite} appetite"]
        if cons:
            bits.append(f"{cons_txt} meals")
        if veg:
            bits.append("veg only")
        return "Got it — " + ", ".join(bits) + ". Building your month plan now..."
    # need_more
    asks = {
        "budget": "what's your monthly food budget?",
        "appetite_level": "how big is your appetite — light, moderate, heavy, or very heavy?",
    }
    want = " and ".join(asks[m] for m in missing)
    return f"Happy to plan that! To get started, {want}"


@app.get("/wallet/{user_id}/{month}")
def wallet(user_id: int, month: str):
    conn, w, _ = svc()
    try:
        return w.get_summary(user_id, month)
    finally:
        conn.close()


@app.post("/wallet/{user_id}/{month}/close")
def close_month(user_id: int, month: str):
    conn, w, _ = svc()
    try:
        rolled = w.close_cycle(user_id, month)
        return {"rolled_over": rolled, "next_month_balance_added": rolled}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


# ================= daily personalization (docs/SPEC-daily-personalization.md) =================
import threading
from datetime import date as _date, datetime as _dt
import daily
import agent
from typing import Optional

# Canned Instamart rows for mock mode, so bundles + add-ons demo without a token.
_MOCK_IM = {q: [{"id": f"mock-{q}", "name": n, "price": p, "image_url": "", "rating": 4.3}]
            for q, n, p in (("curd", "Amul Masti Dahi 400g", 35), ("banana", "Robusta Banana 6pc", 42),
                            ("eggs", "Farm Eggs 6pc", 54), ("bread", "Brown Bread 400g", 45),
                            ("poha", "MTR Ready Poha", 60), ("fruit", "Seasonal Fruit Bowl", 79),
                            ("makhana", "Roasted Makhana 80g", 99), ("chaas", "Amul Chaas 200ml", 15),
                            ("sprouts", "Moong Sprouts 200g", 35), ("lassi", "Amul Lassi 200ml", 25),
                            ("milk", "Amul Taaza 500ml", 28), ("dates", "Medjoul Dates 200g", 149),
                            ("paneer", "Amul Paneer 200g", 90), ("tofu", "Tofu 200g", 85),
                            ("cucumber", "Fresh Cucumber 500g", 30),
                            ("roasted chana", "Roasted Chana 200g", 55))}


def _im_client():
    if not _live():
        return None
    from instamart import InstamartClient
    return InstamartClient(token=STATE["client"].token)


def _ensure_address():
    """Live calls need an addressId; until the browser posts one, use the first saved
    address (as CatalogFetcher/OrderExecutor do). Instamart returns nothing without it."""
    if _live() and not STATE["address_id"]:
        try:
            addrs = STATE["client"].call("get_addresses", {}).get("addresses") or []
            if addrs:
                STATE["address_id"] = str(addrs[0].get("id"))
        except Exception as e:  # noqa: BLE001
            print(f"[daily] could not resolve an address: {e}")


def _daily_deps():
    _ensure_address()
    im = _im_client()
    if im is None:
        im_fn = lambda q: _MOCK_IM.get((q or "").split(" ")[0], [])  # noqa: E731
    else:
        from instamart import search as _ims
        def im_fn(q):
            # cached per address+query: menus are rebuilt often and Instamart 429s fast
            k = (STATE["address_id"], q)
            hit = _IM_CACHE.get(k)
            if hit and _time.time() - hit[0] < CATALOG_TTL_S:
                return hit[1]
            rows = _ims(im, STATE["address_id"], q, limit=10)
            _IM_CACHE[k] = (_time.time(), rows)
            return rows
    return {"dishes_fn": lambda veg_only: get_catalog(veg_only), "im_fn": im_fn,
            "stock_fn": _stock if im is not None else None,
            "food_exec": _executor(), "im_client": im, "address_id": STATE["address_id"]}


_IM_CACHE = {}   # (address_id, query) -> (fetched_at, rows)


def _stock(item):
    """Is this exact menu item still orderable? True / False / None (unknown).

    Searches the dish by name and finds the same itemId; any failure or a miss is
    'unknown' so a flaky search can't trigger a rebuild.
    """
    try:
        resp = STATE["client"].call("search_menu", {"addressId": STATE["address_id"],
                                                    "query": item["name"]})
    except Exception:  # noqa: BLE001
        return None
    from catalog_fetcher import _iter_items
    for it in _iter_items(resp):
        if str(it.get("menu_item_id") or it.get("id")) == str(item["id"]):
            return str(it.get("inStock", 1)) not in ("0", "False", "false")
    return None


_CITIES = ("Bengaluru", "Bangalore", "Mumbai", "Delhi", "New Delhi", "Gurugram", "Gurgaon", "Noida",
           "Hyderabad", "Chennai", "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Chandigarh",
           "Indore", "Kochi", "Coimbatore", "Nagpur", "Surat", "Bhopal", "Visakhapatnam", "Goa",
           "Ghaziabad", "Faridabad", "Navi Mumbai", "Thane", "Mysuru", "Vadodara")


def _city_from_address():
    """Swiggy addresses carry no city field; find a known city in the active addressLine."""
    if not _live():
        return None
    try:
        addrs = STATE["client"].call("get_addresses", {}).get("addresses") or []
    except Exception:  # noqa: BLE001 — city only drives the soft weather signal
        return None
    a = next((x for x in addrs if str(x.get("id")) == str(STATE["address_id"])), addrs[0] if addrs else {})
    line = (a.get("addressLine") or "").lower()
    # longest first so "New Delhi" beats "Delhi" and "Navi Mumbai" beats "Mumbai"
    return next((c for c in sorted(_CITIES, key=len, reverse=True) if c.lower() in line), None)


def _daily(fn):
    """Run fn(conn, deps) with a connection; ValueError -> 400."""
    conn = get_conn()
    try:
        return fn(conn, _daily_deps())
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()


class DailyProfileIn(BaseModel):
    diet_type: Optional[str] = None
    weekday_overrides: Optional[dict] = None
    allergies: Optional[list] = None
    goal: Optional[str] = None
    slots: Optional[list] = None
    windows: Optional[dict] = None
    monthly_budget: Optional[float] = None
    city: Optional[str] = None
    mode: Optional[str] = None
    quiz_picks: list = []      # onboarding taste quiz -> +3 dish each


class FeedbackIn(BaseModel):
    card_id: int
    type: str                  # up|down|not_today|never|rating
    value: Optional[float] = None        # rating 1-5


class LogIn(BaseModel):
    slot: str
    kind: str = "home"         # elsewhere|home|skipped|chat
    text: str = ""


class MemoryEditIn(BaseModel):
    dimension: str
    key: str
    weight: Optional[float] = None
    delete: bool = False
    block: Optional[bool] = None


class AgentIn(BaseModel):
    message: str


@app.get("/daily/quiz")
def daily_quiz(diet: str = "veg"):
    return {"dishes": daily.quiz(diet)}


@app.post("/daily/nightly")
def daily_nightly():
    return {"users_built": run_nightly()}


@app.get("/daily/{user_id}/profile")
def daily_get_profile(user_id: int):
    return _daily(lambda c, d: {"profile": daily.get_profile(c, user_id)})


@app.post("/daily/{user_id}/profile")
def daily_save_profile(user_id: int, body: DailyProfileIn):
    def go(conn, deps):
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            raise ValueError("unknown user")
        data = body.model_dump(exclude={"quiz_picks"})
        if not data.get("city") and not (daily.get_profile(conn, user_id) or {}).get("city"):
            data["city"] = _city_from_address()
        p = daily.save_profile(conn, user_id, data)
        for name in body.quiz_picks[:10]:
            daily.record(conn, user_id, "quiz", "dish", str(name))
        pulled = daily.pull_history(conn, user_id, deps["im_client"], deps["address_id"])
        pulled += daily.pull_food_orders(conn, user_id, STATE["client"] if _live() else None, deps["address_id"])
        daily.write_memory_md(conn, user_id)
        # a profile change (weekday diet, allergies…) invalidates unordered menus from today
        # on; the live/dry-run switch alone changes no card, so it keeps them
        if set(body.model_dump(exclude_none=True)) - {"mode", "quiz_picks"} or body.quiz_picks:
            conn.execute("DELETE FROM daily_menu WHERE user_id=? AND date>=? AND id NOT IN ("
                         "SELECT c.menu_id FROM menu_card c JOIN order_record o ON o.card_id=c.id)",
                         (user_id, _date.today().isoformat()))
            conn.commit()
        return {"profile": p, "history_items": pulled}
    return _daily(go)


@app.get("/daily/{user_id}/today")
def daily_today(user_id: int, day: str = None):
    def go(conn, deps):
        d = _date.fromisoformat(day) if day else _date.today()
        v = daily.today(conn, user_id, d, _dt.now(), deps["dishes_fn"], deps["im_fn"],
                        deps["stock_fn"])
        if v is None:
            raise HTTPException(404, "no daily profile")
        return v
    return _daily(go)


@app.post("/daily/{user_id}/regenerate")
def daily_regenerate(user_id: int, slot: str = None):
    def go(conn, deps):
        daily.build_day(conn, user_id, _date.today(), deps["dishes_fn"], deps["im_fn"],
                        slots=[slot] if slot else None)
        return {"ok": True}
    return _daily(go)


@app.post("/daily/{user_id}/order/{card_id}")
def daily_order(user_id: int, card_id: int, preview: bool = False):
    return _daily(lambda c, d: daily.order(c, user_id, card_id, d["food_exec"], d["im_client"],
                                           d["address_id"], confirm=True, preview=preview))


@app.post("/daily/{user_id}/feedback")
def daily_feedback(user_id: int, body: FeedbackIn):
    def go(conn, deps):
        card = daily.get_card(conn, body.card_id)
        if not card or card["user_id"] != user_id:
            raise ValueError("no such card")
        t = body.type
        if t == "rating":
            if body.value is None or not 1 <= body.value <= 5:
                raise ValueError("rating must be 1-5")
            t = "up" if body.value >= 4 else "down" if body.value <= 2 else None
            if t is None:
                return {"ok": True}
        if t == "never":
            daily.record(conn, user_id, "never", "dish",
                         card["items"][0].get("canonical") or card["items"][0]["name"], body.card_id, value=0)
        elif t in ("up", "down", "not_today"):
            daily.record_card(conn, user_id, card, t, card["position"])
        else:
            raise ValueError("type must be up|down|not_today|never|rating")
        daily.write_memory_md(conn, user_id)
        return {"ok": True}
    return _daily(go)


@app.post("/daily/{user_id}/log")
def daily_log(user_id: int, body: LogIn):
    def go(conn, deps):
        if body.kind == "skipped":
            names = []
        elif body.text:
            names = daily.parse_food_text(body.text)
        else:
            names = ["home meal" if body.kind == "home" else "outside meal"]
        src = "chat_log" if body.kind == "chat" else "nudge"
        return daily.log_food(conn, user_id, _date.today(), body.slot, src, names)
    return _daily(go)


@app.get("/daily/{user_id}/quality")
def daily_quality(user_id: int):
    """Audit today's built plan against the Indian-meal rules (plan_quality.py)."""
    import plan_quality

    def go(conn, deps):
        v = daily.today(conn, user_id, _date.today(), _dt.now(), deps["dishes_fn"], deps["im_fn"])
        if v is None:
            raise HTTPException(404, "no daily profile")
        issues = plan_quality.check_day(conn, v)
        return {"ok": not issues, "issues": issues}
    return _daily(go)


@app.get("/daily/{user_id}/memory")
def daily_memory(user_id: int):
    return _daily(lambda c, d: daily.memory(c, user_id))


@app.post("/daily/{user_id}/memory")
def daily_memory_edit(user_id: int, body: MemoryEditIn):
    return _daily(lambda c, d: daily.edit_memory(c, user_id, body.dimension, body.key,
                                                 body.weight, body.delete, body.block))


@app.post("/daily/{user_id}/agent")
def daily_agent(user_id: int, body: AgentIn):
    return _daily(lambda c, d: agent.run(c, user_id, body.message, d))


@app.delete("/daily/{user_id}")
def daily_delete_account(user_id: int):
    """Account deletion: erases the user's profile, plans, feedback, orders and memory."""
    _daily(lambda c, d: daily.delete_user(c, user_id))
    return {"deleted": user_id}


def run_nightly():
    """Refresh token -> recompute weights -> memory MD -> tomorrow's menus."""
    import swiggy_auth
    if STATE["mode"] == "mcp" and swiggy_auth.refresh():
        _init_runtime()
    conn = get_conn()
    try:
        deps = _daily_deps()
        for r in conn.execute("SELECT user_id FROM user_profile").fetchall():
            daily.pull_food_orders(conn, r["user_id"], STATE["client"] if _live() else None, deps["address_id"])
        return daily.nightly(conn, deps["dishes_fn"], deps["im_fn"])
    finally:
        conn.close()


NIGHTLY_HOUR = int(os.environ.get("DAILY_NIGHTLY_HOUR", "2"))


def _scheduler():
    last = None
    while True:
        now = _dt.now()
        if now.hour == NIGHTLY_HOUR and last != now.date():
            last = now.date()
            try:
                print(f"[daily] nightly batch built {run_nightly()} users")
            except Exception as e:  # noqa: BLE001 — keep the scheduler alive
                print(f"[daily] nightly batch failed: {e}")
        _time.sleep(300)


if os.environ.get("DAILY_SCHEDULER", "1") == "1":
    threading.Thread(target=_scheduler, daemon=True, name="daily-nightly").start()


def _warm_catalog():
    # a cold live catalog is ~80s of search_menu calls; pay it at boot, not on first open
    _ensure_address()
    for veg in (True, False):
        try:
            get_catalog(veg)
        except Exception as e:  # noqa: BLE001 — a cold first request still works, just slower
            print(f"[daily] catalog warm-up failed: {e}")


if _live():
    threading.Thread(target=_warm_catalog, daemon=True, name="catalog-warm").start()
