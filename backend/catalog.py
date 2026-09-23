"""Dish catalog types + mock data.

In demo, mock. In prototype, Catalog Fetcher fills these from Swiggy MCP
(search_restaurants, search_menu). Optimizer only sees Dish objects — it never
knows or cares whether they came from mock or live MCP. That decoupling is the point.
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Dish:
    dish_id: str
    name: str
    restaurant_id: str
    restaurant_name: str
    meal_type: str          # breakfast | lunch | dinner
    price: float            # base price (regular variant), INR
    rating: float           # 0-5
    cuisine: str            # north_indian, south_indian, chinese ...
    tags: tuple             # ("paneer","veg","spicy") -- lowercase keywords
    veg: bool
    variants: dict          # {"regular": price, "large": price} optional sizes
    image_url: str = ""     # Swiggy CDN imageUrl (real fetch); "" for mocks
    course: str = "complete"  # bread|staple|curry|complete|side — see course.py.
                              # Decides whether this dish can stand as a meal on
                              # its own, needs a bread/rice, or is only a side.
    dish_kind: str = "meal"   # meal|snack|sweet|beverage — see course.py.
                              # The CATEGORY axis the optimizer's meal-slot
                              # hard filter gates on: a gulab jamun is
                              # course=side AND kind=sweet, and only kind=meal
                              # dishes may headline a breakfast/lunch/dinner.
                              # Defaulted so existing positional constructions
                              # (tests, helpers) keep working unchanged.
    source: str = ""          # "" = restaurant (default); "instamart" = grocery
                              # item from Swiggy Instamart. Only pairing dishes
                              # carry this today — the mains filter never sees
                              # them — and it flows onto PlannedSlot
                              # side_source/side2_source for the UI + order flow.


def variant_price(dish: Dish, multiplier: float) -> tuple:
    """Pick size variant closest to portion multiplier. Returns (variant_name, price).

    multiplier <1.0 -> prefer smaller/regular. >=1.25 and 'large' exists -> large.
    If no large variant, caller plans an add-on; here we just scale price est.
    """
    variants = dict(dish.variants) if dish.variants else {"regular": dish.price}
    variants.pop("_raw", None)  # raw Swiggy variant blob is not a price point
    if not variants:
        variants = {"regular": dish.price}
    if multiplier >= 1.25 and "large" in variants:
        return "large", variants["large"]
    if multiplier <= 0.85 and "half" in variants:
        return "half", variants["half"]
    # no matching variant -> scale base price by multiplier (approx extra qty/side)
    base_name = "regular" if "regular" in variants else next(iter(variants))
    est = round(variants[base_name] * max(1.0, multiplier), 2)
    return base_name, est


# ---- mock catalog: realistic Indian dishes across meal slots + price bands ----
def mock_catalog():
    """Mock pool. Courses are classified from the names by course.classify, the
    same path the live Swiggy fetch uses — so mock and live behave identically
    and the pairing logic is exercised by tests."""
    from course import course_of, dish_kind_of
    def d(*a, **kw):
        dish = Dish(*a, **kw)
        # course AND kind both come from the same name rules the live fetch
        # uses — mock/live parity on both axes.
        return replace(dish, course=course_of(dish.name),
                       dish_kind=dish_kind_of(dish.name))
    img = "https://media-assets.swiggy.com/swiggy/image/upload/mock/{}.jpg".format
    return [
        # breakfast
        d("b1", "Masala Dosa", "r1", "Sri Udupi", "breakfast", 90, 4.4, "south_indian", ("dosa","veg"), True, {"regular":90,"large":130}, img("masala_dosa")),
        d("b2", "Poha Plate", "r2", "Local Tiffin", "breakfast", 60, 4.1, "north_indian", ("poha","veg"), True, {"regular":60}, img("poha")),
        d("b3", "Idli Vada Combo", "r1", "Sri Udupi", "breakfast", 80, 4.3, "south_indian", ("idli","veg"), True, {"regular":80,"large":110}, img("idli_vada")),
        d("b4", "Aloo Paratha (2)", "r3", "Punjabi Rasoi", "breakfast", 110, 4.5, "north_indian", ("paratha","veg"), True, {"regular":110,"large":150}, img("aloo_paratha")),
        d("b5", "Egg Bhurji Pav", "r4", "Cafe Bandra", "breakfast", 120, 4.2, "north_indian", ("egg","nonveg"), False, {"regular":120}, img("egg_bhurji")),
        # lunch
        d("l1", "Paneer Butter Masala Thali", "r3", "Punjabi Rasoi", "lunch", 220, 4.6, "north_indian", ("paneer","veg","thali"), True, {"regular":220,"large":300}, img("paneer_thali")),
        d("l2", "Veg Meals (Unlimited)", "r1", "Sri Udupi", "lunch", 150, 4.4, "south_indian", ("thali","veg"), True, {"regular":150}, img("veg_meals")),
        d("l3", "Chicken Biryani", "r5", "Paradise", "lunch", 260, 4.5, "hyderabadi", ("chicken","nonveg","biryani"), False, {"regular":260,"large":360}, img("chicken_biryani")),
        d("l4", "Paneer Tikka Bowl", "r6", "Bowl Co", "lunch", 180, 4.3, "north_indian", ("paneer","veg"), True, {"regular":180,"large":240}, img("paneer_tikka_bowl")),
        d("l5", "Rajma Chawal", "r2", "Local Tiffin", "lunch", 130, 4.2, "north_indian", ("rajma","veg"), True, {"regular":130}, img("rajma_chawal")),
        d("l6", "Dal Khichdi", "r2", "Local Tiffin", "lunch", 110, 4.0, "north_indian", ("dal","veg","light"), True, {"regular":110}, img("dal_khichdi")),
        # dinner
        d("d1", "Paneer Roti Combo", "r3", "Punjabi Rasoi", "dinner", 200, 4.5, "north_indian", ("paneer","veg"), True, {"regular":200,"large":270}, img("paneer_roti")),
        d("d2", "Veg Fried Rice", "r7", "Wok Express", "dinner", 160, 4.1, "chinese", ("rice","veg"), True, {"regular":160,"large":210}, img("veg_fried_rice")),
        d("d3", "Egg Curry Rice", "r4", "Cafe Bandra", "dinner", 170, 4.2, "north_indian", ("egg","nonveg"), False, {"regular":170}, img("egg_curry_rice")),
        d("d4", "Chicken Curry Roti", "r5", "Paradise", "dinner", 240, 4.4, "north_indian", ("chicken","nonveg"), False, {"regular":240,"large":320}, img("chicken_curry_roti")),
        d("d5", "Chole Bhature", "r3", "Punjabi Rasoi", "dinner", 140, 4.3, "north_indian", ("chole","veg"), True, {"regular":140}, img("chole_bhature")),
        d("d6", "Curd Rice", "r1", "Sri Udupi", "dinner", 100, 4.0, "south_indian", ("rice","veg","light"), True, {"regular":100}, img("curd_rice")),
        # curries (need a bread/rice) + the breads and staples that pair with
        # them — these exercise the composition path in optimizer.py.
        d("c1", "Paneer Butter Masala", "r3", "Punjabi Rasoi", "dinner", 210, 4.6, "north_indian", ("paneer","veg"), True, {"regular":210,"large":280}, img("pbm")),
        d("c2", "Dal Tadka", "r2", "Local Tiffin", "dinner", 120, 4.2, "north_indian", ("dal","veg"), True, {"regular":120}, img("dal_tadka")),
        d("c3", "Kadai Paneer", "r3", "Punjabi Rasoi", "lunch", 230, 4.5, "north_indian", ("paneer","veg"), True, {"regular":230}, img("kadai_paneer")),
        d("c4", "Butter Chicken", "r5", "Paradise", "dinner", 280, 4.6, "north_indian", ("chicken","nonveg"), False, {"regular":280,"large":380}, img("butter_chicken")),
        d("br1", "Tawa Roti", "r3", "Punjabi Rasoi", "dinner", 12, 4.1, "north_indian", ("roti","veg"), True, {"regular":12}, img("tawa_roti")),
        d("br2", "Butter Naan", "r3", "Punjabi Rasoi", "dinner", 45, 4.4, "north_indian", ("naan","veg"), True, {"regular":45}, img("butter_naan")),
        d("br3", "Tandoori Roti", "r5", "Paradise", "lunch", 18, 4.2, "north_indian", ("roti","veg"), True, {"regular":18}, img("tandoori_roti")),
        d("st1", "Jeera Rice", "r3", "Punjabi Rasoi", "dinner", 90, 4.3, "north_indian", ("rice","veg"), True, {"regular":90}, img("jeera_rice")),
        d("st2", "Steamed Rice", "r2", "Local Tiffin", "lunch", 60, 4.0, "north_indian", ("rice","veg"), True, {"regular":60}, img("steamed_rice")),
    ]
