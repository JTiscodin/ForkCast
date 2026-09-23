"""Indian food knowledge base — curated ontology of named dishes and groceries.

WHY THIS EXISTS
---------------
course.py classifies ANY name string into a course + kind, but it has no
understanding of what a dish IS — its serving unit, satiety, meal
appropriateness, or dietary constraints. A "Chhena Toast" matches zero form
words, defaults to COMPLETE/meal, and gets planned as dinner. That's not a
course.py bug — course.py is a name matcher, not a food database.

This module IS the food database. For every named item we know, it records:
  - What KIND of food it is (meal, sweet, snack, beverage, condiment)
  - What COURSE it plays in a meal (from course.py's vocabulary)
  - Whether it can HEADLINE a meal slot (main_meal_eligible)
  - Serving unit and satiety, so the optimizer sizes portions realistically
  - Dietary flags and health tags, so hard filters work structurally

It does NOT replace course.py for classifying unknown items. It sits ABOVE
course.py: look up here first, fall through to course.py only when no entry
exists.

MODULARITY
----------
The catalog is split into named tuples at module level so the test file can
reference a few known entries by variable name (CHENNA_TOAST, BIRYANI, etc.)
without importing the entire KNOWN_ITEMS dict.
"""
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

# Course constants — mirror course.py so this module is self-contained.
BREAD = "bread"
STAPLE = "staple"
CURRY = "curry"
COMPLETE = "complete"
SIDE = "side"

# Kind constants
KIND_MEAL = "meal"
KIND_SNACK = "snack"
KIND_SWEET = "sweet"
KIND_BEVERAGE = "beverage"
KIND_CONDIMENT = "condiment"

# Spice levels
SPICE_MILD = "mild"
SPICE_MEDIUM = "medium"
SPICE_SPICY = "spicy"
SPICE_HOT = "hot"


@dataclass(frozen=True)
class FoodKnowledge:
    """Canonical food-item record. Immutable by design — never mutated at
    runtime; add new entries in the catalog below."""
    name: str                     # canonical (English) name
    aliases: tuple = ()           # known alternate names / spellings

    # Classification (course.py vocabulary + kind)
    dish_kind: str = KIND_MEAL    # meal|snack|sweet|beverage|condiment
    course: str = COMPLETE        # bread|staple|curry|complete|side

    # Cultural / regional
    cuisine: str = "north_indian"  # north_indian, south_indian, bengali, etc.

    # Meal role
    meal_roles: tuple = ("lunch", "dinner")  # which slots the item suits
    main_meal_eligible: bool = True           # can this headline a meal slot?
    pairing_roles: tuple = ("any",)           # after_meal, with_meal, any, none

    # Portion / satiety
    serving_unit: str = "plate"  # piece, plate, bowl, glass, katori
    typical_servings: tuple = (1, 1)  # (min, max) servings per person
    satiety: float = 0.5              # 0.0 (not filling) — 1.0 (very filling)

    # Dietary
    dietary_flags: tuple = ("veg",)   # veg, nonveg, eggetarian, jain, vegan
    health_tags: tuple = ()           # high_protein, low_calorie, diabetic_friendly, etc.
    spice_level: str = SPICE_MEDIUM   # mild, medium, spicy, hot

    # Human-readable
    description: str = ""


# ---------------------------------------------------------------------------
# Can be re-assigned from tests to override the catalog.
# ---------------------------------------------------------------------------
_KNOWN: dict[str, FoodKnowledge] = {}


def _register(item: FoodKnowledge) -> None:
    """Insert an item keyed by its canonical name + every alias."""
    keys = {item.name.lower()} | {a.lower() for a in item.aliases}
    for k in keys:
        _KNOWN[k] = item


# ===========================================================================
# CATALOG — Sweets & Mithai
# ===========================================================================

CHENNA_TOAST = FoodKnowledge(
    name="Chhena Toast",
    aliases=("chena toast", "chhena toast mithai"),
    dish_kind=KIND_SWEET,
    course=SIDE,
    cuisine="bengali",
    meal_roles=("dessert", "snack"),
    main_meal_eligible=False,
    pairing_roles=("after_meal",),
    serving_unit="piece",
    typical_servings=(1, 2),
    satiety=0.2,
    description="Soft chhena patties shallow-fried and soaked in sugar syrup",
)
_register(CHENNA_TOAST)

GULAB_JAMUN = FoodKnowledge(
    name="Gulab Jamun",
    aliases=("gulab jamun", "gulabjamun"),
    dish_kind=KIND_SWEET,
    course=SIDE,
    cuisine="north_indian",
    meal_roles=("dessert", "snack"),
    main_meal_eligible=False,
    pairing_roles=("after_meal",),
    serving_unit="piece",
    typical_servings=(2, 3),
    satiety=0.25,
    description="Deep-fried milk-solid balls soaked in rose-flavoured sugar syrup",
)
_register(GULAB_JAMUN)

RASGULLA = FoodKnowledge(
    name="Rasgulla",
    aliases=("rasgulla", "rosogolla", "rasogolla"),
    dish_kind=KIND_SWEET,
    course=SIDE,
    cuisine="bengali",
    meal_roles=("dessert", "snack"),
    main_meal_eligible=False,
    pairing_roles=("after_meal",),
    serving_unit="piece",
    typical_servings=(2, 4),
    satiety=0.2,
    description="Spongy chhena balls in light sugar syrup",
)
_register(RASGULLA)

RASMALAI = FoodKnowledge(
    name="Rasmalai",
    aliases=("ras malai", "rasmalai"),
    dish_kind=KIND_SWEET,
    course=SIDE,
    cuisine="bengali",
    meal_roles=("dessert", "snack"),
    main_meal_eligible=False,
    pairing_roles=("after_meal",),
    serving_unit="piece",
    typical_servings=(1, 2),
    satiety=0.3,
    description="Soft chhena patties in sweetened, saffron-infused milk",
)
_register(RASMALAI)

JALEBI = FoodKnowledge(
    name="Jalebi",
    aliases=("jalebi", "jilebi", "jilapi"),
    dish_kind=KIND_SWEET,
    course=SIDE,
    cuisine="north_indian",
    meal_roles=("dessert", "snack", "breakfast"),
    main_meal_eligible=False,
    pairing_roles=("after_meal",),
    serving_unit="piece",
    typical_servings=(2, 4),
    satiety=0.2,
    description="Crisp deep-fried batter spirals soaked in saffron sugar syrup",
)
_register(JALEBI)

LADDOO = FoodKnowledge(
    name="Laddoo",
    aliases=("laddoo", "laddu", "motichoor laddoo", "motichur laddoo",
             "besan laddoo", "boondi laddoo"),
    dish_kind=KIND_SWEET,
    course=SIDE,
    cuisine="north_indian",
    meal_roles=("dessert", "snack"),
    main_meal_eligible=False,
    pairing_roles=("after_meal",),
    serving_unit="piece",
    typical_servings=(1, 2),
    satiety=0.25,
    description="Round sweet balls made from gram flour, semolina, or ground coconut",
)
_register(LADDOO)

KHEER = FoodKnowledge(
    name="Kheer",
    aliases=("kheer", "payasam", "payesh"),
    dish_kind=KIND_SWEET,
    course=SIDE,
    cuisine="north_indian",
    meal_roles=("dessert", "snack"),
    main_meal_eligible=False,
    pairing_roles=("after_meal",),
    serving_unit="bowl",
    typical_servings=(1, 1),
    satiety=0.3,
    description="Rice pudding slow-cooked with milk, sugar, and cardamom",
)
_register(KHEER)

BARFI = FoodKnowledge(
    name="Barfi",
    aliases=("barfi", "burfi", "kaju katli", "kaju barfi", "pista barfi"),
    dish_kind=KIND_SWEET,
    course=SIDE,
    cuisine="north_indian",
    meal_roles=("dessert", "snack"),
    main_meal_eligible=False,
    pairing_roles=("after_meal",),
    serving_unit="piece",
    typical_servings=(1, 3),
    satiety=0.2,
    description="Dense milk-fudge sweet, often layered with nuts or silver leaf",
)
_register(BARFI)

JAMUN_SWEETS = [
    ("Kala Jamun", "kala jamun", 0.3),
    ("Shahi Tukda", ("shahi tukda", "shahi tukra", "double ka meetha"), 0.3),
    ("Phirni", ("phirni", "firni"), 0.25),
    ("Seviyan", ("seviyan", "sewaiyan", "vermicelli kheer"), 0.25),
    ("Malpua", ("malpua",), 0.3),
    ("Rabri", ("rabri", "rabdi"), 0.25),
    ("Basundi", ("basundi",), 0.3),
    ("Sandesh", ("sandesh", "sondesh"), 0.2),
    ("Modak", ("modak", "modakam"), 0.25),
    ("Sheera", ("sheera", "sooji halwa", "rava kesari"), 0.3),
    ("Halwa", ("halwa", "gajar halwa", "carrot halwa", "atta halwa",
               "sohan halwa"), 0.3),
    ("Mysore Pak", ("mysore pak", "mysorepak"), 0.3),
    ("Ghevar", ("ghevar", "ghivar"), 0.25),
    ("Shrikhand", ("shrikhand", "shrikhand"), 0.35),
    ("Kulfi", ("kulfi", "malai kulfi", "pista kulfi", "mango kulfi"), 0.3),
    ("Peda", ("peda", "pedha", "doodh peda"), 0.2),
    ("Chum Chum", ("chum chum", "chom chom", "cham cham"), 0.2),
    ("Sohan Papdi", ("sohan papdi", "soan papdi", "sohan papri"), 0.15),
    ("Puran Poli", ("puran poli", "holige", "obbattu"), 0.35),
    ("Kalakand", ("kalakand",), 0.25),
    ("Milk Cake", ("milk cake", "kalakand"), 0.25),
    ("Moong Dal Halwa", ("moong dal halwa", "moongdal halwa"), 0.35),
    ("Pinni", ("pinni",), 0.3),
    ("Panjiri", ("panjiri", "panjeeri"), 0.3),
    ("Chikki", ("chikki", "peanut chikki", "til chikki"), 0.2),
    ("Sweet Pongal", ("sweet pongal", "sakkarai pongal"), 0.35),
    ("Adhirasam", ("adhirasam", "athirasam"), 0.2),
]
for _name, _aliases, _sat in JAMUN_SWEETS:
    _register(FoodKnowledge(
        name=_name, aliases=_aliases,
        dish_kind=KIND_SWEET, course=SIDE, cuisine="north_indian",
        meal_roles=("dessert", "snack"), main_meal_eligible=False,
        pairing_roles=("after_meal",), serving_unit="piece",
        typical_servings=(1, 2), satiety=_sat,
    ))

# Explicit ice-cream / frozen dessert entries (the name "ice cream" already
# matches course.py's SIDE form, but the knowledge entry adds satiety & unit).
_register(FoodKnowledge(
    name="Ice Cream", aliases=("ice cream", "kulfi"),
    dish_kind=KIND_SWEET, course=SIDE, cuisine="north_indian",
    meal_roles=("dessert", "snack"), main_meal_eligible=False,
    pairing_roles=("after_meal",), serving_unit="scoop",
    typical_servings=(1, 3), satiety=0.2,
))
_register(FoodKnowledge(
    name="Brownie", aliases=("brownie", "chocolate brownie", "fudge brownie"),
    dish_kind=KIND_SWEET, course=SIDE, cuisine="continental",
    meal_roles=("dessert", "snack"), main_meal_eligible=False,
    pairing_roles=("after_meal",), serving_unit="piece",
    typical_servings=(1, 1), satiety=0.25,
))
_register(FoodKnowledge(
    name="Pastry", aliases=("pastry", "pastries", "cake slice",
                           "black forest", "pineapple pastry"),
    dish_kind=KIND_SWEET, course=SIDE, cuisine="continental",
    meal_roles=("dessert", "snack"), main_meal_eligible=False,
    pairing_roles=("after_meal",), serving_unit="piece",
    typical_servings=(1, 1), satiety=0.25,
))
_register(FoodKnowledge(
    name="Cheesecake", aliases=("cheesecake",),
    dish_kind=KIND_SWEET, course=SIDE, cuisine="continental",
    meal_roles=("dessert", "snack"), main_meal_eligible=False,
    pairing_roles=("after_meal",), serving_unit="slice",
    typical_servings=(1, 1), satiety=0.3,
))
_register(FoodKnowledge(
    name="Custard", aliases=("custard", "fruit custard"),
    dish_kind=KIND_SWEET, course=SIDE, cuisine="continental",
    meal_roles=("dessert",), main_meal_eligible=False,
    pairing_roles=("after_meal",), serving_unit="bowl",
    typical_servings=(1, 1), satiety=0.2,
))

# ===========================================================================
# CATALOG — Snacks & Street Food
# ===========================================================================

SAMOSA = FoodKnowledge(
    name="Samosa",
    aliases=("samosa", "samosas", "samosa chaat"),
    dish_kind=KIND_SNACK,
    course=SIDE,
    cuisine="north_indian",
    meal_roles=("snack", "breakfast"),
    main_meal_eligible=False,
    pairing_roles=("with_meal", "any"),
    serving_unit="piece",
    typical_servings=(2, 4),
    satiety=0.3,
    description="Deep-fried pastry filled with spiced potato and peas",
)
_register(SAMOSA)

SNACKS = [
    ("Kachori", ("kachori", "kachauri", "dal kachori"), 0.3, SIDE),
    ("Pakora", ("pakora", "pakoda", "bhajiya", "bhajji", "onion bhaji",
                "mixed pakora"), 0.25, SIDE),
    ("Tikki", ("tikki", "aloo tikki", "ragda pattice"), 0.3, SIDE),
    ("Chaat", ("chaat", "papdi chaat", "dahi papdi", "aloo chaat"), 0.25, SIDE),
    ("Pani Puri", ("pani puri", "golgappa", "puchka", "gup chup"), 0.15, SIDE),
    ("Bhel Puri", ("bhel puri", "bhel", "bhel puri"), 0.2, SIDE),
    ("Vada", ("vada", "medu vada", "masala vada", "sambar vada"), 0.3, SIDE),
    ("Dhokla", ("dhokla", "khaman dhokla", "nylon khaman"), 0.3, SIDE),
    ("Khandvi", ("khandvi", "patoli"), 0.2, SIDE),
    ("Fafda", ("fafda",), 0.25, SIDE),
    ("Cutlet", ("cutlet", "vegetable cutlet", "fish cutlet"), 0.25, SIDE),
    ("Spring Roll", ("spring roll", "spring rolls"), 0.2, SIDE),
    ("Bread Pakora", ("bread pakora", "bread pakoda"), 0.35, SIDE),
    ("Cheese Balls", ("cheese balls", "mozzarella sticks"), 0.2, SIDE),
    ("French Fries", ("french fries", "fries", "chips"), 0.2, SIDE),
    ("Nachos", ("nachos", "nacho", "nacho chips"), 0.2, SIDE),
    ("Namkeen", ("namkeen", "bhujia", "mixture", "chivda", "gathiya",
                 "sev"), 0.15, SIDE),
    ("Khakhra", ("khakhra", "mathri"), 0.15, SIDE),
    ("Momo", ("momo", "momos", "steamed momo"), 0.3, COMPLETE),
    ("Popcorn", ("popcorn",), 0.15, SIDE),
    ("Wonton", ("wonton", "wantons"), 0.2, SIDE),
    ("Nuggets", ("nuggets", "chicken nuggets", "veg nuggets"), 0.25, SIDE),
    ("Macaron", ("macaron", "macarons"), 0.1, SIDE),
    ("Cinnamon Roll", ("cinnamon roll",), 0.25, SIDE),
    ("Donut", ("donut", "doughnut", "donuts", "doughnuts"), 0.2, SIDE),
]
for _name, _aliases, _sat, _course in SNACKS:
    _cuisine = "tibetan" if "momo" in _name.lower() else "north_indian"
    _register(FoodKnowledge(
        name=_name, aliases=_aliases,
        dish_kind=KIND_SNACK, course=_course, cuisine=_cuisine,
        meal_roles=("snack",), main_meal_eligible=False,
        pairing_roles=("any",), serving_unit="piece",
        typical_servings=(1, 2), satiety=_sat,
    ))

# ===========================================================================
# CATALOG — Beverages
# ===========================================================================

BEVERAGES = [
    ("Chai", ("chai", "masala chai", "ginger tea", "adrak chai",
              "cardamom tea", "elaichi chai"), 0.1, "north_indian"),
    ("Coffee", ("coffee", "filter coffee", "south indian filter coffee",
                "cold coffee", "frappe", "latte", "cappuccino"), 0.1, "north_indian"),
    ("Lassi", ("lassi", "sweet lassi", "salted lassi", "mango lassi",
               "pista lassi"), 0.25, "north_indian"),
    ("Chaas", ("chaas", "chaach", "buttermilk", "masala chaas",
               "salted buttermilk"), 0.15, "north_indian"),
    ("Nimbu Pani", ("nimbu pani", "limbu pani", "nimbu soda",
                     "shikanji"), 0.05, "north_indian"),
    ("Jaljeera", ("jaljeera", "jal jira"), 0.05, "north_indian"),
    ("Thandai", ("thandai", "thandai"), 0.1, "north_indian"),
    ("Badam Milk", ("badam milk", "almond milk", "badam doodh"), 0.15, "north_indian"),
    ("Rose Milk", ("rose milk",), 0.1, "south_indian"),
    ("Soda", ("soda", "soda water", "club soda", "mojito"), 0.0, "continental"),
    ("Juice", ("juice", "fresh juice", "orange juice", "apple juice",
               "mango juice", "mixed fruit juice"), 0.15, "continental"),
    ("Milkshake", ("milkshake", "shake", "milk shake"), 0.25, "continental"),
    ("Smoothie", ("smoothie", "fruit smoothie"), 0.2, "continental"),
    ("Soft Drink", ("soft drink", "cold drink", "coke", "cola", "pepsi",
                    "sprite", "fanta", "limca", "thumbs up"), 0.0, "continental"),
    ("Coconut Water", ("coconut water", "nariyal pani", "tender coconut"), 0.05, "south_indian"),
    ("Hot Chocolate", ("hot chocolate", "hot cocoa"), 0.2, "continental"),
    ("Falooda", ("falooda",), 0.3, "north_indian"),
]
for _name, _aliases, _sat, _cuisine in BEVERAGES:
    _register(FoodKnowledge(
        name=_name, aliases=_aliases,
        dish_kind=KIND_BEVERAGE, course=SIDE, cuisine=_cuisine,
        meal_roles=("any",), main_meal_eligible=False,
        pairing_roles=("with_meal", "any"), serving_unit="glass",
        typical_servings=(1, 1), satiety=_sat,
        description=f"A {_name.lower()} beverage",
    ))

# ===========================================================================
# CATALOG — Regional Staples (breads, rice, breakfast items)
# ===========================================================================

STAPLES = [
    ("Roti", ("roti", "phulka", "tawa roti", "missi roti", "rumali roti",
              "tandoori roti", "butter roti", "chapati"), BREAD, 0.4, 0.35),
    ("Naan", ("naan", "butter naan", "garlic naan", "cheese naan",
              "tandoori naan"), BREAD, 0.5, 0.4),
    ("Paratha", ("paratha", "laccha paratha", "aloo paratha", "gobi paratha",
                 "paneer paratha", "mooli paratha"), BREAD, 0.5, 0.45),
    ("Puri", ("puri", "poori", "bhatura", "bhature"), BREAD, 0.3, 0.4),
    ("Kulcha", ("kulcha", "amritsari kulcha"), BREAD, 0.4, 0.35),
    ("Thepla", ("thepla", "methi thepla"), BREAD, 0.35, 0.35),
    ("Appam", ("appam", "appa", "hoppers"), BREAD, 0.3, 0.3),
    ("Pav", ("pav", "laadi pav", "masala pav"), BREAD, 0.3, 0.3),
    ("Steamed Rice", ("steamed rice", "plain rice", "boiled rice", "rice"),
     STAPLE, 0.5, 0.55),
    ("Jeera Rice", ("jeera rice", "ghee rice", "basmati rice"), STAPLE, 0.5, 0.55),
    ("Veg Pulao", ("veg pulao", "pulao", "vegetable pulao"), STAPLE, 0.5, 0.55),
    ("Biryani", ("biryani", "chicken biryani", "veg biryani", "dum biryani",
                 "mutton biryani", "egg biryani", "paneer biryani"),
     COMPLETE, 1.0, 0.7),
    ("Thali", ("thali", "veg thali", "nonveg thali", "gujarati thali",
               "south indian thali", "punjabi thali"),
     COMPLETE, 1.0, 0.75),
    ("Dosa", ("dosa", "masala dosa", "plain dosa", "rava dosa",
              "paper dosa", "onion dosa", "mysore masala dosa"),
     COMPLETE, 0.8, 0.6),
    ("Idli", ("idli", "idly", "idli vada", "idli sambar"),
     COMPLETE, 0.6, 0.5),
    ("Vada (meal)", ("sambar vada", "medu vada", "dahi vada", "vada sambar"),
     COMPLETE, 0.5, 0.5),
    ("Uttapam", ("uttapam", "uthappam", "onion uttapam"),
     COMPLETE, 0.6, 0.55),
    ("Poha", ("poha", "kanda poha", "indori poha", "aloo poha"),
     COMPLETE, 0.6, 0.45),
    ("Upma", ("upma", "rava upma", "semolina upma", "suji upma"),
     COMPLETE, 0.5, 0.45),
    ("Chilla", ("chilla", "cheela", "besan chilla", "paneer chilla"),
     COMPLETE, 0.5, 0.5),
    ("Khichdi", ("khichdi", "khichadi", "dal khichdi"),
     COMPLETE, 1.0, 0.6),
    ("Pav Bhaji", ("pav bhaji",), COMPLETE, 1.0, 0.65),
    ("Vada Pav", ("vada pav", "vadapav"), COMPLETE, 0.6, 0.55),
    ("Misal", ("misal", "misal pav", "missal", "missal pav"),
     COMPLETE, 0.7, 0.6),
    ("Chole Bhature", ("chole bhature", "chhole bhature"),
     COMPLETE, 1.0, 0.7),
    ("Puri Bhaji", ("puri bhaji", "poori bhaji"),
     COMPLETE, 1.0, 0.65),
    ("Bhurji", ("bhurji", "egg bhurji", "anda bhurji", "paneer bhurji"),
     COMPLETE, 0.5, 0.5),
    ("Omelette", ("omelette", "egg omelette", "masala omelette"),
     COMPLETE, 0.5, 0.45),
    ("Noodles", ("noodles", "hakka noodles", "veg noodles", "chicken noodles"),
     COMPLETE, 0.7, 0.55),
    ("Fried Rice", ("fried rice", "veg fried rice", "chicken fried rice",
                    "schezwan fried rice"),
     COMPLETE, 0.7, 0.55),
    ("Maggi", ("maggi", "instant noodles"), COMPLETE, 0.4, 0.35),
    ("Pasta", ("pasta", "white sauce pasta", "red sauce pasta", "arabiata"),
     COMPLETE, 0.5, 0.5),
    ("Sandwich", ("sandwich", "grilled sandwich", "toast sandwich",
                  "club sandwich"), COMPLETE, 0.6, 0.5),
    ("Wrap", ("wrap", "frankie", "kathi roll", "egg roll", "kebab roll"),
     COMPLETE, 0.7, 0.55),
    ("Momos (meal)", ("momo platter", "momo combo"), COMPLETE, 0.5, 0.55),
    ("Burger", ("burger", "veg burger", "chicken burger", "aloo tikki burger",
                "whopper"), COMPLETE, 0.7, 0.55),
    ("Pizza", ("pizza", "margherita", "farmhouse pizza"), COMPLETE, 0.8, 0.6),
]
for _name, _aliases, _course, _meal_role, _sat in STAPLES:
    _ht = ("high_protein",) if "paneer" in _name.lower() or "egg" in _name.lower() else ()
    _spice = SPICE_MILD if ("roti" in _name.lower() or "rice" in _name.lower()
                           or "idli" in _name.lower()) else SPICE_MEDIUM
    _register(FoodKnowledge(
        name=_name, aliases=_aliases, dish_kind=KIND_MEAL, course=_course,
        cuisine="north_indian",
        meal_roles=("breakfast", "lunch", "dinner") if _meal_role > 0.5
                  else ("breakfast", "lunch"),
        main_meal_eligible=True, pairing_roles=("any",),
        serving_unit="plate", typical_servings=(1, 1), satiety=_sat,
        health_tags=_ht, spice_level=_spice,
    ))

# ===========================================================================
# CATALOG — Common Indian Meals (curries & dishes, for health/portion ref)
# ===========================================================================

MEALS = [
    ("Paneer Butter Masala", ("paneer butter masala", "pbm"), CURRY,
     "rich creamy tomato gravy with paneer", 0.55),
    ("Kadai Paneer", ("kadai paneer", "kadhai paneer"), CURRY,
     "paneer and capsicum in spicy onion-tomato gravy", 0.5),
    ("Shahi Paneer", ("shahi paneer",), CURRY,
     "rich creamy paneer in nutty gravy", 0.55),
    ("Palak Paneer", ("palak paneer", "saag paneer"), CURRY,
     "paneer cubes in spiced spinach puree", 0.5),
    ("Matar Paneer", ("matar paneer", "mutter paneer"), CURRY,
     "paneer and green peas in tomato gravy", 0.5),
    ("Dal Makhani", ("dal makhani", "makhani dal"), CURRY,
     "slow-cooked black lentils in creamy gravy", 0.55),
    ("Dal Tadka", ("dal tadka", "dal fry", "yellow dal"), CURRY,
     "tempered yellow lentils with garlic and ghee", 0.5),
    ("Chana Masala", ("chana masala", "chole masala", "chole"), CURRY,
     "spiced chickpea curry", 0.5),
    ("Rajma", ("rajma", "rajma masala"), CURRY,
     "kidney beans in thick onion-tomato gravy", 0.5),
    ("Malai Kofta", ("malai kofta", "kofta"), CURRY,
     "cream gravy with fried vegetable dumplings", 0.55),
    ("Butter Chicken", ("butter chicken", "murgh makhani"), CURRY,
     "creamy tomato-based chicken gravy", 0.55, "nonveg"),
    ("Chicken Curry", ("chicken curry", "chicken masala", "kadai chicken"), CURRY,
     "everyday spiced chicken gravy", 0.5, "nonveg"),
    ("Mutton Curry", ("mutton curry", "mutton masala", "mutton rogan josh"), CURRY,
     "slow-cooked tender mutton in rich gravy", 0.55, "nonveg"),
    ("Fish Curry", ("fish curry", "fish masala", "fish moilee"), CURRY,
     "tangy coconut-based fish gravy", 0.45, "nonveg"),
    ("Chicken Biryani", ("chicken biryani", "murgh biryani"), COMPLETE,
     "layered basmati rice with spiced chicken", 0.7, "nonveg"),
    ("Mutton Biryani", ("mutton biryani",), COMPLETE,
     "layered basmati rice with tender mutton", 0.7, "nonveg"),
    ("Egg Curry", ("egg curry", "anda curry"), CURRY,
     "boiled eggs in spiced onion-tomato gravy", 0.45, "eggetarian"),
    ("Mix Veg", ("mix veg", "mixed vegetable", "veg kadai"), CURRY,
     "assorted vegetables in spiced gravy", 0.45),
    ("Veg Kolhapuri", ("veg kolhapuri",), CURRY,
     "mixed vegetables in spicy Kolhapuri gravy", 0.45),
]
for _name, _aliases, _course, _desc, _sat, *_rest in MEALS:
    _diet = _rest[0] if _rest else "veg"
    _cuisine = "hyderabadi" if "biryani" in _name.lower() else "north_indian"
    _spice = SPICE_MEDIUM
    if "kolhapuri" in _name.lower() or "kadai" in _name.lower():
        _spice = SPICE_SPICY
    if "palak" in _name.lower() or "dal tadka" in _name.lower():
        _spice = SPICE_MILD
    _register(FoodKnowledge(
        name=_name, aliases=_aliases, dish_kind=KIND_MEAL, course=_course,
        cuisine=_cuisine,
        meal_roles=("lunch", "dinner"), main_meal_eligible=True,
        pairing_roles=("any",), serving_unit="katori",
        typical_servings=(1, 2), satiety=_sat,
        dietary_flags=(_diet,), spice_level=_spice,
        description=_desc,
    ))

# ===========================================================================
# CATALOG — Condiments & Accompaniments
# ===========================================================================

CONDIMENTS = [
    ("Raita", ("raita", "boondi raita", "mix raita", "pudina raita",
               "cucumber raita"), 0.1),
    ("Papad", ("papad", "papadum", "poppadom", "fryums"), 0.05),
    ("Achar", ("achar", "achaar", "pickle", "mango pickle"), 0.0),
    ("Chutney", ("chutney", "mint chutney", "tamarind chutney",
                 "coconut chutney", "imli chutney"), 0.05),
    ("Salad", ("salad", "onion salad", "green salad", "kachumber"), 0.05),
    ("Salan", ("salan", "mirchi ka salan"), 0.05),
    ("Curd", ("curd", "dahi", "yogurt"), 0.1),
]
for _name, _aliases, _sat in CONDIMENTS:
    _register(FoodKnowledge(
        name=_name, aliases=_aliases, dish_kind=KIND_CONDIMENT, course=SIDE,
        cuisine="north_indian",
        meal_roles=("any",), main_meal_eligible=False,
        pairing_roles=("with_meal",), serving_unit="katori",
        typical_servings=(1, 1), satiety=_sat,
    ))


# ===========================================================================
# PUBLIC API
# ===========================================================================

def lookup(name: str) -> FoodKnowledge | None:
    """Canonical lookup by name or alias. Case-insensitive."""
    return _KNOWN.get(name.lower().strip())


def classify_meal_suitability(name: str) -> dict:
    """Return meal-eligibility metadata for the given item name.

    Fields: main_meal_eligible (bool), serving_unit (str),
    satiety (float), typical_servings ((int,int)), dish_kind (str),
    course (str), known (bool).
    """
    entry = lookup(name)
    if entry is None:
        return {
            "known": False,
            "main_meal_eligible": True,   # default: allow through
            "serving_unit": "",
            "satiety": 0.5,
            "typical_servings": (1, 1),
            "dish_kind": "",
            "course": "",
        }
    return {
        "known": True,
        "main_meal_eligible": entry.main_meal_eligible,
        "serving_unit": entry.serving_unit,
        "satiety": entry.satiety,
        "typical_servings": entry.typical_servings,
        "dish_kind": entry.dish_kind,
        "course": entry.course,
    }


def available_kinds_for(slot_type: str, preferences: dict) -> list[str]:
    """Return the list of dish_kinds that can fill a given slot.

    Args:
        slot_type: "breakfast", "lunch", "dinner", "dessert", "snack"
        preferences: {"veg_level": "veg", ...} for future filtering

    Returns ordered list of dish_kind strings: the first is the most
    appropriate for the slot.
    """
    slot_to_kinds = {
        "breakfast": [KIND_MEAL, KIND_SNACK],
        "lunch": [KIND_MEAL],
        "dinner": [KIND_MEAL],
        "dessert": [KIND_SWEET],
        "snack": [KIND_SNACK, KIND_SWEET],
    }
    return slot_to_kinds.get(slot_type, [KIND_MEAL])


def search_by_tags(cuisine: str = "", kind: str = "",
                   dietary: str = "", health: str = "") -> list[FoodKnowledge]:
    """Search the knowledge base by optional filters.

    Empty/unset filters match all items of that axis. All specified
    filters are AND-ed.
    """
    results = []
    for item in _KNOWN.values():
        # Avoid duplicates — same FoodKnowledge can be registered under
        # multiple keys; track by id().
        if item in results:
            continue
        if cuisine and item.cuisine != cuisine:
            continue
        if kind and item.dish_kind != kind:
            continue
        if dietary and dietary not in item.dietary_flags:
            continue
        if health and health not in item.health_tags:
            continue
        results.append(item)
    return results


def filter_by_diet(items: list[FoodKnowledge], profile: dict) -> list[FoodKnowledge]:
    """Hard-exclude items that violate dietary constraints.

    profile dict (from TasteProfile.hard_filters()):
      {"veg_only": bool, "allowed_dietary_flags": [str, ...],
       "allergies": [str, ...]}

    Returns filtered list.
    """
    out = []
    veg = profile.get("veg_only", False)
    allowed = set(profile.get("allowed_dietary_flags", []))
    allergies = set(a.lower() for a in profile.get("allergies", []))

    for item in items:
        # Veg filter
        if veg and "veg" not in item.dietary_flags:
            continue
        # Allowed diet flags
        if allowed and not any(f in item.dietary_flags for f in allowed):
            continue
        # Allergy check on name + aliases (case-insensitive substring match)
        if allergies:
            texts = [item.name.lower()] + [a.lower() for a in item.aliases]
            if any(allergen in t for t in texts for allergen in allergies):
                continue
        out.append(item)
    return out


def explain(item: FoodKnowledge) -> str:
    """Human-readable summary for the AI to use in explanations."""
    parts = [
        f"{item.name} is a {item.dish_kind}",
        f"served as {item.serving_unit}(s)",
        f"({item.satiety:.0%} satiety)",
    ]
    if not item.main_meal_eligible:
        parts.append("and CANNOT be a full meal on its own")
    if item.dietary_flags:
        parts.append(f"[{','.join(item.dietary_flags)}]")
    return " ".join(parts)


def stats() -> dict:
    """Return catalog statistics for debugging / admin."""
    by_kind = {}
    by_diet = {}
    count = 0
    seen = set()
    for v in _KNOWN.values():
        if id(v) in seen:
            continue
        seen.add(id(v))
        count += 1
        by_kind[v.dish_kind] = by_kind.get(v.dish_kind, 0) + 1
        for f in v.dietary_flags:
            by_diet[f] = by_diet.get(f, 0) + 1
    return {
        "total_unique": count,
        "total_keys": len(_KNOWN),
        "by_kind": by_kind,
        "by_diet": by_diet,
    }