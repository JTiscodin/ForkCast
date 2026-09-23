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
import os

from catalog import Dish, mock_catalog
from course import course_of, classify_unknown, kind_unknown

MEAL_TYPES = ("breakfast", "lunch", "dinner")

# Ask Gemini to classify dish names the keyword+fuzzy rules couldn't read.
# One call per unseen dish_id, cached for the process lifetime — so it costs a
# few dozen calls when a new catalog is first fetched, then nothing. Off by
# default so a missing GEMINI_API_KEY never changes planning behaviour; the
# rules alone already handle the overwhelming majority of names.
COURSE_LLM_FALLBACK = os.environ.get("COURSE_LLM_FALLBACK", "0") == "1"

# Use get_restaurant_menu descriptions to settle dishes the name alone can't
# classify. Costs a few extra MCP calls (~0.7s each), bounded by the two limits
# below, so it stays well inside a normal plan build.
DESCRIPTION_ENRICH = os.environ.get("DESCRIPTION_ENRICH", "1") == "1"
DESCRIPTION_MAX_RESTAURANTS = int(os.environ.get("DESCRIPTION_MAX_RESTAURANTS", "3"))
DESCRIPTION_PAGES = int(os.environ.get("DESCRIPTION_PAGES", "1"))

# How many search_menu pages to pull per meal-seed query. The first page alone
# left the optimizer staring at ~5 dishes per meal and recycling them across
# 30 days; a second page (following the response's nextOffset) roughly doubles
# the pool for one extra ~0.7s round-trip per query.
SEARCH_PAGES = int(os.environ.get("SEARCH_PAGES", "2"))

# Query seeds per meal slot — drives the live search_menu fan-out to build a pool.
# The pool used to be too small to plan a month without repeats: 3 seeds per slot,
# one page each, left the optimizer ~5 dishes per meal. More seeds plus a second
# page (SEARCH_PAGES) widen the pool enough that the optimizer can rotate a whole
# month of meals without cycling. The cost is linear: every extra seed or page is
# one sequential ~0.7s network round-trip to Swiggy, so a bigger pool means a
# slower first plan build.
#
# NOTE on desserts: no seed names a sweet on purpose. Sweets arrive as
# COLLATERAL of the broad seeds ("thali"/"combo" menus are the highest-density
# sources of dessert items). They are not deleted from the pool — the
# optimizer's dish_kind hard filter neutralizes them for meal slots, and they
# remain available for snack-slot use.
SLOT_QUERIES = {
    "breakfast": ["dosa", "paratha", "poha", "idli", "upma", "sandwich"],
    "lunch": ["thali", "paneer", "biryani", "rajma chawal", "chole"],
    # "roti" as a dinner seed pulled in bare ₹10 breads that the optimizer then
    # planned as whole dinners. Seed with real dinner dishes instead; breads are
    # fetched separately below, purely as pairing stock.
    "dinner": ["dal", "curry", "paneer", "kadai", "combo"],
}

# Non-veg seeds, added on top of the above when the user has NOT asked for
# veg-only. Every seed in SLOT_QUERIES names a vegetarian dish (dosa, paneer,
# dal, ...), so a catalog built from those alone was 100% vegetarian - and a
# user asking for a high-protein non-veg plan got 30 days of poha and dal,
# because the optimizer can only choose from what was fetched. Diet preference
# has to steer the SEARCH, not just filter the results.
NONVEG_QUERIES = {
    "breakfast": ["egg", "omelette", "egg roll"],
    "lunch": ["chicken", "chicken biryani", "fish", "mutton biryani"],
    "dinner": ["chicken curry", "mutton", "egg curry", "fish curry"],
}

# High-protein seeds, layered in when the user mentions protein. Kept separate
# so a plain non-veg request doesn't drag in protein-bowl noise.
PROTEIN_QUERIES = {
    "veg": ["paneer tikka", "soya chaap", "rajma", "chole"],
    "nonveg": ["grilled chicken", "chicken tikka", "egg bhurji"],
}

# Accompaniment stock — breads and rice fetched so curries have something to be
# paired WITH. These are never planned as a meal on their own (course.py rules);
# they only ever attach to a curry. Kept separate from SLOT_QUERIES so the meal
# seeds stay focused on things that can actually headline a meal.
ACCOMPANIMENT_QUERIES = ["roti", "naan", "rice"]


class CatalogFetcher:
    def __init__(self, mode="mock", mcp_client=None, address_id=None):
        assert mode in ("mock", "mcp")
        if mode == "mcp" and mcp_client is None:
            raise ValueError("mcp mode needs mcp_client")
        self.mode = mode
        self.mcp = mcp_client
        self.address_id = address_id

    def fetch(self, area=None, cuisines=None, veg_only=False, max_price=None,
              address_id=None, high_protein=False):
        addr = address_id or self.address_id
        dishes = (self._mock_fetch() if self.mode == "mock"
                  else self._mcp_fetch(addr, veg_only, high_protein))
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
    def _mcp_fetch(self, address_id, veg_only, high_protein=False):
        """Fan out query-driven search_menu across meal-type seeds, merge to Dish pool.

        search_menu requires an addressId; resolve it from get_addresses if not given.

        The seed set depends on DIET: the base seeds are all vegetarian dishes,
        so a non-veg user needs chicken/egg/fish seeds added or the pool they
        get to choose from contains no non-veg food at all.
        """
        if not address_id:
            address_id = self._resolve_address()
        seen = {}
        errors = 0
        attempts = 0

        # Build the seed set for this user's diet before fetching anything.
        seeds = {m: list(q) for m, q in SLOT_QUERIES.items()}
        if not veg_only:
            for m, extra in NONVEG_QUERIES.items():
                seeds.setdefault(m, []).extend(extra)
        if high_protein:
            bucket = PROTEIN_QUERIES["veg" if veg_only else "nonveg"]
            # Spread protein seeds across lunch and dinner, where they belong.
            seeds.setdefault("lunch", []).extend(bucket[:2])
            seeds.setdefault("dinner", []).extend(bucket[2:] or bucket[:1])

        for meal_type, queries in seeds.items():
            for q in queries:
                attempts += 1
                items = self._search(address_id, q, veg_only, pages=SEARCH_PAGES)
                if not items:
                    # Every page of this query failed — count it, then keep
                    # building the pool from the queries that work.
                    errors += 1
                    continue
                for item in items:
                    dish = self._map_item(item, meal_type)
                    if dish and dish.dish_id not in seen:
                        seen[dish.dish_id] = dish

        # Accompaniment pass: breads/rice for pairing with curries. Tagged
        # meal_type "dinner" only as a placeholder — the optimizer selects
        # accompaniments by COURSE, never by meal_type, so this doesn't make
        # them eligible as dinners. One page is plenty of bread stock.
        for q in ACCOMPANIMENT_QUERIES:
            attempts += 1
            items = self._search(address_id, q, veg_only, pages=1)
            if not items:
                errors += 1
                continue
            for item in items:
                dish = self._map_item(item, "dinner")
                if dish and dish.dish_id not in seen:
                    seen[dish.dish_id] = dish

        # Description pass: search_menu returns no description, but
        # get_restaurant_menu does (100% coverage observed) and it is often far
        # more legible than a branded name - "Raj Kachori" arrives as "Crispy
        # Kachori Filled with Potatoes, Moong Dal, Yogurt". We only fetch menus
        # for dishes the NAME could not classify confidently, so this costs a
        # couple of extra calls rather than a full menu crawl per restaurant.
        if DESCRIPTION_ENRICH:
            self._enrich_uncertain(seen, address_id)

        if not seen:
            raise RuntimeError(
                f"Swiggy catalog fetch returned nothing "
                f"({errors}/{attempts} queries failed). Check token/network.")
        if errors:
            print(f"[catalog] built {len(seen)} dishes; {errors}/{attempts} queries failed")
        return list(seen.values())

    def _search(self, address_id, query, veg_only, pages):
        """Run one search_menu query, following nextOffset for up to `pages` calls.

        Returns the merged list of raw items. A single slow/failed Swiggy call
        must NOT abort the whole plan: each page is wrapped in its own
        try/except, so a failed page keeps whatever items earlier pages already
        collected and simply stops paginating.
        """
        items = []
        offset = None
        for _ in range(max(1, pages)):
            args = {"addressId": address_id, "query": query}
            if veg_only:
                args["vegFilter"] = 1
            if offset is not None:
                args["offset"] = offset
            try:
                resp = self.mcp.call("search_menu", args)
            except Exception as e:  # noqa: BLE001 — resilience over precision here
                # A dead JWT is NOT a per-query failure to swallow — every
                # query will 401 the same way, and the user should be prompted
                # to re-login, not shown "catalog fetch returned nothing".
                # Duck-typed so the injected client stays swappable.
                if getattr(e, "expired", False):
                    raise
                print(f"[catalog] search_menu '{query}' failed: {type(e).__name__}: {e}")
                break
            items.extend(_iter_items(resp))
            next_offset = resp.get("nextOffset") if isinstance(resp, dict) else None
            if next_offset is None or next_offset == offset:
                break
            offset = next_offset
        return items

    def _enrich_uncertain(self, seen, address_id):
        """Re-classify low-confidence dishes using their menu description.

        Only restaurants that actually own an uncertain dish are fetched, and
        only the first page or two of each - a full menu is ~15 pages, which is
        far too slow to do for every restaurant on every plan.
        """
        from dataclasses import replace
        from course import classify, classify_with_description

        uncertain = {}
        for dish in seen.values():
            # Gate on COURSE confidence only. A dish whose name-pass KIND is
            # uncertain but whose course is confident (form/keyword) could in
            # principle also get a description look — but that would widen the
            # set of restaurants fetched and grow MCP cost, so the gate stays
            # as-is by design. Kind-only uncertainty is cheap to live with:
            # the worst case is a sweet treated as a meal-kind dish, which the
            # course=side gate already blocks from meal slots in most cases.
            if classify(dish.name).confidence in ("default", "keyword"):
                uncertain.setdefault(dish.restaurant_id, []).append(dish)
        if not uncertain:
            return

        # Bound the work: the busiest few restaurants cover most of the pool.
        targets = sorted(uncertain.items(), key=lambda kv: -len(kv[1]))
        targets = targets[:DESCRIPTION_MAX_RESTAURANTS]

        changed = 0
        for rid, dishes in targets:
            descs = self._fetch_descriptions(rid, address_id)
            if not descs:
                continue
            for dish in dishes:
                desc = descs.get(dish.name.strip().lower())
                if not desc:
                    continue
                info = classify_with_description(dish.name, desc)
                if info.course != dish.course:
                    # Take the refined KIND along with the course — the two
                    # axes are resolved together, so they move together.
                    seen[dish.dish_id] = replace(
                        dish, course=info.course, dish_kind=info.dish_kind)
                    changed += 1
                elif info.dish_kind != dish.dish_kind:
                    # Course unchanged but the description settled the kind
                    # (e.g. a default-COMPLETE dessert whose blurb says
                    # "sweet"). Kind-only refinement still matters: it is what
                    # keeps sweets out of meal slots downstream.
                    seen[dish.dish_id] = replace(dish, dish_kind=info.dish_kind)
                    changed += 1
        if changed:
            print(f"[catalog] descriptions re-classified {changed} dish(es)")

    def _fetch_descriptions(self, restaurant_id, address_id):
        """{lowercased dish name: description} for one restaurant, first pages."""
        out = {}
        for page in range(1, DESCRIPTION_PAGES + 1):
            try:
                resp = self.mcp.call("get_restaurant_menu", {
                    "restaurantId": restaurant_id,
                    "addressId": address_id,
                    "page": page,
                })
            except Exception as e:  # noqa: BLE001 - enrichment is best-effort
                print(f"[catalog] menu fetch {restaurant_id} p{page} failed: {e}")
                break
            for cat in (resp.get("categories") or []):
                for item in (cat.get("items") or []):
                    desc = item.get("description")
                    if desc:
                        out[str(item.get("name", "")).strip().lower()] = desc
            if not resp.get("hasMore"):
                break
        return out

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
            # Course decides whether this can BE a meal or only accompany one.
            # Without it a ₹10 "Tawa Roti" surfaced by the dinner seed scored
            # better than any real dish and filled the plan with bare bread.
            #
            # classify_unknown falls back to one cached Gemini call for names
            # the rules genuinely can't read — branded strings like "Samosa
            # Party Bucket - Mini Dal Kachori" are exactly what keyword rules
            # are bad at. Cached by dish_id, so it is a handful of calls when a
            # catalog is first seen and zero thereafter.
            dish_id = str(item.get("menu_item_id") or item.get("id") or name)
            dish_course = classify_unknown(
                dish_id, name, use_llm=COURSE_LLM_FALLBACK)
            # The KIND axis rides the same cache entry — one Gemini call
            # resolves both, so this is a pure lookup, never a second call.
            dish_kind = kind_unknown(
                dish_id, name, use_llm=COURSE_LLM_FALLBACK)
            dish = Dish(
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
                course=dish_course,
                dish_kind=dish_kind,
            )
            # Enrich with food knowledge metadata if available.
            _enrich_from_knowledge(dish)
            return dish
        except (ValueError, TypeError):
            return None


def _enrich_from_knowledge(dish):
    """Copy food-knowledge metadata onto a Dish when we know the item.

    Only fills fields that are currently unset (satiety default 0.5, etc.) —
    it never overrides the course/kind that classify_unknown already resolved.
    The critical field is main_meal_eligible: an item the knowledge base
    confirms is NOT a ground meal (a Chhena Toast) gets main_meal_eligible=False
    so the optimizer's mains gate blocks it even if course.py said COMPLETE.
    """
    try:
        from food_classifier import enrich_dish
        info = enrich_dish(dish)
        if info.source == "food_knowledge":
            dish.course = info.course
            dish.dish_kind = info.dish_kind
        dish.satiety = info.satiety
        dish.serving_unit = info.serving_unit
        dish.main_meal_eligible = info.main_meal_eligible
    except Exception:  # noqa: BLE001 — enrichment is best-effort, never fatal
        pass


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


_MEAT_NAME_KW = ("chicken", "mutton", "murg", "lamb", "keema", "kheema", "fish",
                 "prawn", "shrimp", "crab", "egg", "anda", "omelette", "bacon",
                 "ham", "meat", "beef", "pork", "kodi", "tangdi", "seekh")


def _is_veg(item):
    """Whether a menu item is vegetarian.

    Swiggy sends isVeg=True for vegetarian items and **omits it (None) for
    non-veg** — it is not a true boolean. Defaulting a missing value to True
    marked every chicken dish vegetarian, so a user asking for a non-veg plan
    got a 100% vegetarian catalog and the veg% stat read 92% on a plan full of
    chicken searches. When the flag is absent, fall back to the dish name.
    """
    for key in ("is_veg", "isVeg"):
        if item.get(key) is not None:
            return bool(item[key])
    if item.get("vegClassifier") is not None:
        return str(item["vegClassifier"]).upper() == "VEG"
    name = str(item.get("name", "")).lower()
    return not any(kw in name for kw in _MEAT_NAME_KW)


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
