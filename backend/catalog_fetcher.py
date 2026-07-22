"""Catalog Fetcher (Docs section 7). Bridges Swiggy MCP -> optimizer's Dish objects.

Demo: mode='mock' -> returns curated mock_catalog(), filtered by cuisine/veg/price.
Prototype: mode='mcp' -> calls the real Swiggy Food MCP (search_menu) and maps the
           verified response shape to Dish objects. MCP client injected (SwiggyMCPClient
           or MockMCPClient) so this stays testable.

Real-schema notes (mcp.swiggy.com/builders/docs/reference/food):
  - search_restaurants(addressId, query, offset) and search_menu(addressId, query,
    restaurantIdOfAddedItem, vegFilter, offset) are BOTH query-driven — there is no
    "list everything" call. So to build a month candidate pool we run a set of
    dish/cuisine queries (one per meal-type seed) and merge results.
  - Only restaurants with availabilityStatus == "OPEN" are usable.
  - Menu items carry customizations as EITHER 'variations' (legacy) or 'variantsV2'
    (current) — we keep whichever exists so the cart update later uses the same one.
  - Pagination via 'nextOffset' on the response.

The optimizer never imports this module's transport detail. It just eats a Dish list.
"""
from catalog import Dish, mock_catalog

MEAL_TYPES = ("breakfast", "lunch", "dinner")

# Query seeds per meal slot — drives the live search_menu fan-out to build a pool.
# Kept small (3 per slot) because each live Swiggy query is a sequential network
# round-trip; more seeds = slower first plan. Each query returns many dishes, so
# 3 well-chosen seeds already yield a rich pool.
SLOT_QUERIES = {
    "breakfast": ["dosa", "paratha", "poha"],
    "lunch": ["thali", "paneer", "biryani"],
    "dinner": ["roti", "curry", "paneer"],
}


class CatalogFetcher:
    def __init__(self, mode="mock", mcp_client=None, address_id=None):
        assert mode in ("mock", "mcp")
        if mode == "mcp" and mcp_client is None:
            raise ValueError("mcp mode needs mcp_client")
        self.mode = mode
        self.mcp = mcp_client
        self.address_id = address_id

    def fetch(self, area=None, cuisines=None, veg_only=False, max_price=None,
              address_id=None):
        addr = address_id or self.address_id
        dishes = self._mock_fetch() if self.mode == "mock" else self._mcp_fetch(addr, veg_only)
        if cuisines:
            cset = {c.lower() for c in cuisines}
            dishes = [d for d in dishes if d.cuisine.lower() in cset]
        if veg_only:
            dishes = [d for d in dishes if d.veg]
        if max_price is not None:
            dishes = [d for d in dishes if d.price <= max_price]
        return dishes

    def _mock_fetch(self):
        return mock_catalog()

    # ---- live Swiggy MCP path ----
    def _mcp_fetch(self, address_id, veg_only):
        """Fan out query-driven search_menu across meal-type seeds, merge to Dish pool.

        search_menu requires an addressId; resolve it from get_addresses if not given.
        """
        if not address_id:
            address_id = self._resolve_address()
        seen = {}
        errors = 0
        attempts = 0
        for meal_type, queries in SLOT_QUERIES.items():
            for q in queries:
                attempts += 1
                # A single slow/failed Swiggy query must NOT abort the whole plan.
                # Skip it and keep building the pool from the queries that work.
                try:
                    resp = self.mcp.call("search_menu", {
                        "addressId": address_id,
                        "query": q,
                        **({"vegFilter": 1} if veg_only else {}),
                    })
                except Exception as e:  # noqa: BLE001 — resilience over precision here
                    errors += 1
                    print(f"[catalog] search_menu '{q}' failed: {type(e).__name__}: {e}")
                    continue
                for item in _iter_items(resp):
                    dish = self._map_item(item, meal_type)
                    if dish and dish.dish_id not in seen:
                        seen[dish.dish_id] = dish
        if not seen:
            raise RuntimeError(
                f"Swiggy catalog fetch returned nothing "
                f"({errors}/{attempts} queries failed). Check token/network.")
        if errors:
            print(f"[catalog] built {len(seen)} dishes; {errors}/{attempts} queries failed")
        return list(seen.values())

    def _resolve_address(self):
        resp = self.mcp.call("get_addresses", {})
        addrs = resp.get("addresses") or resp.get("data") or []
        if not addrs:
            raise ValueError("no saved Swiggy addresses; add one in the Swiggy app")
        return str(addrs[0].get("id") or addrs[0].get("addressId"))

    def _map_item(self, item, meal_type):
        """Map a real search_menu item to a Dish. Skip out-of-stock items.

        Real Swiggy fields (verified live): name, price, isVeg, menu_item_id,
        inStock, restaurant_id, restaurant_name, rating (string), hasAddons.
        There is NO per-item category/mealType, so the meal_type is taken from
        the QUERY SEED that surfaced this item (breakfast/lunch/dinner bucket);
        a name that clearly reads as breakfast can override to breakfast.
        """
        try:
            if str(item.get("inStock", 1)) in ("0", "False", "false"):
                return None
            price = float(item.get("price") or item.get("finalPrice")
                          or item.get("final_price") or 0)
            if price <= 0:
                return None
            name = item.get("name", "Item")
            veg = _is_veg(item)
            rid = str(item.get("restaurant_id") or item.get("restaurantId") or "")
            rname = item.get("restaurant_name") or item.get("restaurantName") or "Unknown"
            image_url = (item.get("imageUrl") or item.get("image_url")
                         or item.get("imageId") or "")
            variants = _map_variants(item, price)
            # meal_type: query seed is the source of truth; only override to
            # breakfast when the name is unmistakably a breakfast dish.
            mt = meal_type
            if _looks_breakfast(name):
                mt = "breakfast"
            return Dish(
                dish_id=str(item.get("menu_item_id") or item.get("id")
                            or item.get("itemId") or f"{rid}:{name}"),
                name=name,
                restaurant_id=rid,
                restaurant_name=rname,
                meal_type=mt,
                price=price,
                rating=_to_float(item.get("rating"), 4.0),
                cuisine=(item.get("cuisine") or "north_indian").lower(),
                tags=tuple(_extract_tags(name, veg)),
                veg=veg,
                variants=variants,
                image_url=image_url,
            )
        except (ValueError, TypeError):
            return None


def _iter_items(resp):
    """Real search_menu wraps items under 'items'/'data'/'menu'. Be tolerant."""
    if isinstance(resp, dict):
        for key in ("items", "data", "menu", "results"):
            v = resp.get(key)
            if isinstance(v, list):
                return v
    if isinstance(resp, list):
        return resp
    return []


def _to_float(v, default):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _looks_breakfast(name):
    n = name.lower()
    return any(k in n for k in _BREAKFAST_KW)


def _is_veg(item):
    if "is_veg" in item:
        return bool(item["is_veg"])
    if "isVeg" in item:
        return bool(item["isVeg"])
    if "vegClassifier" in item:
        return str(item["vegClassifier"]).upper() == "VEG"
    return True


# ---- heuristics for mapping raw menu -> optimizer fields ----
_BREAKFAST_KW = ("dosa", "idli", "poha", "paratha", "upma", "vada", "bhurji", "omelette", "pancake")
_MEAT_KW = ("chicken", "mutton", "egg", "fish", "prawn")
_STAPLE_KW = ("paneer", "dal", "rajma", "chole", "biryani", "rice", "roti", "thali")


def _guess_meal_type(name, category):
    txt = f"{name} {category}".lower()
    if any(k in txt for k in _BREAKFAST_KW):
        return "breakfast"
    # default lunch/dinner split by category hint, else lunch
    if "dinner" in txt:
        return "dinner"
    return "lunch"


def _extract_tags(name, veg):
    n = name.lower()
    tags = [k for k in _STAPLE_KW if k in n]
    tags += [k for k in _MEAT_KW if k in n]
    tags.append("veg" if veg else "nonveg")
    return tags or (["veg"] if veg else ["nonveg"])


def _map_variants(item, base):
    """Normalize Swiggy variant formats -> {name: price}.

    Real items carry EITHER 'variations' (legacy) or 'variantsV2' (current). We
    collapse both to a simple {regular/half/large: price} map the optimizer/swap
    engine understand. The ORIGINAL raw variant object is stashed under key
    '_raw' so the cart-update step can echo back the exact format Swiggy expects.
    """
    variants = {"regular": base}
    raw = item.get("variantsV2") or item.get("variations") or item.get("variants")
    if raw:
        variants["_raw"] = raw
    # flatten common option lists to price points
    option_lists = []
    if isinstance(raw, dict):  # variantsV2 shape: {variantGroups:[{variations:[...]}]}
        for grp in raw.get("variantGroups", []) or []:
            option_lists.extend(grp.get("variations", []) or [])
    elif isinstance(raw, list):  # legacy 'variations' flat list
        option_lists = raw
    for v in option_lists:
        vn = (v.get("name") or "").lower()
        try:
            vp = float(v.get("price") or v.get("finalPrice") or base)
        except (ValueError, TypeError):
            continue
        if any(k in vn for k in ("large", "full", "jumbo")):
            variants["large"] = vp
        elif any(k in vn for k in ("half", "small", "mini", "regular")):
            variants.setdefault("half" if "half" in vn or "small" in vn else "regular", vp)
    return variants
