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
import config  # noqa: F401 — loads .env before anything reads os.environ
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from db import init_db, get_conn
from wallet_service import WalletService
from appetite import build_profile, AppetiteProfile
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
        print(f"[auth] no live Swiggy client: {e}")
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
    if key not in _CATALOG_CACHE:
        # Pass the CURRENT address explicitly — the fetcher's own address_id
        # was baked in at construction and may predate the user's pick.
        _CATALOG_CACHE[key] = STATE["fetcher"].fetch(
            address_id=STATE["address_id"],
            veg_only=veg_only, high_protein=high_protein)
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
                                                  _executor())


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
        raise HTTPException(502, f"Swiggy address lookup failed: {e}")
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
        constraints = [Constraint(c["dish_tag"], c["min_count"])
                       for c in blueprint_chat._normalize_constraints(body.constraints)]
        catalog = get_catalog(body.veg_only, body.high_protein)
        result = optimize(catalog, prof,
                          body.budget, days=body.days, constraints=constraints,
                          veg_only=body.veg_only, meals=body.meals)
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
            raise HTTPException(503, f"Database busy — please retry: {e}")
        print(f"[plan] DB error: {e}\n{_tb.format_exc()}")
        raise HTTPException(500, f"Database error: {e}")
    except RuntimeError as e:
        # catalog empty (live mode token/network failure) — actionable 502
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
        raise HTTPException(500, f"{type(e).__name__}: {e}")
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
    )


@app.get("/plan/{plan_id}")
def get_plan(plan_id: int):
    conn, _, plan_svc = svc()
    try:
        plan, slots = plan_svc.get_plan(plan_id)
    finally:
        conn.close()
    if not plan:
        raise HTTPException(404, "plan not found")
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
    cons_txt = ", ".join(
        f"{c['min_count']} {c['dish_tag']}"
        for c in blueprint_chat._normalize_constraints(cons)) or "no specific"

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
