"""Swiggy Instamart MCP client — grocery/quick-commerce, endpoint /im.

Same OAuth token as the Food server (one token, all Swiggy MCP servers —
verified against mcp.swiggy.com/builders/docs: user-level access, scope
mcp:tools). Shares the JSON-RPC/_rpc plumbing from swiggy_mcp.SwiggyMCPClient
by subclassing and only overriding the endpoint URL, so auth, expiry
detection, retries and SSE parsing stay identical.

Tools on the Instamart server (from a live tools/list):
  get_addresses, create_address, delete_address, search_products,
  your_go_to_items, get_cart, update_cart, clear_cart, checkout,
  get_orders, track_order, get_delivery_status, report_error,
  get_payment_options, check_payment_status, confirm_order

Why this module exists: the meal planner orders RESTAURANT meals, but a
month-long plan also needs staples (milk, curd, eggs, fruit, atta) that
restaurants sell at a markup or not at all. Instamart covers those at
grocery prices. Only SEARCH is wired for now — update_cart/checkout touch
real money and stay unwired until deliberately enabled.
"""
from swiggy_mcp import SwiggyMCPClient, SwiggyMCPError, SWIGGY_MCP_URL
import os

INSTAMART_URL = os.environ.get("SWIGGY_IM_MCP_URL", "https://mcp.swiggy.com/im")


class InstamartClient(SwiggyMCPClient):
    """Food-client RPC machinery pointed at the Instamart server."""

    def __init__(self, token=None, timeout=12):
        # Skip the parent __init__ (it validates SWIGGY_MCP_TOKEN against the
        # FOOD url env var name) but keep its expiry pre-check — an expired JWT
        # must fail fast here too, not on the first search deep in a plan.
        self.url = INSTAMART_URL
        self.token = token or os.environ.get("SWIGGY_MCP_TOKEN")
        if not self.token:
            raise SwiggyMCPError(
                "No OAuth token. Link Swiggy account and set SWIGGY_MCP_TOKEN.")
        from swiggy_mcp import token_expired
        if token_expired(self.token):
            raise SwiggyMCPError("JWT has expired", expired=True)
        self._id = 0
        self.timeout = timeout

    # ---- thin typed wrappers ----
    def search_products(self, address_id, query, offset=0):
        return self.call("search_products",
                         {"addressId": address_id, "query": query,
                          "offset": offset})

    def get_cart(self):
        return self.call("get_cart", {})

    def update_cart(self, address_id, cart_items, clear_first=True):
        """cart_items: [{"spinId"|"productId":..., "quantity": n, ...}]"""
        args = {"addressId": address_id, "cartItems": cart_items}
        if clear_first:
            args["clearExistingCart"] = True
        return self.call("update_cart", args)

    def checkout(self, address_id):
        return self.call("checkout", {"addressId": address_id})


# ---- catalog-facing normalization -------------------------------------------
# One Instamart product has variations (250ml/500ml/1L). For planning we want
# ONE row per variation (each spinId is orderable) with a flat, Dish-like
# shape the rest of the code can consume without knowing Swiggy internals.

def normalize_products(raw, limit=40):
    """Flatten search_products output -> [{...}] with stable keys.

    Keeps the first in-stock variation of each product (the cheapest orderable
    unit is enough for price-aware planning; deep variation lists are noise
    for a budget view) and maps to the field names the frontend already
    understands from the food catalog.
    """
    products = raw.get("products", []) if isinstance(raw, dict) else []
    out = []
    for p in products[:limit]:
        if not isinstance(p, dict):
            continue
        # pick the cheapest IN-STOCK variation; grocery items go out of stock
        # constantly and a dead spinId in a plan is worse than no entry
        vars_ = [v for v in p.get("variations", [])
                 if isinstance(v, dict) and v.get("isInStockAndAvailable")]
        if not vars_:
            continue
        v = min(vars_, key=lambda v: (v.get("price") or {}).get("offerPrice")
                or 999999)
        price = (v.get("price") or {}).get("offerPrice") or 0
        rating = (v.get("rating") or {}).get("value")
        out.append({
            "id": v.get("spinId") or v.get("skuId"),
            "name": v.get("displayName") or p.get("displayName"),
            "brand": v.get("brandName") or p.get("brand"),
            "quantity": v.get("quantityDescription"),
            "price": price,
            "mrp": (v.get("price") or {}).get("mrp") or price,
            "rating": float(rating) if rating else None,
            "image_url": v.get("imageUrl") or p.get("imageUrl"),
            "in_stock": True,
            "product_id": p.get("productId"),
        })
    return out


def search(client, address_id, query, offset=0, limit=40):
    """Search + normalize in one call. Returns the flat list."""
    return normalize_products(
        client.search_products(address_id, query, offset=offset), limit=limit)


# ---- pairing-pool builder (optimizer PASS 4 input) --------------------------
# Kind -> grocery queries. Mirrors course.py's kind word tables: what a user
# calls a "drink" or "sweet" is what Instamart stocks it under. Queries are
# deliberately broad and grocery-priced (a Rs17 Amul Taaza vs a Rs80
# restaurant lassi); the optimizer's rating bar + rotation does the choosing.
KIND_QUERIES = {
    "beverage": ["milk", "lassi", "chaas", "juice", "cold drink"],
    "sweet": ["ice cream", "gulab jamun", "kheer", "sweets"],
    "snack": ["namkeen", "chips", "cookies"],
}

# Groceries can't be headlined as meals, so their Dish rows must never pass
# the optimizer's mains gate — kind != "meal" enforces that structurally.
# Name-classified kind wins; the query bucket is only the fallback for names
# the classifier can't read (its default is "meal", which must not survive).
_IM_KINDS = ("beverage", "sweet", "snack")


def pairing_pool(client, address_id, kinds, per_kind=6, per_query=12):
    """Build Dish candidates for the optimizer's PASS 4 pairing pools.

    Only the kinds the user actually asked for are fetched (a "beverages with
    lunch" plan shouldn't pay for sweet/snack searches). Each query's results
    are normalized, mapped to Dish(source="instamart"), deduped by dish_id,
    and returned flat — the optimizer's kind filter does the bucketing.

    Failures are swallowed per-query (returns what it got): an Instamart
    outage must degrade to restaurant-only pairings, not kill the plan.
    """
    from catalog import Dish
    from course import classify

    out, seen = [], set()
    wanted = [k for k in kinds if k in _IM_KINDS]
    for kind in wanted:
        added_this_kind = 0
        for q in KIND_QUERIES.get(kind, []):
            if added_this_kind >= per_kind:
                break
            try:
                rows = search(client, address_id, q, limit=per_query)
            except Exception as e:  # noqa: BLE001 - degrade, don't fail the plan
                print(f"[instamart] pairing query '{q}' failed: {e}")
                continue
            for r in rows:
                if added_this_kind >= per_kind:
                    break
                did = f"im:{r['id']}"          # prefix: never collide with
                if did in seen:                # restaurant dish_ids in dish_by_id
                    continue
                if not r["price"] or r["price"] <= 0:
                    continue
                seen.add(did)
                # Classify the NAME for kind (a "milk" query still surfaces
                # cookies on promo); the query bucket is only the fallback —
                # classify()'s default is "meal", which must never survive on
                # a grocery row or it would headline a meal slot.
                name = r["name"] or q
                ci = classify(name)
                dish_kind = ci.dish_kind if ci.dish_kind in _IM_KINDS else kind
                out.append(Dish(
                    dish_id=did,
                    name=name,
                    restaurant_id="instamart",
                    restaurant_name=r["brand"] or "Instamart",
                    # slot multipliers key on the SLOT's meal_type, not the
                    # candidate's; any valid value works here.
                    meal_type="dinner",
                    price=float(r["price"]),
                    # normalize_products leaves rating None when Swiggy has
                    # none — default like the food fetcher does (4.0), so the
                    # >= 3.5 bar doesn't TypeError on None.
                    rating=float(r["rating"] or 4.0),
                    cuisine="grocery",
                    tags=(kind,),
                    # Instamart vegClassifier is unreliable (observed
                    # VEG_CLASSIFIER_INVALID on plain milk); default veg for
                    # the dairy/drink/sweet queries we run — a wrong guess on
                    # a beverage pairing is the lesser evil vs veg_only
                    # users losing grocery pairings entirely.
                    veg=True,
                    variants={"regular": float(r["price"])},
                    image_url=r["image_url"] or "",
                    course=ci.course,
                    dish_kind=dish_kind,
                    source="instamart",
                ))
                added_this_kind += 1
    return out
