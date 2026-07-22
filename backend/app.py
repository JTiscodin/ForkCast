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
from pydantic import BaseModel

from db import init_db, get_conn
from wallet_service import WalletService
from appetite import build_profile, AppetiteProfile
from catalog_fetcher import CatalogFetcher
from optimizer import optimize, Constraint
from plan_service import PlanService
from order_executor import OrderExecutor
from swap_service import alternatives
from intake import parse_intake
import gemini

# ---- mode: 'mock' (demo) or 'mcp' (real Swiggy). Set SWIGGY_MODE=mcp + token. ----
MODE = os.environ.get("SWIGGY_MODE", "mock").lower()
ADDRESS_ID = os.environ.get("SWIGGY_ADDRESS_ID")  # optional; else get_addresses

_mcp_client = None
if MODE == "mcp":
    from swiggy_mcp import SwiggyMCPClient
    _mcp_client = SwiggyMCPClient()  # reads SWIGGY_MCP_TOKEN env

init_db()
app = FastAPI(title="Budget Meal Planner")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

fetcher = CatalogFetcher(mode=MODE, mcp_client=_mcp_client, address_id=ADDRESS_ID)
_APPETITE_CACHE = {}   # user_id -> AppetiteProfile (also persisted)

# Catalog is fetched lazily (live MCP fetch is slow — ~15 queries). Cached after
# first build so the server boots instantly and subsequent plans are fast.
_CATALOG_CACHE = {}    # cache_key -> [Dish]


def get_catalog(veg_only=False):
    key = ("veg" if veg_only else "all")
    if key not in _CATALOG_CACHE:
        _CATALOG_CACHE[key] = fetcher.fetch(veg_only=veg_only)
    return _CATALOG_CACHE[key]


def _executor():
    return OrderExecutor(mode=MODE, mcp_client=_mcp_client, address_id=ADDRESS_ID)


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


class RespondIn(BaseModel):
    answer: str
    new_day: int = None
    new_meal_type: str = None


class UserIn(BaseModel):
    name: str
    area: str = None


class ChatIn(BaseModel):
    user_id: int
    message: str
    session_state: dict = {}      # frontend echoes prior {extracted:{...}} back each turn


# ---------- endpoints ----------
@app.post("/user")
def create_user(body: UserIn):
    conn, w, _ = svc()
    uid = w.create_user(body.name, body.area)
    conn.close()
    return {"user_id": uid}


@app.get("/mode")
def get_mode():
    return {"mode": MODE, "live": MODE == "mcp"}


@app.get("/mcp/addresses")
def mcp_addresses():
    """Live only: list saved Swiggy addresses to pick an addressId for ordering."""
    if MODE != "mcp":
        raise HTTPException(400, "not in mcp mode")
    return _mcp_client.call("get_addresses", {})


@app.get("/mcp/tools")
def mcp_tools():
    """Live only: introspect the real Swiggy MCP tool list."""
    if MODE != "mcp":
        raise HTTPException(400, "not in mcp mode")
    return _mcp_client.list_tools()


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
    prof = build_profile(body.user_id, body.appetite_level,
                         body.roti_per_meal, body.rice_katori_per_meal)
    _APPETITE_CACHE[body.user_id] = prof
    return prof.to_row()


@app.post("/plan")
def make_plan(body: PlanIn):
    prof = _APPETITE_CACHE.get(body.user_id) or build_profile(body.user_id, "moderate")
    constraints = [Constraint(c["dish_tag"], c["min_count"]) for c in body.constraints]
    result = optimize(get_catalog(body.veg_only), prof, body.budget, days=body.days,
                      constraints=constraints, veg_only=body.veg_only)
    conn, _, plan_svc = svc()
    plan_id = plan_svc.save_plan(body.user_id, body.month, result)
    conn.close()
    return {
        "plan_id": plan_id,
        "feasible": result.feasible,
        "total_cost": result.total_cost,
        "budget": result.budget,
        "leftover": result.leftover,
        "constraint_status": result.constraint_status,
        "message": result.message,
    }


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
        return {"alternatives": alternatives(dict(s), get_catalog(veg_only), mult, band, veg_only)}
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
    """Thin conversational orchestration. Extracts fields (reusing parse_intake),
    merges across turns via session_state, and returns a structured next step.
    The LLM only extracts + phrases replies — it never invents a plan."""
    prior = (body.session_state or {}).get("extracted", {})
    parsed = parse_intake(body.message)
    extracted = _merge_extracted(prior, parsed)

    have_budget = extracted.get("budget") is not None
    have_appetite = extracted.get("appetite_level") is not None
    missing = []
    if not have_budget:
        missing.append("budget")
    if not have_appetite:
        missing.append("appetite_level")

    if have_budget and have_appetite:
        action = "ready_to_plan"
        reply = _chat_reply(action, extracted, missing)
    else:
        action = "need_more"
        reply = _chat_reply(action, extracted, missing)

    return {
        "reply": reply,
        "action": action,
        "extracted": {
            "budget": extracted.get("budget"),
            "constraints": extracted.get("constraints", []),
            "veg_only": bool(extracted.get("veg_only", False)),
            "appetite_level": extracted.get("appetite_level"),
            "days": extracted.get("days", 30),
        },
        "missing": missing,
    }


def _chat_reply(action, extracted, missing):
    """Phrase the assistant reply. Uses Gemini if available, else deterministic."""
    budget = extracted.get("budget")
    appetite = extracted.get("appetite_level")
    cons = extracted.get("constraints", [])
    veg = extracted.get("veg_only")
    cons_txt = ", ".join(f"{c['min_count']} {c['dish_tag']}" for c in cons) or "no specific"

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
